import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import json
import time

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'infotainment_lab'))
from native_traffic import HEADER, gateway_records, snapshot, unpack


def test_observation_packet_and_gateway_records_preserve_bytes_and_validate_boundaries():
    record = ((2 << 11) | 0x321).to_bytes(2, 'big') + b'\x12\x34' + b'\0' * 6
    event = HEADER.pack(b'NTR2', 1, 1234567890, b'\x7f\0\0\x66', 4321, len(record)) + record
    assert unpack(event) == (1, 1234567890, 4321, record)
    assert gateway_records(record * 2) == [(0x321, b'\x12\x34')] * 2
    for damaged in (event[:-1], b'', b'BAD!' + event[4:]):
        with pytest.raises(ValueError):
            unpack(damaged)
    assert gateway_records(record[:-1]) == []
    assert gateway_records(b'\xff\xff' + b'\0' * 8) == []


def test_observer_has_no_synthetic_fallback_when_device_stopped(tmp_path):
    result = snapshot(tmp_path)
    assert result['state'] == 'stopped' and result['frames'] == []


def test_device_stop_hides_a_recent_observation_snapshot(tmp_path):
    (tmp_path / 'status.json').write_text(json.dumps({'phase': 'stopped'}))
    (tmp_path / 'native-traffic.json').write_text(json.dumps({'updated_at': time.time(), 'frames': [{'id': 3}]}))
    assert snapshot(tmp_path)['frames'] == []


@pytest.mark.skipif(sys.platform != 'linux' or not shutil.which('gcc'), reason='Linux C toolchain required')
def test_native_capture_keeps_send_results_and_original_api_and_never_blocks(tmp_path):
    adapter = tmp_path / 'capture.so'
    source = Path(__file__).parents[1] / 'infotainment_lab/runtime/native-traffic.c'
    subprocess.run(['gcc', '-shared', '-fPIC', '-Wall', '-Wextra', str(source), '-o', str(adapter), '-ldl'], check=True)
    framework = tmp_path / 'framework.c'
    framework.write_text('''
#include <errno.h>
int calls;
void request(void*,unsigned int,const void*,unsigned short)
 __asm__("_ZN27PlatformM3VehicleLinkCommon11sendMessageEjPKvt");
void request(void *self,unsigned int id,const void *data,unsigned short size) {calls++;errno=ERANGE;}
''')
    library = tmp_path / 'framework.so'
    subprocess.run(['gcc', '-shared', '-fPIC', str(framework), '-o', str(library)], check=True)
    main = tmp_path / 'probe.c'
    main.write_text('''
#include <arpa/inet.h>
#include <errno.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <unistd.h>
extern int calls;
void request(void*,unsigned int,const void*,unsigned short)
 __asm__("_ZN27PlatformM3VehicleLinkCommon11sendMessageEjPKvt");
int main(int argc,char **argv) {
 unsigned char data[10]={0x13,0x21,0x12,0x34};
 for (int i=0;i<1000;i++) request(0,0x321,data+2,2);
 if (calls!=1000 || errno!=ERANGE) return 1;
 struct sockaddr_in peer={.sin_family=AF_INET,.sin_addr.s_addr=htonl(0x7f000066),.sin_port=htons(atoi(argv[1]))};
 int fd=socket(AF_INET,SOCK_DGRAM,0);
 if (sendto(fd,data,10,0,(void*)&peer,sizeof peer)!=10) return 2;
 if (connect(fd,(void*)&peer,sizeof peer)) return 3;
 if (send(fd,data,10,0)!=10) return 4;
 close(fd);
 if (send(fd,data,10,0)!=-1 || errno!=EBADF) return 5;
}
''')
    executable = tmp_path / 'probe'
    subprocess.run(['gcc', str(main), str(library), '-o', str(executable)], check=True)
    # Fill the unread observation queue. A slow viewer must not stall the OS.
    path = tmp_path / 'observer.sock'
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as observer, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        observer.bind(str(path))
        observer.settimeout(.2)
        receiver.bind(('127.0.0.102', 0))
        receiver.settimeout(.2)
        env = dict(os.environ, LD_PRELOAD=str(adapter), TESLA_NATIVE_TRAFFIC_SOCKET=str(path))
        subprocess.run([str(executable), str(receiver.getsockname()[1])], env=env, check=True, timeout=10)
        assert receiver.recv(100) == bytes.fromhex('13 21 12 34 00 00 00 00 00 00')
        assert receiver.recv(100) == bytes.fromhex('13 21 12 34 00 00 00 00 00 00')
        kind, stamp, port, raw = unpack(observer.recv(5000))
        assert kind == 2 and gateway_records(raw) == [(0x321, b'\x12\x34')]

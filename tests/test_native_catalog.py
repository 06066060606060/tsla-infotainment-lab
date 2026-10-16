from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from infotainment_lab.native_catalog import extract


@pytest.mark.skipif(sys.platform != 'linux' or not shutil.which('gcc'), reason='ELF compiler required')
def test_catalogue_uses_relocated_tables_and_validates_parent_links(tmp_path):
    source = tmp_path / 'catalogue.c'
    source.write_text('''
#include <stdint.h>
typedef struct {int value; const char *label;} Enum;
typedef struct Signal Signal;
typedef struct Bus Bus;
typedef struct Message {const char *name; uint32_t id,length,period,count;
    uint64_t unused; Signal *signals; Bus *parent;} Message;
struct Signal {const char *name; uint64_t key; const char *unit; Message *parent; Enum *choices;};
struct Bus {const char *name; uint32_t id,count; Message *messages;};
extern Bus CANBusList[];
extern Message Sample_messages[];
Enum Example_map[]={{0,"OFF"},{1,"ON"},{-1,""}};
Signal Example_signals[]={{"example",4,"unit",Sample_messages,Example_map}};
Message Sample_messages[]={{"Example",700,2,100,1,0,Example_signals,CANBusList}};
Bus CANBusList[]={{"ETH",3,1,Sample_messages}};
struct {uint64_t count; Bus *buses;} CANData={1,CANBusList};
''')
    target = tmp_path / 'metadata.so'
    subprocess.run(['gcc', '-shared', '-fPIC', str(source), '-o', str(target)], check=True)
    result = extract(target)
    assert result == [{'bus': 'ETH', 'bus_id': 3, 'id': 700, 'name': 'Example', 'length': 2,
                       'period_ms': 100, 'signals': [{'name': 'example', 'unit': 'unit',
                                                   'choices': {'0': 'OFF', '1': 'ON'}}]}]
    source.write_text(source.read_text().replace('Sample_messages,Example_map', '0,Example_map'))
    subprocess.run(['gcc', '-shared', '-fPIC', str(source), '-o', str(target)], check=True)
    with pytest.raises(ValueError, match='parent mismatch'):
        extract(target)


def test_catalogue_refuses_unknown_binary_without_executing_it(tmp_path):
    path = tmp_path / 'foreign.so'
    path.write_bytes(b'not a firmware ELF')
    with pytest.raises(ValueError, match='ELF'):
        extract(path)

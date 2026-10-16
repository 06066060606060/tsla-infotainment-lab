"""The diagnostic platform selector reads a local file, without host mutation."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != 'linux' or not shutil.which('gcc'), reason='Linux C toolchain required')
def test_only_platform_reads_are_redirected_and_writes_are_refused(tmp_path):
    shim = tmp_path / 'platform.so'
    source = Path(__file__).parents[1] / 'infotainment_lab/runtime/native-service-platform.c'
    subprocess.run(['gcc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror', str(source),
                    '-o', str(shim), '-ldl'], check=True)
    product = tmp_path / 'product'
    product.write_text('Model3\n')
    untouched = tmp_path / 'unrelated'
    untouched.write_text('Unchanged\n')
    main = tmp_path / 'main.c'
    main.write_text('''
#define _LARGEFILE64_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
int main(int argc,char **argv) {
 char data[64]={0};
 int fd=open64("/var/etc/jcanproduct",O_RDONLY);
 if(fd<0) return 1;
 read(fd,data,63); close(fd); printf("%s",data);
 if(open("/var/etc/jcanproduct",O_WRONLY|O_TRUNC)!=-1 || errno!=EROFS) return 2;
 fd=open(argv[1],O_RDONLY); if(fd<0) return 3;
 int n=read(fd,data,63); close(fd); data[n]=0; printf("%s",data);
 fd=open(argv[2],O_WRONLY|O_CREAT|O_EXCL,0600); if(fd<0) return 4;
 close(fd); return 0;
}
''')
    executable = tmp_path / 'probe'
    subprocess.run(['gcc', str(main), '-o', str(executable)], check=True)
    created = tmp_path / 'created'
    result = subprocess.run([str(executable), str(untouched), str(created)], check=True,
        capture_output=True, text=True, env=dict(os.environ, LD_PRELOAD=str(shim), TESLA_NATIVE_SERVICE_PRODUCT=str(product)))
    assert result.stdout == 'Model3\nUnchanged\n'
    assert product.read_text() == 'Model3\n'
    assert created.stat().st_mode & 0o777 == 0o600

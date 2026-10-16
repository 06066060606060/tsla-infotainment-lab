"""Keep the decorative TPMS fix isolated from other loading indicators."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != 'linux' or not shutil.which('gcc')
                   or not Path('/usr/include/X11/Xlib.h').exists(),
                   reason='Linux C toolchain and X11 headers required')
def test_only_tpms_asset_spinner_is_disabled_by_the_owned_session(tmp_path):
    adapter = tmp_path / 'input.so'
    source = Path(__file__).parents[1] / 'infotainment_lab/runtime/native-input.c'
    subprocess.run(['gcc', '-shared', '-fPIC', '-Wall', '-Wextra', str(source),
                    '-o', str(adapter), '-lX11', '-ldl'], check=True)
    framework = tmp_path / 'framework.c'
    framework.write_text('''
#include <stdbool.h>
void asset(void*,void*,void*,const void*,bool,bool)
    __asm__("_ZN12AssetGenViewC1EP11DisplayView7QStringRK5Stylebb");
void asset(void *self,void *parent,void *name,const void *style,bool generated,bool spinner) {
    *(int*)self = spinner;
}
void card(void*,void*) __asm__("_ZN8TPMSCardC1EP14ICardContainer");
void card(void *self,void *parent) { asset(self,parent,0,0,true,true); }
''')
    library = tmp_path / 'framework.so'
    subprocess.run(['gcc', '-shared', '-fPIC', str(framework), '-o', str(library)], check=True)
    main = tmp_path / 'probe.c'
    main.write_text('''
#include <stdbool.h>
#include <stdio.h>
void card(void*,void*) __asm__("_ZN8TPMSCardC1EP14ICardContainer");
void asset(void*,void*,void*,const void*,bool,bool)
    __asm__("_ZN12AssetGenViewC1EP11DisplayView7QStringRK5Stylebb");
int main(void) {
    int tire=-1,other=-1;
    card(&tire,0);
    asset(&other,0,0,0,true,true);
    printf("%d %d\\n",tire,other);
    return 0;
}
''')
    executable = tmp_path / 'probe'
    subprocess.run(['gcc', str(main), str(library), '-o', str(executable)], check=True)
    for enabled, expected in (('1', '0 1'), ('0', '1 1'), ('', '1 1')):
        result = subprocess.run([str(executable)], capture_output=True, text=True, check=True,
            env=dict(os.environ, LD_PRELOAD=str(adapter), TESLA_NATIVE_TPMS_NO_ASSET_SPINNER=enabled))
        assert result.stdout.strip() == expected

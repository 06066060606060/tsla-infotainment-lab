"""Exercise the opt-in layout adapter without firmware, X display or a vehicle."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != 'linux' or not shutil.which('gcc')
                   or not Path('/usr/include/X11/Xlib.h').exists(), reason='Linux C toolchain required')
def test_park_layout_is_opt_in_and_keeps_other_gears_and_track_mode_native(tmp_path):
    shim = tmp_path / 'input.so'
    source = Path(__file__).parents[1] / 'infotainment_lab/runtime/native-input.c'
    subprocess.run(['gcc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror', str(source),
                    '-o', str(shim), '-ldl'], check=True)
    framework = tmp_path / 'framework.c'
    framework.write_text('''
#include <stdbool.h>
bool parked_state, track_state, native_allowed;
bool allowed(void) __asm__("_ZN12VehicleUtils45allowExtendedAutopilotVizForCurrentShiftStateEv");
bool allowed(void) { return native_allowed; }
bool parked(bool,bool) __asm__("_ZN12VehicleUtils11isCarParkedEbb");
bool parked(bool neutral,bool unknown) { return !neutral && !unknown && parked_state; }
bool track(void) __asm__("_ZN12VehicleUtils11trackModeOnEv");
bool track(void) { return track_state; }
''')
    library = tmp_path / 'framework.so'
    subprocess.run(['gcc', '-shared', '-fPIC', str(framework), '-o', str(library)], check=True)
    main = tmp_path / 'main.c'
    main.write_text('''
#include <stdbool.h>
#include <stdio.h>
extern bool parked_state,track_state,native_allowed;
bool allowed(void) __asm__("_ZN12VehicleUtils45allowExtendedAutopilotVizForCurrentShiftStateEv");
int main(void) {
 parked_state=true; printf("%d ",allowed());
 track_state=true; printf("%d ",allowed());
 track_state=false; parked_state=false; printf("%d ",allowed());
 native_allowed=true; printf("%d\\n",allowed());
}
''')
    executable = tmp_path / 'probe'
    subprocess.run(['gcc', str(main), str(library), '-o', str(executable)], check=True)
    for optin, expected in [('1', '1 0 0 1'), ('0', '0 0 0 1'), ('', '0 0 0 1')]:
        result = subprocess.run([str(executable)], capture_output=True, text=True, check=True,
                    env=dict(os.environ, LD_PRELOAD=str(shim), TESLA_NATIVE_PARK_VIZ=optin))
        assert result.stdout.strip() == expected

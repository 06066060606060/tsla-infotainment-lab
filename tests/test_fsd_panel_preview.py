"""Exercise native panel construction/visibility without firmware or AP data."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != 'linux' or not shutil.which('gcc')
                   or not Path('/usr/include/X11/Xlib.h').exists(), reason='Linux C toolchain required')
@pytest.mark.parametrize('queries_present', [True, False])
def test_fsd_preview_scopes_construction_and_keeps_preferences_and_active_view(tmp_path, queries_present):
    shim = tmp_path / 'input.so'
    source = Path(__file__).parents[1] / 'infotainment_lab/runtime/native-fsd.c'
    subprocess.run(['gcc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror', str(source),
                    '-o', str(shim), '-ldl'], check=True)
    queries = '''
bool configured(void) __asm__("_ZN12VehicleUtils27startFsdFromFsdPanelEnabledEv");
bool configured(void) { return configured_state; }
bool active(void) __asm__("_ZN12VehicleUtils11isFSDActiveEv");
bool active(void) { return active_state; }
''' if queries_present else ''
    framework = tmp_path / 'framework.c'
    framework.write_text('''
#include <stdbool.h>
#include <stdio.h>
#include <pthread.h>
bool configured_state,active_state,native_visible,native_panel;
int native_capability_calls;
bool capability(void) __asm__("_ZN12VehicleUtils11hasFsdPanelEv");
bool capability(void) { native_capability_calls++; return native_panel; }
bool visible(void *) __asm__("_ZNK8FsdPanel12FsdPanelView22shouldShowStartFsdViewEv");
bool visible(void *self) { return self && native_visible; }
void tick(void *) __asm__("_ZN13CenterDisplay11createViewsEv");
void tick(void *self) { (void)self; }
void load(void *,const void *) __asm__("_ZN13ClusterWindow8loadUIMLERK7QString");
static void *worker(void *arg) { *(bool *)arg=capability(); return 0; }
void load(void *self,const void *name) {
 static int depth;
 printf("inside%d=%d ",depth,capability());
 if (depth==0) {
  depth++; load(self,name); depth--;
  printf("outer=%d ",capability());
  pthread_t thread; bool other=true;
  pthread_create(&thread,0,worker,&other); pthread_join(thread,0);
  printf("worker=%d ",other);
 }
}
''' + queries)
    library = tmp_path / 'framework.so'
    subprocess.run(['gcc', '-shared', '-fPIC', str(framework), '-o', str(library), '-pthread'], check=True)
    main = tmp_path / 'main.c'
    main.write_text('''
#include <stdbool.h>
#include <stdio.h>
extern bool configured_state,active_state,native_visible,native_panel;
extern int native_capability_calls;
bool capability(void) __asm__("_ZN12VehicleUtils11hasFsdPanelEv");
bool visible(void *) __asm__("_ZNK8FsdPanel12FsdPanelView22shouldShowStartFsdViewEv");
void load(void *,const void *) __asm__("_ZN13ClusterWindow8loadUIMLERK7QString");
void tick(void *) __asm__("_ZN13CenterDisplay11createViewsEv");
int main(void) {
 int panel=0;
 printf("before=%d ",capability());
 load(&panel,&panel);
 printf("after=%d ",capability());
 native_panel=true; printf("native=%d ",capability());
 configured_state=true; printf("before_tick=%d ",visible(&panel));
 configured_state=false; tick(&panel);
 printf("unconfigured=%d ",visible(&panel));
 configured_state=true; printf("configured=%d ",visible(&panel));
 active_state=true; printf("active=%d ",visible(&panel));
 configured_state=false; native_visible=true;
 printf("native_visible=%d calls=%d\\n",visible(&panel),native_capability_calls);
}
''')
    executable = tmp_path / 'probe'
    subprocess.run(['gcc', str(main), str(library), '-o', str(executable)], check=True)
    for optin in ('1', '0', '', '11'):
        result = subprocess.run([str(executable)], capture_output=True, text=True, check=True,
                    env=dict(os.environ, LD_PRELOAD=str(shim), TESLA_NATIVE_FSD_PANEL_PREVIEW=optin))
        values = dict(item.split('=') for item in result.stdout.split())
        preview = str(int(optin == '1'))
        assert values == dict(before='0', inside0=preview, inside1=preview, outer=preview,
                            worker='0', after='0', native='1', before_tick='0', unconfigured='0',
                            configured=str(int(optin == '1' and queries_present)),
                            active='0', native_visible='1', calls='7')

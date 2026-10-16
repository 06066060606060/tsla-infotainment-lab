"""Test the local native Start/Stop lifecycle with a synthetic Qt/DV ABI."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != 'linux' or not shutil.which('gcc'), reason='Linux C toolchain required')
@pytest.mark.parametrize('original_valid', [True, False])
@pytest.mark.parametrize('missing_enum', [False, True])
def test_start_stop_are_local_and_native_writes_cannot_flicker_the_simulated_state(
        tmp_path, original_valid, missing_enum):
    source = Path(__file__).parents[1] / 'infotainment_lab/runtime/native-fsd.c'
    shim = tmp_path / 'fsd.so'
    subprocess.run(['gcc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror', str(source),
                    '-o', str(shim), '-ldl'], check=True)
    header = '''
#include <stdbool.h>
typedef struct { int value,pending; bool valid,pending_valid; } DV;
extern DV GUI_startFsdButtonState,GUI_stopFsdButtonState;
extern DV GUI_startFsdButtonUnavailableReason,DAS_autopilotState,other;
extern int native_requests;
void start(void *) __asm__("_ZN18StartFsdController21submitStartFsdRequestEv");
void stop(void *) __asm__("_ZN18StartFsdController20submitStopFsdRequestEv");
void load(void *,const void *) __asm__("_ZN13ClusterWindow8loadUIMLERK7QString");
void create(void *) __asm__("_ZN13CenterDisplay11createViewsEv");
void event(void);
void native_poll(void);
'''
    framework = tmp_path / 'framework.c'
    framework.write_text(header + '''
typedef struct { DV *dv; } Locker;
typedef struct { int value; } Variant;
typedef struct { int value; const char *name; } EnumName;
EnumName StartFsdButtonStateNameMap[]={{-7,"Unavailable"},{5,"Available"},{0,0}};
EnumName StopFsdButtonStateNameMap[]={{-9,"Unavailable"},{9,"Available"},{0,0}};
EnumName StartFsdButtonUnavailableReasonNameMap[]={{7,"ReasonNone"},{0,0}};
EnumName AutopilotStateNameMap[]={{99,"Disabled"},{23,"Available"},{63,"ACTIVE_NAME"},{0,0}};
void lock(Locker *,DV *) __asm__("_ZN9DataValue11EventLockerC1ERS_");
void lock(Locker *self,DV *dv) { self->dv=dv; dv->pending=dv->value; dv->pending_valid=dv->valid; }
void unlock(Locker *) __asm__("_ZN9DataValue11EventLockerD1Ev");
void unlock(Locker *self) { self->dv->value=self->dv->pending; self->dv->valid=self->dv->pending_valid; }
void variant(Variant *,int) __asm__("_ZN8QVariantC1Ei");
void variant(Variant *self,int value) { self->value=value; }
void destroy(Variant *) __asm__("_ZN8QVariantD1Ev");
void destroy(Variant *self) { (void)self; }
void get(Variant *,const DV *,bool *) __asm__("_ZNK9DataValue15atomicGetNoLockEPb");
void get(Variant *out,const DV *self,bool *valid) { out->value=self->value; *valid=self->valid; }
void set(DV *,const Variant *,bool) __asm__("_ZN9DataValue14setValueNoLockERK8QVariantb");
void set(DV *self,const Variant *v,bool pushed) { (void)pushed; self->pending=v->value; self->pending_valid=true; }
void invalid(DV *) __asm__("_ZN9DataValue16setInvalidNoLockEv");
void invalid(DV *self) { self->pending_valid=false; }
bool capability(void) __asm__("_ZN12VehicleUtils11hasFsdPanelEv");
bool capability(void) { return false; }
bool configured(void) __asm__("_ZN12VehicleUtils27startFsdFromFsdPanelEnabledEv");
bool configured(void) { return true; }
void load(void *self,const void *name) { (void)self; (void)name; }
void create(void *self) { (void)self; }
void start(void *self) { (void)self; native_requests++; }
void stop(void *self) { (void)self; native_requests++; }
static void raw(DV *dv,int value) { Locker l; lock(&l,dv); dv->pending=value; dv->pending_valid=true; unlock(&l); }
void event(void) { raw(&other,77); }
void native_poll(void) {
 raw(&GUI_startFsdButtonState,-7); raw(&GUI_stopFsdButtonState,-9);
 raw(&GUI_startFsdButtonUnavailableReason,42); raw(&DAS_autopilotState,58); raw(&other,42);
}
'''.replace('ACTIVE_NAME', 'MissingActiveEnum' if missing_enum else 'ActiveFsd'))
    library = tmp_path / 'framework.so'
    subprocess.run(['gcc', '-shared', '-fPIC', str(framework), '-o', str(library)], check=True)
    main = tmp_path / 'main.c'
    main.write_text(header + '''
#include <stdio.h>
#include <unistd.h>
DV GUI_startFsdButtonState,GUI_stopFsdButtonState,GUI_startFsdButtonUnavailableReason;
DV DAS_autopilotState={.value=17,.valid=ORIGINAL_VALID},other;
int native_requests;
static void report(const char *name) {
 printf("%s %d %d %d %d %d %d %d\\n",name,GUI_startFsdButtonState.value,
 GUI_stopFsdButtonState.value,GUI_startFsdButtonUnavailableReason.value,
 DAS_autopilotState.value,DAS_autopilotState.valid,other.value,native_requests);
}
int main(int argc,char **argv) {
 if (argc!=2) return 1;
 int panel=0; load(&panel,&panel); create(&panel); report("ready");
 start(&panel); native_poll(); report("engaged");
 stop(&panel); report("stopped");
 start(&panel);
 FILE *f=fopen(argv[1],"w"); fputs("{\\"fsd_ui_simulation\\":false}",f); fclose(f);
 usleep(250000); event(); report("disabled");
 start(&panel); report("native");
 return 0;
}
'''.replace('ORIGINAL_VALID', 'true' if original_valid else 'false'))
    executable = tmp_path / 'probe'
    # GUI DVs live in the main executable in the real image too. RTLD_NEXT
    # cannot find those copy-relocated symbols; the shim needs RTLD_DEFAULT.
    subprocess.run(['gcc', str(main), str(library), '-Wl,--export-dynamic',
                    '-o', str(executable)], check=True)
    state = tmp_path / 'vehicle-services.json'
    for optin in ('1', '0'):
        state.write_text(json.dumps({'fsd_ui_simulation': True}))
        result = subprocess.run([str(executable), str(state)], capture_output=True, text=True, check=True,
                    env=dict(os.environ, LD_PRELOAD=str(shim), TESLA_NATIVE_FSD_PANEL_PREVIEW=optin,
                             TESLA_NATIVE_STATE=str(tmp_path)))
        values = {parts[0]: list(map(int, parts[1:]))
                  for parts in (line.split() for line in result.stdout.splitlines())}
        if optin == '1' and not missing_enum:
            assert values['ready'][:5] == [5, -9, 7, 23, 1]
            assert values['engaged'] == [-7, 9, 7, 63, 1, 42, 0]
            assert values['stopped'] == [5, -9, 7, 23, 1, 42, 0]
            assert values['disabled'] == [-7, -9, 7, 17 if original_valid else 99,
                                          int(original_valid), 77, 0]
            assert values['native'][-1] == 1
        else:
            assert values['engaged'] == [-7, -9, 42, 58, 1, 42, 1]
            assert values['native'][-2:] == [77, 4]

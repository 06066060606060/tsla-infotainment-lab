"""Native layout regression: preserve navigation and Start/Stop hit regions."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != 'linux' or not shutil.which('gcc'), reason='Linux C toolchain required')
@pytest.mark.parametrize('geometry_present', [True, False])
def test_fsd_navigation_collision_uses_rendered_geometry_and_keeps_native_fallback(tmp_path, geometry_present):
    source = Path(__file__).parents[1] / 'infotainment_lab/runtime/native-fsd.c'
    shim = tmp_path / 'shim.so'
    subprocess.run(['gcc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror', str(source),
                    '-o', str(shim), '-ldl'], check=True)
    framework = tmp_path / 'framework.c'
    framework.write_text(r"""
#include <stdbool.h>
#include <stdio.h>
typedef struct { int left,top,right,bottom; } Rect;
typedef struct View { int x,y,width,height; bool visible; struct View *parent; } View;
View cluster={100,50,740,1200,true,0};
View sidebar={10,20,740,900,true,&cluster};
View panel={16,66,250,80,true,&sidebar};
View turn={0,0,320,80,true,&cluster};
void move(void *,int,int,double,int,double) __asm__("_ZN11DisplayView6moveToEiidN17InterpolatedValue8EaseTypeEd");
void move(void *v,int x,int y,double d,int e,double t) { View *s=v;s->x=x;s->y=y;(void)d;(void)e;(void)t; }
void layout(void *) __asm__("_ZN13ClusterWindow20updateTurnListLayoutEv");
int target_x=210,target_y=60;
void layout(void *v) { (void)v;move(&turn,target_x,target_y,0,2,0); }
void init(void *) __asm__("_ZN8FsdPanel12FsdPanelView4initEv");
void init(void *v) { (void)v; }
void create(void *) __asm__("_ZN13CenterDisplay11createViewsEv");
void create(void *v) { (void)v; }
""" + (r"""
void *parent(void *v) __asm__("_ZN11DisplayView10parentViewEv");
void *parent(void *v) { return ((View *)v)->parent; }
bool visible(void *v,void *p) __asm__("_ZN11DisplayView9isVisibleEPS_");
bool visible(void *v,void *p) { (void)p;return ((View *)v)->visible; }
Rect rect(const void *,void *) __asm__("_ZNK11DisplayView20relativePositionRectEPS_");
static void origin(const View *v,int *x,int *y) { *x=*y=0;for (;v;v=v->parent) { *x+=v->x;*y+=v->y; } }
Rect rect(const void *v,void *p) {
 const View *s=v;int x,y,px,py;origin(s,&x,&y);origin(p,&px,&py);
 return (Rect){x-px,y-py,x-px+s->width-1,y-py+s->height-1};
}
""" if geometry_present else ''))
    lib = tmp_path / 'framework.so'
    subprocess.run(['gcc', '-shared', '-fPIC', str(framework), '-o', str(lib)], check=True)
    main = tmp_path / 'main.c'
    main.write_text(r"""
#include <stdbool.h>
#include <stdio.h>
typedef struct View { int x,y,width,height; bool visible; struct View *parent; } View;
extern View cluster,sidebar,panel,turn;
extern int target_x,target_y;
void init(void *) __asm__("_ZN8FsdPanel12FsdPanelView4initEv");
void create(void *) __asm__("_ZN13CenterDisplay11createViewsEv");
void layout(void *) __asm__("_ZN13ClusterWindow20updateTurnListLayoutEv");
void move(void *,int,int,double,int,double) __asm__("_ZN11DisplayView6moveToEiidN17InterpolatedValue8EaseTypeEd");
static void sample(const char *label) { layout(&cluster);printf("%s=%d,%d ",label,turn.x,turn.y); }
int main(void) {
 init(&panel);sample("early");create(&cluster);sample("left");
 panel.visible=false;sample("hidden");panel.visible=true;
 target_x=350;sample("separate");target_x=210;
 cluster.width=500;sample("narrow");cluster.width=740;
 panel.x=440;target_x=400;sample("right");
 /* A native move outside navigation layout must remain untouched. */
 move(&turn,410,60,0,2,0);printf("unrelated=%d,%d ",turn.x,turn.y);
 panel.visible=false;sample("reset");puts("");
}
""")
    exe = tmp_path / 'probe'
    subprocess.run(['gcc', str(main), str(lib), '-o', str(exe)], check=True)
    for optin in ('1', '0', '11'):
        result = subprocess.run([str(exe)], capture_output=True, text=True, check=True,
                                env=dict(os.environ, LD_PRELOAD=str(shim), TESLA_NATIVE_FSD_PANEL_PREVIEW=optin))
        values = dict(item.split('=') for item in result.stdout.split())
        enabled = optin == '1' and geometry_present
        assert values == dict(early='210,60', left='296,60' if enabled else '210,60',
                              hidden='210,60', separate='350,60',
                              narrow='210,186' if enabled else '210,60',
                              right='110,60' if enabled else '400,60',
                              unrelated='410,60', reset='210,60')

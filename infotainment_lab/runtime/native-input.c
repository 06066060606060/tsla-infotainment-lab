#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdbool.h>
#include <X11/Xlib.h>
static void *desktop_touch;
static _Thread_local int native_mouse_dispatch;
static Window owned_windows[256];
static void remember_window(Window w) {
    for (int i=0;i<256;i++) if (!owned_windows[i]) { owned_windows[i]=w; return; }
}
static bool owns_window(Window w) {
    for (int i=0;i<256;i++) if (owned_windows[i]==w) return true;
    return false;
}
Window XCreateWindow(Display *d,Window parent,int x,int y,unsigned width,unsigned height,
                     unsigned border,int depth,unsigned cls,Visual *visual,unsigned long mask,XSetWindowAttributes *a) {
    static Window (*next)(Display*,Window,int,int,unsigned,unsigned,unsigned,int,unsigned,Visual*,unsigned long,XSetWindowAttributes*);
    if (!next) next=dlsym(RTLD_NEXT,"XCreateWindow");
    Window w=next(d,parent,x,y,width,height,border,depth,cls,visual,mask,a);
    remember_window(w); return w;
}
Window XCreateSimpleWindow(Display *d,Window parent,int x,int y,unsigned width,unsigned height,
                           unsigned border,unsigned long border_pixel,unsigned long background) {
    static Window (*next)(Display*,Window,int,int,unsigned,unsigned,unsigned,unsigned long,unsigned long);
    if (!next) next=dlsym(RTLD_NEXT,"XCreateSimpleWindow");
    Window w=next(d,parent,x,y,width,height,border,border_pixel,background);
    remember_window(w); return w;
}
int XDestroyWindow(Display *d,Window w) {
    static int (*next)(Display*,Window);
    if (!next) next=dlsym(RTLD_NEXT,"XDestroyWindow");
    for (int i=0;i<256;i++) if (owned_windows[i]==w) owned_windows[i]=0;
    return next(d,w);
}
/* Firmware selects paint events for its display but normally reads touch from
 * vehicle hardware. Enable standard X11 input on its desktop display window. */
int XSelectInput(Display *d, Window w, long mask) {
    static int (*next)(Display*,Window,long);
    static Window (*root)(Display*);
    static int (*geometry)(Display*,Window,Window*,int*,int*,unsigned*,unsigned*,unsigned*,unsigned*);
    if (!next) {
        next=dlsym(RTLD_NEXT,"XSelectInput");
        root=dlsym(RTLD_NEXT,"XDefaultRootWindow");
        geometry=dlsym(RTLD_NEXT,"XGetGeometry");
    }
    if ((mask & (1L<<15)) && w != root(d) && owns_window(w)) {
        Window r; int x,y; unsigned width,height,border,depth;
        if (geometry(d,w,&r,&x,&y,&width,&height,&border,&depth) && width>200 && height>200) {
            mask |= (1L<<0)|(1L<<1)|(1L<<2)|(1L<<3)|(1L<<6);
            fprintf(stderr,"Native X11 input enabled on window 0x%lx (%ux%u)\n",w,width,height);
        }
    }
    return next(d,w,mask);
}
void touch_ctor(void *self, void *display) __asm__("_ZN11TouchDeviceC1EP13DisplayDevice");
void touch_ctor(void *self, void *display) {
    static void (*next)(void*,void*);
    if (!next) next=dlsym(RTLD_NEXT,"_ZN11TouchDeviceC1EP13DisplayDevice");
    next(self,display);
    desktop_touch=self;
    fprintf(stderr,"Native mouse-to-touch adapter attached\n");
}
static void forward_mouse(void *event) {
    static void (*mouse)(void*,void*);
    if (!mouse) mouse=dlsym(RTLD_NEXT,"_ZN11TouchDevice10mouseEventEP11QMouseEvent");
    if (desktop_touch && mouse) {
        native_mouse_dispatch=1;
        mouse(desktop_touch,event);
        native_mouse_dispatch=0;
    }
}
void queue_event(void *self,int id,bool down,int x,int y,long long timestamp)
    __asm__("_ZN11TouchDriver10queueEventEibiix");
void queue_event(void *self,int id,bool down,int x,int y,long long timestamp) {
    static void (*next)(void*,int,bool,int,int,long long);
    static double *scale;
    if (!next) {
        next=dlsym(RTLD_NEXT,"_ZN11TouchDriver10queueEventEibiix");
        scale=dlsym(RTLD_DEFAULT,"_ZN13DisplayDevice11windowScaleE");
    }
    if (native_mouse_dispatch && scale && *scale > 0.1 && *scale < 4.0) {
        x=(int)(x / *scale + 0.5);
        y=(int)(y / *scale + 0.5);
    }
    next(self,id,down,x,y,timestamp);
}
void press(void *self, void *event) __asm__("_ZN19DisplayDeviceWidget15mousePressEventEP11QMouseEvent");
void press(void *self, void *event) {
    static void (*next)(void*,void*);
    if (!next) next=dlsym(RTLD_NEXT,"_ZN19DisplayDeviceWidget15mousePressEventEP11QMouseEvent");
    next(self,event);
    forward_mouse(event);
}
void release(void *self, void *event) __asm__("_ZN19DisplayDeviceWidget17mouseReleaseEventEP11QMouseEvent");
void release(void *self, void *event) { (void)self; forward_mouse(event); }
void motion(void *self, void *event) __asm__("_ZN19DisplayDeviceWidget14mouseMoveEventEP11QMouseEvent");
void motion(void *self, void *event) { (void)self; forward_mouse(event); }

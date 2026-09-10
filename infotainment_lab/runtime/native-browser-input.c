#define _GNU_SOURCE
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <dlfcn.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

/* Ordinary X11 input delivery for the firmware's off-screen composited windows.
 * Uses exported UI methods only; no binary offsets or IPC identity changes. */
typedef struct { int x,y; } Point;
typedef struct { int x1,y1,x2,y2; } Rect;
typedef struct { void *view; Display *display; Window window; Rect rect; int x,y; double origin_x,origin_y,kx,ky; bool down; } Target;
static Target targets[128];
static Target *active_target;
static Target *keyboard_target;
static struct { Target *target; XKeyEvent event; } held_keys[256];
typedef bool (*NativeEventFilter)(void *);
static NativeEventFilter previous_filter;
static bool dispatcher_installed;
static int forward_xevent(XEvent *);
static bool dispatcher_filter(void *message) {
    if (forward_xevent(message)) return true;
    return previous_filter && previous_filter(message);
}
static void install_dispatcher_filter(void) {
    if (dispatcher_installed) return;
    void *(*instance)(void *)=dlsym(RTLD_DEFAULT,"_ZN24QAbstractEventDispatcher8instanceEP7QThread");
    NativeEventFilter (*set_filter)(void *,NativeEventFilter)=dlsym(RTLD_DEFAULT,"_ZN24QAbstractEventDispatcher14setEventFilterEPFbPvE");
    if (!instance || !set_filter) return;
    void *dispatcher=instance(NULL);
    if (!dispatcher) return;
    previous_filter=set_filter(dispatcher,dispatcher_filter);
    if (previous_filter==dispatcher_filter) previous_filter=NULL;
    dispatcher_installed=true;
    fprintf(stderr,"Native browser keyboard and pointer filter attached\n");
}
static void send_button(Target *,int,int,int,unsigned);
static void clear_keyboard(Target *,bool);

static bool has_class(Display *display,Window window,const char *name,bool prefix) {
    XClassHint hint={0};
    if (!window || !XGetClassHint(display,window,&hint)) return false;
    bool result=hint.res_class && (prefix ? strncmp(hint.res_class,name,strlen(name))==0 : strcmp(hint.res_class,name)==0);
    if (hint.res_name) XFree(hint.res_name);
    if (hint.res_class) XFree(hint.res_class);
    return result;
}
static bool keyboard_visible(Target *t) {
    if (!t || !t->window || !t->display || !has_class(t->display,t->window,"TeslaMCU2-",true)) return false;
    XWindowAttributes browser,root;
    return XGetWindowAttributes(t->display,t->window,&browser) && browser.map_state==IsViewable &&
        XGetWindowAttributes(t->display,DefaultRootWindow(t->display),&root) &&
        t->rect.x2>=t->rect.x1 && t->rect.y2>=t->rect.y1 && t->rect.x2>=0 && t->rect.y2>=0 &&
        t->rect.x1<root.width && t->rect.y1<root.height;
}
static void send_key(Target *t,const XKeyEvent *original) {
    XEvent event; memset(&event,0,sizeof(event));
    event.xkey=*original;
    event.xkey.display=t->display; event.xkey.window=t->window;
    event.xkey.root=DefaultRootWindow(t->display); event.xkey.subwindow=None;
    event.xkey.same_screen=True; event.xkey.x=t->x; event.xkey.y=t->y;
    Window child;
    XTranslateCoordinates(t->display,t->window,event.xkey.root,t->x,t->y,&event.xkey.x_root,&event.xkey.y_root,&child);
    XSendEvent(t->display,t->window,False,original->type==KeyPress?KeyPressMask:KeyReleaseMask,&event);
    XFlush(t->display);
}
static void clear_keyboard(Target *t,bool destroyed) {
    if (!t) return;
    for (unsigned key=0;key<256;key++) if (held_keys[key].target==t) {
        if (!destroyed && t->window) {
            XKeyEvent event=held_keys[key].event;
            event.type=KeyRelease;
            send_key(t,&event);
        }
        held_keys[key].target=NULL;
    }
    if (keyboard_target==t) keyboard_target=NULL;
}
static void finish_drag(Target *t) {
    if (t && t->down) { send_button(t,ButtonRelease,t->x,t->y,Button1); t->down=false; }
}
static _Thread_local int resizing;
static double car_scale(void) {
    static double *scale;
    if (!scale) scale=dlsym(RTLD_DEFAULT,"_ZN13DisplayDevice11windowScaleE");
    return scale && *scale>.1 && *scale<4 ? *scale : 1;
}
static void logical_size(Display *d,Window w,unsigned *width,unsigned *height) {
    XClassHint hint={0};
    if (resizing || !XGetClassHint(d,w,&hint)) return;
    bool browser=hint.res_class && strncmp(hint.res_class,"TeslaMCU2-",10)==0;
    if (hint.res_name) XFree(hint.res_name);
    if (hint.res_class) XFree(hint.res_class);
    if (browser) {
        if (*width>100) *width=(unsigned)(*width/car_scale()+.5);
        if (*height>100) *height=(unsigned)(*height/car_scale()+.5);
    }
}
int XResizeWindow(Display *d,Window w,unsigned width,unsigned height) {
    static int (*next)(Display*,Window,unsigned,unsigned);
    if (!next) next=dlsym(RTLD_NEXT,"XResizeWindow");
    logical_size(d,w,&width,&height); resizing++;
    int result=next(d,w,width,height); resizing--; return result;
}
int XMoveResizeWindow(Display *d,Window w,int x,int y,unsigned width,unsigned height) {
    static int (*next)(Display*,Window,int,int,unsigned,unsigned);
    if (!next) next=dlsym(RTLD_NEXT,"XMoveResizeWindow");
    logical_size(d,w,&width,&height); resizing++;
    int result=next(d,w,x,y,width,height); resizing--; return result;
}
int XConfigureWindow(Display *d,Window w,unsigned mask,XWindowChanges *changes) {
    static int (*next)(Display*,Window,unsigned,XWindowChanges*);
    if (!next) next=dlsym(RTLD_NEXT,"XConfigureWindow");
    XWindowChanges c=*changes;
    unsigned width=mask&CWWidth ? c.width:0,height=mask&CWHeight ? c.height:0;
    logical_size(d,w,&width,&height);
    if (mask&CWWidth) c.width=width;
    if (mask&CWHeight) c.height=height;
    resizing++; int result=next(d,w,mask,&c); resizing--; return result;
}
static Target *target(void *view) {
    for (int i=0;i<128;i++) if (targets[i].view==view) return &targets[i];
    for (int i=0;i<128;i++) if (!targets[i].view) { targets[i].view=view; return &targets[i]; }
    return NULL;
}
bool matches(void *self,Window window,Display *display)
    __asm__("_ZN19ExternalDisplayView13windowMatchesEmP9_XDisplay");
bool matches(void *self,Window window,Display *display) {
    static bool (*next)(void*,Window,Display*);
    if (!next) next=dlsym(RTLD_NEXT,"_ZN19ExternalDisplayView13windowMatchesEmP9_XDisplay");
    bool result=next(self,window,display);
    if (result) {
        Target *t=target(self);
        if (t) { t->window=window; t->display=display; }
    }
    return result;
}
void setrect(void *self,Rect rect)
    __asm__("_ZN23ExternalDirectTouchView13setWindowRectE5QRect");
void setrect(void *self,Rect rect) {
    static void (*next)(void*,Rect);
    if (!next) next=dlsym(RTLD_NEXT,"_ZN23ExternalDirectTouchView13setWindowRectE5QRect");
    Target *t=target(self);
    if (t) {
        if (memcmp(&t->rect,&rect,sizeof(rect)) && active_target==t) {
            finish_drag(t);
            active_target=NULL;
        }
        t->rect=rect;
        if (keyboard_target==t && !keyboard_visible(t)) clear_keyboard(t,false);
    }
    next(self,rect);
}
static void send_button(Target *t,int type,int x,int y,unsigned button) {
    if (!t || !t->window || !t->display) return;
    XWindowAttributes a;
    if (!XGetWindowAttributes(t->display,t->window,&a)) return;
    XEvent e; memset(&e,0,sizeof(e));
    e.xbutton.type=type; e.xbutton.display=t->display; e.xbutton.window=t->window;
    e.xbutton.root=DefaultRootWindow(t->display); e.xbutton.same_screen=True;
    e.xbutton.x=x; e.xbutton.y=y;
    Window child;
    XTranslateCoordinates(t->display,t->window,e.xbutton.root,x,y,&e.xbutton.x_root,&e.xbutton.y_root,&child);
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC,&ts);
    e.xbutton.time=(Time)(ts.tv_sec*1000UL+ts.tv_nsec/1000000UL); e.xbutton.button=button;
    e.xbutton.state=type==ButtonRelease && button==Button1?Button1Mask:0;
    XSendEvent(t->display,t->window,False,type==ButtonPress?ButtonPressMask:ButtonReleaseMask,&e);
    XFlush(t->display);
}
static void send_motion(Target *t,int rx,int ry,unsigned modifiers) {
    int x=(int)((rx-t->origin_x)*t->kx+.5), y=(int)((ry-t->origin_y)*t->ky+.5);
    if (x==t->x && y==t->y) return;
    t->x=x; t->y=y;
    XEvent e; memset(&e,0,sizeof(e));
    e.xmotion.type=MotionNotify; e.xmotion.display=t->display; e.xmotion.window=t->window;
    e.xmotion.root=DefaultRootWindow(t->display); e.xmotion.same_screen=True;
    e.xmotion.state=modifiers|Button1Mask; e.xmotion.x=x; e.xmotion.y=y;
    Window child;
    XTranslateCoordinates(t->display,t->window,e.xmotion.root,x,y,&e.xmotion.x_root,&e.xmotion.y_root,&child);
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC,&ts);
    e.xmotion.time=(Time)(ts.tv_sec*1000UL+ts.tv_nsec/1000000UL);
    XSendEvent(t->display,t->window,False,PointerMotionMask|ButtonMotionMask|Button1MotionMask,&e);
    XFlush(t->display);
}
void touched(void *self,int id,Point point)
    __asm__("_ZN23ExternalDirectTouchView7touchedEi6QPoint");
void touched(void *self,int id,Point point) {
    static void (*next)(void*,int,Point);
    if (!next) next=dlsym(RTLD_NEXT,"_ZN23ExternalDirectTouchView7touchedEi6QPoint");
    next(self,id,point);
    Target *t=target(self);
    if (!t || !t->window) return;
    install_dispatcher_filter();
    if (keyboard_target!=t) clear_keyboard(keyboard_target,false);
    if (keyboard_visible(t)) keyboard_target=t;
    XWindowAttributes a;
    if (!XGetWindowAttributes(t->display,t->window,&a)) return;
    /* Convert from the car canvas through its display rectangle into the
     * current X11 browser's logical pixels, including expanded panels. */
    t->kx=1; t->ky=1;
    if (t->rect.x2>=t->rect.x1 && t->rect.y2>=t->rect.y1) {
        t->kx=a.width/(double)(t->rect.x2-t->rect.x1+1);
        t->ky=a.height/(double)(t->rect.y2-t->rect.y1+1);
    }
    t->x=(int)(point.x*car_scale()*t->kx+.5);
    t->y=(int)(point.y*car_scale()*t->ky+.5);
    finish_drag(active_target);
    t->down=true;
    Window root,child; int rx,ry,wx,wy; unsigned mask;
    if (XQueryPointer(t->display,DefaultRootWindow(t->display),&root,&child,&rx,&ry,&wx,&wy,&mask)) {
        t->origin_x=rx-t->x/t->kx; t->origin_y=ry-t->y/t->ky;
        active_target=t;
    }
    send_button(t,ButtonPress,t->x,t->y,Button1);
}
void released(void *self,int id)
    __asm__("_ZN23ExternalDirectTouchView8releasedEi");
void released(void *self,int id) {
    static void (*next)(void*,int);
    if (!next) next=dlsym(RTLD_NEXT,"_ZN23ExternalDirectTouchView8releasedEi");
    next(self,id);
    Target *t=target(self);
    finish_drag(t);
}

void dragged(void *self,int id,Point delta)
    __asm__("_ZN23ExternalDirectTouchView7draggedEi5QSize");
void dragged(void *self,int id,Point delta) {
    static void (*next)(void*,int,Point);
    if (!next) next=dlsym(RTLD_NEXT,"_ZN23ExternalDirectTouchView7draggedEi5QSize");
    next(self,id,delta);
    Target *t=target(self);
    if (!t || !t->down || !t->window || t->kx<=0 || t->ky<=0) return;
    Window root,child; int rx,ry,wx,wy; unsigned mask;
    if (!XQueryPointer(t->display,DefaultRootWindow(t->display),&root,&child,&rx,&ry,&wx,&wy,&mask)) return;
    send_motion(t,rx,ry,mask);
}

static int forward_xevent(XEvent *event) {
    if (event && (event->type==DestroyNotify || event->type==UnmapNotify)) {
        Window window=event->type==DestroyNotify?event->xdestroywindow.window:event->xunmap.window;
        for (int i=0;i<128;i++) if (targets[i].window==window) {
            clear_keyboard(&targets[i],event->type==DestroyNotify);
            if (event->type==UnmapNotify) finish_drag(&targets[i]);
            targets[i].down=false;
            if (active_target==&targets[i]) active_target=NULL;
            if (event->type==DestroyNotify) { targets[i].window=0; targets[i].view=NULL; }
        }
    }
    Target *t=active_target;
    Target *keyboard=keyboard_target;
    if (keyboard && event && !event->xany.send_event && event->xany.window!=keyboard->window) {
        if (!keyboard_visible(keyboard)) {
            clear_keyboard(keyboard,false);
        } else if (event->type==ButtonPress && event->xbutton.button==Button1 &&
                   (event->xbutton.x_root<keyboard->rect.x1 || event->xbutton.x_root>keyboard->rect.x2 ||
                    event->xbutton.y_root<keyboard->rect.y1 || event->xbutton.y_root>keyboard->rect.y2)) {
            clear_keyboard(keyboard,false);
        } else if (event->type==FocusOut && event->xfocus.mode==NotifyNormal) {
            clear_keyboard(keyboard,false);
        } else if ((event->type==KeyPress || event->type==KeyRelease) && event->xkey.keycode<256 &&
                   has_class(event->xkey.display,event->xkey.window,"QtCar",false)) {
            unsigned key=event->xkey.keycode;
            if (event->type==KeyPress) {
                held_keys[key].target=keyboard;
                held_keys[key].event=event->xkey;
            } else if (held_keys[key].target!=keyboard) {
                return 0;
            } else {
                held_keys[key].target=NULL;
            }
            send_key(keyboard,&event->xkey);
            return 1;
        }
    }
    if (t && event && !event->xany.send_event && event->xany.window!=t->window) {
        if ((event->type==ButtonPress || event->type==ButtonRelease) &&
            event->xbutton.button>=4 && event->xbutton.button<=7) {
            int x=(int)((event->xbutton.x_root-t->origin_x)*t->kx+.5);
            int y=(int)((event->xbutton.y_root-t->origin_y)*t->ky+.5);
            XWindowAttributes a;
            if (XGetWindowAttributes(t->display,t->window,&a) && a.map_state==IsViewable &&
                x>=0 && y>=0 && x<a.width && y<a.height) {
                send_button(t,event->type,x,y,event->xbutton.button);
                return 1;
            }
        } else if (event->type==MotionNotify && t->down) {
            send_motion(t,event->xmotion.x_root,event->xmotion.y_root,event->xmotion.state);
        } else if (event->type==ButtonRelease && event->xbutton.button==Button1 && t->down) {
            send_motion(t,event->xbutton.x_root,event->xbutton.y_root,event->xbutton.state);
            finish_drag(t);
        }
    }
    return 0;
}

/* Preserve compatibility with callers using XIM or the exported Qt entry
 * point. Normal physical input uses the registered native-event filter above;
 * this firmware does not call XFilterEvent for every keyboard event. */
Bool XFilterEvent(XEvent *event,Window window) {
    static Bool (*next)(XEvent*,Window);
    if (!next) next=dlsym(RTLD_NEXT,"XFilterEvent");
    if (forward_xevent(event)) return True;
    return next(event,window);
}

int process_xevent(void *self,XEvent *event)
    __asm__("_ZN12QApplication15x11ProcessEventEP7_XEvent");
int process_xevent(void *self,XEvent *event) {
    static int (*next)(void*,XEvent*);
    if (!next) next=dlsym(RTLD_NEXT,"_ZN12QApplication15x11ProcessEventEP7_XEvent");
    if (forward_xevent(event)) return 1;
    return next(self,event);
}

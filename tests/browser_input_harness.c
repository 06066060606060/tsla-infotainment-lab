/* An ordinary X11 event receiver and small UI stubs for the input adapter.
 * It runs only on the test's private nested X server. No firmware is loaded. */
#define _POSIX_C_SOURCE 200809L
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/keysym.h>
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <sys/select.h>

typedef struct { int x,y; } Point;
typedef struct { int x1,y1,x2,y2; } Rect;

bool matches(void *,Window,Display *) __asm__("_ZN19ExternalDisplayView13windowMatchesEmP9_XDisplay");
void setrect(void *,Rect) __asm__("_ZN23ExternalDirectTouchView13setWindowRectE5QRect");
void touched(void *,int,Point) __asm__("_ZN23ExternalDirectTouchView7touchedEi6QPoint");
void released(void *,int) __asm__("_ZN23ExternalDirectTouchView8releasedEi");
void dragged(void *,int,Point) __asm__("_ZN23ExternalDirectTouchView7draggedEi5QSize");
int process_xevent(void *,XEvent *) __asm__("_ZN12QApplication15x11ProcessEventEP7_XEvent");
typedef bool (*NativeEventFilter)(void *);
bool dispatch_event(void *);
extern unsigned original_filter_calls;

#ifdef UI_STUB
unsigned original_filter_calls;
static bool original_filter(void *event) { (void)event; original_filter_calls++; return false; }
static NativeEventFilter current_filter=original_filter;
static int dispatcher;
void *dispatcher_instance(void *) __asm__("_ZN24QAbstractEventDispatcher8instanceEP7QThread");
void *dispatcher_instance(void *thread) { (void)thread; return &dispatcher; }
NativeEventFilter dispatcher_set_filter(void *,NativeEventFilter) __asm__("_ZN24QAbstractEventDispatcher14setEventFilterEPFbPvE");
NativeEventFilter dispatcher_set_filter(void *self,NativeEventFilter filter) {
    assert(self==&dispatcher);
    NativeEventFilter previous=current_filter;
    current_filter=filter;
    return previous;
}
bool dispatch_event(void *event) { return current_filter(event); }
double window_scale __asm__("_ZN13DisplayDevice11windowScaleE") = .6;
bool matches(void *view,Window window,Display *display) {
    (void)view; (void)window; (void)display; return true;
}
void setrect(void *view,Rect rect) { (void)view; (void)rect; }
void touched(void *view,int id,Point point) { (void)view; (void)id; (void)point; }
void released(void *view,int id) { (void)view; (void)id; }
void dragged(void *view,int id,Point point) { (void)view; (void)id; (void)point; }
int process_xevent(void *view,XEvent *event) { (void)view; (void)event; return 0; }
#else
static XEvent receive(Display *display,int expected_type,int x,int y,unsigned button) {
    XSync(display,False);
    if (!XPending(display)) {
        fd_set files; FD_ZERO(&files); FD_SET(ConnectionNumber(display),&files);
        struct timeval timeout={3,0};
        assert(select(ConnectionNumber(display)+1,&files,NULL,NULL,&timeout)>0);
    }
    XEvent event;
    XNextEvent(display,&event);
    if (event.type!=expected_type || event.xbutton.x!=x || event.xbutton.y!=y) {
        fprintf(stderr,"Expected event %d at %d,%d; got %d at %d,%d\n",
                expected_type,x,y,event.type,event.xbutton.x,event.xbutton.y);
    }
    assert(event.type==expected_type);
    assert(event.xbutton.x==x && event.xbutton.y==y);
    if (expected_type==ButtonPress || expected_type==ButtonRelease)
        assert(event.xbutton.button==button);
    assert(event.xany.send_event);
    return event;
}

static void no_events(Display *display) {
    XSync(display,False);
    assert(!XPending(display));
}

static XEvent pointer_event(Display *display,Window root,int type,int x,int y,unsigned button) {
    XEvent event; memset(&event,0,sizeof(event));
    event.xbutton.type=type;
    event.xbutton.display=display;
    event.xbutton.window=root;
    event.xbutton.root=root;
    event.xbutton.x_root=x;
    event.xbutton.y_root=y;
    event.xbutton.same_screen=True;
    event.xbutton.button=button;
    return event;
}

static bool use_x11_filter;
static bool use_dispatcher;
static void key_event(Display *display,Window source,int type,KeySym symbol,unsigned state,int consumed) {
    XEvent event; memset(&event,0,sizeof(event));
    event.xkey.type=type;
    event.xkey.display=display; event.xkey.window=source;
    event.xkey.root=DefaultRootWindow(display); event.xkey.same_screen=True;
    event.xkey.keycode=XKeysymToKeycode(display,symbol); event.xkey.state=state;
    event.xkey.time=12345;
    unsigned prior=original_filter_calls;
    int result=use_dispatcher?dispatch_event(&event):use_x11_filter?XFilterEvent(&event,None):process_xevent(NULL,&event);
    assert(result==consumed);
    if (use_dispatcher) assert(original_filter_calls==prior+(consumed?0:1));
    if (consumed) {
        XEvent delivered=receive(display,type,100,200,0);
        assert(delivered.xkey.keycode==event.xkey.keycode);
        assert(delivered.xkey.state==state && delivered.xkey.time==12345);
        assert(delivered.xkey.x_root==1300 && delivered.xkey.y_root==2120);
    } else no_events(display);
}

int main(void) {
    Display *display=XOpenDisplay(NULL);
    assert(display);
    Window root=DefaultRootWindow(display);
    Window browser=XCreateSimpleWindow(display,root,1200,1920,1200,1920,0,0,0);
    XClassHint browser_class={"input-test","TeslaMCU2-test"};
    XSetClassHint(display,browser,&browser_class);
    XSelectInput(display,browser,ButtonPressMask|ButtonReleaseMask|PointerMotionMask|KeyPressMask|KeyReleaseMask);
    XMapWindow(display,browser);
    XSync(display,False);

    /* The compositor requests physical dimensions; Chromium keeps logical ones. */
    XMoveResizeWindow(display,browser,1200,1920,720,1152);
    XWindowAttributes geometry;
    XGetWindowAttributes(display,browser,&geometry);
    assert(geometry.x==1200 && geometry.y==1920);
    assert(geometry.width==1200 && geometry.height==1920);
    XResizeWindow(display,browser,360,600);
    XGetWindowAttributes(display,browser,&geometry);
    assert(geometry.width==600 && geometry.height==1000);
    XWindowChanges changes={.width=720,.height=1152};
    XConfigureWindow(display,browser,CWWidth|CWHeight,&changes);
    XGetWindowAttributes(display,browser,&geometry);
    assert(geometry.width==1200 && geometry.height==1920);
    assert(changes.width==720 && changes.height==1152);
    Window ordinary=XCreateSimpleWindow(display,root,0,0,100,100,0,0,0);
    XClassHint ordinary_class={"other-test","OtherApplication"};
    XSetClassHint(display,ordinary,&ordinary_class);
    XResizeWindow(display,ordinary,720,480);
    XGetWindowAttributes(display,ordinary,&geometry);
    assert(geometry.width==720 && geometry.height==480);
    Window car=XCreateSimpleWindow(display,root,0,0,720,800,0,0,0);
    XClassHint car_class={"QtCar","QtCar"};
    XSetClassHint(display,car,&car_class);

    int view=1;
    assert(matches(&view,browser,display));
    setrect(&view,(Rect){0,0,719,1151});
    XWarpPointer(display,None,root,0,0,0,0,60,120);
    XSync(display,False);
    touched(&view,0,(Point){100,200});
    XEvent event=receive(display,ButtonPress,100,200,Button1);
    assert(event.xbutton.state==0);
    assert(event.xbutton.x_root==1300 && event.xbutton.y_root==2120);

    XWarpPointer(display,None,root,0,0,0,0,120,180);
    XSync(display,False);
    dragged(&view,0,(Point){100,100});
    event=receive(display,MotionNotify,200,300,0);
    assert(event.xmotion.state & Button1Mask);

    event=pointer_event(display,root,MotionNotify,150,210,0);
    event.xmotion.state=ShiftMask;
    process_xevent(&view,&event);
    event=receive(display,MotionNotify,250,350,0);
    assert(event.xmotion.state==(ShiftMask|Button1Mask));

    /* Release beyond the displayed card: a drag must not become stuck. */
    event=pointer_event(display,root,ButtonRelease,840,750,Button1);
    process_xevent(&view,&event);
    receive(display,MotionNotify,1400,1250,0);
    event=receive(display,ButtonRelease,1400,1250,Button1);
    assert(event.xbutton.state==Button1Mask);
    released(&view,0);
    no_events(display);

    /* Wheel remains usable after release and does not inherit Button1. */
    event=pointer_event(display,root,ButtonPress,120,180,Button4);
    assert(process_xevent(&view,&event)==1);
    event=receive(display,ButtonPress,200,300,Button4);
    assert(event.xbutton.state==0);
    event=pointer_event(display,root,ButtonRelease,120,180,Button4);
    assert(process_xevent(&view,&event)==1);
    event=receive(display,ButtonRelease,200,300,Button4);
    assert(event.xbutton.state==0);

    /* A viewport change releases the old drag and discards its transform. */
    XWarpPointer(display,None,root,0,0,0,0,60,120);
    XSync(display,False);
    touched(&view,0,(Point){100,200});
    receive(display,ButtonPress,100,200,Button1);
    setrect(&view,(Rect){0,0,1199,719});
    receive(display,ButtonRelease,100,200,Button1);
    event=pointer_event(display,root,MotionNotify,150,210,0);
    process_xevent(&view,&event);
    event=pointer_event(display,root,ButtonPress,120,180,Button4);
    assert(process_xevent(&view,&event)==0);
    released(&view,0);
    no_events(display);

    /* Direct release callbacks emit one release, even if called twice. */
    setrect(&view,(Rect){0,0,719,1151});
    touched(&view,0,(Point){100,200});
    receive(display,ButtonPress,100,200,Button1);
    released(&view,0);
    receive(display,ButtonRelease,100,200,Button1);
    released(&view,0);
    no_events(display);
    /* The last clicked browser receives physical keys once, including the
     * original keycode/modifiers needed for selection and keyboard shortcuts. */
    key_event(display,car,KeyPress,XK_Control_L,0,1);
    key_event(display,car,KeyPress,XK_a,ControlMask,1);
    key_event(display,car,KeyRelease,XK_a,ControlMask,1);
    key_event(display,car,KeyPress,XK_c,ControlMask,1);
    key_event(display,car,KeyRelease,XK_c,ControlMask,1);
    key_event(display,car,KeyPress,XK_v,ControlMask,1);
    key_event(display,car,KeyRelease,XK_v,ControlMask,1);
    key_event(display,car,KeyRelease,XK_Control_L,ControlMask,1);
    key_event(display,car,KeyPress,XK_A,ShiftMask,1);
    key_event(display,car,KeyRelease,XK_A,ShiftMask,1);
    key_event(display,ordinary,KeyPress,XK_a,0,0);
    key_event(display,browser,KeyPress,XK_a,0,0);
    use_x11_filter=true;
    key_event(display,car,KeyPress,XK_Control_L,0,1);
    key_event(display,car,KeyPress,XK_a,ControlMask,1);
    key_event(display,car,KeyRelease,XK_a,ControlMask,1);
    key_event(display,car,KeyRelease,XK_Control_L,ControlMask,1);
    use_x11_filter=false;
    use_dispatcher=true;
    key_event(display,car,KeyPress,XK_Control_L,0,1);
    key_event(display,car,KeyPress,XK_a,ControlMask,1);
    key_event(display,car,KeyRelease,XK_a,ControlMask,1);
    key_event(display,car,KeyPress,XK_c,ControlMask,1);
    key_event(display,car,KeyRelease,XK_c,ControlMask,1);
    key_event(display,car,KeyPress,XK_v,ControlMask,1);
    key_event(display,car,KeyRelease,XK_v,ControlMask,1);
    key_event(display,car,KeyRelease,XK_Control_L,ControlMask,1);
    key_event(display,ordinary,KeyPress,XK_a,0,0);
    use_dispatcher=false;

    /* Chromium's keyboard overlay may resize the viewport after a text click;
     * keep keyboard focus while the browser view remains on the car canvas. */
    setrect(&view,(Rect){0,0,719,799});
    key_event(display,car,KeyPress,XK_b,0,1);
    key_event(display,car,KeyRelease,XK_b,0,1);
    key_event(display,car,KeyPress,XK_Control_L,0,1);
    setrect(&view,(Rect){0,-1920,719,-1121});
    event=receive(display,KeyRelease,100,200,0);
    assert(event.xkey.keycode==XKeysymToKeycode(display,XK_Control_L));
    key_event(display,car,KeyPress,XK_c,ControlMask,0);

    setrect(&view,(Rect){0,0,719,799});
    XWarpPointer(display,None,root,0,0,0,0,60,50);
    XSync(display,False);
    touched(&view,0,(Point){100,200});
    receive(display,ButtonPress,100,288,Button1);
    released(&view,0);
    receive(display,ButtonRelease,100,288,Button1);
    event=pointer_event(display,car,ButtonPress,10,820,Button1);
    process_xevent(NULL,&event);
    key_event(display,car,KeyPress,XK_a,0,0);
    no_events(display);
    XDestroyWindow(display,car);

    XDestroyWindow(display,ordinary);
    XDestroyWindow(display,browser);
    XCloseDisplay(display);
    puts("X11 browser drag, release, wheel and resize passed; keyboard shortcuts and focus passed");
    return 0;
}
#endif

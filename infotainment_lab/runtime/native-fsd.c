#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>
#include <stddef.h>
#include <stdatomic.h>
#include <string.h>
#include <ctype.h>
#include <time.h>

/* Build the optional native FSD panel before late desktop profile writes arrive.
 * Scope the capability to markup construction: other firmware managers must
 * keep their own capability checks, particularly before AP data is initialized. */
static _Thread_local unsigned fsd_markup_construction;
static bool fsd_ui_ready;
static _Thread_local bool fsd_is_ui_thread, fsd_refreshing;
static void refresh_simulation(void);
static void repair_fsd_navigation_overlap(void);

static bool fsd_panel_preview_enabled(void) {
    const char *value = getenv("TESLA_NATIVE_FSD_PANEL_PREVIEW");
    return value && value[0] == '1' && value[1] == '\0';
}

void fsd_load_markup(void *self, const void *name)
    __asm__("_ZN13ClusterWindow8loadUIMLERK7QString");
void fsd_load_markup(void *self, const void *name) {
    static void (*next)(void *, const void *);
    if (!next) next = dlsym(RTLD_NEXT, "_ZN13ClusterWindow8loadUIMLERK7QString");
    if (!next) abort();
    fsd_markup_construction++;
    next(self, name);
    fsd_markup_construction--;
}

bool fsd_panel_capability(void) __asm__("_ZN12VehicleUtils11hasFsdPanelEv");
bool fsd_panel_capability(void) {
    static bool (*next)(void);
    if (!next) next = dlsym(RTLD_NEXT, "_ZN12VehicleUtils11hasFsdPanelEv");
    bool native = next ? next() : false;
    return native || (next && fsd_markup_construction && fsd_panel_preview_enabled());
}

/* Preview an unavailable button without supplying AP readiness or engagement.
 * The native outer panel guards and the driver's preferences still apply. */
bool fsd_start_view_visible(void *self)
    __asm__("_ZNK8FsdPanel12FsdPanelView22shouldShowStartFsdViewEv");
bool fsd_start_view_visible(void *self) {
    static bool (*next)(void *);
    static bool (*configured)(void);
    static bool (*active)(void);
    if (!next) next = dlsym(RTLD_NEXT, "_ZNK8FsdPanel12FsdPanelView22shouldShowStartFsdViewEv");
    if (!next) return false;
    bool native = next(self);
    if (!fsd_panel_preview_enabled()) return native;
    if (!fsd_ui_ready || fsd_markup_construction) return false;
    if (native) return true;
    if (!configured) configured = dlsym(RTLD_NEXT, "_ZN12VehicleUtils27startFsdFromFsdPanelEnabledEv");
    if (!active) active = dlsym(RTLD_NEXT, "_ZN12VehicleUtils11isFSDActiveEv");
    return configured && active && configured() && !active();
}

/* Defer visibility/state publication until the center display has completed
 * its native view construction. Hidden panels receive no tick callbacks. */
static void *fsd_panel_view;
void fsd_panel_init(void *self) __asm__("_ZN8FsdPanel12FsdPanelView4initEv");
void fsd_panel_init(void *self) {
    static void (*next)(void *);
    if (!next) next = dlsym(RTLD_NEXT, "_ZN8FsdPanel12FsdPanelView4initEv");
    if (next) next(self);
    fsd_panel_view = self;
}
void fsd_create_views(void *self) __asm__("_ZN13CenterDisplay11createViewsEv");
void fsd_create_views(void *self) {
    static void (*next)(void *);
    static void (*update)(void *);
    if (!next) next = dlsym(RTLD_NEXT, "_ZN13CenterDisplay11createViewsEv");
    if (!next) return;
    next(self);
    if (!fsd_panel_preview_enabled()) return;
    fsd_ui_ready = true;
    fsd_is_ui_thread = true;
    refresh_simulation();
    if (!update) update = dlsym(RTLD_NEXT, "_ZN8FsdPanel12FsdPanelView11updateStateEv");
    if (update && fsd_panel_view) update(fsd_panel_view);
}

/* The single-display preview also exposes the panel in driver-side layouts.
 * Native navigation reserves its width only on the passenger side. Keep both
 * views readable using their public, rendered geometry in cluster coordinates.
 * QRect is four ints (inclusive edges), returned in registers on this Qt4 ABI. */
typedef struct { int left, top, right, bottom; } NativeRect;
static void *fsd_cluster_window, *fsd_turn_list;
static _Thread_local void *fsd_turn_layout;
static _Thread_local bool fsd_repairing_layout;

static void repair_fsd_navigation_overlap(void) {
    if (!fsd_ui_ready || !fsd_panel_preview_enabled() || fsd_repairing_layout
            || !fsd_panel_view || !fsd_cluster_window || !fsd_turn_list) return;
    static NativeRect (*rect)(const void *, void *);
    static bool (*visible)(void *, void *);
    static void *(*parent)(void *);
    static void (*move)(void *, int, int, double, int, double);
    if (!rect) rect = dlsym(RTLD_NEXT, "_ZNK11DisplayView20relativePositionRectEPS_");
    if (!parent) parent = dlsym(RTLD_NEXT, "_ZN11DisplayView10parentViewEv");
    if (!visible) visible = dlsym(RTLD_NEXT, "_ZN11DisplayView9isVisibleEPS_");
    if (!move) move = dlsym(RTLD_NEXT, "_ZN11DisplayView6moveToEiidN17InterpolatedValue8EaseTypeEd");
    if (!rect || !visible || !parent || !move || !visible(fsd_panel_view, NULL)
            || !visible(fsd_turn_list, NULL)) return;
    NativeRect panel = rect(fsd_panel_view, fsd_cluster_window);
    NativeRect turn = rect(fsd_turn_list, fsd_cluster_window);
    NativeRect viewport = rect(fsd_cluster_window, fsd_cluster_window);
    if (panel.right < panel.left || panel.bottom < panel.top
            || turn.right < turn.left || turn.bottom < turn.top
            || viewport.right < viewport.left || viewport.bottom < viewport.top
            || panel.left > turn.right || turn.left > panel.right
            || panel.top > turn.bottom || turn.top > panel.bottom) return;
    const int gap = 20;
    int width = turn.right - turn.left + 1;
    int x = turn.left, y = turn.top;
    if (panel.left + (panel.right - panel.left) / 2
            <= viewport.left + (viewport.right - viewport.left) / 2) {
        if (panel.right + gap + width <= viewport.right) x = panel.right + gap + 1;
        else y = panel.bottom + gap + 1;
    } else {
        if (panel.left - gap - width >= viewport.left) x = panel.left - gap - width;
        else y = panel.bottom + gap + 1;
    }
    /* moveTo expects parent coordinates, which can differ from cluster space. */
    NativeRect parent_rect = rect(fsd_turn_list, parent(fsd_turn_list));
    fsd_repairing_layout = true;
    move(fsd_turn_list, parent_rect.left + x - turn.left,
         parent_rect.top + y - turn.top, 0, 2, 0);
    fsd_repairing_layout = false;
}

void fsd_update_turn_layout(void *self) __asm__("_ZN13ClusterWindow20updateTurnListLayoutEv");
void fsd_update_turn_layout(void *self) {
    static void (*next)(void *);
    if (!next) next = dlsym(RTLD_NEXT, "_ZN13ClusterWindow20updateTurnListLayoutEv");
    if (!next) return;
    void *previous = fsd_turn_layout;
    fsd_turn_layout = fsd_panel_preview_enabled() ? self : NULL;
    next(self);
    fsd_turn_layout = previous;
    repair_fsd_navigation_overlap();
}

/* Capture only the navigation view positioned by the native layout method. */
void fsd_move_to(void *self, int x, int y, double duration, int ease, double delay)
    __asm__("_ZN11DisplayView6moveToEiidN17InterpolatedValue8EaseTypeEd");
void fsd_move_to(void *self, int x, int y, double duration, int ease, double delay) {
    static void (*next)(void *, int, int, double, int, double);
    if (!next) next = dlsym(RTLD_NEXT, "_ZN11DisplayView6moveToEiidN17InterpolatedValue8EaseTypeEd");
    if (!next) return;
    if (fsd_turn_layout) { fsd_cluster_window = fsd_turn_layout; fsd_turn_list = self; }
    next(self, x, y, duration, ease, delay);
}
#define FSD_MOVE_EDGE(NAME, SYMBOL) \
void NAME(void *self, int position, double duration, int ease, double delay) __asm__(SYMBOL); \
void NAME(void *self, int position, double duration, int ease, double delay) { \
    static void (*next)(void *, int, double, int, double); \
    if (!next) next = dlsym(RTLD_NEXT, SYMBOL); \
    if (!next) return; \
    if (fsd_turn_layout) { fsd_cluster_window = fsd_turn_layout; fsd_turn_list = self; } \
    next(self, position, duration, ease, delay); \
}
FSD_MOVE_EDGE(fsd_move_right, "_ZN11DisplayView9moveRightEidN17InterpolatedValue8EaseTypeEd")
FSD_MOVE_EDGE(fsd_move_top, "_ZN11DisplayView7moveTopEidN17InterpolatedValue8EaseTypeEd")

/* Opaque, over-sized storage for the tested Qt4 QVariant and native EventLocker
 * ABI. Native constructors/destructors own their layout; no DV offsets are used. */
typedef union { max_align_t align; unsigned char bytes[128]; } NativeStorage;
typedef struct { int value; const char *name; } EnumName;
static struct {
    void (*lock)(void *, void *);
    void (*unlock)(void *);
    void (*variant)(void *, int);
    void (*destroy)(void *);
    void (*get)(void *, const void *, bool *);
    void (*set)(void *, const void *, bool);
    void (*invalidate)(void *);
    void *start, *stop, *reason, *ap;
    int available, unavailable, stop_available, stop_unavailable, none, idle, active;
    bool ready;
} fsd_abi;
static _Atomic bool simulation_running, simulation_engaged;
static NativeStorage previous_ap;
static bool previous_ap_valid;

static bool enum_value(const char *table, const char *name, int *value) {
    const EnumName *items = dlsym(RTLD_DEFAULT, table);
    if (!items) return false;
    for (int j = 0; j < 256 && items[j].name && items[j].name[0]; j++) {
        if (!strcmp(items[j].name, name)) { *value = items[j].value; return true; }
    }
    return false;
}

static bool prepare_simulation_abi(void) {
    if (fsd_abi.ready) return true;
    fsd_abi.lock = dlsym(RTLD_NEXT, "_ZN9DataValue11EventLockerC1ERS_");
    fsd_abi.unlock = dlsym(RTLD_NEXT, "_ZN9DataValue11EventLockerD1Ev");
    fsd_abi.variant = dlsym(RTLD_NEXT, "_ZN8QVariantC1Ei");
    fsd_abi.destroy = dlsym(RTLD_NEXT, "_ZN8QVariantD1Ev");
    fsd_abi.get = dlsym(RTLD_NEXT, "_ZNK9DataValue15atomicGetNoLockEPb");
    fsd_abi.set = dlsym(RTLD_NEXT, "_ZN9DataValue14setValueNoLockERK8QVariantb");
    fsd_abi.invalidate = dlsym(RTLD_NEXT, "_ZN9DataValue16setInvalidNoLockEv");
    fsd_abi.start = dlsym(RTLD_DEFAULT, "GUI_startFsdButtonState");
    fsd_abi.stop = dlsym(RTLD_DEFAULT, "GUI_stopFsdButtonState");
    fsd_abi.reason = dlsym(RTLD_DEFAULT, "GUI_startFsdButtonUnavailableReason");
    fsd_abi.ap = dlsym(RTLD_DEFAULT, "DAS_autopilotState");
    fsd_abi.ready = fsd_abi.lock && fsd_abi.unlock && fsd_abi.variant && fsd_abi.destroy
        && fsd_abi.get && fsd_abi.set && fsd_abi.invalidate && fsd_abi.start
        && fsd_abi.stop && fsd_abi.reason && fsd_abi.ap
        && enum_value("StartFsdButtonStateNameMap", "Available", &fsd_abi.available)
        && enum_value("StartFsdButtonStateNameMap", "Unavailable", &fsd_abi.unavailable)
        && enum_value("StopFsdButtonStateNameMap", "Available", &fsd_abi.stop_available)
        && enum_value("StopFsdButtonStateNameMap", "Unavailable", &fsd_abi.stop_unavailable)
        && enum_value("StartFsdButtonUnavailableReasonNameMap", "ReasonNone", &fsd_abi.none)
        && enum_value("AutopilotStateNameMap", "Available", &fsd_abi.idle)
        && enum_value("AutopilotStateNameMap", "ActiveFsd", &fsd_abi.active);
    static bool warned;
    if (!fsd_abi.ready && !warned) {
        warned = true;
        fprintf(stderr, "Self-Driving UI simulation unavailable: native ABI or enums do not match\n");
    }
    return fsd_abi.ready;
}

static void set_enum_locked(void *dv, int value) {
    NativeStorage variant;
    fsd_abi.variant(&variant, value);
    fsd_abi.set(dv, &variant, false);
    fsd_abi.destroy(&variant);
}

static void set_enum(void *dv, int value) {
    NativeStorage lock;
    fsd_abi.lock(&lock, dv);
    set_enum_locked(dv, value);
    fsd_abi.unlock(&lock);
}

static void publish_simulation(void) {
    bool engaged = atomic_load(&simulation_engaged);
    set_enum(fsd_abi.ap, engaged ? fsd_abi.active : fsd_abi.idle);
    set_enum(fsd_abi.start, engaged ? fsd_abi.unavailable : fsd_abi.available);
    set_enum(fsd_abi.stop, engaged ? fsd_abi.stop_available : fsd_abi.stop_unavailable);
    set_enum(fsd_abi.reason, fsd_abi.none);
}

static bool simulation_requested(void) {
    const char *state = getenv("TESLA_NATIVE_STATE");
    if (!state) return false;
    char path[4096], data[8192];
    int size = snprintf(path, sizeof(path), "%s/vehicle-services.json", state);
    if (size < 0 || (size_t)size >= sizeof(path)) return false;
    FILE *file = fopen(path, "r");
    if (!file) return false;
    size_t length = fread(data, 1, sizeof(data) - 1, file);
    bool complete = !ferror(file) && feof(file);
    fclose(file); data[length] = '\0';
    if (!complete) return false;
    const char *key = strstr(data, "\"fsd_ui_simulation\"");
    if (!key) return false;
    key += strlen("\"fsd_ui_simulation\"");
    while (isspace((unsigned char)*key)) key++;
    if (*key++ != ':') return false;
    while (isspace((unsigned char)*key)) key++;
    return !strncmp(key, "true", 4) && (key[4] == ',' || key[4] == '}' || isspace((unsigned char)key[4]));
}

static void refresh_simulation_inner(void) {
    static double checked;
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    double tick = now.tv_sec + now.tv_nsec / 1e9;
    if (tick - checked < .2) return;
    checked = tick;
    repair_fsd_navigation_overlap();
    static bool (*configured)(void);
    if (!configured) configured = dlsym(RTLD_NEXT, "_ZN12VehicleUtils27startFsdFromFsdPanelEnabledEv");
    bool wanted = fsd_ui_ready && fsd_panel_preview_enabled() && configured
        && configured() && simulation_requested() && prepare_simulation_abi();
    if (wanted == atomic_load(&simulation_running)) return;
    atomic_store(&simulation_engaged, false);
    if (wanted) {
        NativeStorage lock;
        fsd_abi.lock(&lock, fsd_abi.ap);
        fsd_abi.get(&previous_ap, fsd_abi.ap, &previous_ap_valid);
        fsd_abi.unlock(&lock);
        atomic_store(&simulation_running, true);
        publish_simulation();
        fprintf(stderr, "Self-Driving UI simulation enabled; no driving controller\n");
    } else {
        atomic_store(&simulation_running, false);
        NativeStorage lock;
        fsd_abi.lock(&lock, fsd_abi.ap);
        if (previous_ap_valid) fsd_abi.set(fsd_abi.ap, &previous_ap, false);
        else {
            int disabled;
            if (enum_value("AutopilotStateNameMap", "Disabled", &disabled)) set_enum_locked(fsd_abi.ap, disabled);
            fsd_abi.invalidate(fsd_abi.ap);
        }
        fsd_abi.unlock(&lock);
        fsd_abi.destroy(&previous_ap);
        set_enum(fsd_abi.start, fsd_abi.unavailable);
        set_enum(fsd_abi.stop, fsd_abi.stop_unavailable);
        fprintf(stderr, "Self-Driving UI simulation disabled\n");
    }
}

static void refresh_simulation(void) {
    if (!fsd_is_ui_thread || fsd_refreshing) return;
    fsd_refreshing = true;
    refresh_simulation_inner();
    fsd_refreshing = false;
}

/* Preserve native manager work. Replace only the four opted-in UI fields before
 * their EventLocker commits, so observers never see alternating native/sim states. */
static _Thread_local struct { void *lock, *dv; } watched_locks[16];
static bool simulation_value(void *dv, int *value) {
    if (!atomic_load(&simulation_running)) return false;
    bool engaged = atomic_load(&simulation_engaged);
    if (dv == fsd_abi.start) *value = engaged ? fsd_abi.unavailable : fsd_abi.available;
    else if (dv == fsd_abi.stop) *value = engaged ? fsd_abi.stop_available : fsd_abi.stop_unavailable;
    else if (dv == fsd_abi.reason) *value = fsd_abi.none;
    else if (dv == fsd_abi.ap) *value = engaged ? fsd_abi.active : fsd_abi.idle;
    else return false;
    return true;
}

#define FSD_LOCK_CTOR(N) \
void fsd_lock_##N(void *self, void *dv) __asm__("_ZN9DataValue11EventLockerC" #N "ERS_"); \
void fsd_lock_##N(void *self, void *dv) { \
    static void (*next)(void *, void *); \
    if (!next) next = dlsym(RTLD_NEXT, "_ZN9DataValue11EventLockerC" #N "ERS_"); \
    if (!next) abort(); \
    next(self, dv); \
    int value; \
    if (simulation_value(dv, &value)) { \
        for (int j = 0; j < 16; j++) if (!watched_locks[j].lock) { \
            watched_locks[j].lock = self; watched_locks[j].dv = dv; break; \
        } \
    } \
}
FSD_LOCK_CTOR(1)
FSD_LOCK_CTOR(2)

#define FSD_LOCK_DTOR(N) \
void fsd_unlock_##N(void *self) __asm__("_ZN9DataValue11EventLockerD" #N "Ev"); \
void fsd_unlock_##N(void *self) { \
    static void (*next)(void *); \
    if (!next) next = dlsym(RTLD_NEXT, "_ZN9DataValue11EventLockerD" #N "Ev"); \
    if (!next) abort(); \
    for (int j = 0; j < 16; j++) if (watched_locks[j].lock == self) { \
        int value; \
        if (simulation_value(watched_locks[j].dv, &value)) set_enum_locked(watched_locks[j].dv, value); \
        watched_locks[j].lock = NULL; watched_locks[j].dv = NULL; break; \
    } \
    next(self); \
    refresh_simulation(); \
}
FSD_LOCK_DTOR(1)
FSD_LOCK_DTOR(2)

/* C++ identifiers include the length of the complete method name. */
void fsd_start_request(void *self) __asm__("_ZN18StartFsdController21submitStartFsdRequestEv");
void fsd_start_request(void *self) {
    refresh_simulation();
    if (atomic_load(&simulation_running)) {
        atomic_store(&simulation_engaged, true); publish_simulation();
        fprintf(stderr, "Self-Driving UI simulation engaged\n"); return;
    }
    static void (*next)(void *);
    if (!next) next = dlsym(RTLD_NEXT, "_ZN18StartFsdController21submitStartFsdRequestEv");
    if (next) next(self);
}
void fsd_stop_request(void *self) __asm__("_ZN18StartFsdController20submitStopFsdRequestEv");
void fsd_stop_request(void *self) {
    refresh_simulation();
    if (atomic_load(&simulation_running)) {
        atomic_store(&simulation_engaged, false); publish_simulation();
        fprintf(stderr, "Self-Driving UI simulation stopped\n"); return;
    }
    static void (*next)(void *);
    if (!next) next = dlsym(RTLD_NEXT, "_ZN18StartFsdController20submitStopFsdRequestEv");
    if (next) next(self);
}

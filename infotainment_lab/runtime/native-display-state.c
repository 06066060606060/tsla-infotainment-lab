/* Avoid an ICE splash-screen callback dereferencing an uninitialized display state.
 * The 2026.26.6.5 x86_64 implementation reads its active state at offset 0x58
 * before checking it. Match that function's instruction sequence before using
 * this layout; other implementations and initialized states pass through.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void lab_restart_display_timer(void *self, bool enabled)
    __asm__("_ZN19DisplayStateManager12restartTimerEb");

void lab_restart_display_timer(void *self, bool enabled) {
    typedef void (*restart_fn)(void *, bool);
    restart_fn original = (restart_fn)dlsym(RTLD_NEXT,
        "_ZN19DisplayStateManager12restartTimerEb");
    if (!original) {
        fprintf(stderr, "display-state guard: original restartTimer is unavailable\n");
        return;
    }
    const char *guard = getenv("TESLA_NATIVE_DISPLAY_STATE_GUARD");
    static const unsigned char signature[] = {
        0x41,0x57,0x41,0x56,0x41,0x55,0x41,0x54,0x55,0x53,0x48,0x89,0xfb,
        0x48,0x8d,0x64,0x24,0xc8,0x64,0x48,0x8b,0x2c,0x25,0x28,0,0,0,
        0x48,0x89,0x6c,0x24,0x28,0x89,0xf5,0x48,0x8b,0x7f,0x58,0x48,0x8b,0x07
    };
    if (guard && !strcmp(guard, "1") &&
        !memcmp((const unsigned char *)original, signature, sizeof(signature))) {
        void *active = NULL;
        if (self) memcpy(&active, (const unsigned char *)self + 0x58, sizeof(active));
        if (!active) {
            fprintf(stderr, "display-state guard: skipped restartTimer before display-state initialization\n");
            return;
        }
    }
    original(self, enabled);
}

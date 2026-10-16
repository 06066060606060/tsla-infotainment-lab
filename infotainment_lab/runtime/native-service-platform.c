/* Supply the session's generic model to the diagnostic web backend's platform
 * selector. The vehicle normally generates /var/etc/jcanproduct at boot.
 * Redirect reads of that one path; host files and authentication stay intact. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>

static int platform_open(const char *symbol, const char *path, int flags, mode_t mode) {
    int (*next)(const char *, int, ...) = dlsym(RTLD_NEXT, symbol);
    const char *product = getenv("TESLA_NATIVE_SERVICE_PRODUCT");
    if (product && product[0] == '/' && path && !strcmp(path, "/var/etc/jcanproduct")) {
        if ((flags & O_ACCMODE) != O_RDONLY || (flags & (O_CREAT | O_TRUNC | O_APPEND))) {
            errno = EROFS;
            return -1;
        }
        path = product;
    }
    return next(path, flags, mode);
}

#define WRAP_OPEN(NAME) \
int NAME(const char *path, int flags, ...) { \
    mode_t mode = 0; \
    if ((flags & O_CREAT) || (flags & O_TMPFILE) == O_TMPFILE) { \
        va_list args; va_start(args, flags); mode = va_arg(args, mode_t); va_end(args); \
    } \
    return platform_open(#NAME, path, flags, mode); \
}
WRAP_OPEN(open)
WRAP_OPEN(open64)

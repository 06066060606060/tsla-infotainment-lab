/* Keeps the firmware off Tesla's servers. Names under Tesla's domains never
 * resolve, except the two media names the lab serves on loopback. It is loaded
 * into every firmware process the lab starts; other lookups pass through to libc.
 * Connections to literal IP addresses are not intercepted. */
#define _GNU_SOURCE
#include <ctype.h>
#include <dlfcn.h>
#include <errno.h>
#include <netdb.h>
#include <stdio.h>
#include <string.h>

static const char *const blocked[] = {"tesla.com", "teslamotors.com", "tesla.services", "tesla.cn"};
static const char *const local[] = {"firmware-media.vn.teslamotors.com", "firmware-media-adapter.vn.teslamotors.com"};

/* 0 pass through, 1 blocked, 2 loopback */
static int classify(const char *name) {
    char host[256];
    size_t n = name ? strlen(name) : 0;
    while (n && name[n - 1] == '.') n--;
    if (!n || n >= sizeof host) return 0;
    for (size_t i = 0; i < n; i++) host[i] = (char)tolower((unsigned char)name[i]);
    host[n] = 0;
    for (size_t i = 0; i < sizeof local / sizeof *local; i++)
        if (!strcmp(host, local[i])) return 2;
    for (size_t i = 0; i < sizeof blocked / sizeof *blocked; i++) {
        size_t d = strlen(blocked[i]);
        if (n >= d && !strcmp(host + n - d, blocked[i]) && (n == d || host[n - d - 1] == '.')) {
            fprintf(stderr, "netguard: blocked lookup of %s\n", host);
            return 1;
        }
    }
    return 0;
}

int getaddrinfo(const char *node, const char *service, const struct addrinfo *hints, struct addrinfo **res) {
    static int (*real)(const char *, const char *, const struct addrinfo *, struct addrinfo **);
    if (!real) real = dlsym(RTLD_NEXT, "getaddrinfo");
    switch (classify(node)) {
    case 1: return EAI_NONAME;
    case 2: return real("127.0.0.1", service, hints, res);
    default: return real(node, service, hints, res);
    }
}

struct hostent *gethostbyname(const char *name) {
    static struct hostent *(*real)(const char *);
    if (!real) real = dlsym(RTLD_NEXT, "gethostbyname");
    switch (classify(name)) {
    case 1: h_errno = HOST_NOT_FOUND; return NULL;
    case 2: return real("127.0.0.1");
    default: return real(name);
    }
}

int gethostbyname_r(const char *name, struct hostent *ret, char *buf, size_t len, struct hostent **result, int *err) {
    static int (*real)(const char *, struct hostent *, char *, size_t, struct hostent **, int *);
    if (!real) real = dlsym(RTLD_NEXT, "gethostbyname_r");
    switch (classify(name)) {
    case 1: *result = NULL; *err = HOST_NOT_FOUND; return ENOENT;
    case 2: return real("127.0.0.1", ret, buf, len, result, err);
    default: return real(name, ret, buf, len, result, err);
    }
}

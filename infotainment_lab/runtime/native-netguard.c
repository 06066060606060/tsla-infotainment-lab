/* Keeps the firmware off Tesla's servers. Names under Tesla's domains never
 * resolve, except the two media names the lab serves on loopback. It is loaded
 * into every firmware process the lab starts; other lookups pass through to libc.
 * Connections to literal IP addresses are not intercepted. */
#define _GNU_SOURCE
#include <ctype.h>
#include <dlfcn.h>
#include <errno.h>
#include <netdb.h>
#include <arpa/inet.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>

/* Opt-in for the native navigation RPC server, whose default is INADDR_ANY.
 * Its local clients use localhost. Keep UDP telemetry bindings unchanged. */
int bind(int fd, const struct sockaddr *address, socklen_t length) {
    static int (*real)(int, const struct sockaddr *, socklen_t);
    if (!real) real = dlsym(RTLD_NEXT, "bind");
    const char *local_only = getenv("TESLA_NATIVE_SERVICE_LOOPBACK");
    int type = 0;
    socklen_t type_length = sizeof type;
    if (local_only && !strcmp(local_only, "1") && address &&
        !getsockopt(fd, SOL_SOCKET, SO_TYPE, &type, &type_length) && type == SOCK_STREAM) {
        if (address->sa_family == AF_INET && length >= sizeof(struct sockaddr_in)) {
            struct sockaddr_in local_address;
            memcpy(&local_address, address, sizeof local_address);
            if (local_address.sin_addr.s_addr == htonl(INADDR_ANY)) {
                local_address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
                return real(fd, (const struct sockaddr *)&local_address, sizeof local_address);
            }
        } else if (address->sa_family == AF_INET6 && length >= sizeof(struct sockaddr_in6)) {
            struct sockaddr_in6 local_address;
            memcpy(&local_address, address, sizeof local_address);
            if (IN6_IS_ADDR_UNSPECIFIED(&local_address.sin6_addr)) {
                local_address.sin6_addr = in6addr_loopback;
                return real(fd, (const struct sockaddr *)&local_address, sizeof local_address);
            }
        }
    }
    return real(fd, address, length);
}

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

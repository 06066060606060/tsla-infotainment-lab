/* Passive observation of firmware gateway calls and successful UDP sends.
 * Only the owned display processes preload this adapter. The original call,
 * return value and errno are preserved; observation never waits on a reader. */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#define MAX_PACKET 4096
static _Thread_local int observer_fd = -1;

static void observe(const void *data, size_t size, const struct sockaddr *address, socklen_t address_size, unsigned char kind) {
    int saved_errno = errno;
    const char *path = getenv("TESLA_NATIVE_TRAFFIC_SOCKET");
    if (!path || !data || !size || size > MAX_PACKET || !address ||
        address_size < sizeof(struct sockaddr_in) || address->sa_family != AF_INET) goto done;
    const struct sockaddr_in *peer = (const struct sockaddr_in *)address;
    if (peer->sin_addr.s_addr != htonl(0x7f000066)) goto done; /* owned gateway 127.0.0.102 */
    struct sockaddr_un target = {.sun_family = AF_UNIX};
    size_t path_size = strlen(path);
    if (path_size >= sizeof target.sun_path) goto done;
    memcpy(target.sun_path, path, path_size + 1);
    if (observer_fd < 0) observer_fd = socket(AF_UNIX, SOCK_DGRAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (observer_fd < 0) goto done;
    struct __attribute__((packed)) {
        char magic[4];
        unsigned char kind;
        uint64_t monotonic_ns;
        uint32_t peer_ip;
        uint16_t peer_port;
        uint16_t length;
        unsigned char payload[MAX_PACKET];
    } packet;
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now)) goto done;
    memcpy(packet.magic, "NTR2", 4);
    packet.kind = kind;
    packet.monotonic_ns = (uint64_t)now.tv_sec * 1000000000 + now.tv_nsec;
    packet.peer_ip = peer->sin_addr.s_addr;
    packet.peer_port = ntohs(peer->sin_port);
    packet.length = size;
    memcpy(packet.payload, data, size);
    /* Use the syscall through RTLD_NEXT to avoid observing this local copy. */
    ssize_t (*next)(int,const void *,size_t,int,const struct sockaddr *,socklen_t) = dlsym(RTLD_NEXT, "sendto");
    if (next) next(observer_fd, &packet, offsetof(typeof(packet), payload) + size,
                   MSG_DONTWAIT | MSG_NOSIGNAL, (const struct sockaddr *)&target, sizeof target);
done:
    errno = saved_errno;
}

ssize_t sendto(int fd, const void *data, size_t size, int flags,
               const struct sockaddr *address, socklen_t address_size) {
    static ssize_t (*next)(int,const void *,size_t,int,const struct sockaddr *,socklen_t);
    if (!next) next = dlsym(RTLD_NEXT, "sendto");
    ssize_t result = next(fd, data, size, flags, address, address_size);
    if (result > 0) observe(data, result, address, address_size, 1);
    return result;
}

ssize_t send(int fd, const void *data, size_t size, int flags) {
    static ssize_t (*next)(int,const void *,size_t,int);
    if (!next) next = dlsym(RTLD_NEXT, "send");
    ssize_t result = next(fd, data, size, flags);
    int saved_errno = errno;
    if (result > 0) {
        struct sockaddr_storage peer;
        socklen_t length = sizeof peer;
        if (!getpeername(fd, (struct sockaddr *)&peer, &length))
            observe(data, result, (struct sockaddr *)&peer, length, 1);
    }
    errno = saved_errno;
    return result;
}

/* Record the OS's actual gateway API calls even when no vehicle gateway is
 * connected. These are explicitly requests, not confirmed socket/bus sends. */
static void request(unsigned int id, const void *data, unsigned short size) {
    if (id > 0x7ff || size > 8 || (!data && size)) return;
    unsigned char record[10] = {0};
    uint16_t header = htons((size << 11) | id);
    memcpy(record, &header, 2);
    if (size) memcpy(record + 2, data, size);
    struct sockaddr_in peer = {.sin_family = AF_INET, .sin_addr.s_addr = htonl(0x7f000066)};
    observe(record, sizeof record, (struct sockaddr *)&peer, sizeof peer, 2);
}

#define REQUEST_HOOK(TYPE, NAME) \
void NAME(void *self,unsigned int id,const void *data,unsigned short size) \
    __asm__("_ZN" TYPE "11sendMessageEjPKvt"); \
void NAME(void *self,unsigned int id,const void *data,unsigned short size) { \
    static void (*next)(void *,unsigned int,const void *,unsigned short); \
    if (!next) next = dlsym(RTLD_NEXT,"_ZN" TYPE "11sendMessageEjPKvt"); \
    if (!next) abort(); \
    next(self,id,data,size); \
    request(id,data,size); \
}
REQUEST_HOOK("27PlatformM3VehicleLinkCommon", m3_request)
REQUEST_HOOK("14UdpVehicleLink", sx_request)

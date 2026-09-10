/* Local V4L2 compatibility, adapted from Derrick Yao's
 * tesla-subsystem-for-windows-dot-8/tesla-v4l2-camera-shim.c.
 * This is loaded only by the desktop lab's center-display process.
 * Ordinary descriptors are passed through to libc without alteration. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <poll.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/select.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <time.h>
#include <limits.h>
#include <unistd.h>

#define MAX_FAKE_DEVICES 8
#define MAX_BUFFERS 8
#define MAX_SIM_PATH PATH_MAX
#define DEFAULT_WIDTH 1280
#define DEFAULT_HEIGHT 720
#define DEFAULT_FPS 12

struct fake_buffer {
    void *ptr;
    size_t length;
    unsigned int index;
    bool mapped;
    bool queued;
};

struct fake_device {
    int fd;
    int width;
    int height;
    uint32_t pixfmt;
    size_t sizeimage;
    unsigned int buffer_count;
    unsigned int next_index;
    bool streaming;
    long long frame_no;
    long long last_frame_ms;
    long long last_report_ms;
    long long reported_frames;
    char device_path[MAX_SIM_PATH];
    char frame_path[MAX_SIM_PATH];
    char camera_name[64];
    struct fake_buffer buffers[MAX_BUFFERS];
};

typedef int (*open_fn)(const char *path, int flags, ...);
typedef int (*openat_fn)(int dirfd, const char *path, int flags, ...);
typedef int (*close_fn)(int fd);
typedef int (*ioctl_fn)(int fd, unsigned long request, ...);
typedef void *(*mmap_fn)(void *addr, size_t length, int prot, int flags, int fd,
                         off_t offset);
typedef int (*munmap_fn)(void *addr, size_t length);
typedef ssize_t (*read_fn)(int fd, void *buf, size_t count);
typedef int (*poll_fn)(struct pollfd *fds, nfds_t nfds, int timeout);
typedef int (*select_fn)(int nfds, fd_set *readfds, fd_set *writefds,
                         fd_set *exceptfds, struct timeval *timeout);

static open_fn real_open;
static openat_fn real_openat;
static close_fn real_close;
static ioctl_fn real_ioctl;
static mmap_fn real_mmap;
static munmap_fn real_munmap;
static read_fn real_read;
static poll_fn real_poll;
static select_fn real_select;
static struct fake_device devices[MAX_FAKE_DEVICES];

static void *lookup_next(const char *symbol) {
    void *fn = dlsym(RTLD_NEXT, symbol);
    if (fn == NULL) {
        fprintf(stderr, "[tesla-v4l2-camera-shim] missing %s: %s\n", symbol,
                dlerror());
        abort();
    }
    return fn;
}

static void ensure_real_symbols(void) {
    if (real_open != NULL) {
        return;
    }
    real_open = (open_fn)lookup_next("open");
    real_openat = (openat_fn)lookup_next("openat");
    real_close = (close_fn)lookup_next("close");
    real_ioctl = (ioctl_fn)lookup_next("ioctl");
    real_mmap = (mmap_fn)lookup_next("mmap");
    real_munmap = (munmap_fn)lookup_next("munmap");
    real_read = (read_fn)lookup_next("read");
    real_poll = (poll_fn)lookup_next("poll");
    real_select = (select_fn)lookup_next("select");
}

static bool shim_enabled(void) {
    const char *value = getenv("TESLA_V4L2_CAMERA_SHIM");
    return value == NULL || value[0] == '\0' || value[0] != '0';
}

static bool trace_enabled(void) {
    const char *value = getenv("TESLA_V4L2_TRACE");
    return value != NULL && value[0] != '\0' && value[0] != '0';
}

static const char *camera_device_path(void) {
    const char *value = getenv("TESLA_V4L2_CAMERA_DEVICE");
    return value && value[0] ? value : "/dev/video32";
}

static const char *frame_file_path(void) {
    const char *value = getenv("TESLA_V4L2_FRAME_FILE");
    return value && value[0] ? value : "/tmp/tesla-sim/v4l2-back.rgb";
}

static const char *adas_camera_map(void) {
    const char *value = getenv("TESLA_ADAS_CAMERA_MAP");
    return value && value[0] ? value
                             : "/dev/video32:back,/dev/video33:front,/dev/video34:left_repeater,/dev/video35:right_repeater";
}

static bool adas_camera_enabled(void) {
    const char *value = getenv("TESLA_ADAS_CAMERA_SIM");
    return value == NULL || value[0] == '\0' || value[0] != '0';
}

static const char *adas_raw_dir(void) {
    const char *value = getenv("TESLA_ADAS_CAMERA_RAW_DIR");
    return value && value[0] ? value : "/tmp/tesla-sim";
}

static bool known_camera_name(const char *camera) {
    return strcmp(camera, "front") == 0 || strcmp(camera, "back") == 0 ||
           strcmp(camera, "left_repeater") == 0 ||
           strcmp(camera, "right_repeater") == 0;
}

static void trim_token(char *text) {
    char *start = text;
    char *end;
    while (*start == ' ' || *start == '\t' || *start == '\n' || *start == '\r') {
        start++;
    }
    if (start != text) {
        memmove(text, start, strlen(start) + 1);
    }
    end = text + strlen(text);
    while (end > text &&
           (end[-1] == ' ' || end[-1] == '\t' || end[-1] == '\n' ||
            end[-1] == '\r')) {
        end--;
    }
    *end = '\0';
}

static void raw_frame_path_for_camera(const char *camera, char *out,
                                      size_t out_len) {
    snprintf(out, out_len, "%s/v4l2-%s.rgb", adas_raw_dir(), camera);
}

static bool camera_info_for_path(const char *path, char *frame_out,
                                 size_t frame_len, char *camera_out,
                                 size_t camera_len) {
    char map[2048];
    char *saveptr = NULL;
    char *entry;
    if (!shim_enabled() || path == NULL) {
        return false;
    }
    if (adas_camera_enabled()) {
        snprintf(map, sizeof(map), "%s", adas_camera_map());
        for (entry = strtok_r(map, ",", &saveptr); entry != NULL;
             entry = strtok_r(NULL, ",", &saveptr)) {
            char *sep;
            trim_token(entry);
            sep = strrchr(entry, ':');
            if (sep == NULL) {
                continue;
            }
            *sep = '\0';
            sep++;
            trim_token(entry);
            trim_token(sep);
            if (strcmp(path, entry) == 0 && known_camera_name(sep)) {
                snprintf(camera_out, camera_len, "%s", sep);
                raw_frame_path_for_camera(sep, frame_out, frame_len);
                return true;
            }
        }
    }
    if (strcmp(path, camera_device_path()) == 0) {
        snprintf(camera_out, camera_len, "%s", "back");
        snprintf(frame_out, frame_len, "%s", frame_file_path());
        return true;
    }
    return false;
}

static int env_int(const char *name, int fallback, int low, int high) {
    const char *value = getenv(name);
    char *end = NULL;
    long parsed;
    if (value == NULL || value[0] == '\0') {
        return fallback;
    }
    parsed = strtol(value, &end, 10);
    if (end == value || parsed < low || parsed > high) {
        return fallback;
    }
    return (int)parsed;
}

static uint32_t fourcc_from_text(const char *text, uint32_t fallback) {
    if (text == NULL || strlen(text) != 4) {
        return fallback;
    }
    return v4l2_fourcc(text[0], text[1], text[2], text[3]);
}

static void fourcc_text(uint32_t fmt, char out[5]) {
    out[0] = (char)(fmt & 0xff);
    out[1] = (char)((fmt >> 8) & 0xff);
    out[2] = (char)((fmt >> 16) & 0xff);
    out[3] = (char)((fmt >> 24) & 0xff);
    out[4] = '\0';
}

static long long monotonic_ms(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        return 0;
    }
    return ((long long)ts.tv_sec * 1000LL) +
           ((long long)ts.tv_nsec / 1000000LL);
}

static int bytes_per_pixel(uint32_t pixfmt) {
    switch (pixfmt) {
    case V4L2_PIX_FMT_RGB24:
    case V4L2_PIX_FMT_BGR24:
        return 3;
    case V4L2_PIX_FMT_RGB32:
    case V4L2_PIX_FMT_BGR32:
    case V4L2_PIX_FMT_XRGB32:
    case V4L2_PIX_FMT_XBGR32:
    case V4L2_PIX_FMT_ARGB32:
    case V4L2_PIX_FMT_ABGR32:
        return 4;
    default:
        return 2;
    }
}

static bool supported_pixfmt(uint32_t pixfmt) {
    switch (pixfmt) {
    case V4L2_PIX_FMT_YUYV:
    case V4L2_PIX_FMT_UYVY:
    case V4L2_PIX_FMT_NV12:
    case V4L2_PIX_FMT_RGB24:
    case V4L2_PIX_FMT_BGR24:
    case V4L2_PIX_FMT_RGB32:
    case V4L2_PIX_FMT_BGR32:
    case V4L2_PIX_FMT_XRGB32:
    case V4L2_PIX_FMT_XBGR32:
    case V4L2_PIX_FMT_ARGB32:
    case V4L2_PIX_FMT_ABGR32:
        return true;
    default:
        return false;
    }
}

static size_t image_size_for(int width, int height, uint32_t pixfmt) {
    if (pixfmt == V4L2_PIX_FMT_NV12) {
        return (size_t)width * (size_t)height * 3u / 2u;
    }
    return (size_t)width * (size_t)height * (size_t)bytes_per_pixel(pixfmt);
}

static uint8_t clip_u8(int value) {
    if (value < 0) {
        return 0;
    }
    if (value > 255) {
        return 255;
    }
    return (uint8_t)value;
}

static void rgb_to_yuv(uint8_t r, uint8_t g, uint8_t b, uint8_t *y, uint8_t *u,
                       uint8_t *v) {
    *y = clip_u8(((66 * r + 129 * g + 25 * b + 128) >> 8) + 16);
    *u = clip_u8(((-38 * r - 74 * g + 112 * b + 128) >> 8) + 128);
    *v = clip_u8(((112 * r - 94 * g - 18 * b + 128) >> 8) + 128);
}

static struct fake_device *device_for_fd(int fd) {
    if (fd < 0) {
        return NULL;
    }
    for (int i = 0; i < MAX_FAKE_DEVICES; i++) {
        if (devices[i].fd >= 0 && devices[i].fd == fd) {
            return &devices[i];
        }
    }
    return NULL;
}

static struct fake_device *device_for_ptr(void *ptr, unsigned int *buffer_index) {
    for (int i = 0; i < MAX_FAKE_DEVICES; i++) {
        if (devices[i].fd < 0) {
            continue;
        }
        for (unsigned int j = 0; j < devices[i].buffer_count; j++) {
            if (devices[i].buffers[j].mapped && devices[i].buffers[j].ptr == ptr) {
                if (buffer_index) {
                    *buffer_index = j;
                }
                return &devices[i];
            }
        }
    }
    return NULL;
}

__attribute__((constructor)) static void init_devices(void) {
    for (int i = 0; i < MAX_FAKE_DEVICES; i++) {
        devices[i].fd = -1;
        devices[i].width = DEFAULT_WIDTH;
        devices[i].height = DEFAULT_HEIGHT;
        devices[i].pixfmt = V4L2_PIX_FMT_YUYV;
        devices[i].sizeimage = image_size_for(DEFAULT_WIDTH, DEFAULT_HEIGHT,
                                              V4L2_PIX_FMT_YUYV);
    }
}

static bool path_matches_camera(const char *path) {
    char frame_path[MAX_SIM_PATH];
    char camera_name[64];
    return camera_info_for_path(path, frame_path, sizeof(frame_path), camera_name,
                                sizeof(camera_name));
}

static int open_fake_device(const char *path) {
    int fd;
    struct fake_device *dev = NULL;
    uint32_t default_fmt;
    char mapped_frame_path[MAX_SIM_PATH];
    char mapped_camera_name[64];
    ensure_real_symbols();
    if (!camera_info_for_path(path, mapped_frame_path, sizeof(mapped_frame_path),
                              mapped_camera_name, sizeof(mapped_camera_name))) {
        errno = ENOENT;
        return -1;
    }
    fd = real_open("/dev/null", O_RDWR | O_CLOEXEC);
    if (fd < 0) {
        return fd;
    }
    for (int i = 0; i < MAX_FAKE_DEVICES; i++) {
        if (devices[i].fd < 0) {
            dev = &devices[i];
            break;
        }
    }
    if (dev == NULL) {
        real_close(fd);
        errno = EMFILE;
        return -1;
    }
    default_fmt = fourcc_from_text(getenv("TESLA_V4L2_PIXEL_FORMAT"),
                                   V4L2_PIX_FMT_YUYV);
    if (!supported_pixfmt(default_fmt)) {
        default_fmt = V4L2_PIX_FMT_YUYV;
    }
    memset(dev, 0, sizeof(*dev));
    dev->fd = fd;
    dev->width = env_int("TESLA_V4L2_WIDTH", DEFAULT_WIDTH, 160, 4096);
    dev->height = env_int("TESLA_V4L2_HEIGHT", DEFAULT_HEIGHT, 120, 2160);
    dev->pixfmt = default_fmt;
    dev->sizeimage = image_size_for(dev->width, dev->height, dev->pixfmt);
    snprintf(dev->device_path, sizeof(dev->device_path), "%s", path);
    snprintf(dev->frame_path, sizeof(dev->frame_path), "%s", mapped_frame_path);
    snprintf(dev->camera_name, sizeof(dev->camera_name), "%s", mapped_camera_name);
    if (trace_enabled()) {
        char fmt[5];
        fourcc_text(dev->pixfmt, fmt);
        fprintf(stderr,
                "[tesla-v4l2-camera-shim] opened fake %s camera=%s frame=%s fd=%d %dx%d %s\n",
                dev->device_path, dev->camera_name, dev->frame_path, fd,
                dev->width, dev->height, fmt);
    }
    return fd;
}

static void sleep_for_frame(struct fake_device *dev) {
    int fps = env_int("TESLA_V4L2_CAMERA_FPS", DEFAULT_FPS, 1, 60);
    long interval = 1000 / fps;
    long long now = monotonic_ms();
    if (dev->last_frame_ms > 0 && now - dev->last_frame_ms < interval) {
        usleep((useconds_t)((interval - (now - dev->last_frame_ms)) * 1000));
    }
    dev->last_frame_ms = monotonic_ms();
}

static bool read_rgb_frame(struct fake_device *dev, uint8_t *rgb) {
    const char *path = dev->frame_path[0] ? dev->frame_path : frame_file_path();
    size_t expected = (size_t)dev->width * (size_t)dev->height * 3u;
    FILE *fp = fopen(path, "rb");
    size_t got;
    if (fp == NULL) {
        return false;
    }
    got = fread(rgb, 1, expected, fp);
    fclose(fp);
    return got == expected;
}

static uint8_t *load_rgb_or_synthetic(struct fake_device *dev) {
    size_t rgb_size = (size_t)dev->width * (size_t)dev->height * 3u;
    uint8_t *rgb = malloc(rgb_size);
    if (rgb == NULL) {
        return NULL;
    }
    if (!read_rgb_frame(dev, rgb)) {
        memset(rgb, 0, rgb_size);
    }
    return rgb;
}

static void fill_yuyv(uint8_t *dst, const uint8_t *rgb, int width, int height,
                      bool uyvy) {
    for (int y = 0; y < height; y++) {
        for (int x = 0; x < width; x += 2) {
            const uint8_t *p0 = rgb + ((size_t)y * (size_t)width + (size_t)x) * 3u;
            const uint8_t *p1 =
                rgb + ((size_t)y * (size_t)width + (size_t)(x + 1)) * 3u;
            uint8_t y0, u0, v0, y1, u1, v1;
            uint8_t u, v;
            rgb_to_yuv(p0[0], p0[1], p0[2], &y0, &u0, &v0);
            rgb_to_yuv(p1[0], p1[1], p1[2], &y1, &u1, &v1);
            u = (uint8_t)(((int)u0 + (int)u1) / 2);
            v = (uint8_t)(((int)v0 + (int)v1) / 2);
            if (uyvy) {
                *dst++ = u;
                *dst++ = y0;
                *dst++ = v;
                *dst++ = y1;
            } else {
                *dst++ = y0;
                *dst++ = u;
                *dst++ = y1;
                *dst++ = v;
            }
        }
    }
}

static void fill_nv12(uint8_t *dst, const uint8_t *rgb, int width, int height) {
    uint8_t *y_plane = dst;
    uint8_t *uv_plane = dst + (size_t)width * (size_t)height;
    for (int y = 0; y < height; y++) {
        for (int x = 0; x < width; x++) {
            const uint8_t *p = rgb + ((size_t)y * (size_t)width + (size_t)x) * 3u;
            uint8_t yy, uu, vv;
            rgb_to_yuv(p[0], p[1], p[2], &yy, &uu, &vv);
            y_plane[(size_t)y * (size_t)width + (size_t)x] = yy;
        }
    }
    for (int y = 0; y < height; y += 2) {
        for (int x = 0; x < width; x += 2) {
            int us = 0;
            int vs = 0;
            for (int yy = 0; yy < 2; yy++) {
                for (int xx = 0; xx < 2; xx++) {
                    const uint8_t *p =
                        rgb + ((size_t)(y + yy) * (size_t)width +
                               (size_t)(x + xx)) *
                                  3u;
                    uint8_t yv, uv, vv;
                    rgb_to_yuv(p[0], p[1], p[2], &yv, &uv, &vv);
                    us += uv;
                    vs += vv;
                }
            }
            *uv_plane++ = (uint8_t)(us / 4);
            *uv_plane++ = (uint8_t)(vs / 4);
        }
    }
}

static void fill_rgb_like(uint8_t *dst, const uint8_t *rgb, int width, int height,
                          uint32_t pixfmt) {
    size_t pixels = (size_t)width * (size_t)height;
    (void)width;
    (void)height;
    for (size_t i = 0; i < pixels; i++) {
        uint8_t r = rgb[i * 3u + 0u];
        uint8_t g = rgb[i * 3u + 1u];
        uint8_t b = rgb[i * 3u + 2u];
        switch (pixfmt) {
        case V4L2_PIX_FMT_RGB24:
            *dst++ = r;
            *dst++ = g;
            *dst++ = b;
            break;
        case V4L2_PIX_FMT_BGR24:
            *dst++ = b;
            *dst++ = g;
            *dst++ = r;
            break;
        case V4L2_PIX_FMT_RGB32:
        case V4L2_PIX_FMT_XRGB32:
        case V4L2_PIX_FMT_ARGB32:
            *dst++ = b;
            *dst++ = g;
            *dst++ = r;
            *dst++ = 0xff;
            break;
        default:
            *dst++ = r;
            *dst++ = g;
            *dst++ = b;
            *dst++ = 0xff;
            break;
        }
    }
}

static void fill_frame(struct fake_device *dev, unsigned int index) {
    uint8_t *rgb;
    uint8_t *dst;
    if (index >= dev->buffer_count || !dev->buffers[index].mapped ||
        dev->buffers[index].length < dev->sizeimage ||
        dev->buffers[index].ptr == NULL) {
        return;
    }
    dst = (uint8_t *)dev->buffers[index].ptr;
    rgb = load_rgb_or_synthetic(dev);
    if (rgb == NULL) {
        memset(dst, 0, dev->buffers[index].length);
        return;
    }
    switch (dev->pixfmt) {
    case V4L2_PIX_FMT_UYVY:
        fill_yuyv(dst, rgb, dev->width, dev->height, true);
        break;
    case V4L2_PIX_FMT_NV12:
        fill_nv12(dst, rgb, dev->width, dev->height);
        break;
    case V4L2_PIX_FMT_RGB24:
    case V4L2_PIX_FMT_BGR24:
    case V4L2_PIX_FMT_RGB32:
    case V4L2_PIX_FMT_BGR32:
    case V4L2_PIX_FMT_XRGB32:
    case V4L2_PIX_FMT_XBGR32:
    case V4L2_PIX_FMT_ARGB32:
    case V4L2_PIX_FMT_ABGR32:
        fill_rgb_like(dst, rgb, dev->width, dev->height, dev->pixfmt);
        break;
    case V4L2_PIX_FMT_YUYV:
    default:
        fill_yuyv(dst, rgb, dev->width, dev->height, false);
        break;
    }
    free(rgb);
}

static void report_frame(struct fake_device *dev) {
    dev->frame_no++;
    long long now = monotonic_ms();
    const char *path = getenv("TESLA_CAMERA_CONSUMER_STATUS");
    if (!path || now - dev->last_report_ms < 1000) return;
    char temporary[PATH_MAX];
    if (snprintf(temporary, sizeof(temporary), "%s.new", path) >= (int)sizeof(temporary)) return;
    FILE *out = fopen(temporary, "w");
    if (!out) return;
    double fps = dev->last_report_ms ? (dev->frame_no - dev->reported_frames) * 1000.0 / (now - dev->last_report_ms) : 0;
    fprintf(out, "{\"frames\":%lld,\"fps\":%.1f,\"updated_at\":%lld}\n", dev->frame_no, fps, (long long)time(NULL));
    fclose(out);
    rename(temporary, path);
    dev->last_report_ms = now;
    dev->reported_frames = dev->frame_no;
}

static void apply_format(struct fake_device *dev, struct v4l2_format *fmt) {
    struct v4l2_pix_format *pix = &fmt->fmt.pix;
    if (pix->width >= 160 && pix->width <= 4096) {
        dev->width = (int)pix->width;
    }
    if (pix->height >= 120 && pix->height <= 2160) {
        dev->height = (int)pix->height;
    }
    dev->width &= ~1;
    dev->height &= ~1;
    if (supported_pixfmt(pix->pixelformat)) {
        dev->pixfmt = pix->pixelformat;
    }
    dev->sizeimage = image_size_for(dev->width, dev->height, dev->pixfmt);
    pix->width = (uint32_t)dev->width;
    pix->height = (uint32_t)dev->height;
    pix->pixelformat = dev->pixfmt;
    pix->field = V4L2_FIELD_NONE;
    pix->bytesperline = (uint32_t)(dev->sizeimage / (size_t)dev->height);
    if (dev->pixfmt == V4L2_PIX_FMT_NV12) {
        pix->bytesperline = (uint32_t)dev->width;
    }
    pix->sizeimage = (uint32_t)dev->sizeimage;
    pix->colorspace = V4L2_COLORSPACE_SRGB;
}

static void current_format(struct fake_device *dev, struct v4l2_format *fmt) {
    memset(&fmt->fmt, 0, sizeof(fmt->fmt));
    fmt->type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    fmt->fmt.pix.width = (uint32_t)dev->width;
    fmt->fmt.pix.height = (uint32_t)dev->height;
    fmt->fmt.pix.pixelformat = dev->pixfmt;
    fmt->fmt.pix.field = V4L2_FIELD_NONE;
    fmt->fmt.pix.bytesperline =
        dev->pixfmt == V4L2_PIX_FMT_NV12
            ? (uint32_t)dev->width
            : (uint32_t)(dev->sizeimage / (size_t)dev->height);
    fmt->fmt.pix.sizeimage = (uint32_t)dev->sizeimage;
    fmt->fmt.pix.colorspace = V4L2_COLORSPACE_SRGB;
}

static int handle_ioctl(struct fake_device *dev, unsigned long request, void *arg) {
    switch (request) {
    case VIDIOC_QUERYCAP: {
        struct v4l2_capability *cap = (struct v4l2_capability *)arg;
        memset(cap, 0, sizeof(*cap));
        snprintf((char *)cap->driver, sizeof(cap->driver), "tesla-v4l2");
        snprintf((char *)cap->card, sizeof(cap->card), "Tesla Sim %.14s Camera",
                 dev->camera_name[0] ? dev->camera_name : "back");
        snprintf((char *)cap->bus_info, sizeof(cap->bus_info), "platform:tesla-sim");
        cap->version = (6 << 16) | (1 << 8);
        cap->capabilities = V4L2_CAP_VIDEO_CAPTURE | V4L2_CAP_STREAMING |
                            V4L2_CAP_READWRITE | V4L2_CAP_DEVICE_CAPS;
        cap->device_caps =
            V4L2_CAP_VIDEO_CAPTURE | V4L2_CAP_STREAMING | V4L2_CAP_READWRITE;
        return 0;
    }
    case VIDIOC_ENUM_FMT: {
        struct v4l2_fmtdesc *desc = (struct v4l2_fmtdesc *)arg;
        static const uint32_t formats[] = {V4L2_PIX_FMT_YUYV, V4L2_PIX_FMT_UYVY,
                                           V4L2_PIX_FMT_NV12, V4L2_PIX_FMT_RGB24,
                                           V4L2_PIX_FMT_BGR24};
        if (desc->index >= sizeof(formats) / sizeof(formats[0])) {
            errno = EINVAL;
            return -1;
        }
        desc->type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        desc->pixelformat = formats[desc->index];
        snprintf((char *)desc->description, sizeof(desc->description),
                 "Tesla simulated camera");
        return 0;
    }
    case VIDIOC_G_FMT:
        current_format(dev, (struct v4l2_format *)arg);
        return 0;
    case VIDIOC_TRY_FMT:
    case VIDIOC_S_FMT: {
        struct v4l2_format *fmt = (struct v4l2_format *)arg;
        if (fmt->type != V4L2_BUF_TYPE_VIDEO_CAPTURE) {
            errno = EINVAL;
            return -1;
        }
        if (request == VIDIOC_S_FMT && dev->buffer_count) {
            errno = EBUSY;
            return -1;
        }
        if (request == VIDIOC_TRY_FMT) {
            struct fake_device trial = *dev;
            apply_format(&trial, fmt);
            return 0;
        }
        apply_format(dev, fmt);
        if (trace_enabled()) {
            char text[5];
            fourcc_text(dev->pixfmt, text);
            fprintf(stderr, "[tesla-v4l2-camera-shim] S_FMT %dx%d %s size=%zu\n",
                    dev->width, dev->height, text, dev->sizeimage);
        }
        return 0;
    }
    case VIDIOC_REQBUFS: {
        struct v4l2_requestbuffers *req = (struct v4l2_requestbuffers *)arg;
        if (req->type != V4L2_BUF_TYPE_VIDEO_CAPTURE ||
            req->memory != V4L2_MEMORY_MMAP) {
            errno = EINVAL;
            return -1;
        }
        if (req->count == 0) {
            dev->buffer_count = 0;
            return 0;
        }
        if (dev->buffer_count) {
            errno = EBUSY;
            return -1;
        }
        dev->buffer_count = req->count;
        if (dev->buffer_count > MAX_BUFFERS) {
            dev->buffer_count = MAX_BUFFERS;
        }
        req->count = dev->buffer_count;
        for (unsigned int i = 0; i < dev->buffer_count; i++) {
            dev->buffers[i].index = i;
            dev->buffers[i].length = dev->sizeimage;
            dev->buffers[i].queued = false;
        }
        if (trace_enabled()) {
            fprintf(stderr, "[tesla-v4l2-camera-shim] REQBUFS count=%u\n",
                    dev->buffer_count);
        }
        return 0;
    }
    case VIDIOC_QUERYBUF: {
        struct v4l2_buffer *buf = (struct v4l2_buffer *)arg;
        if (buf->index >= dev->buffer_count) {
            errno = EINVAL;
            return -1;
        }
        buf->type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buf->memory = V4L2_MEMORY_MMAP;
        buf->length = (uint32_t)dev->buffers[buf->index].length;
        buf->bytesused = (uint32_t)dev->buffers[buf->index].length;
        buf->field = V4L2_FIELD_NONE;
        buf->m.offset = (uint32_t)(buf->index * dev->sizeimage);
        return 0;
    }
    case VIDIOC_QBUF: {
        struct v4l2_buffer *buf = (struct v4l2_buffer *)arg;
        if (buf->index >= dev->buffer_count) {
            errno = EINVAL;
            return -1;
        }
        dev->buffers[buf->index].queued = true;
        return 0;
    }
    case VIDIOC_DQBUF: {
        struct v4l2_buffer *buf = (struct v4l2_buffer *)arg;
        unsigned int index;
        if (dev->buffer_count == 0 || !dev->streaming) {
            errno = EINVAL;
            return -1;
        }
        sleep_for_frame(dev);
        index = dev->next_index % dev->buffer_count;
        dev->next_index++;
        fill_frame(dev, index);
        report_frame(dev);
        memset(buf, 0, sizeof(*buf));
        buf->index = index;
        buf->type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buf->memory = V4L2_MEMORY_MMAP;
        buf->length = (uint32_t)dev->buffers[index].length;
        buf->bytesused = (uint32_t)dev->buffers[index].length;
        buf->field = V4L2_FIELD_NONE;
        buf->flags = V4L2_BUF_FLAG_DONE;
        gettimeofday(&buf->timestamp, NULL);
        return 0;
    }
    case VIDIOC_STREAMON:
        dev->streaming = true;
        return 0;
    case VIDIOC_STREAMOFF:
        dev->streaming = false;
        return 0;
    case VIDIOC_ENUMINPUT: {
        struct v4l2_input *input = (struct v4l2_input *)arg;
        if (input->index > 0) {
            errno = EINVAL;
            return -1;
        }
        memset(input, 0, sizeof(*input));
        input->index = 0;
        input->type = V4L2_INPUT_TYPE_CAMERA;
        snprintf((char *)input->name, sizeof(input->name), "Tesla simulator %.15s",
                 dev->camera_name[0] ? dev->camera_name : "back");
        return 0;
    }
    case VIDIOC_G_INPUT:
        *(int *)arg = 0;
        return 0;
    case VIDIOC_S_INPUT:
        return 0;
    case VIDIOC_G_PARM:
    case VIDIOC_S_PARM: {
        struct v4l2_streamparm *parm = (struct v4l2_streamparm *)arg;
        int fps = env_int("TESLA_V4L2_CAMERA_FPS", DEFAULT_FPS, 1, 60);
        memset(parm, 0, sizeof(*parm));
        parm->type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        parm->parm.capture.capability = V4L2_CAP_TIMEPERFRAME;
        parm->parm.capture.timeperframe.numerator = 1;
        parm->parm.capture.timeperframe.denominator = (uint32_t)fps;
        return 0;
    }
    case VIDIOC_CROPCAP: {
        struct v4l2_cropcap *crop = (struct v4l2_cropcap *)arg;
        memset(crop, 0, sizeof(*crop));
        crop->type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        crop->bounds.width = (uint32_t)dev->width;
        crop->bounds.height = (uint32_t)dev->height;
        crop->defrect.width = (uint32_t)dev->width;
        crop->defrect.height = (uint32_t)dev->height;
        crop->pixelaspect.numerator = 1;
        crop->pixelaspect.denominator = 1;
        return 0;
    }
    case VIDIOC_G_CROP: {
        struct v4l2_crop *crop = (struct v4l2_crop *)arg;
        crop->type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        crop->c.width = (uint32_t)dev->width;
        crop->c.height = (uint32_t)dev->height;
        return 0;
    }
    case VIDIOC_S_CROP:
    case VIDIOC_LOG_STATUS:
        return 0;
    case VIDIOC_QUERYCTRL:
        errno = EINVAL;
        return -1;
    case VIDIOC_G_CTRL: {
        struct v4l2_control *ctrl = (struct v4l2_control *)arg;
        ctrl->value = 0;
        return 0;
    }
    case VIDIOC_S_CTRL:
        return 0;
    default:
        if (trace_enabled()) {
            fprintf(stderr,
                    "[tesla-v4l2-camera-shim] unhandled ioctl fd=%d req=0x%lx\n",
                    dev->fd, request);
        }
        errno = EINVAL;
        return -1;
    }
}

int open(const char *path, int flags, ...) {
    mode_t mode = 0;
    va_list ap;
    ensure_real_symbols();
    if (flags & O_CREAT) {
        va_start(ap, flags);
        mode = (mode_t)va_arg(ap, int);
        va_end(ap);
    }
    if (path_matches_camera(path)) {
        return open_fake_device(path);
    }
    if (flags & O_CREAT) {
        return real_open(path, flags, mode);
    }
    return real_open(path, flags);
}

int open64(const char *path, int flags, ...) {
    mode_t mode = 0;
    va_list ap;
    ensure_real_symbols();
    if (flags & O_CREAT) {
        va_start(ap, flags);
        mode = (mode_t)va_arg(ap, int);
        va_end(ap);
    }
    if (path_matches_camera(path)) {
        return open_fake_device(path);
    }
    if (flags & O_CREAT) {
        return real_open(path, flags, mode);
    }
    return real_open(path, flags);
}

int openat(int dirfd, const char *path, int flags, ...) {
    mode_t mode = 0;
    va_list ap;
    ensure_real_symbols();
    if (flags & O_CREAT) {
        va_start(ap, flags);
        mode = (mode_t)va_arg(ap, int);
        va_end(ap);
    }
    if (path_matches_camera(path)) {
        return open_fake_device(path);
    }
    if (flags & O_CREAT) {
        return real_openat(dirfd, path, flags, mode);
    }
    return real_openat(dirfd, path, flags);
}

int openat64(int dirfd, const char *path, int flags, ...) {
    mode_t mode = 0;
    va_list ap;
    ensure_real_symbols();
    if (flags & O_CREAT) {
        va_start(ap, flags);
        mode = (mode_t)va_arg(ap, int);
        va_end(ap);
    }
    if (path_matches_camera(path)) {
        return open_fake_device(path);
    }
    if (flags & O_CREAT) {
        return real_openat(dirfd, path, flags, mode);
    }
    return real_openat(dirfd, path, flags);
}

int close(int fd) {
    struct fake_device *dev;
    ensure_real_symbols();
    dev = device_for_fd(fd);
    if (dev != NULL) {
        if (trace_enabled()) {
            fprintf(stderr, "[tesla-v4l2-camera-shim] close fd=%d\n", fd);
        }
        dev->fd = -1;
        return real_close(fd);
    }
    return real_close(fd);
}

int ioctl(int fd, unsigned long request, ...) {
    va_list ap;
    void *arg;
    struct fake_device *dev;
    ensure_real_symbols();
    va_start(ap, request);
    arg = va_arg(ap, void *);
    va_end(ap);
    dev = device_for_fd(fd);
    if (dev != NULL) {
        return handle_ioctl(dev, request, arg);
    }
    return real_ioctl(fd, request, arg);
}

void *mmap(void *addr, size_t length, int prot, int flags, int fd, off_t offset) {
    struct fake_device *dev;
    ensure_real_symbols();
    dev = device_for_fd(fd);
    if (dev != NULL) {
        unsigned int index = (unsigned int)((size_t)offset / dev->sizeimage);
        void *ptr;
        if (offset < 0 || (size_t)offset % dev->sizeimage || index >= dev->buffer_count ||
            length < dev->sizeimage || dev->buffers[index].mapped) {
            errno = EINVAL;
            return MAP_FAILED;
        }
        ptr = real_mmap(NULL, length, PROT_READ | PROT_WRITE,
                        MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (ptr == MAP_FAILED) {
            return MAP_FAILED;
        }
        dev->buffers[index].ptr = ptr;
        dev->buffers[index].length = length;
        dev->buffers[index].mapped = true;
        fill_frame(dev, index);
        return ptr;
    }
    return real_mmap(addr, length, prot, flags, fd, offset);
}

void *mmap64(void *addr, size_t length, int prot, int flags, int fd,
             off64_t offset) {
    return mmap(addr, length, prot, flags, fd, (off_t)offset);
}

int munmap(void *addr, size_t length) {
    struct fake_device *dev;
    unsigned int index = 0;
    ensure_real_symbols();
    dev = device_for_ptr(addr, &index);
    if (dev != NULL) {
        dev->buffers[index].ptr = NULL;
        dev->buffers[index].mapped = false;
        return real_munmap(addr, length);
    }
    return real_munmap(addr, length);
}

ssize_t read(int fd, void *buf, size_t count) {
    struct fake_device *dev;
    ensure_real_symbols();
    dev = device_for_fd(fd);
    if (dev != NULL) {
        uint8_t *rgb = load_rgb_or_synthetic(dev);
        size_t copy = count < dev->sizeimage ? count : dev->sizeimage;
        uint8_t *frame;
        if (rgb == NULL) {
            memset(buf, 0, copy);
            return (ssize_t)copy;
        }
        frame = malloc(dev->sizeimage);
        if (frame == NULL) {
            free(rgb);
            errno = ENOMEM;
            return -1;
        }
        if (dev->pixfmt == V4L2_PIX_FMT_UYVY) {
            fill_yuyv(frame, rgb, dev->width, dev->height, true);
        } else if (dev->pixfmt == V4L2_PIX_FMT_NV12) {
            fill_nv12(frame, rgb, dev->width, dev->height);
        } else if (dev->pixfmt == V4L2_PIX_FMT_YUYV) {
            fill_yuyv(frame, rgb, dev->width, dev->height, false);
        } else {
            fill_rgb_like(frame, rgb, dev->width, dev->height, dev->pixfmt);
        }
        sleep_for_frame(dev);
        report_frame(dev);
        memcpy(buf, frame, copy);
        free(frame);
        free(rgb);
        return (ssize_t)copy;
    }
    return real_read(fd, buf, count);
}

int poll(struct pollfd *fds, nfds_t nfds, int timeout) {
    ensure_real_symbols();
    return real_poll(fds, nfds, timeout);
}

int select(int nfds, fd_set *readfds, fd_set *writefds, fd_set *exceptfds,
           struct timeval *timeout) {
    ensure_real_symbols();
    return real_select(nfds, readfds, writefds, exceptfds, timeout);
}

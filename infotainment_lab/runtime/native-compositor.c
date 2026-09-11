#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>

typedef void (*viz_external_display_ctor)(void *self,
                                          void *parent,
                                          const void *window_name,
                                          bool direct_viz,
                                          const void *background,
                                          bool external_composite);
typedef unsigned long (*xcomposite_name_window_pixmap_fn)(void *display,
                                                          unsigned long window);
typedef void (*xcomposite_redirect_window_fn)(void *display,
                                              unsigned long window,
                                              int update);
typedef void (*xsync_fn)(void *display, int discard);
typedef void *(*egl_get_display_fn)(void *native_display);
typedef int (*egl_get_error_fn)(void);
typedef void *(*egl_get_proc_address_fn)(const char *name);
typedef void *(*egl_create_image_khr_fn)(void *display,
                                         void *context,
                                         unsigned int target,
                                         void *buffer,
                                         const int *attributes);
typedef int (*egl_destroy_image_khr_fn)(void *display, void *image);
typedef void (*gl_egl_image_target_texture_2d_oes_fn)(unsigned int target,
                                                      void *image);

typedef struct _XDisplay Display;
typedef struct _XVisual Visual;
typedef struct _XScreen Screen;

typedef struct {
    int x;
    int y;
    int width;
    int height;
    int border_width;
    int depth;
    Visual *visual;
    unsigned long root;
    int class;
    int bit_gravity;
    int win_gravity;
    int backing_store;
    unsigned long backing_planes;
    unsigned long backing_pixel;
    int save_under;
    unsigned long colormap;
    int map_installed;
    int map_state;
    long all_event_masks;
    long your_event_mask;
    long do_not_propagate_mask;
    int override_redirect;
    Screen *screen;
} x_window_attributes;

typedef struct {
    Visual *visual;
    unsigned long visualid;
    int screen;
    int depth;
    int class;
    unsigned long red_mask;
    unsigned long green_mask;
    unsigned long blue_mask;
    int colormap_size;
    int bits_per_rgb;
} x_visual_info;

typedef struct {
    int width;
    int height;
    int xoffset;
    int format;
    char *data;
    int byte_order;
    int bitmap_unit;
    int bitmap_bit_order;
    int bitmap_pad;
    int depth;
    int bytes_per_line;
    int bits_per_pixel;
    unsigned long red_mask;
    unsigned long green_mask;
    unsigned long blue_mask;
} x_image;

typedef int (*x_get_window_attributes_fn)(Display *display,
                                          unsigned long window,
                                          x_window_attributes *attributes);
typedef int (*x_default_screen_fn)(Display *display);
typedef unsigned long (*x_visual_id_from_visual_fn)(Visual *visual);
typedef int (*x_free_fn)(void *data);
typedef x_image *(*x_get_image_fn)(Display *display,
                                   unsigned long drawable,
                                   int x,
                                   int y,
                                   unsigned int width,
                                   unsigned int height,
                                   unsigned long plane_mask,
                                   int format);
typedef int (*x_destroy_image_fn)(x_image *image);
typedef unsigned long (*x_get_pixel_fn)(x_image *image, int x, int y);
typedef const char *(*glx_query_extensions_string_fn)(Display *display,
                                                      int screen);
typedef void **(*glx_choose_fbconfig_fn)(Display *display,
                                         int screen,
                                         const int *attributes,
                                         int *count);
typedef x_visual_info *(*glx_get_visual_from_fbconfig_fn)(Display *display,
                                                          void *config);
typedef int (*glx_get_fbconfig_attrib_fn)(Display *display,
                                          void *config,
                                          int attribute,
                                          int *value);
typedef unsigned long (*glx_create_pixmap_fn)(Display *display,
                                              void *config,
                                              unsigned long pixmap,
                                              const int *attributes);
typedef void (*glx_destroy_pixmap_fn)(Display *display,
                                      unsigned long pixmap);
typedef void (*glx_bind_tex_image_ext_fn)(Display *display,
                                          unsigned long drawable,
                                          int buffer,
                                          const int *attributes);
typedef void (*glx_release_tex_image_ext_fn)(Display *display,
                                             unsigned long drawable,
                                             int buffer);
typedef void *(*glx_get_proc_address_fn)(const unsigned char *name);
typedef void (*gl_tex_image_2d_fn)(unsigned int target,
                                   int level,
                                   int internal_format,
                                   int width,
                                   int height,
                                   int border,
                                   unsigned int format,
                                   unsigned int type,
                                   const void *pixels);
typedef void (*gl_pixel_storei_fn)(unsigned int name, int value);
typedef unsigned int (*gl_get_error_fn)(void);
typedef void (*gl_get_integerv_fn)(unsigned int name, int *value);
typedef void (*gl_bind_texture_fn)(unsigned int target, unsigned int texture);

#define EGL_NATIVE_PIXMAP_KHR 0x30b0
#define GL_TEXTURE_2D 0x0de1
#define GL_RGBA 0x1908
#define GL_UNSIGNED_BYTE 0x1401
#define GL_NO_ERROR 0
#define GL_UNPACK_ALIGNMENT 0x0cf5
#define GL_TEXTURE_BINDING_2D 0x8069
#define GLX_RGBA_BIT 0x00000001
#define GLX_PIXMAP_BIT 0x00000002
#define GLX_DRAWABLE_TYPE 0x8010
#define GLX_RENDER_TYPE 0x8011
#define GLX_X_RENDERABLE 0x8012
#define GLX_BIND_TO_TEXTURE_RGB_EXT 0x20d0
#define GLX_BIND_TO_TEXTURE_RGBA_EXT 0x20d1
#define GLX_BIND_TO_TEXTURE_TARGETS_EXT 0x20d3
#define GLX_TEXTURE_FORMAT_EXT 0x20d5
#define GLX_TEXTURE_TARGET_EXT 0x20d6
#define GLX_TEXTURE_FORMAT_RGB_EXT 0x20d9
#define GLX_TEXTURE_FORMAT_RGBA_EXT 0x20da
#define GLX_TEXTURE_2D_BIT_EXT 0x00000002
#define GLX_TEXTURE_2D_EXT 0x20dc
#define GLX_FRONT_LEFT_EXT 0x20de

#define TESLA_FAKE_EGL_MAGIC 0x5445534c41474c58ULL
#define PIXMAP_SOURCE_COUNT 16
#define XYPixmap 1
#define ZPixmap 2

static bool force_native_apviz(void) {
    const char *value = getenv("TESLA_FORCE_NATIVE_APVIZ");
    return value == NULL || value[0] == '\0' || value[0] != '0';
}

static bool trace_native_apviz(void) {
    const char *value = getenv("TESLA_NATIVE_APVIZ_TRACE");
    return value != NULL && value[0] != '\0' && value[0] != '0';
}

static bool glx_fallback_enabled(void) {
    const char *value = getenv("TESLA_NATIVE_APVIZ_GLX_FALLBACK");
    return value == NULL || value[0] == '\0' || value[0] != '0';
}

static bool cpu_upload_enabled(void) {
    const char *value = getenv("TESLA_NATIVE_APVIZ_CPU_UPLOAD");
    return value == NULL || value[0] == '\0' || value[0] != '0';
}

static bool glx_bind_enabled(void) {
    const char *value = getenv("TESLA_NATIVE_APVIZ_GLX_BIND");
    return value != NULL && value[0] != '\0' && value[0] != '0';
}

static long refresh_interval_ms(void) {
    const char *value = getenv("TESLA_NATIVE_APVIZ_REFRESH_MS");
    char *end = NULL;
    long parsed;
    if (value == NULL || value[0] == '\0') {
        return 500;
    }
    parsed = strtol(value, &end, 10);
    if (end == value || parsed < 0) {
        return 500;
    }
    return parsed;
}

static long long monotonic_ms(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        return 0;
    }
    return ((long long)ts.tv_sec * 1000LL) +
           ((long long)ts.tv_nsec / 1000000LL);
}

static void *lookup_next(const char *symbol) {
    void *fn = dlsym(RTLD_NEXT, symbol);
    if (fn == NULL && trace_native_apviz()) {
        fprintf(stderr, "[tesla-native-apviz-shim] missing %s: %s\n",
                symbol, dlerror());
    }
    return fn;
}

static viz_external_display_ctor lookup_ctor(const char *symbol) {
    void *fn = lookup_next(symbol);
    if (fn == NULL) {
        abort();
    }
    return (viz_external_display_ctor)fn;
}

static egl_create_image_khr_fn real_egl_create_image_khr;
static egl_destroy_image_khr_fn real_egl_destroy_image_khr;
static gl_egl_image_target_texture_2d_oes_fn
    real_gl_egl_image_target_texture_2d_oes;

struct pixmap_source {
    Display *display;
    unsigned long window;
    unsigned long pixmap;
    int width;
    int height;
    int depth;
    unsigned long visualid;
};

struct fake_egl_image {
    unsigned long long magic;
    Display *display;
    unsigned long window;
    unsigned long pixmap;
    int width;
    int height;
    int depth;
    unsigned long visualid;
    void *fbconfig;
    unsigned long glx_pixmap;
    int texture_format;
    unsigned int texture_id;
    long long last_upload_ms;
    bool bound;
};

static struct pixmap_source pixmap_sources[PIXMAP_SOURCE_COUNT];
static unsigned int pixmap_source_cursor;
static struct fake_egl_image *texture_images[PIXMAP_SOURCE_COUNT];

static void register_texture_image(struct fake_egl_image *image) {
    if (image == NULL || image->texture_id == 0) {
        return;
    }
    for (unsigned int i = 0; i < PIXMAP_SOURCE_COUNT; ++i) {
        if (texture_images[i] == image || texture_images[i] == NULL) {
            texture_images[i] = image;
            return;
        }
    }
    texture_images[image->texture_id % PIXMAP_SOURCE_COUNT] = image;
}

static void unregister_texture_image(struct fake_egl_image *image) {
    for (unsigned int i = 0; i < PIXMAP_SOURCE_COUNT; ++i) {
        if (texture_images[i] == image) {
            texture_images[i] = NULL;
        }
    }
}

static struct fake_egl_image *find_texture_image(unsigned int texture) {
    for (unsigned int i = 0; i < PIXMAP_SOURCE_COUNT; ++i) {
        if (texture_images[i] != NULL &&
            texture_images[i]->magic == TESLA_FAKE_EGL_MAGIC &&
            texture_images[i]->texture_id == texture) {
            return texture_images[i];
        }
    }
    return NULL;
}

struct glx_api {
    bool attempted;
    bool ok;
    x_get_window_attributes_fn XGetWindowAttributes;
    x_default_screen_fn XDefaultScreen;
    x_visual_id_from_visual_fn XVisualIDFromVisual;
    x_free_fn XFree;
    glx_query_extensions_string_fn glXQueryExtensionsString;
    glx_choose_fbconfig_fn glXChooseFBConfig;
    glx_get_visual_from_fbconfig_fn glXGetVisualFromFBConfig;
    glx_get_fbconfig_attrib_fn glXGetFBConfigAttrib;
    glx_create_pixmap_fn glXCreatePixmap;
    glx_destroy_pixmap_fn glXDestroyPixmap;
    glx_bind_tex_image_ext_fn glXBindTexImageEXT;
    glx_release_tex_image_ext_fn glXReleaseTexImageEXT;
};

static struct glx_api glx;

struct cpu_upload_api {
    bool attempted;
    bool ok;
    x_get_window_attributes_fn XGetWindowAttributes;
    x_visual_id_from_visual_fn XVisualIDFromVisual;
    x_get_image_fn XGetImage;
    x_destroy_image_fn XDestroyImage;
    x_get_pixel_fn XGetPixel;
    gl_tex_image_2d_fn glTexImage2D;
    gl_pixel_storei_fn glPixelStorei;
    gl_get_error_fn glGetError;
    gl_get_integerv_fn glGetIntegerv;
};

static struct cpu_upload_api cpu;

static void *lookup_default_or_library(const char *library_name,
                                       const char *symbol) {
    void *fn = dlsym(RTLD_DEFAULT, symbol);
    if (fn == NULL) {
        void *library = dlopen(library_name, RTLD_LAZY | RTLD_GLOBAL);
        if (library != NULL) {
            fn = dlsym(library, symbol);
        }
    }
    if (fn == NULL && trace_native_apviz()) {
        fprintf(stderr, "[tesla-native-apviz-shim] missing %s\n", symbol);
    }
    return fn;
}

static void *lookup_glx_extension(const char *symbol) {
    void *fn = lookup_default_or_library("libGL.so.1", symbol);
    if (fn == NULL) {
        glx_get_proc_address_fn get_proc =
            (glx_get_proc_address_fn)lookup_default_or_library(
                "libGL.so.1", "glXGetProcAddressARB");
        if (get_proc == NULL) {
            get_proc = (glx_get_proc_address_fn)lookup_default_or_library(
                "libGL.so.1", "glXGetProcAddress");
        }
        if (get_proc != NULL) {
            fn = get_proc((const unsigned char *)symbol);
        }
    }
    return fn;
}

static bool load_glx_api(void) {
    if (glx.attempted) {
        return glx.ok;
    }
    glx.attempted = true;

    glx.XGetWindowAttributes = (x_get_window_attributes_fn)
        lookup_default_or_library("libX11.so.6", "XGetWindowAttributes");
    glx.XDefaultScreen = (x_default_screen_fn)
        lookup_default_or_library("libX11.so.6", "XDefaultScreen");
    glx.XVisualIDFromVisual = (x_visual_id_from_visual_fn)
        lookup_default_or_library("libX11.so.6", "XVisualIDFromVisual");
    glx.XFree =
        (x_free_fn)lookup_default_or_library("libX11.so.6", "XFree");
    glx.glXQueryExtensionsString = (glx_query_extensions_string_fn)
        lookup_default_or_library("libGL.so.1", "glXQueryExtensionsString");
    glx.glXChooseFBConfig = (glx_choose_fbconfig_fn)
        lookup_default_or_library("libGL.so.1", "glXChooseFBConfig");
    glx.glXGetVisualFromFBConfig = (glx_get_visual_from_fbconfig_fn)
        lookup_default_or_library("libGL.so.1", "glXGetVisualFromFBConfig");
    glx.glXGetFBConfigAttrib = (glx_get_fbconfig_attrib_fn)
        lookup_default_or_library("libGL.so.1", "glXGetFBConfigAttrib");
    glx.glXCreatePixmap = (glx_create_pixmap_fn)
        lookup_default_or_library("libGL.so.1", "glXCreatePixmap");
    glx.glXDestroyPixmap = (glx_destroy_pixmap_fn)
        lookup_default_or_library("libGL.so.1", "glXDestroyPixmap");
    glx.glXBindTexImageEXT =
        (glx_bind_tex_image_ext_fn)lookup_glx_extension("glXBindTexImageEXT");
    glx.glXReleaseTexImageEXT = (glx_release_tex_image_ext_fn)
        lookup_glx_extension("glXReleaseTexImageEXT");

    glx.ok = glx.XGetWindowAttributes != NULL && glx.XDefaultScreen != NULL &&
             glx.XVisualIDFromVisual != NULL && glx.XFree != NULL &&
             glx.glXQueryExtensionsString != NULL &&
             glx.glXChooseFBConfig != NULL &&
             glx.glXGetVisualFromFBConfig != NULL &&
             glx.glXGetFBConfigAttrib != NULL &&
             glx.glXCreatePixmap != NULL && glx.glXDestroyPixmap != NULL &&
             glx.glXBindTexImageEXT != NULL &&
             glx.glXReleaseTexImageEXT != NULL;
    if (trace_native_apviz()) {
        fprintf(stderr, "[tesla-native-apviz-shim] GLX fallback api %s\n",
                glx.ok ? "ready" : "unavailable");
    }
    return glx.ok;
}

static bool load_cpu_upload_api(void) {
    if (cpu.attempted) {
        return cpu.ok;
    }
    cpu.attempted = true;

    cpu.XGetWindowAttributes = (x_get_window_attributes_fn)
        lookup_default_or_library("libX11.so.6", "XGetWindowAttributes");
    cpu.XVisualIDFromVisual = (x_visual_id_from_visual_fn)
        lookup_default_or_library("libX11.so.6", "XVisualIDFromVisual");
    cpu.XGetImage =
        (x_get_image_fn)lookup_default_or_library("libX11.so.6", "XGetImage");
    cpu.XDestroyImage = (x_destroy_image_fn)
        lookup_default_or_library("libX11.so.6", "XDestroyImage");
    cpu.XGetPixel = (x_get_pixel_fn)
        lookup_default_or_library("libX11.so.6", "XGetPixel");
    cpu.glTexImage2D =
        (gl_tex_image_2d_fn)lookup_default_or_library("libGL.so.1",
                                                      "glTexImage2D");
    cpu.glPixelStorei =
        (gl_pixel_storei_fn)lookup_default_or_library("libGL.so.1",
                                                      "glPixelStorei");
    cpu.glGetError =
        (gl_get_error_fn)lookup_default_or_library("libGL.so.1",
                                                   "glGetError");
    cpu.glGetIntegerv =
        (gl_get_integerv_fn)lookup_default_or_library("libGL.so.1",
                                                      "glGetIntegerv");

    cpu.ok = cpu.XGetWindowAttributes != NULL &&
             cpu.XVisualIDFromVisual != NULL && cpu.XGetImage != NULL &&
             cpu.XDestroyImage != NULL && cpu.XGetPixel != NULL &&
             cpu.glTexImage2D != NULL && cpu.glPixelStorei != NULL &&
             cpu.glGetError != NULL && cpu.glGetIntegerv != NULL;
    if (trace_native_apviz()) {
        fprintf(stderr, "[tesla-native-apviz-shim] CPU upload api %s\n",
                cpu.ok ? "ready" : "unavailable");
    }
    return cpu.ok;
}

static void record_pixmap_source(Display *display,
                                 unsigned long window,
                                 unsigned long pixmap) {
    struct pixmap_source source = {
        .display = display,
        .window = window,
        .pixmap = pixmap,
    };

    if (load_cpu_upload_api()) {
        x_window_attributes attributes;
        memset(&attributes, 0, sizeof(attributes));
        if (cpu.XGetWindowAttributes(display, window, &attributes) != 0) {
            source.width = attributes.width;
            source.height = attributes.height;
            source.depth = attributes.depth;
            if (attributes.visual != NULL) {
                source.visualid =
                    cpu.XVisualIDFromVisual(attributes.visual);
            }
        }
    }

    pixmap_sources[pixmap_source_cursor++ % PIXMAP_SOURCE_COUNT] = source;
}

static const struct pixmap_source *find_pixmap_source(unsigned long pixmap) {
    for (unsigned int i = 0; i < PIXMAP_SOURCE_COUNT; ++i) {
        if (pixmap_sources[i].pixmap == pixmap) {
            return &pixmap_sources[i];
        }
    }
    return NULL;
}

static bool config_supports_texture(void *display,
                                    void *config,
                                    int *texture_format) {
    int bind_rgba = 0;
    int bind_rgb = 0;
    int targets = 0;

    glx.glXGetFBConfigAttrib(display, config, GLX_BIND_TO_TEXTURE_RGBA_EXT,
                             &bind_rgba);
    glx.glXGetFBConfigAttrib(display, config, GLX_BIND_TO_TEXTURE_RGB_EXT,
                             &bind_rgb);
    glx.glXGetFBConfigAttrib(display, config, GLX_BIND_TO_TEXTURE_TARGETS_EXT,
                             &targets);

    if ((targets & GLX_TEXTURE_2D_BIT_EXT) == 0) {
        return false;
    }
    if (bind_rgb) {
        *texture_format = GLX_TEXTURE_FORMAT_RGB_EXT;
        return true;
    }
    if (bind_rgba) {
        *texture_format = GLX_TEXTURE_FORMAT_RGBA_EXT;
        return true;
    }
    return false;
}

static void *choose_texture_fbconfig(struct fake_egl_image *image) {
    int count = 0;
    int screen = glx.XDefaultScreen(image->display);
    int attributes[] = {
        GLX_DRAWABLE_TYPE, GLX_PIXMAP_BIT,
        GLX_RENDER_TYPE, GLX_RGBA_BIT,
        GLX_X_RENDERABLE, 1,
        0,
    };
    void **configs =
        glx.glXChooseFBConfig(image->display, screen, attributes, &count);
    void *fallback = NULL;
    int fallback_format = 0;

    if (configs == NULL || count <= 0) {
        configs = glx.glXChooseFBConfig(image->display, screen, NULL, &count);
    }
    if (configs == NULL || count <= 0) {
        return NULL;
    }

    for (int i = 0; i < count; ++i) {
        int texture_format = 0;
        x_visual_info *visual =
            glx.glXGetVisualFromFBConfig(image->display, configs[i]);
        bool visual_matches =
            visual != NULL && visual->visualid == image->visualid &&
            (image->depth == 0 || visual->depth == image->depth);

        if (config_supports_texture(image->display, configs[i],
                                    &texture_format)) {
            if (fallback == NULL) {
                fallback = configs[i];
                fallback_format = texture_format;
            }
            if (visual_matches) {
                void *chosen = configs[i];
                image->texture_format = texture_format;
                if (visual != NULL) {
                    glx.XFree(visual);
                }
                glx.XFree(configs);
                return chosen;
            }
        }
        if (visual != NULL) {
            glx.XFree(visual);
        }
    }

    image->texture_format = fallback_format;
    glx.XFree(configs);
    return fallback;
}

static struct fake_egl_image *create_fake_egl_image(unsigned long pixmap) {
    const struct pixmap_source *source = find_pixmap_source(pixmap);
    struct fake_egl_image *image;

    if (!glx_fallback_enabled() || source == NULL || source->display == NULL) {
        return NULL;
    }

    image = calloc(1, sizeof(*image));
    if (image == NULL) {
        return NULL;
    }
    image->magic = TESLA_FAKE_EGL_MAGIC;
    image->display = source->display;
    image->window = source->window;
    image->pixmap = source->pixmap;
    image->width = source->width;
    image->height = source->height;
    image->depth = source->depth;
    image->visualid = source->visualid;

    if (cpu_upload_enabled()) {
        if (trace_native_apviz()) {
            fprintf(stderr,
                    "[tesla-native-apviz-shim] using CPU texture upload "
                    "fallback for pixmap=0x%lx window=0x%lx %dx%d depth=%d "
                    "visual=0x%lx\n",
                    image->pixmap, image->window, image->width, image->height,
                    image->depth, image->visualid);
        }
        return image;
    }

    if (!load_glx_api()) {
        free(image);
        return NULL;
    }

    {
        int screen = glx.XDefaultScreen(source->display);
        const char *extensions =
            glx.glXQueryExtensionsString(source->display, screen);
        if (extensions == NULL ||
            strstr(extensions, "GLX_EXT_texture_from_pixmap") == NULL) {
            if (trace_native_apviz()) {
                fprintf(stderr,
                        "[tesla-native-apviz-shim] GLX texture_from_pixmap "
                        "not exposed\n");
            }
            free(image);
            return NULL;
        }
    }

    image->fbconfig = choose_texture_fbconfig(image);
    if (image->fbconfig == NULL || image->texture_format == 0) {
        if (trace_native_apviz()) {
            fprintf(stderr,
                    "[tesla-native-apviz-shim] no GLX texture fbconfig for "
                    "pixmap=0x%lx visual=0x%lx depth=%d\n",
                    image->pixmap, image->visualid, image->depth);
        }
        free(image);
        return NULL;
    }

    if (trace_native_apviz()) {
        fprintf(stderr,
                "[tesla-native-apviz-shim] using GLX fallback for pixmap=0x%lx "
                "window=0x%lx %dx%d depth=%d visual=0x%lx format=0x%x\n",
                image->pixmap, image->window, image->width, image->height,
                image->depth, image->visualid, image->texture_format);
    }
    return image;
}

static bool is_fake_egl_image(void *image) {
    struct fake_egl_image *fake = (struct fake_egl_image *)image;
    return fake != NULL && fake->magic == TESLA_FAKE_EGL_MAGIC;
}

static int mask_shift(unsigned long mask) {
    int shift = 0;
    if (mask == 0) {
        return 0;
    }
    while ((mask & 1UL) == 0) {
        mask >>= 1;
        ++shift;
    }
    return shift;
}

static unsigned char component_to_8(unsigned long pixel, unsigned long mask) {
    int shift;
    unsigned long max_value;
    unsigned long value;

    if (mask == 0) {
        return 0;
    }
    shift = mask_shift(mask);
    max_value = mask >> shift;
    value = (pixel & mask) >> shift;
    if (max_value == 0) {
        return 0;
    }
    return (unsigned char)((value * 255UL) / max_value);
}

static unsigned long read_ximage_pixel(x_image *image, int x, int y) {
    unsigned char *row = (unsigned char *)image->data +
                         ((size_t)y * (size_t)image->bytes_per_line);
    if (image->bits_per_pixel == 32) {
        uint32_t pixel;
        memcpy(&pixel, row + ((size_t)x * 4U), sizeof(pixel));
        return pixel;
    }
    if (image->bits_per_pixel == 24) {
        unsigned char *p = row + ((size_t)x * 3U);
        if (image->byte_order == 0) {
            return (unsigned long)p[0] | ((unsigned long)p[1] << 8) |
                   ((unsigned long)p[2] << 16);
        }
        return ((unsigned long)p[0] << 16) | ((unsigned long)p[1] << 8) |
               (unsigned long)p[2];
    }
    return cpu.XGetPixel(image, x, y);
}

static unsigned int upload_rgba_texture(unsigned int target, int width,
                                        int height, const void *pixels) {
    int unpack_alignment = 4;
    /* Qt shares this context: its padded glyph rows need the original alignment. */
    cpu.glGetIntegerv(GL_UNPACK_ALIGNMENT, &unpack_alignment);
    cpu.glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    cpu.glTexImage2D(target, 0, GL_RGBA, width, height, 0,
                     GL_RGBA, GL_UNSIGNED_BYTE, pixels);
    unsigned int error = cpu.glGetError();
    cpu.glPixelStorei(GL_UNPACK_ALIGNMENT, unpack_alignment);
    return error;
}

static bool upload_fake_egl_image_cpu(unsigned int target,
                                      struct fake_egl_image *image) {
    x_image *ximage;
    unsigned char *pixels;
    size_t pixel_count;
    unsigned int error;
    unsigned long red_mask;
    unsigned long green_mask;
    unsigned long blue_mask;
    int bound_texture = 0;

    if (!cpu_upload_enabled() || target != GL_TEXTURE_2D ||
        image->width <= 0 || image->height <= 0 || !load_cpu_upload_api()) {
        return false;
    }

    /* A named Composite pixmap is a snapshot of the backing allocation.
     * Mapping or resizing replaces that allocation. Acquire the current one
     * for each upload so browser navigation and panel resizing cannot leave
     * the compositor displaying an abandoned backing store. */
    static xcomposite_name_window_pixmap_fn current_pixmap;
    static int (*free_pixmap)(Display *, unsigned long);
    if (!current_pixmap) current_pixmap = (xcomposite_name_window_pixmap_fn)
        lookup_next("XCompositeNameWindowPixmap");
    if (!free_pixmap) free_pixmap = lookup_default_or_library("libX11.so.6", "XFreePixmap");
    x_window_attributes current;
    if (!current_pixmap || !free_pixmap ||
        !cpu.XGetWindowAttributes(image->display, image->window, &current) ||
        current.map_state != 2 || current.width <= 0 || current.height <= 0)
        return false;
    unsigned long live_pixmap = current_pixmap(image->display, image->window);
    if (!live_pixmap) return false;
    image->width = current.width;
    image->height = current.height;
    ximage = cpu.XGetImage(image->display, live_pixmap, 0, 0,
                           (unsigned int)current.width,
                           (unsigned int)current.height, ~0UL, ZPixmap);
    free_pixmap(image->display, live_pixmap);
    if (ximage == NULL) {
        if (trace_native_apviz()) {
            fprintf(stderr,
                    "[tesla-native-apviz-shim] XGetImage failed for "
                    "pixmap=0x%lx %dx%d\n",
                    image->pixmap, image->width, image->height);
        }
        return false;
    }

    pixel_count = (size_t)image->width * (size_t)image->height;
    pixels = calloc(pixel_count, 4U);
    if (pixels == NULL) {
        cpu.XDestroyImage(ximage);
        return false;
    }

    red_mask = ximage->red_mask;
    green_mask = ximage->green_mask;
    blue_mask = ximage->blue_mask;
    if (red_mask == 0 && green_mask == 0 && blue_mask == 0 &&
        (ximage->bits_per_pixel == 24 || ximage->bits_per_pixel == 32)) {
        red_mask = 0x00ff0000UL;
        green_mask = 0x0000ff00UL;
        blue_mask = 0x000000ffUL;
    }

    for (int y = 0; y < image->height; ++y) {
        for (int x = 0; x < image->width; ++x) {
            unsigned long pixel = read_ximage_pixel(ximage, x, y);
            unsigned char *out =
                pixels + (((size_t)y * (size_t)image->width + (size_t)x) *
                          4U);
            if (red_mask == 0xff0000UL && green_mask == 0xff00UL && blue_mask == 0xffUL) {
                out[0] = (unsigned char)(pixel >> 16);
                out[1] = (unsigned char)(pixel >> 8);
                out[2] = (unsigned char)pixel;
            } else {
                out[0] = component_to_8(pixel, red_mask);
                out[1] = component_to_8(pixel, green_mask);
                out[2] = component_to_8(pixel, blue_mask);
            }
            out[3] = 255;
        }
    }

    cpu.glGetIntegerv(GL_TEXTURE_BINDING_2D, &bound_texture);
    if (bound_texture > 0) {
        image->texture_id = (unsigned int)bound_texture;
        register_texture_image(image);
    }
    error = upload_rgba_texture(target, image->width, image->height, pixels);
    if (error == GL_NO_ERROR) {
        image->last_upload_ms = monotonic_ms();
    }

    if (trace_native_apviz()) {
        fprintf(stderr,
                "[tesla-native-apviz-shim] CPU uploaded pixmap=0x%lx "
                "%dx%d bpp=%d masks=%lx/%lx/%lx used=%lx/%lx/%lx "
                "texture=%u glError=0x%x\n",
                image->pixmap, ximage->width, ximage->height,
                ximage->bits_per_pixel, ximage->red_mask, ximage->green_mask,
                ximage->blue_mask, red_mask, green_mask, blue_mask,
                image->texture_id, error);
    }

    free(pixels);
    cpu.XDestroyImage(ximage);
    return error == GL_NO_ERROR;
}

static bool bind_fake_egl_image(unsigned int target, void *raw_image) {
    struct fake_egl_image *image = (struct fake_egl_image *)raw_image;
    int pixmap_attributes[5];

    if (!is_fake_egl_image(raw_image)) {
        return false;
    }
    if (upload_fake_egl_image_cpu(target, image)) {
        return true;
    }
    if (!glx_bind_enabled() || !load_glx_api()) {
        return false;
    }
    if (target != GL_TEXTURE_2D) {
        if (trace_native_apviz()) {
            fprintf(stderr,
                    "[tesla-native-apviz-shim] refusing fake EGL bind for "
                    "target=0x%x\n",
                    target);
        }
        return false;
    }
    if (image->glx_pixmap == 0) {
        pixmap_attributes[0] = GLX_TEXTURE_TARGET_EXT;
        pixmap_attributes[1] = GLX_TEXTURE_2D_EXT;
        pixmap_attributes[2] = GLX_TEXTURE_FORMAT_EXT;
        pixmap_attributes[3] = image->texture_format;
        pixmap_attributes[4] = 0;
        if (trace_native_apviz()) {
            fprintf(stderr,
                    "[tesla-native-apviz-shim] creating GLX pixmap from "
                    "xpixmap=0x%lx format=0x%x\n",
                    image->pixmap, image->texture_format);
        }
        image->glx_pixmap =
            glx.glXCreatePixmap(image->display, image->fbconfig,
                                image->pixmap, pixmap_attributes);
        if (image->glx_pixmap == 0) {
            if (trace_native_apviz()) {
                fprintf(stderr,
                        "[tesla-native-apviz-shim] glXCreatePixmap failed "
                        "for pixmap=0x%lx\n",
                        image->pixmap);
            }
            return false;
        }
        if (trace_native_apviz()) {
            fprintf(stderr,
                    "[tesla-native-apviz-shim] created GLX pixmap=0x%lx\n",
                    image->glx_pixmap);
        }
    }

    if (trace_native_apviz()) {
        fprintf(stderr,
                "[tesla-native-apviz-shim] binding GLX pixmap=0x%lx\n",
                image->glx_pixmap);
    }
    glx.glXBindTexImageEXT(image->display, image->glx_pixmap,
                           GLX_FRONT_LEFT_EXT, NULL);
    image->bound = true;
    if (trace_native_apviz()) {
        fprintf(stderr,
                "[tesla-native-apviz-shim] bound GLX pixmap=0x%lx from "
                "xpixmap=0x%lx\n",
                image->glx_pixmap, image->pixmap);
    }
    return true;
}

static void destroy_fake_egl_image(void *raw_image) {
    struct fake_egl_image *image = (struct fake_egl_image *)raw_image;
    if (!is_fake_egl_image(raw_image)) {
        return;
    }
    unregister_texture_image(image);
    if (image->glx_pixmap != 0 && load_glx_api()) {
        if (image->bound && image->glx_pixmap != 0) {
            glx.glXReleaseTexImageEXT(image->display, image->glx_pixmap,
                                      GLX_FRONT_LEFT_EXT);
        }
        if (image->glx_pixmap != 0) {
            glx.glXDestroyPixmap(image->display, image->glx_pixmap);
        }
    }
    if (trace_native_apviz()) {
        fprintf(stderr,
                "[tesla-native-apviz-shim] destroyed fake EGL image for "
                "pixmap=0x%lx\n",
                image->pixmap);
    }
    image->magic = 0;
    free(image);
}

static void *tesla_eglCreateImageKHR(void *display,
                                     void *context,
                                     unsigned int target,
                                     void *buffer,
                                     const int *attributes) {
    void *image = NULL;
    int error = 0;
    unsigned long pixmap = (unsigned long)buffer;

    if (real_egl_create_image_khr != NULL) {
        image = real_egl_create_image_khr(display, context, target, buffer,
                                          attributes);
    }

    if (target == EGL_NATIVE_PIXMAP_KHR && image == NULL) {
        egl_get_error_fn egl_get_error =
            (egl_get_error_fn)lookup_next("eglGetError");
        error = egl_get_error != NULL ? egl_get_error() : 0;
        image = create_fake_egl_image(pixmap);
    }

    if (trace_native_apviz() && target == EGL_NATIVE_PIXMAP_KHR) {
        if (image == NULL) {
            fprintf(stderr,
                    "[tesla-native-apviz-shim] eglCreateImageKHR target=0x%x "
                    "buffer=%p failed error=0x%x\n",
                    target, buffer, error);
        } else if (is_fake_egl_image(image)) {
            fprintf(stderr,
                    "[tesla-native-apviz-shim] eglCreateImageKHR target=0x%x "
                    "buffer=%p using fake GLX image=%p error=0x%x\n",
                    target, buffer, image, error);
        } else {
            fprintf(stderr,
                    "[tesla-native-apviz-shim] eglCreateImageKHR target=0x%x "
                    "buffer=%p image=%p\n",
                    target, buffer, image);
        }
    }

    return image;
}

static int tesla_eglDestroyImageKHR(void *display, void *image) {
    if (is_fake_egl_image(image)) {
        destroy_fake_egl_image(image);
        return 1;
    }
    if (real_egl_destroy_image_khr != NULL) {
        return real_egl_destroy_image_khr(display, image);
    }
    return 0;
}

void glBindTexture(unsigned int target, unsigned int texture) {
    static gl_bind_texture_fn real_gl_bind_texture;
    struct fake_egl_image *image;
    long long now;
    long interval;

    if (real_gl_bind_texture == NULL) {
        real_gl_bind_texture =
            (gl_bind_texture_fn)lookup_next("glBindTexture");
    }
    if (real_gl_bind_texture != NULL) {
        real_gl_bind_texture(target, texture);
    }

    if (target != GL_TEXTURE_2D || texture == 0 || !cpu_upload_enabled()) {
        return;
    }

    image = find_texture_image(texture);
    if (image == NULL) {
        return;
    }

    interval = refresh_interval_ms();
    now = monotonic_ms();
    if (interval > 0 && image->last_upload_ms != 0 &&
        now - image->last_upload_ms < interval) {
        return;
    }
    upload_fake_egl_image_cpu(target, image);
}

static void tesla_glEGLImageTargetTexture2DOES(unsigned int target,
                                               void *image) {
    if (is_fake_egl_image(image)) {
        bind_fake_egl_image(target, image);
        return;
    }
    if (real_gl_egl_image_target_texture_2d_oes != NULL) {
        real_gl_egl_image_target_texture_2d_oes(target, image);
    }
}

void *eglGetProcAddress(const char *name) {
    static egl_get_proc_address_fn real_egl_get_proc_address;
    void *fn;

    if (real_egl_get_proc_address == NULL) {
        real_egl_get_proc_address =
            (egl_get_proc_address_fn)lookup_next("eglGetProcAddress");
    }
    fn = real_egl_get_proc_address != NULL ? real_egl_get_proc_address(name)
                                           : NULL;

    if (name != NULL && strcmp(name, "eglCreateImageKHR") == 0) {
        real_egl_create_image_khr = (egl_create_image_khr_fn)fn;
        if (trace_native_apviz()) {
            fprintf(stderr,
                    "[tesla-native-apviz-shim] hooked eglCreateImageKHR=%p\n",
                    fn);
        }
        return (void *)&tesla_eglCreateImageKHR;
    }
    if (name != NULL && strcmp(name, "eglDestroyImageKHR") == 0) {
        real_egl_destroy_image_khr = (egl_destroy_image_khr_fn)fn;
        if (trace_native_apviz()) {
            fprintf(stderr,
                    "[tesla-native-apviz-shim] hooked eglDestroyImageKHR=%p\n",
                    fn);
        }
        return (void *)&tesla_eglDestroyImageKHR;
    }
    if (name != NULL && strcmp(name, "glEGLImageTargetTexture2DOES") == 0) {
        real_gl_egl_image_target_texture_2d_oes =
            (gl_egl_image_target_texture_2d_oes_fn)fn;
        if (trace_native_apviz()) {
            fprintf(stderr,
                    "[tesla-native-apviz-shim] hooked "
                    "glEGLImageTargetTexture2DOES=%p\n",
                    fn);
        }
        return (void *)&tesla_glEGLImageTargetTexture2DOES;
    }

    return fn;
}

unsigned long XCompositeNameWindowPixmap(void *display, unsigned long window) {
    static xcomposite_name_window_pixmap_fn real_name_window_pixmap;
    unsigned long pixmap = 0;

    if (real_name_window_pixmap == NULL) {
        real_name_window_pixmap = (xcomposite_name_window_pixmap_fn)
            lookup_next("XCompositeNameWindowPixmap");
    }
    if (real_name_window_pixmap != NULL) {
        pixmap = real_name_window_pixmap(display, window);
    }
    if (pixmap != 0) {
        record_pixmap_source((Display *)display, window, pixmap);
    }
    if (trace_native_apviz()) {
        fprintf(stderr,
                "[tesla-native-apviz-shim] XCompositeNameWindowPixmap "
                "window=0x%lx pixmap=0x%lx\n",
                window, pixmap);
    }
    return pixmap;
}

void XCompositeRedirectWindow(void *display, unsigned long window, int update) {
    static xcomposite_redirect_window_fn real_redirect_window;

    if (real_redirect_window == NULL) {
        real_redirect_window = (xcomposite_redirect_window_fn)
            lookup_next("XCompositeRedirectWindow");
    }
    if (trace_native_apviz()) {
        fprintf(stderr,
                "[tesla-native-apviz-shim] XCompositeRedirectWindow "
                "window=0x%lx update=%d\n",
                window, update);
    }
    if (real_redirect_window != NULL) {
        real_redirect_window(display, window, update);
    }
}

void _ZN22VizExternalDisplayViewC1EP11DisplayViewRK7QStringbRK9SkinColorb(
    void *self,
    void *parent,
    const void *window_name,
    bool direct_viz,
    const void *background,
    bool external_composite) {
    static viz_external_display_ctor real_ctor;
    static bool logged;
    if (real_ctor == NULL) {
        real_ctor = lookup_ctor(
            "_ZN22VizExternalDisplayViewC1EP11DisplayViewRK7QStringbRK9SkinColorb");
    }

    if (force_native_apviz()) {
        if (!logged) {
            fprintf(stderr,
                    "[tesla-native-apviz-shim] forcing VizExternalDisplayView "
                    "native flags on\n");
            logged = true;
        }
        direct_viz = true;
        external_composite = true;
    }

    real_ctor(self, parent, window_name, direct_viz, background,
              external_composite);
}

void _ZN22VizExternalDisplayViewC2EP11DisplayViewRK7QStringbRK9SkinColorb(
    void *self,
    void *parent,
    const void *window_name,
    bool direct_viz,
    const void *background,
    bool external_composite) {
    static viz_external_display_ctor real_ctor;
    if (real_ctor == NULL) {
        real_ctor = lookup_ctor(
            "_ZN22VizExternalDisplayViewC2EP11DisplayViewRK7QStringbRK9SkinColorb");
    }

    if (force_native_apviz()) {
        direct_viz = true;
        external_composite = true;
    }

    real_ctor(self, parent, window_name, direct_viz, background,
              external_composite);
}

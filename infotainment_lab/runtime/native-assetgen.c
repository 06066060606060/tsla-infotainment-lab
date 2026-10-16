/* Share the generated-asset cache between the owned UI and Godot workers.
 * Firmware's StorageUtils defaults to /home/godot on the vehicle. Redirect
 * that exported path function, without changing Qt object layouts or images. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdlib.h>

void *asset_data_folder(void *result) __asm__("_ZN12StorageUtils15godotDataFolderEv");
void *asset_data_folder(void *result) {
    const char *path = getenv("TESLA_NATIVE_ASSET_DATA");
    if (path && path[0] == '/') {
        /* QString returns through the caller's hidden result pointer. Let
         * Qt construct it, preserving its own allocation and encoding. */
        void *(*from_utf8)(void *, const char *, int) =
            dlsym(RTLD_NEXT, "_ZN7QString8fromUtf8EPKci");
        /* Godot loads its Qt-based app with local symbol visibility. */
        if (!from_utf8) {
            void *qt = dlopen("libQtCore.so.4", RTLD_LAZY | RTLD_NOLOAD);
            if (qt) {
                from_utf8 = dlsym(qt, "_ZN7QString8fromUtf8EPKci");
                dlclose(qt);
            }
        }
        if (!from_utf8) abort();
        from_utf8(result, path, -1);
        return result;
    }
    void *(*next)(void *) = dlsym(RTLD_NEXT, "_ZN12StorageUtils15godotDataFolderEv");
    if (!next) abort();
    return next(result);
}

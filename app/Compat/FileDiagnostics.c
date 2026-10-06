#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

static int (*nativeOpen)(const char *, int, ...);
static FILE *(*nativeFopen)(const char *, const char *);
static int (*nativeStat)(const char *, struct stat *);
static int (*nativeAccess)(const char *, int);
static pthread_once_t once = PTHREAD_ONCE_INIT;

static void LoadFileFunctions(void) {
    void *system = dlopen("/usr/lib/libSystem.B.dylib", RTLD_NOW | RTLD_LOCAL | RTLD_FIRST);
    nativeOpen = dlsym(system, "open");
    nativeFopen = dlsym(system, "fopen");
    nativeStat = dlsym(system, "stat");
    nativeAccess = dlsym(system, "access");
    if (!nativeOpen || !nativeFopen || !nativeStat || !nativeAccess) abort();
}

static void RecordFailure(const char *operation, const char *path, void *caller) {
    int error = errno;
    if (!getenv("EMU_DIAGNOSTICS")) { errno = error; return; }
    Dl_info image = {0};
    static atomic_uint reports;
    if (dladdr(caller, &image) && image.dli_fname &&
        strstr(image.dli_fname, "/GameClient.framework/GameClient") &&
        atomic_fetch_add(&reports, 1) < 160) {
        fprintf(stderr, "GameFile: %s errno=%d path=%s\n", operation, error, path ? path : "(null)");
    }
    errno = error;
}

int SROpen(const char *path, int flags, ...) __asm__("_open");
int SROpen(const char *path, int flags, ...) {
    pthread_once(&once, LoadFileFunctions);
    int result;
    if (flags & O_CREAT) {
        va_list arguments; va_start(arguments, flags);
        int mode = va_arg(arguments, int); va_end(arguments);
        result = nativeOpen(path, flags, mode);
    } else result = nativeOpen(path, flags);
    if (result < 0) RecordFailure("open", path, __builtin_return_address(0));
    return result;
}

FILE *SRFopen(const char *path, const char *mode) __asm__("_fopen");
FILE *SRFopen(const char *path, const char *mode) {
    pthread_once(&once, LoadFileFunctions);
    FILE *result = nativeFopen(path, mode);
    if (!result) RecordFailure("fopen", path, __builtin_return_address(0));
    return result;
}

int SRStat(const char *path, struct stat *info) __asm__("_stat");
int SRStat(const char *path, struct stat *info) {
    pthread_once(&once, LoadFileFunctions);
    int result = nativeStat(path, info);
    if (result < 0) RecordFailure("stat", path, __builtin_return_address(0));
    return result;
}

int SRAccess(const char *path, int mode) __asm__("_access");
int SRAccess(const char *path, int mode) {
    pthread_once(&once, LoadFileFunctions);
    int result = nativeAccess(path, mode);
    if (result < 0) RecordFailure("access", path, __builtin_return_address(0));
    return result;
}

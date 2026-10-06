// Unsupported desktop calls fail explicitly instead of returning fake success.
#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <syslog.h>
static void Stop(const char *name, void *caller) __attribute__((noreturn));
static void Stop(const char *name, void *caller) {
    Dl_info image = {0}; dladdr(caller, &image);
    NSString *path = [NSHomeDirectory() stringByAppendingPathComponent:@"Documents/guest-load.log"];
    FILE *file = fopen(path.fileSystemRepresentation, "a");
    if (file) { fprintf(file, "UNIMPLEMENTED %s caller=%s+0x%lx\n", name, image.dli_fname ?: "?", (unsigned long)((char *)caller-(char *)image.dli_fbase)); fclose(file); }
    fprintf(stderr, "UNIMPLEMENTED %s\n", name); abort();
}
@interface SRMissingDesktopObject : NSObject @end
@implementation SRMissingDesktopObject
+ (id)forwardingTargetForSelector:(SEL)s { Stop([[NSString stringWithFormat:@"+[%@ %@]", NSStringFromClass(self), NSStringFromSelector(s)] UTF8String], __builtin_return_address(0)); }
- (id)forwardingTargetForSelector:(SEL)s { Stop([[NSString stringWithFormat:@"-[%@ %@]", NSStringFromClass(self.class), NSStringFromSelector(s)] UTF8String], __builtin_return_address(0)); }
@end

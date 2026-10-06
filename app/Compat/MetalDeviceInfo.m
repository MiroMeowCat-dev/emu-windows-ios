#import <Metal/Metal.h>
#import <objc/runtime.h>

// Describe the single built-in display GPU. Keep every existing native method.
static BOOL LowPower(id device, SEL selector) { return NO; }
static BOOL Headless(id device, SEL selector) { return NO; }
static BOOL Removable(id device, SEL selector) { return NO; }
static NSUInteger Location(id device, SEL selector) { return 0; } // MTLDeviceLocationBuiltIn.
static NSUInteger LocationNumber(id device, SEL selector) { return 1; }

__attribute__((constructor)) static void RegisterDeviceDescription(void) {
    id<MTLDevice> device = MTLCreateSystemDefaultDevice();
    if (!device) return;
    Class type = object_getClass(device);
    struct { const char *name; IMP implementation; const char *encoding; } methods[] = {
        {"isLowPower", (IMP)LowPower, "B@:"},
        {"isHeadless", (IMP)Headless, "B@:"},
        {"isRemovable", (IMP)Removable, "B@:"},
        {"location", (IMP)Location, "Q@:"},
        {"locationNumber", (IMP)LocationNumber, "Q@:"}
    };
    for (unsigned i = 0; i < sizeof(methods) / sizeof(methods[0]); ++i) {
        SEL selector = sel_registerName(methods[i].name);
        if (!class_getInstanceMethod(type, selector)) {
            class_addMethod(type, selector, methods[i].implementation, methods[i].encoding);
        }
    }
}

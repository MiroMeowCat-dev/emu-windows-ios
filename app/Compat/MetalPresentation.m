#import <QuartzCore/CAMetalLayer.h>
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char gameDrawableSizeKey;
static void (*nativeSetDrawableSize)(id, SEL, CGSize);

static void SetDrawableSize(CAMetalLayer *layer, SEL selector, CGSize size) {
    Dl_info caller = {0};
    BOOL fromGame = dladdr(__builtin_return_address(0), &caller) && caller.dli_fname &&
                    strstr(caller.dli_fname, "/GameClient.framework/GameClient");
    if (fromGame) {
        // The engine owns its render resolution. UIKit can resize the view,
        // but must not replace that resolution after the viewport was set.
        objc_setAssociatedObject(layer, &gameDrawableSizeKey, [NSValue valueWithCGSize:size], OBJC_ASSOCIATION_RETAIN_NONATOMIC);
        layer.contentsGravity = kCAGravityResize;
        if (getenv("EMU_DIAGNOSTICS"))
            fprintf(stderr, "MetalPresentation: game resolution %.0fx%.0f\n", size.width, size.height);
    } else {
        NSValue *requested = objc_getAssociatedObject(layer, &gameDrawableSizeKey);
        if (requested) {
            CGSize gameSize = requested.CGSizeValue;
            static unsigned reports;
            if (getenv("EMU_DIAGNOSTICS") && !CGSizeEqualToSize(size, gameSize) && reports++ < 8) {
                fprintf(stderr, "MetalPresentation: keep %.0fx%.0f instead of automatic %.0fx%.0f\n",
                        gameSize.width, gameSize.height, size.width, size.height);
            }
            size = gameSize;
        }
    }
    nativeSetDrawableSize(layer, selector, size);
}

__attribute__((constructor)) static void RegisterPresentation(void) {
    Method method = class_getInstanceMethod(CAMetalLayer.class, @selector(setDrawableSize:));
    nativeSetDrawableSize = (void *)method_setImplementation(method, (IMP)SetDrawableSize);
}

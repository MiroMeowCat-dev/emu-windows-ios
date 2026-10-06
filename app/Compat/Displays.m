#import <UIKit/UIKit.h>
#import <QuartzCore/CAMetalLayer.h>
#import <objc/runtime.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

static UIScreen *Screen(uint32_t identifier) {
    NSArray<UIScreen *> *screens = UIScreen.screens;
    return identifier > 0 && identifier <= screens.count ? screens[identifier - 1] : nil;
}

static CGRect ScreenBounds(UIScreen *screen) {
    for (UIScene *scene in UIApplication.sharedApplication.connectedScenes) {
        if ([scene isKindOfClass:UIWindowScene.class] &&
            scene.activationState == UISceneActivationStateForegroundActive &&
            ((UIWindowScene *)scene).screen == screen) {
            return ((UIWindowScene *)scene).coordinateSpace.bounds;
        }
    }
    return screen.bounds;
}

@interface SRNSScreen : NSObject
@property(nonatomic, strong) UIScreen *screen;
@property(nonatomic) uint32_t identifier;
@end

@implementation SRNSScreen
+ (NSArray *)screens {
    NSMutableArray *result = [NSMutableArray array];
    uint32_t identifier = 1;
    for (UIScreen *screen in UIScreen.screens) {
        SRNSScreen *item = [SRNSScreen new];
        item.screen = screen;
        item.identifier = identifier++;
        [result addObject:item];
    }
    return result;
}
+ (id)mainScreen { return [[self screens] firstObject]; }
- (NSDictionary *)deviceDescription { return @{@"NSScreenNumber":@(self.identifier)}; }
- (CGFloat)backingScaleFactor { return self.screen.nativeScale; }
- (CGRect)frame { return ScreenBounds(self.screen); }
- (CGRect)visibleFrame { return ScreenBounds(self.screen); }
@end

@interface SRDisplayMode : NSObject
@property(nonatomic) CGSize pixels;
@property(nonatomic) CGFloat scale;
@property(nonatomic) double refresh;
@end
@implementation SRDisplayMode @end

static SRDisplayMode *Mode(UIScreen *screen, UIScreenMode *mode) {
    if (!screen || !mode) return nil;
    SRDisplayMode *result = [SRDisplayMode new];
    CGSize size = mode.size;
    CGSize bounds = ScreenBounds(screen).size;
    if ((bounds.width > bounds.height) != (size.width > size.height)) {
        size = CGSizeMake(size.height, size.width);
    }
    result.pixels = size;
    result.scale = screen.nativeScale;
    result.refresh = screen.maximumFramesPerSecond;
    return result;
}

uint32_t CGMainDisplayID(void) { return 1; }
CGRect CGDisplayBounds(uint32_t identifier) { return ScreenBounds(Screen(identifier)); }
int32_t CGDisplayIsMain(uint32_t identifier) { return identifier == 1; }
uint32_t CGDisplayMirrorsDisplay(uint32_t identifier) {
    UIScreen *mirrored = Screen(identifier).mirroredScreen;
    NSUInteger index = mirrored ? [UIScreen.screens indexOfObjectIdenticalTo:mirrored] : NSNotFound;
    return index == NSNotFound ? 0 : (uint32_t)index + 1;
}
size_t CGDisplayPixelsWide(uint32_t identifier) {
    UIScreen *screen = Screen(identifier);
    return (size_t)Mode(screen, screen.currentMode).pixels.width;
}
size_t CGDisplayPixelsHigh(uint32_t identifier) {
    UIScreen *screen = Screen(identifier);
    return (size_t)Mode(screen, screen.currentMode).pixels.height;
}
int32_t CGGetOnlineDisplayList(uint32_t capacity, uint32_t *displays, uint32_t *count) {
    if (!count) return 1001;
    NSArray *screens = UIScreen.screens;
    if (!displays) { *count = (uint32_t)screens.count; return 0; }
    *count = MIN(capacity, (uint32_t)screens.count);
    for (uint32_t i = 0; i < *count; ++i) displays[i] = i + 1;
    return 0;
}
void *CGDisplayCopyDisplayMode(uint32_t identifier) {
    UIScreen *screen = Screen(identifier);
    return (void *)CFBridgingRetain(Mode(screen, screen.currentMode));
}
CFArrayRef CGDisplayCopyAllDisplayModes(uint32_t identifier, CFDictionaryRef options) {
    UIScreen *screen = Screen(identifier);
    if (!screen) return NULL;
    NSMutableArray *result = [NSMutableArray array];
    for (UIScreenMode *mode in screen.availableModes) [result addObject:Mode(screen, mode)];
    if (!result.count && screen.currentMode) [result addObject:Mode(screen, screen.currentMode)];
    // These are render sizes, not new physical display timings. The game reads
    // their pixel dimensions and resizes its own Metal drawable accordingly.
    SRDisplayMode *native = Mode(screen, screen.currentMode);
    const CGFloat heights[] = {540, 630, 720, 840, 900, 1080};
    for (NSUInteger i = 0; native && i < sizeof(heights) / sizeof(heights[0]); ++i) {
        CGFloat height = heights[i];
        if (height >= native.pixels.height) continue;
        CGFloat width = round(height * native.pixels.width / native.pixels.height / 2) * 2;
        CGSize pixels = CGSizeMake(width, height);
        BOOL duplicate = NO;
        for (SRDisplayMode *mode in result) if (CGSizeEqualToSize(mode.pixels, pixels)) duplicate = YES;
        if (duplicate) continue;
        SRDisplayMode *scaled = [SRDisplayMode new];
        scaled.pixels = pixels;
        scaled.scale = 1;
        scaled.refresh = native.refresh;
        [result addObject:scaled];
    }
    static BOOL reported;
    if (!reported && getenv("EMU_DIAGNOSTICS")) {
        reported = YES;
        for (SRDisplayMode *mode in result)
            fprintf(stderr, "DisplayModes: %.0fx%.0f\n", mode.pixels.width, mode.pixels.height);
    }
    return CFBridgingRetain(result);
}
size_t CGDisplayModeGetPixelWidth(void *value) { return (size_t)((__bridge SRDisplayMode *)value).pixels.width; }
size_t CGDisplayModeGetPixelHeight(void *value) { return (size_t)((__bridge SRDisplayMode *)value).pixels.height; }
size_t CGDisplayModeGetWidth(void *value) {
    SRDisplayMode *mode = (__bridge SRDisplayMode *)value;
    return mode.scale > 0 ? (size_t)(mode.pixels.width / mode.scale) : 0;
}
size_t CGDisplayModeGetHeight(void *value) {
    SRDisplayMode *mode = (__bridge SRDisplayMode *)value;
    return mode.scale > 0 ? (size_t)(mode.pixels.height / mode.scale) : 0;
}
double CGDisplayModeGetRefreshRate(void *value) { return ((__bridge SRDisplayMode *)value).refresh; }
uint32_t CGDisplayModeGetIOFlags(void *value) { return value ? 3 : 0; }
bool CGDisplayModeIsUsableForDesktopGUI(void *value) { return value != NULL; }
CFStringRef CGDisplayModeCopyPixelEncoding(void *value) {
    return value ? CFRetain(CFSTR("IO32BitDirectPixels")) : NULL;
}
void CGDisplayModeRelease(void *value) { if (value) CFRelease(value); }

NSDictionary *SRDisplayModesTest(void) {
    void *current = CGDisplayCopyDisplayMode(CGMainDisplayID());
    CGSize native = CGSizeMake(CGDisplayModeGetPixelWidth(current), CGDisplayModeGetPixelHeight(current));
    CFArrayRef modes = CGDisplayCopyAllDisplayModes(CGMainDisplayID(), NULL);
    NSMutableArray *sizes = [NSMutableArray new];
    BOOL nativeFound = NO, valid = modes != NULL;
    for (id mode in (__bridge NSArray *)modes) {
        void *value = (__bridge void *)mode;
        size_t w = CGDisplayModeGetPixelWidth(value), h = CGDisplayModeGetPixelHeight(value);
        valid = valid && w > 0 && h > 0 && w <= native.width && h <= native.height;
        nativeFound = nativeFound || (w == native.width && h == native.height);
        [sizes addObject:@[@(w), @(h)]];
    }
    if (modes) CFRelease(modes);
    CGDisplayModeRelease(current);
    return @{@"native":@[@(native.width), @(native.height)], @"modes":sizes,
             @"passed":@(valid && nativeFound && sizes.count >= 7)};
}

// iOS presents through its synchronized compositor. Preserve that actual behavior.
static BOOL SyncEnabled(id layer, SEL selector) { return YES; }
static void SetSyncEnabled(id layer, SEL selector, BOOL enabled) {
    if (!enabled) NSLog(@"SnowRunner requested unsynchronized presentation; iOS compositor remains synchronized");
}
__attribute__((constructor)) static void RegisterLayerCompatibility(void) {
    Class layer = CAMetalLayer.class;
    SEL getter = NSSelectorFromString(@"displaySyncEnabled");
    SEL setter = NSSelectorFromString(@"setDisplaySyncEnabled:");
    if (!class_getInstanceMethod(layer, getter)) class_addMethod(layer, getter, (IMP)SyncEnabled, "B@:");
    if (!class_getInstanceMethod(layer, setter)) class_addMethod(layer, setter, (IMP)SetSyncEnabled, "v@:B");
}

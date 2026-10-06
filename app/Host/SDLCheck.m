#define SDL_MAIN_HANDLED
#import "SDLCheck.h"
#import <Metal/Metal.h>
#import <QuartzCore/CAMetalLayer.h>
#include <SDL2/SDL.h>
#include <SDL2/SDL_syswm.h>
#include <dlfcn.h>
#include "../Compat/SDL2264Indices.h"

#define CALL(name) ((__typeof__(&name))table[index_##name])

static void Stage(NSString *text) {
    NSURL *documents = [NSFileManager.defaultManager URLsForDirectory:NSDocumentDirectory inDomains:NSUserDomainMask].firstObject;
    FILE *file = fopen([documents URLByAppendingPathComponent:@"sdl-stage.log"].fileSystemRepresentation, "a");
    if (file) { fprintf(file, "%s\n", text.UTF8String); fclose(file); }
    NSLog(@"SDL_CHECK %@", text);
}

void RunSDLCheck(UIWindow *hostWindow, void (^completion)(NSDictionary *, NSString *)) {
    [NSData.data writeToFile:[NSHomeDirectory() stringByAppendingPathComponent:@"Documents/sdl-stage.log"] atomically:YES];
    Stage(@"START");
    NSMutableDictionary *result = [NSMutableDictionary dictionary];
    result[@"gameClientLoaded"] = @NO;
    result[@"gameFrameRendered"] = @NO;
    result[@"time"] = [[NSISO8601DateFormatter new] stringFromDate:NSDate.date];
    NSString *path = [NSBundle.mainBundle.privateFrameworksPath stringByAppendingPathComponent:@"SDLBridge.framework/SDLBridge"];
    void *bridge = dlopen(path.fileSystemRepresentation, RTLD_NOW | RTLD_LOCAL | RTLD_FIRST);
    int32_t (*entry)(uint32_t, void *, uint32_t) = bridge ? dlsym(bridge, "SDL_DYNAPI_entry") : NULL;
    void *table[833] = {0};
    int status = entry ? entry(1, table, sizeof(table)) : -1;
    result[@"tableEntries"] = @833;
    result[@"tableReady"] = @(status == 0);
    Stage([NSString stringWithFormat:@"TABLE %d", status]);
    if (status != 0) {
        const char *error = dlerror();
        result[@"error"] = error ? @(error) : @"Could not populate the SDL function table";
        completion(result, result[@"error"]);
        return;
    }

    SDL_version version;
    CALL(SDL_GetVersion)(&version);
    result[@"nativeVersion"] = [NSString stringWithFormat:@"%u.%u.%u", version.major, version.minor, version.patch];
    result[@"platform"] = @(CALL(SDL_GetPlatform)());
    CALL(SDL_SetMainReady)();
    CALL(SDL_SetHint)(SDL_HINT_RENDER_DRIVER, "metal");
    int initialized = CALL(SDL_Init)(SDL_INIT_VIDEO | SDL_INIT_EVENTS);
    Stage([NSString stringWithFormat:@"INIT %d", initialized]);
    result[@"initialized"] = @(initialized == 0);
    if (initialized != 0) {
        result[@"error"] = @(CALL(SDL_GetError)());
        CALL(SDL_Quit)();
        completion(result, result[@"error"]);
        return;
    }
    const char *driver = CALL(SDL_GetCurrentVideoDriver)();
    result[@"videoDriver"] = driver ? @(driver) : @"";

    SDL_Window *window = CALL(SDL_CreateWindow)("SDL iOS check", SDL_WINDOWPOS_UNDEFINED,
        SDL_WINDOWPOS_UNDEFINED, 640, 360, SDL_WINDOW_METAL | SDL_WINDOW_ALLOW_HIGHDPI);
    result[@"windowCreated"] = @(window != NULL);
    Stage([NSString stringWithFormat:@"WINDOW %d", window != NULL]);
    SDL_MetalView metalView = window ? CALL(SDL_Metal_CreateView)(window) : NULL;
    result[@"metalViewCreated"] = @(metalView != NULL);
    SDL_SysWMinfo info;
    memset(&info, 0, sizeof(info));
    SDL_VERSION(&info.version);
    BOOL windowInfo = window && CALL(SDL_GetWindowWMInfo)(window, &info);
    UIWindow *nativeWindow = windowInfo && info.subsystem == SDL_SYSWM_UIKIT ? info.info.uikit.window : nil;
    result[@"uikitWindowFound"] = @(nativeWindow != nil);
    Stage([NSString stringWithFormat:@"UIKIT_WINDOW %d", nativeWindow != nil]);
    if (nativeWindow) {
        nativeWindow.hidden = YES;
        nativeWindow.windowScene = hostWindow.windowScene;
        [nativeWindow makeKeyAndVisible];
        [nativeWindow layoutIfNeeded];
        UILabel *label = [[UILabel alloc] initWithFrame:CGRectInset(nativeWindow.bounds, 24, 24)];
        label.text = @"SDL for iOS\n\nDiagnostic surface; no game code is loaded.";
        label.textColor = UIColor.whiteColor;
        label.font = [UIFont systemFontOfSize:22 weight:UIFontWeightMedium];
        label.textAlignment = NSTextAlignmentCenter;
        label.numberOfLines = 0;
        label.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
        [nativeWindow addSubview:label];
    }

    CAMetalLayer *layer = metalView ? (__bridge CAMetalLayer *)CALL(SDL_Metal_GetLayer)(metalView) : nil;
    id<MTLDevice> device = MTLCreateSystemDefaultDevice();
    layer.device = device;
    layer.pixelFormat = MTLPixelFormatBGRA8Unorm;
    layer.drawableSize = CGSizeMake(640, 360);
    id<CAMetalDrawable> drawable = nativeWindow && layer ? [layer nextDrawable] : nil;
    result[@"drawableCreated"] = @(drawable != nil);
    id<MTLCommandBuffer> buffer = nil;
    if (drawable) {
        MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
        pass.colorAttachments[0].texture = drawable.texture;
        pass.colorAttachments[0].loadAction = MTLLoadActionClear;
        pass.colorAttachments[0].storeAction = MTLStoreActionStore;
        pass.colorAttachments[0].clearColor = MTLClearColorMake(0.03, 0.14, 0.20, 1.0);
        id<MTLCommandQueue> queue = [device newCommandQueue];
        buffer = [queue commandBuffer];
        id<MTLRenderCommandEncoder> encoder = [buffer renderCommandEncoderWithDescriptor:pass];
        [encoder endEncoding];
        [buffer presentDrawable:drawable];
        [buffer commit];
        [buffer waitUntilCompleted];
    }
    result[@"diagnosticFrameCompleted"] = @(buffer && buffer.status == MTLCommandBufferStatusCompleted);
    Stage([NSString stringWithFormat:@"FRAME %d", [result[@"diagnosticFrameCompleted"] boolValue]]);
    result[@"metalError"] = buffer.error.description ?: @"";

    SDL_Event event;
    memset(&event, 0, sizeof(event));
    event.type = SDL_USEREVENT;
    event.user.code = 0x534e4f57;
    int pushed = CALL(SDL_PushEvent)(&event);
    BOOL found = NO;
    for (int i = 0; i < 100 && CALL(SDL_PollEvent)(&event); ++i) {
        if (event.type == SDL_USEREVENT && event.user.code == 0x534e4f57) found = YES;
    }
    result[@"eventRoundTrip"] = @(pushed == 1 && found);
    SDL_Event finger = {0}, mouse = {0};
    finger.type = SDL_FINGERMOTION;
    mouse.type = SDL_MOUSEMOTION;
    mouse.motion.which = SDL_TOUCH_MOUSEID;
    mouse.motion.x = 123; mouse.motion.y = 456;
    CALL(SDL_PushEvent)(&finger);
    CALL(SDL_PushEvent)(&mouse);
    BOOL rawFingerSeen = NO, translatedMouseSeen = NO;
    for (int i = 0; i < 100 && CALL(SDL_PollEvent)(&event); ++i) {
        if (event.type == SDL_FINGERMOTION) rawFingerSeen = YES;
        if (event.type == SDL_MOUSEMOTION && event.motion.x == 123 && event.motion.y == 456) translatedMouseSeen = YES;
    }
    result[@"rawFingerEventsHidden"] = @(!rawFingerSeen);
    result[@"mouseEventsPreserved"] = @(translatedMouseSeen);
    // Exercise real native coordinates, not just pushed events. A programmatic
    // warp need not accumulate motion deltas on the UIKit mouse backend.
    CALL(SDL_WarpMouseInWindow)(window, 120, 90);
    int mouseX = 0, mouseY = 0;
    CALL(SDL_GetRelativeMouseState)(&mouseX, &mouseY);
    CALL(SDL_WarpMouseInWindow)(window, 164, 112);
    mouse.motion.x = 164; mouse.motion.y = 112;
    CALL(SDL_PushEvent)(&mouse);
    CALL(SDL_GetRelativeMouseState)(&mouseX, &mouseY);
    result[@"nativeMouseDeltaAfterWarp"] = @[@(mouseX), @(mouseY)];
    CALL(SDL_GetMouseState)(&mouseX, &mouseY);
    result[@"nativeMousePositionPreserved"] = @(mouseX == 164 && mouseY == 112);
    NSDictionary *(*testMouseRouting)(SDL_Window *) = dlsym(bridge, "SRMouseRoutingTest");
    if (testMouseRouting) result[@"touchMouseRouting"] = testMouseRouting(window);
    NSDictionary *(*testKeyboardRouting)(void) = dlsym(bridge, "SRKeyboardRoutingTest");
    if (testKeyboardRouting) result[@"touchKeyboardRouting"] = testKeyboardRouting();
    NSString *compatPath = [NSBundle.mainBundle.privateFrameworksPath stringByAppendingPathComponent:@"MacCompat.framework/MacCompat"];
    void *compat = dlopen(compatPath.fileSystemRepresentation, RTLD_NOW | RTLD_LOCAL | RTLD_FIRST);
    NSDictionary *(*testDisplayModes)(void) = compat ? dlsym(compat, "SRDisplayModesTest") : NULL;
    if (testDisplayModes) result[@"displayModes"] = testDisplayModes();
    result[@"gameModeOptIn"] = @([NSBundle.mainBundle.infoDictionary[@"LSSupportsGameMode"] boolValue] &&
                                   [NSBundle.mainBundle.infoDictionary[@"GCSupportsGameMode"] boolValue]);
    NSDictionary *(*testTouchInput)(void) = dlsym(bridge, "SRTouchInputTest");
    if (testTouchInput) result[@"touchGamepad"] = testTouchInput();
    NSDictionary *(*testTouchLayout)(UIWindowScene *) = dlsym(bridge, "SRTouchLayoutTest");
    if (testTouchLayout) result[@"touchLayout"] = testTouchLayout(hostWindow.windowScene);
    result[@"physicalTouchGesturesTested"] = @NO;
    if (!window || !metalView) result[@"error"] = @(CALL(SDL_GetError)());
    // Keep the diagnostic surface briefly visible, then restore the host window.
    void (*destroyView)(SDL_MetalView) = CALL(SDL_Metal_DestroyView);
    void (*destroyWindow)(SDL_Window *) = CALL(SDL_DestroyWindow);
    void (*quit)(void) = CALL(SDL_Quit);
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 2 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
        if (metalView) destroyView(metalView);
        if (window) destroyWindow(window);
        quit();
        [hostWindow makeKeyAndVisible];
        Stage(@"FINISHED");
        NSString *message = [NSString stringWithFormat:
            @"SDL %@ / %@\n\nTable: 833 functions\nWindow: %@\nMetal: %@\nEvent queue: %@\n\nThis check does not load game code or verify gameplay. See Documents/sdl-check.json for all results.",
            result[@"nativeVersion"], result[@"videoDriver"],
            [result[@"windowCreated"] boolValue] ? @"OK" : @"Error",
            [result[@"diagnosticFrameCompleted"] boolValue] ? @"OK" : @"Error",
            [result[@"eventRoundTrip"] boolValue] ? @"OK" : @"Error"];
        completion(result, message);
    });
}

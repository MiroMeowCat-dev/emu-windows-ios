#include <dlfcn.h>
#include <limits.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdatomic.h>
#import <UIKit/UIKit.h>
#import <QuartzCore/CAMetalLayer.h>
#import <GameController/GameController.h>
#include <SDL2/SDL.h>
#include <SDL2/SDL_syswm.h>

#include "SDL2264Names.inc"
#include "SDL2264Indices.h"
#include "GameContext.h"
#include "TouchPointer.h"

static void *functions[833];
static pthread_once_t once = PTHREAD_ONCE_INIT;
static int ready;
static char *(*native_base_path)(void);
static SDL_Window *(*native_create_window)(const char *, int, int, int, int, Uint32);
static void *(*native_get_metal_layer)(SDL_Renderer *);
static int (*native_send_virtual_key)(Uint8, SDL_Scancode);
static const Uint8 *(*native_keyboard_state)(int *);
typedef struct {
    BOOL down, observed, releasePending;
    uint64_t observedEpoch, releaseEpoch;
} SROverlayKey;
static SROverlayKey overlayKeys[SDL_NUM_SCANCODES];
static uint64_t keyEpoch;
static Uint32 (*native_relative_mouse)(int *, int *);
static Uint32 (*native_mouse_state)(int *, int *);
static int (*native_set_relative_mouse)(SDL_bool);
static void (*native_warp_mouse)(SDL_Window *, int, int);
static int (*native_show_cursor)(int);
static Sint16 (*native_controller_axis)(SDL_GameController *, SDL_GameControllerAxis);
static int (*native_poll_event)(SDL_Event *);
static atomic_bool touch_mouse;
static atomic_bool touch_down, requested_relative;
static BOOL touch_pointer_routing;
static BOOL diagnostics;
// UIKit touch delivery, event polling and the game all run on the main thread.
static SRTouchPointer pointer;
static SRGameContext gameContext = SRContextMenu;
static uint32_t lastFrame;
static BOOL hasFrame;
static int activationBalance;
static uint32_t activationFrame;
static BOOL hasActivationFrame;
void SRInstallMenuControls(UIWindowScene *, int (*)(Uint8, SDL_Scancode));
void SRUpdateControlsContext(SRGameContext);

int32_t SDL_DYNAPI_entry(uint32_t version, void *table, uint32_t size);

static BOOL UsesTouchPointer(void) {
    return touch_pointer_routing && GCMouse.mice.count == 0;
}

static BOOL GameCapturesPointer(void) {
    // Cursor visibility alone is insufficient: controller-driven menus may
    // hide their pointer too. Use the game's explicit camera-lock request.
    return atomic_load(&requested_relative);
}

static int SendOverlayKey(Uint8 state, SDL_Scancode key) {
    if (key <= SDL_SCANCODE_UNKNOWN || key >= SDL_NUM_SCANCODES) return -1;
    SROverlayKey *entry = &overlayKeys[key];
    if (state == SDL_PRESSED) {
        entry->releasePending = NO;
        if (entry->down) return 0;
        entry->down = YES;
        entry->observed = NO;
    } else {
        if (entry->down && !entry->releasePending) {
            entry->releasePending = YES;
            entry->releaseEpoch = keyEpoch;
        }
        // The UI may poll before gameplay. Even an observed key must survive
        // the rest of this frame; only FinishKeyboardFrame releases it.
        return 0;
    }
    return native_send_virtual_key(state, key);
}

static const Uint8 *guest_keyboard_state(int *count) {
    const Uint8 *state = native_keyboard_state(count);
    for (int key = 0; key < SDL_NUM_SCANCODES; ++key) {
        SROverlayKey *entry = &overlayKeys[key];
        if (entry->down && !entry->observed) {
            entry->observed = YES;
            entry->observedEpoch = keyEpoch;
        }
    }
    return state;
}

static void FinishKeyboardFrame(void) {
    for (int key = 0; key < SDL_NUM_SCANCODES; ++key) {
        SROverlayKey *entry = &overlayKeys[key];
        if (!entry->releasePending) continue;
        BOOL readInEarlierFrame = entry->observed && entry->observedEpoch != keyEpoch;
        // Do not replay an old tap later if keyboard polling has stopped.
        BOOL expired = keyEpoch - entry->releaseEpoch >= 8;
        if (readInEarlierFrame || expired) {
            native_send_virtual_key(SDL_RELEASED, (SDL_Scancode)key);
            *entry = (SROverlayKey){0};
        }
    }
    // Advance AFTER evaluating releases: a UI read during the current event
    // pump must not release the key before the subsequent gameplay poll.
    ++keyEpoch;
}

void SRReleaseAllOverlayKeys(void) {
    for (int key = 0; key < SDL_NUM_SCANCODES; ++key) {
        if (overlayKeys[key].down) native_send_virtual_key(SDL_RELEASED, (SDL_Scancode)key);
        overlayKeys[key] = (SROverlayKey){0};
    }
}

static int guest_set_relative_mouse(SDL_bool enabled) {
    atomic_store(&requested_relative, enabled == SDL_TRUE);
    // A finger supplies an absolute screen position. Desktop pointer locking
    // must not turn that position into camera motion or pin it to screen center.
    return native_set_relative_mouse(UsesTouchPointer() ? SDL_FALSE : enabled);
}

static void guest_warp_mouse(SDL_Window *window, int x, int y) {
    if (UsesTouchPointer() && (GameCapturesPointer() || SRPointerOwnsPosition(&pointer))) return;
    native_warp_mouse(window, x, y);
}

static void FinishInputFrame(void) {
    static SRGameContext candidate = SRContextMenu;
    static unsigned samples;
    SRGameContext context = SRReadGameContext();
    SRLogGameContext();
    if (candidate != context) { candidate = context; samples = 1; }
    else if (samples < 2) ++samples;
    // Avoid releasing a held pedal for a one-sample transient state.
    if (samples == 2 && context != gameContext) {
        gameContext = context;
        // A gesture belongs to the screen where it started, not its successor.
        SRPointerReset(&pointer);
        activationBalance = 0;
        hasActivationFrame = NO;
        if (diagnostics) fprintf(stderr, "GameContext: %s\n",
            context == SRContextDriving ? "driving" : context == SRContextMap ? "map" : "menu");
    }
    // A loading screen can pump events without rendering a new game frame.
    // Refresh visibility even then, and also after an overlay is recreated.
    SRUpdateControlsContext(gameContext);
    uint32_t frame;
    if (SRGameFrame(&frame) && frame != 0) {
        if (hasFrame && frame == lastFrame) return;
        lastFrame = frame;
        hasFrame = YES;
    }
    FinishKeyboardFrame();
    unsigned previous = pointer.phase;
    BOOL focusReady = !UsesTouchPointer() || (SRPointerFocusReady() && activationBalance == 0);
    SRPointerTick(&pointer, focusReady);
    if (diagnostics && previous != pointer.phase)
        fprintf(stderr, "TouchFrame: phase=%u at=%d,%d queue=%u capture=%d frame=%u hudFlags=%u pointerFocus=%d timedOut=%d\n",
            pointer.phase, pointer.x, pointer.y, pointer.count, GameCapturesPointer(), lastFrame,
            SRGamePointerFlags(), SRPointerFocusReady(), pointer.focusTimedOut);
}

static int guest_poll_event(SDL_Event *event) {
    if (!event) return native_poll_event(NULL);
    while (native_poll_event(event)) {
        // UIKit SDL already converts these touches to real mouse events.
        // The Mac game's finger-event branch reads mouse/keyboard union fields
        // from the incompatible finger structure, causing duplicate bad input.
        if (event->type == SDL_FINGERDOWN || event->type == SDL_FINGERUP ||
            event->type == SDL_FINGERMOTION) continue;
        return 1;
    }
    FinishInputFrame();
    return 0;
}

static int WatchMouseSource(void *unused, SDL_Event *event) {
    if (event->type == SDL_MOUSEMOTION) {
        atomic_store(&touch_mouse, event->motion.which == SDL_TOUCH_MOUSEID);
        if (event->motion.which == SDL_TOUCH_MOUSEID)
            SRPointerMove(&pointer, event->motion.x, event->motion.y);
    } else if ((event->type == SDL_MOUSEBUTTONDOWN || event->type == SDL_MOUSEBUTTONUP) &&
               event->button.which == SDL_TOUCH_MOUSEID) {
        atomic_store(&touch_mouse, true);
        if (event->button.button == SDL_BUTTON_LEFT) {
            atomic_store(&touch_down, event->type == SDL_MOUSEBUTTONDOWN);
            if (event->type == SDL_MOUSEBUTTONDOWN)
                SRPointerBegin(&pointer, event->button.x, event->button.y);
            else SRPointerEnd(&pointer, event->button.x, event->button.y);
        }
        static unsigned reports;
        if (diagnostics && reports++ < 64) fprintf(stderr, "TouchMouse: %s at %d,%d cursor=%d capture=%d\n",
            event->type == SDL_MOUSEBUTTONDOWN ? "down" : "up", event->button.x, event->button.y,
            native_show_cursor(SDL_QUERY), atomic_load(&requested_relative));
    }
    return 0;
}

static Uint32 TouchButtons(Uint32 nativeButtons) {
    if (!UsesTouchPointer() || (!atomic_load(&touch_mouse) && !SRPointerOwnsPosition(&pointer)))
        return nativeButtons;
    return (nativeButtons & ~SDL_BUTTON_LMASK) | (SRPointerIsPressed(&pointer) ? SDL_BUTTON_LMASK : 0);
}

static Uint32 guest_relative_mouse(int *x, int *y) {
    int dx = 0, dy = 0;
    Uint32 buttons = native_relative_mouse(&dx, &dy);
    // Camera motion belongs to the dedicated stick during driving. Absolute
    // pointer positions still reach the HUD; map/menu dragging stays native.
    if (UsesTouchPointer() && (atomic_load(&touch_mouse) || SRPointerOwnsPosition(&pointer)) &&
        (gameContext == SRContextDriving || GameCapturesPointer())) dx = dy = 0;
    if (UsesTouchPointer()) {
        uint32_t frame = 0;
        BOOL sameFrame = SRGameFrame(&frame) && frame && hasActivationFrame && frame == activationFrame;
        if (!sameFrame && (activationBalance || (pointer.phase == SRPointerHover && !SRPointerFocusReady()))) {
            // A touch arrives without mouse motion. A balanced pair of activity
            // samples lets the game select its mouse input source before the
            // press; actual focus acknowledgement, not a fixed delay, gates it.
            int activity = activationBalance ? -activationBalance : 1;
            dx += activity;
            activationBalance += activity;
            activationFrame = frame;
            hasActivationFrame = frame != 0;
            if (diagnostics) fprintf(stderr, "PointerActivation: delta=%d frame=%u balance=%d\n", activity, frame, activationBalance);
        }
    }
    if (x) *x = dx;
    if (y) *y = dy;
    return TouchButtons(buttons);
}

static Uint32 guest_mouse_state(int *x, int *y) {
    int actualX = 0, actualY = 0;
    Uint32 buttons = native_mouse_state(&actualX, &actualY);
    if (UsesTouchPointer() && SRPointerOwnsPosition(&pointer)) {
        SRTouchContact *contact = &pointer.contacts[pointer.head];
        actualX = pointer.phase == SRPointerIdle ? contact->startX : pointer.x;
        actualY = pointer.phase == SRPointerIdle ? contact->startY : pointer.y;
    }
    buttons = TouchButtons(buttons);
    static unsigned reports;
    static Uint32 previous;
    if (diagnostics && atomic_load(&touch_mouse) && buttons != previous && reports++ < 32) {
        fprintf(stderr, "GameMouse: buttons=%u at %d,%d\n", buttons, actualX, actualY);
        previous = buttons;
    }
    if (x) *x = actualX;
    if (y) *y = actualY;
    return buttons;
}

static Sint16 guest_controller_axis(SDL_GameController *controller, SDL_GameControllerAxis axis) {
    Sint16 value = native_controller_axis(controller, axis);
    static Sint16 previous[SDL_CONTROLLER_AXIS_MAX];
    static unsigned reports;
    if (diagnostics && axis >= 0 && axis < SDL_CONTROLLER_AXIS_MAX && value != previous[axis] && reports < 80) {
        if (abs(value - previous[axis]) > 2048 || value == 0) {
            SDL_Window *(*focus)(void) = functions[index_SDL_GetKeyboardFocus];
            fprintf(stderr, "GameAxis: axis=%d value=%d focus=%d\n", axis, value, focus() != NULL);
            previous[axis] = value;
            ++reports;
        }
    }
    return value;
}

static char *guest_base_path(void) {
    const char *root = getenv("SNOW_RESOURCE_ROOT");
    if (!root || !*root) return native_base_path();
    size_t size = strlen(root);
    void *(*allocate)(size_t) = functions[index_SDL_malloc];
    char *path = allocate(size + 2);
    if (!path) return NULL;
    memcpy(path, root, size);
    if (root[size - 1] != '/') path[size++] = '/';
    path[size] = 0;
    return path;
}

static SDL_Window *guest_create_window(const char *title, int x, int y, int w, int h, Uint32 flags) {
    Dl_info caller = {0};
    if (dladdr(__builtin_return_address(0), &caller) && caller.dli_fname &&
        strstr(caller.dli_fname, "/GameClient.framework/GameClient")) {
        touch_pointer_routing = YES;
        void *game = dlopen(caller.dli_fname, RTLD_NOW | RTLD_LOCAL | RTLD_NOLOAD);
        if (game) { SRBindGameContext(game); dlclose(game); }
        fprintf(stderr, "SDLBridge: creating game window\n");
    }
    SDL_Window *window = native_create_window(title, x, y, w, h, flags);
    if (!window) return NULL;
    static BOOL watchingMouse;
    if (!watchingMouse) {
        void (*watch)(SDL_EventFilter, void *) = functions[index_SDL_AddEventWatch];
        watch(WatchMouseSource, NULL);
        [NSNotificationCenter.defaultCenter addObserverForName:UIApplicationWillResignActiveNotification object:nil queue:nil usingBlock:^(NSNotification *notification) {
            atomic_store(&touch_down, false);
            atomic_store(&touch_mouse, false);
            SRPointerReset(&pointer);
            SRReleaseAllOverlayKeys();
            hasFrame = NO;
            activationBalance = 0;
            hasActivationFrame = NO;
        }];
        watchingMouse = YES;
    }
    SDL_SysWMinfo info;
    memset(&info, 0, sizeof(info));
    SDL_VERSION(&info.version);
    SDL_bool (*get_info)(SDL_Window *, SDL_SysWMinfo *) = functions[index_SDL_GetWindowWMInfo];
    if (get_info(window, &info) && info.subsystem == SDL_SYSWM_UIKIT) {
        for (UIScene *scene in UIApplication.sharedApplication.connectedScenes) {
            if ([scene isKindOfClass:UIWindowScene.class] && scene.activationState == UISceneActivationStateForegroundActive) {
                UIWindow *nativeWindow = info.info.uikit.window;
                if (nativeWindow.windowScene != scene) {
                    nativeWindow.hidden = YES;
                    nativeWindow.windowScene = (UIWindowScene *)scene;
                }
                nativeWindow.frame = ((UIWindowScene *)scene).coordinateSpace.bounds;
                nativeWindow.rootViewController.view.frame = nativeWindow.bounds;
                [nativeWindow makeKeyAndVisible];
                [nativeWindow layoutIfNeeded];
                [nativeWindow.rootViewController.view setNeedsLayout];
                [nativeWindow.rootViewController.view layoutIfNeeded];
                fprintf(stderr, "SDLBridge: window=%.0fx%.0f view=%.0fx%.0f orientation=%ld\n",
                        nativeWindow.bounds.size.width, nativeWindow.bounds.size.height,
                        nativeWindow.rootViewController.view.bounds.size.width,
                        nativeWindow.rootViewController.view.bounds.size.height,
                        (long)((UIWindowScene *)scene).interfaceOrientation);
                if (getenv("SNOW_RESOURCE_ROOT")) SRInstallMenuControls((UIWindowScene *)scene, SendOverlayKey);
                break;
            }
        }
    }
    return window;
}

static void *guest_get_metal_layer(SDL_Renderer *renderer) {
    void *pointer = native_get_metal_layer(renderer);
    if (!pointer) return NULL;
    CAMetalLayer *layer = (__bridge CAMetalLayer *)pointer;
    static CGSize previousBounds, previousDrawable;
    static unsigned reports;
    CGSize bounds = layer.bounds.size, drawable = layer.drawableSize;
    if (diagnostics && reports < 12 && (!CGSizeEqualToSize(bounds, previousBounds) ||
                         !CGSizeEqualToSize(drawable, previousDrawable))) {
        fprintf(stderr, "SDLBridge: Metal bounds=%.0fx%.0f drawable=%.0fx%.0f scale=%.1f\n",
                bounds.width, bounds.height, drawable.width, drawable.height, layer.contentsScale);
        previousBounds = bounds;
        previousDrawable = drawable;
        ++reports;
    }
    return pointer;
}

static void load_functions(void) {
    diagnostics = getenv("EMU_DIAGNOSTICS") != NULL;
    Dl_info image;
    char directory[PATH_MAX];
    char path[PATH_MAX];
    if (!dladdr((void *)&SDL_DYNAPI_entry, &image)) return;
    if (strlcpy(directory, image.dli_fname, sizeof(directory)) >= sizeof(directory)) return;
    char *slash = strrchr(directory, '/');
    if (!slash) return;
    *slash = 0;
    slash = strrchr(directory, '/');
    if (!slash) return;
    *slash = 0;
    if (snprintf(path, sizeof(path), "%s/SDL2.framework/SDL2", directory) >= sizeof(path)) return;
    void *library = dlopen(path, RTLD_NOW | RTLD_LOCAL | RTLD_FIRST);
    if (!library) {
        fprintf(stderr, "SDLBridge: %s\n", dlerror());
        return;
    }
    for (unsigned i = 0; i < 833; ++i) {
        functions[i] = dlsym(library, sdl_names[i]);
        if (!functions[i]) {
            fprintf(stderr, "SDLBridge: missing %s\n", sdl_names[i]);
            return;
        }
    }
    native_send_virtual_key = dlsym(library, "SDL_SendVirtualKeyboardKey");
    if (!native_send_virtual_key) {
        fprintf(stderr, "SDLBridge: native virtual-keyboard entry point is missing\n");
        return;
    }
    native_base_path = functions[index_SDL_GetBasePath];
    native_keyboard_state = functions[index_SDL_GetKeyboardState];
    functions[index_SDL_GetKeyboardState] = guest_keyboard_state;
    functions[index_SDL_GetBasePath] = guest_base_path;
    native_create_window = functions[index_SDL_CreateWindow];
    functions[index_SDL_CreateWindow] = guest_create_window;
    native_get_metal_layer = functions[index_SDL_RenderGetMetalLayer];
    functions[index_SDL_RenderGetMetalLayer] = guest_get_metal_layer;
    native_relative_mouse = functions[index_SDL_GetRelativeMouseState];
    functions[index_SDL_GetRelativeMouseState] = guest_relative_mouse;
    native_mouse_state = functions[index_SDL_GetMouseState];
    functions[index_SDL_GetMouseState] = guest_mouse_state;
    native_set_relative_mouse = functions[index_SDL_SetRelativeMouseMode];
    functions[index_SDL_SetRelativeMouseMode] = guest_set_relative_mouse;
    native_warp_mouse = functions[index_SDL_WarpMouseInWindow];
    functions[index_SDL_WarpMouseInWindow] = guest_warp_mouse;
    native_show_cursor = functions[index_SDL_ShowCursor];
    native_controller_axis = functions[index_SDL_GameControllerGetAxis];
    functions[index_SDL_GameControllerGetAxis] = guest_controller_axis;
    native_poll_event = functions[index_SDL_PollEvent];
    functions[index_SDL_PollEvent] = guest_poll_event;
    ready = 1;
}

NSDictionary *SRKeyboardRoutingTest(void) {
    if (!ready) return @{@"passed":@NO};
    const Uint8 *keys = native_keyboard_state(NULL);
    SendOverlayKey(SDL_PRESSED, SDL_SCANCODE_V);
    SendOverlayKey(SDL_RELEASED, SDL_SCANCODE_V);
    BOOL pendingPress = keys[SDL_SCANCODE_V] == SDL_PRESSED;
    FinishKeyboardFrame();
    BOOL waitsForPoll = keys[SDL_SCANCODE_V] == SDL_PRESSED;
    guest_keyboard_state(NULL);
    BOOL visibleDuringPoll = keys[SDL_SCANCODE_V] == SDL_PRESSED;
    FinishKeyboardFrame();
    BOOL waitsForGameplay = keys[SDL_SCANCODE_V] == SDL_PRESSED;
    FinishKeyboardFrame();
    BOOL released = keys[SDL_SCANCODE_V] == SDL_RELEASED;

    // Scaleform can read a key before UIKit delivers its release, all within
    // one event pump. That read must not allow immediate release either.
    SendOverlayKey(SDL_PRESSED, SDL_SCANCODE_RETURN);
    guest_keyboard_state(NULL);
    SendOverlayKey(SDL_RELEASED, SDL_SCANCODE_RETURN);
    BOOL deferredAfterRead = keys[SDL_SCANCODE_RETURN] == SDL_PRESSED;
    guest_keyboard_state(NULL);
    FinishKeyboardFrame();
    BOOL uiReadPreserved = keys[SDL_SCANCODE_RETURN] == SDL_PRESSED;
    FinishKeyboardFrame();
    BOOL uiReadReleased = keys[SDL_SCANCODE_RETURN] == SDL_RELEASED;

    SendOverlayKey(SDL_PRESSED, SDL_SCANCODE_V);
    SendOverlayKey(SDL_RELEASED, SDL_SCANCODE_V);
    for (int frame = 0; frame <= 8; ++frame) FinishKeyboardFrame();
    BOOL unreadTapExpires = keys[SDL_SCANCODE_V] == SDL_RELEASED;

    uint64_t previousEpoch = keyEpoch;
    keyEpoch = UINT64_MAX;
    SendOverlayKey(SDL_PRESSED, SDL_SCANCODE_V);
    guest_keyboard_state(NULL);
    SendOverlayKey(SDL_RELEASED, SDL_SCANCODE_V);
    FinishKeyboardFrame();
    BOOL heldAcrossWrap = keys[SDL_SCANCODE_V] == SDL_PRESSED;
    FinishKeyboardFrame();
    BOOL wrapSafe = heldAcrossWrap && keys[SDL_SCANCODE_V] == SDL_RELEASED;
    keyEpoch = previousEpoch;

    SendOverlayKey(SDL_PRESSED, SDL_SCANCODE_SPACE);
    guest_keyboard_state(NULL);
    for (int frame = 0; frame <= 8; ++frame) FinishKeyboardFrame();
    BOOL held = keys[SDL_SCANCODE_SPACE] == SDL_PRESSED;
    native_send_virtual_key(SDL_PRESSED, SDL_SCANCODE_A);
    SRReleaseAllOverlayKeys();
    BOOL cancelled = keys[SDL_SCANCODE_SPACE] == SDL_RELEASED;
    BOOL otherInputPreserved = keys[SDL_SCANCODE_A] == SDL_PRESSED;
    native_send_virtual_key(SDL_RELEASED, SDL_SCANCODE_A);
    BOOL fastTap = pendingPress && waitsForPoll && visibleDuringPoll;
    BOOL orderedRelease = waitsForGameplay && released && deferredAfterRead && uiReadPreserved && uiReadReleased;
    return @{@"fastKeyTapPreserved":@(fastTap), @"releasedAfterGameplayFrame":@(orderedRelease),
             @"unreadTapExpires":@(unreadTapExpires), @"epochWrapSafe":@(wrapSafe), @"heldKeyPreserved":@(held),
             @"cancelReleasesKeys":@(cancelled), @"otherKeyboardInputPreserved":@(otherInputPreserved),
             @"passed":@(fastTap && orderedRelease && unreadTapExpires && wrapSafe && held && cancelled && otherInputPreserved)};
}

NSDictionary *SRMouseRoutingTest(SDL_Window *window) {
    if (!window || !ready) return @{@"passed":@NO, @"error":@"No SDL window"};
    if (GCMouse.mice.count) return @{@"passed":@NO, @"error":@"Physical mouse connected"};
    SDL_bool (*getRelative)(void) = functions[index_SDL_GetRelativeMouseMode];
    SDL_bool oldRelative = getRelative();
    int oldX = 0, oldY = 0;
    native_mouse_state(&oldX, &oldY);
    BOOL oldRouting = touch_pointer_routing;
    BOOL oldRequested = atomic_load(&requested_relative);
    BOOL oldTouch = atomic_load(&touch_mouse), oldDown = atomic_load(&touch_down);
    SRTouchPointer oldPointer = pointer;
    touch_pointer_routing = YES;
    SRPointerReset(&pointer);

    BOOL acceptedCapture = guest_set_relative_mouse(SDL_TRUE) == 0;
    BOOL absoluteTouch = getRelative() == SDL_FALSE;
    native_warp_mouse(window, 120, 90);
    guest_warp_mouse(window, 400, 200);
    int x = 0, y = 0;
    native_mouse_state(&x, &y);
    BOOL cameraWarpIgnored = x == 120 && y == 90;
    guest_set_relative_mouse(SDL_FALSE);
    guest_warp_mouse(window, 164, 112);
    native_mouse_state(&x, &y);
    BOOL menuPointerWorks = x == 164 && y == 112;

    // A complete tap between two polls must survive, with a full hover frame.
    SDL_Event event = {0};
    event.type = SDL_MOUSEBUTTONDOWN;
    event.button.which = SDL_TOUCH_MOUSEID;
    event.button.button = SDL_BUTTON_LEFT;
    event.button.x = 164; event.button.y = 112;
    WatchMouseSource(NULL, &event);
    event.type = SDL_MOUSEBUTTONUP;
    WatchMouseSource(NULL, &event);
    SRPointerTick(&pointer, true);
    BOOL hover = !(guest_mouse_state(&x, &y) & SDL_BUTTON_LMASK) && x == 164 && y == 112;
    guest_warp_mouse(window, 400, 200);
    native_mouse_state(&x, &y);
    BOOL hoverAnchor = x == 164 && y == 112;
    SRPointerTick(&pointer, true);
    BOOL press = (guest_mouse_state(&x, &y) & SDL_BUTTON_LMASK) &&
                 (guest_relative_mouse(NULL, NULL) & SDL_BUTTON_LMASK);
    SRPointerTick(&pointer, true);
    BOOL release = !(guest_mouse_state(&x, &y) & SDL_BUTTON_LMASK);
    guest_warp_mouse(window, 400, 200);
    native_mouse_state(&x, &y);
    BOOL releaseAnchor = x == 164 && y == 112;
    SRPointerTick(&pointer, true);
    BOOL finished = !SRPointerOwnsPosition(&pointer);

    // Two queued taps keep different positions, instead of clicking twice at
    // the newest native mouse coordinate.
    SRPointerBegin(&pointer, 50, 60); SRPointerEnd(&pointer, 50, 60);
    SRPointerBegin(&pointer, 250, 260); SRPointerEnd(&pointer, 250, 260);
    SRPointerTick(&pointer, true); SRPointerTick(&pointer, true);
    BOOL firstTap = (guest_mouse_state(&x, &y) & SDL_BUTTON_LMASK) && x == 50 && y == 60;
    SRPointerTick(&pointer, true); SRPointerTick(&pointer, true); SRPointerTick(&pointer, true);
    BOOL secondTap = (guest_mouse_state(&x, &y) & SDL_BUTTON_LMASK) && x == 250 && y == 260;
    touch_pointer_routing = NO;
    Uint32 nativeButtons = native_mouse_state(&x, &y);
    int bypassX = 0, bypassY = 0;
    BOOL bypass = guest_mouse_state(&bypassX, &bypassY) == nativeButtons && bypassX == x && bypassY == y;
    SRPointerReset(&pointer);
    BOOL reset = !SRPointerIsPressed(&pointer) && !SRPointerOwnsPosition(&pointer);

    pointer = oldPointer;
    touch_pointer_routing = oldRouting;
    atomic_store(&requested_relative, oldRequested);
    atomic_store(&touch_mouse, oldTouch);
    atomic_store(&touch_down, oldDown);
    native_set_relative_mouse(oldRelative);
    native_warp_mouse(window, oldX, oldY);
    return @{@"captureRequestHandled":@(acceptedCapture), @"nativeTouchStaysAbsolute":@(absoluteTouch),
             @"cameraWarpIgnored":@(cameraWarpIgnored), @"menuPointerWorks":@(menuPointerWorks),
             @"hoverBeforePress":@(hover), @"quickTapPreserved":@(press && release && finished),
             @"touchAnchorPreserved":@(hoverAnchor), @"releaseAnchorPreserved":@(releaseAnchor),
             @"queuedTapPositionsPreserved":@(firstTap && secondTap), @"nativeInputBypassesReplay":@(bypass),
             @"resetReleasesTouch":@(reset),
             @"passed":@(acceptedCapture && absoluteTouch && cameraWarpIgnored && menuPointerWorks &&
                         hover && press && release && finished && hoverAnchor && releaseAnchor && firstTap && secondTap && bypass && reset)};
}

int32_t SDL_DYNAPI_entry(uint32_t version, void *table, uint32_t size) {
    if (version != 1 || !table || size > sizeof(functions) || size % sizeof(void *)) return -1;
    pthread_once(&once, load_functions);
    if (!ready) return -1;
    memcpy(table, functions, size);
    return 0;
}

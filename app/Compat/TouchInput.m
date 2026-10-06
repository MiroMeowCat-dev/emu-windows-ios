#import "TouchInput.h"
#include <SDL2/SDL.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

static SDL_Joystick *touchJoystick;
static int touchDevice = -1;

static BOOL HasTouchJoystick(void) {
    // SDL_Quit destroys its joystick handles. UIKit may still deliver a
    // cancelled touch or an app-background notification after the game exits.
    if (!SDL_WasInit(SDL_INIT_JOYSTICK)) {
        touchJoystick = NULL;
        touchDevice = -1;
    }
    return touchJoystick != NULL;
}

void SRTouchInputReset(void) {
    if (!HasTouchJoystick()) return;
    for (int axis = 0; axis < SDL_CONTROLLER_AXIS_MAX; ++axis) {
        Sint16 value = axis >= SDL_CONTROLLER_AXIS_TRIGGERLEFT ? SDL_JOYSTICK_AXIS_MIN : 0;
        SDL_JoystickSetVirtualAxis(touchJoystick, axis, value);
    }
}

BOOL SRTouchInputStart(void) {
    if (HasTouchJoystick()) return YES;
    if (SDL_InitSubSystem(SDL_INIT_GAMECONTROLLER) != 0) return NO;
    SDL_VirtualJoystickDesc description = {0};
    description.version = SDL_VIRTUAL_JOYSTICK_DESC_VERSION;
    description.type = SDL_JOYSTICK_TYPE_GAMECONTROLLER;
    description.naxes = SDL_CONTROLLER_AXIS_MAX;
    description.nbuttons = SDL_CONTROLLER_BUTTON_MAX;
    description.axis_mask = (1u << SDL_CONTROLLER_AXIS_MAX) - 1;
    description.button_mask = (1u << SDL_CONTROLLER_BUTTON_MAX) - 1;
    description.name = "SnowRunner Touch";
    touchDevice = SDL_JoystickAttachVirtualEx(&description);
    if (touchDevice < 0) return NO;
    // The shipped game rejects SDL_CONTROLLER_TYPE_VIRTUAL. Describe our
    // standard six-axis controller with the Xbox layout accepted by that game.
    char guid[33], mapping[768];
    SDL_JoystickGetGUIDString(SDL_JoystickGetDeviceGUID(touchDevice), guid, sizeof(guid));
    snprintf(mapping, sizeof(mapping),
             "%s,SnowRunner Touch,a:b0,b:b1,x:b2,y:b3,back:b4,guide:b5,start:b6,"
             "leftstick:b7,rightstick:b8,leftshoulder:b9,rightshoulder:b10,"
             "dpup:b11,dpdown:b12,dpleft:b13,dpright:b14,leftx:a0,lefty:a1,"
             "rightx:a2,righty:a3,lefttrigger:a4,righttrigger:a5,type:Xbox360,", guid);
    if (SDL_GameControllerAddMapping(mapping) < 0 ||
        SDL_GameControllerTypeForIndex(touchDevice) != SDL_CONTROLLER_TYPE_XBOX360) {
        SDL_JoystickDetachVirtual(touchDevice);
        touchDevice = -1;
        return NO;
    }
    touchJoystick = SDL_JoystickOpen(touchDevice);
    if (!touchJoystick || !SDL_IsGameController(touchDevice)) {
        if (touchJoystick) SDL_JoystickClose(touchJoystick);
        touchJoystick = NULL;
        SDL_JoystickDetachVirtual(touchDevice);
        touchDevice = -1;
        return NO;
    }
    SRTouchInputReset();
    fprintf(stderr, "TouchInput: SDL virtual gamepad ready, device=%d layout=Xbox360\n", touchDevice);
    return YES;
}

void SRTouchSteer(float value) {
    if (!HasTouchJoystick()) return;
    SDL_JoystickSetVirtualAxis(touchJoystick, SDL_CONTROLLER_AXIS_LEFTX,
                              (Sint16)lrintf(fmaxf(-1, fminf(1, value)) * 32767));
}

void SRTouchPedal(BOOL throttle, float value) {
    if (!HasTouchJoystick()) return;
    int axis = throttle ? SDL_CONTROLLER_AXIS_TRIGGERRIGHT : SDL_CONTROLLER_AXIS_TRIGGERLEFT;
    Sint16 raw = (Sint16)lrintf(fmaxf(0, fminf(1, value)) * 65535 - 32768);
    SDL_JoystickSetVirtualAxis(touchJoystick, axis, raw);
}

void SRTouchLook(float x, float y) {
    if (!HasTouchJoystick()) return;
    SDL_JoystickSetVirtualAxis(touchJoystick, SDL_CONTROLLER_AXIS_RIGHTX,
                              (Sint16)lrintf(fmaxf(-1, fminf(1, x)) * 32767));
    SDL_JoystickSetVirtualAxis(touchJoystick, SDL_CONTROLLER_AXIS_RIGHTY,
                              (Sint16)lrintf(fmaxf(-1, fminf(1, y)) * 32767));
}

NSDictionary *SRTouchInputTest(void) {
    if (!SRTouchInputStart()) return @{@"ready":@NO, @"error":@(SDL_GetError())};
    SDL_GameController *controller = SDL_GameControllerOpen(touchDevice);
    if (!controller) {
        NSString *error = @(SDL_GetError());
        SDL_JoystickClose(touchJoystick);
        touchJoystick = NULL;
        SDL_JoystickDetachVirtual(touchDevice);
        touchDevice = -1;
        return @{@"ready":@NO, @"error":error};
    }
    SDL_JoystickUpdate();
    int rest = SDL_GameControllerGetAxis(controller, SDL_CONTROLLER_AXIS_TRIGGERRIGHT);
    SRTouchSteer(0.5f);
    SRTouchPedal(YES, 0.5f);
    SRTouchPedal(NO, 1.0f);
    SDL_JoystickUpdate();
    int steering = SDL_GameControllerGetAxis(controller, SDL_CONTROLLER_AXIS_LEFTX);
    int throttle = SDL_GameControllerGetAxis(controller, SDL_CONTROLLER_AXIS_TRIGGERRIGHT);
    int brake = SDL_GameControllerGetAxis(controller, SDL_CONTROLLER_AXIS_TRIGGERLEFT);
    SRTouchLook(0.5f, -0.5f);
    SDL_JoystickUpdate();
    int lookX = SDL_GameControllerGetAxis(controller, SDL_CONTROLLER_AXIS_RIGHTX);
    int lookY = SDL_GameControllerGetAxis(controller, SDL_CONTROLLER_AXIS_RIGHTY);
    BOOL independent = SDL_GameControllerGetAxis(controller, SDL_CONTROLLER_AXIS_LEFTX) == steering &&
                       SDL_GameControllerGetAxis(controller, SDL_CONTROLLER_AXIS_TRIGGERRIGHT) == throttle &&
                       SDL_GameControllerGetAxis(controller, SDL_CONTROLLER_AXIS_TRIGGERLEFT) == brake;
    SRTouchLook(0, 0);
    SDL_JoystickUpdate();
    BOOL lookReleased = SDL_GameControllerGetAxis(controller, SDL_CONTROLLER_AXIS_RIGHTX) == 0 &&
                        SDL_GameControllerGetAxis(controller, SDL_CONTROLLER_AXIS_RIGHTY) == 0;
    SRTouchInputReset();
    SDL_JoystickUpdate();
    BOOL released = SDL_GameControllerGetAxis(controller, SDL_CONTROLLER_AXIS_LEFTX) == 0 &&
                    SDL_GameControllerGetAxis(controller, SDL_CONTROLLER_AXIS_RIGHTX) == 0 &&
                    SDL_GameControllerGetAxis(controller, SDL_CONTROLLER_AXIS_RIGHTY) == 0 &&
                    SDL_GameControllerGetAxis(controller, SDL_CONTROLLER_AXIS_TRIGGERRIGHT) == 0 &&
                    SDL_GameControllerGetAxis(controller, SDL_CONTROLLER_AXIS_TRIGGERLEFT) == 0;
    BOOL acceptedType = SDL_GameControllerTypeForIndex(touchDevice) == SDL_CONTROLLER_TYPE_XBOX360;
    NSDictionary *result = @{@"ready":@YES, @"gameAcceptedControllerType":@(acceptedType),
        @"restingThrottle":@(rest), @"halfSteering":@(steering),
        @"halfThrottle":@(throttle), @"fullBrake":@(brake), @"released":@(released),
        @"halfLookX":@(lookX), @"halfLookY":@(lookY), @"lookReleased":@(lookReleased), @"independentAxes":@(independent),
        @"passed":@(acceptedType && rest == 0 && abs(steering - 16384) <= 1 && abs(throttle - 16384) <= 1 && brake == 32767 &&
                    abs(lookX - 16384) <= 1 && abs(lookY + 16384) <= 1 && independent && lookReleased && released)};
    SDL_GameControllerClose(controller);
    SDL_JoystickClose(touchJoystick);
    touchJoystick = NULL;
    SDL_JoystickDetachVirtual(touchDevice);
    touchDevice = -1;
    return result;
}

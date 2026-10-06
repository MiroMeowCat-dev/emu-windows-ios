#include "GameContext.h"
#include <dlfcn.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>

static void **gameObject;
static void **worldObject;
static bool (*isPaused)(void);
static bool (*isMapActive)(void *);
static bool (*truckEnabled)(void *);
static uint32_t (*frameNumber)(void *);
static bool (*hudOwnsMouse)(void);
static bool (*scriptOwnsMouse)(void);
static bool (*gamepadMode)(void);
static bool (*dragBlocked)(void);
static bool (*dragRequested)(void);
static void **inputSystem;
static bool (*controlledByGamepad)(void *);

static void *GameSymbol(void *game, const char *name) {
    void *value = dlsym(game, name);
    if (!value) fprintf(stderr, "GameContext: missing export %s\n", name);
    return value;
}

void SRBindGameContext(void *game) {
    gameObject = GameSymbol(game, "GameSsl");
    worldObject = GameSymbol(game, "_ZZN7combine16SINGLETON_OBJECTINS_10SPIN_TIRESEE7GetThisEvE6s_this");
    isPaused = GameSymbol(game, "_ZN7combine17IsSpinTiresPausedEv");
    isMapActive = GameSymbol(game, "_ZN10sslMINIMAP15IsMinimapActiveEv");
    truckEnabled = GameSymbol(game, "_ZNK8GAME_SSL21IsTruckControlEnabledEv");
    frameNumber = GameSymbol(game, "_ZN8GAME_SSL14GetFrameNumberEv");
    hudOwnsMouse = GameSymbol(game, "_Z15IsGfxMouseInUsev");
    scriptOwnsMouse = GameSymbol(game, "_ZN7combine19IsMouseSkippedBySslEv");
    gamepadMode = GameSymbol(game, "_ZN7combine16IsGamepadModeSslEv");
    dragBlocked = GameSymbol(game, "_Z37IsDriveCameraDraggingBlockedFromHuskyv");
    dragRequested = GameSymbol(game, "_Z39IsDriveCameraDraggingRequestedFromHuskyv");
    inputSystem = GameSymbol(game, "gsSysInput");
    controlledByGamepad = GameSymbol(game, "_ZNK14gsINPUT_SYSTEM21IsControlledByGamepadEv");
}

SRGameContext SRReadGameContext(void) {
    void *game = gameObject ? *gameObject : NULL;
    if (!game || !isMapActive || !truckEnabled || !worldObject || !isPaused)
        return SRContextMenu;

    // Read-only member of the exact game build pinned by supported-game.json.
    // cbSetIngameMenuState writes it; ProcessDriveLogic reads it to block driving.
    // This distinguishes settings over the map from the map pausing the world.
    const size_t ingameMenuOffset = 0x79;
    if (*((const uint8_t *)game + ingameMenuOffset)) return SRContextMenu;

    // This exported method uses its own singleton and does not read `this` in
    // the supported ARM64 build. It handles an absent minimap itself.
    if (isMapActive(NULL)) return SRContextMap;
    if (!*worldObject || isPaused()) return SRContextMenu;
    return truckEnabled(game) ? SRContextDriving : SRContextMenu;
}

bool SRGameFrame(uint32_t *frame) {
    if (!gameObject || !*gameObject || !frameNumber) return false;
    *frame = frameNumber(*gameObject);
    return true;
}

unsigned SRGamePointerFlags(void) {
    return (hudOwnsMouse && hudOwnsMouse() ? 1u : 0u) |
           (scriptOwnsMouse && scriptOwnsMouse() ? 2u : 0u) |
           (gamepadMode && gamepadMode() ? 4u : 0u);
}

bool SRPointerFocusReady(void) {
    // No game is bound in the SDL-only self-test or before game initialization.
    if (!gameObject || !*gameObject) return true;
    if (!worldObject || !*worldObject) return true;
    if (!inputSystem || !*inputSystem || !controlledByGamepad) return false;
    // The focused device pointer can change before HUD listeners are notified.
    // This getter reads the input type that actually drives those listeners.
    return !controlledByGamepad(*inputSystem);
}

void SRLogGameContext(void) {
    if (!getenv("EMU_DIAGNOSTICS")) return;
    void *game = gameObject ? *gameObject : NULL;
    if (!game) return;
    bool menu = *((const uint8_t *)game + 0x79) != 0;
    bool map = isMapActive && isMapActive(NULL);
    bool paused = worldObject && *worldObject && isPaused && isPaused();
    bool driving = truckEnabled && truckEnabled(game);
    unsigned flags = SRGamePointerFlags();
    bool blocked = dragBlocked && dragBlocked();
    bool requested = dragRequested && dragRequested();
    bool pointerFocus = SRPointerFocusReady();
    unsigned bits = menu | (map << 1) | (paused << 2) | (driving << 3) | (flags << 4) |
                    (blocked << 7) | (requested << 8) | (pointerFocus << 9);
    static unsigned previous = ~0u;
    if (bits != previous) {
        fprintf(stderr, "GameSignals: menu=%d map=%d paused=%d truck=%d hud=%d script=%d gamepad=%d dragBlocked=%d dragRequested=%d pointerFocus=%d\n",
                menu, map, paused, driving, (flags & 1) != 0, (flags & 2) != 0, (flags & 4) != 0,
                blocked, requested, pointerFocus);
        previous = bits;
    }
}

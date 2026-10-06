#pragma once
#include <stdbool.h>

// SnowRunner polls button state; it ignores SDL mouse-button events. Preserve
// short taps and give the UI one frame of hover before delivering a press.
enum { SRPointerIdle, SRPointerHover, SRPointerPressed, SRPointerReleased };
enum { SRPointerCapacity = 8 };

typedef struct {
    int startX, startY, x, y;
    bool released;
} SRTouchContact;

typedef struct {
    SRTouchContact contacts[SRPointerCapacity];
    unsigned head, count, phase;
    unsigned focusWait;
    unsigned focusFrames;
    bool focusTimedOut;
    bool tracking;
    int x, y;
} SRTouchPointer;

static inline void SRPointerReset(SRTouchPointer *pointer) {
    *pointer = (SRTouchPointer){0};
}

static inline void SRPointerBegin(SRTouchPointer *pointer, int x, int y) {
    if (pointer->count == SRPointerCapacity) {
        // Drop the entire newest contact rather than replay it at another tap.
        pointer->tracking = false;
        return;
    }
    unsigned tail = (pointer->head + pointer->count) % SRPointerCapacity;
    pointer->contacts[tail] = (SRTouchContact){x, y, x, y, false};
    ++pointer->count;
    pointer->tracking = true;
}

static inline void SRPointerMove(SRTouchPointer *pointer, int x, int y) {
    if (!pointer->tracking || !pointer->count) return;
    unsigned tail = (pointer->head + pointer->count - 1) % SRPointerCapacity;
    pointer->contacts[tail].x = x;
    pointer->contacts[tail].y = y;
}

static inline void SRPointerEnd(SRTouchPointer *pointer, int x, int y) {
    if (!pointer->tracking || !pointer->count) return;
    SRPointerMove(pointer, x, y);
    unsigned tail = (pointer->head + pointer->count - 1) % SRPointerCapacity;
    pointer->contacts[tail].released = true;
    pointer->tracking = false;
}

static inline void SRPointerTick(SRTouchPointer *pointer, bool focusReady) {
    if (pointer->phase == SRPointerReleased) {
        pointer->head = (pointer->head + 1) % SRPointerCapacity;
        --pointer->count;
        pointer->phase = SRPointerIdle;
    }
    if (!pointer->count) return;
    SRTouchContact *contact = &pointer->contacts[pointer->head];
    switch (pointer->phase) {
        case SRPointerIdle:
            pointer->x = contact->startX;
            pointer->y = contact->startY;
            pointer->phase = SRPointerHover;
            pointer->focusWait = 0;
            pointer->focusFrames = focusReady ? 1 : 0;
            pointer->focusTimedOut = false;
            break;
        case SRPointerHover:
            pointer->focusFrames = focusReady ? pointer->focusFrames + 1 : 0;
            if (pointer->focusFrames >= 2) pointer->phase = SRPointerPressed;
            else if (++pointer->focusWait == 12) {
                // Do not replay a stale click much later at an unrelated UI.
                pointer->focusTimedOut = true;
                pointer->phase = SRPointerReleased;
                if (pointer->count == 1) pointer->tracking = false;
            }
            break;
        case SRPointerPressed:
            pointer->x = contact->x;
            pointer->y = contact->y;
            if (contact->released) pointer->phase = SRPointerReleased;
            break;
    }
}

static inline bool SRPointerOwnsPosition(const SRTouchPointer *pointer) {
    return pointer->count != 0;
}

static inline bool SRPointerIsPressed(const SRTouchPointer *pointer) {
    return pointer->phase == SRPointerPressed;
}

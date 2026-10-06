#include "../app/Compat/TouchPointer.h"
#include <assert.h>

int main(void) {
    SRTouchPointer pointer = {0};
    SRPointerBegin(&pointer, 100, 200);
    SRPointerEnd(&pointer, 101, 202);
    assert(SRPointerOwnsPosition(&pointer) && !SRPointerIsPressed(&pointer));
    SRPointerTick(&pointer, true);
    assert(!SRPointerIsPressed(&pointer) && pointer.x == 100 && pointer.y == 200);
    SRPointerTick(&pointer, true);
    assert(SRPointerIsPressed(&pointer) && pointer.x == 100 && pointer.y == 200);
    SRPointerTick(&pointer, true);
    assert(!SRPointerIsPressed(&pointer) && SRPointerOwnsPosition(&pointer));
    assert(pointer.x == 101 && pointer.y == 202);
    SRPointerTick(&pointer, true);
    assert(!SRPointerOwnsPosition(&pointer));

    // A held drag keeps its press and delivers moving absolute coordinates.
    SRPointerBegin(&pointer, 10, 20);
    SRPointerTick(&pointer, true);
    SRPointerTick(&pointer, true);
    for (int x = 20; x <= 100; x += 10) {
        SRPointerMove(&pointer, x, 30);
        SRPointerTick(&pointer, true);
        assert(SRPointerIsPressed(&pointer) && pointer.x == x && pointer.y == 30);
    }
    SRPointerEnd(&pointer, 100, 30);
    SRPointerTick(&pointer, true);
    assert(!SRPointerIsPressed(&pointer));
    SRPointerTick(&pointer, true);

    // Every queued contact keeps its own coordinates; queue overflow cannot
    // replace an earlier tap with the dropped contact's release position.
    for (int i = 0; i < SRPointerCapacity + 1; ++i) {
        SRPointerBegin(&pointer, 50 * i, i);
        SRPointerEnd(&pointer, 50 * i, i);
    }
    assert(pointer.count == SRPointerCapacity);
    for (int i = 0; i < SRPointerCapacity; ++i) {
        if (i == 0) SRPointerTick(&pointer, true);
        assert(!SRPointerIsPressed(&pointer) && pointer.x == 50 * i && pointer.y == i);
        SRPointerTick(&pointer, true);
        assert(SRPointerIsPressed(&pointer) && pointer.x == 50 * i && pointer.y == i);
        SRPointerTick(&pointer, true);
        assert(!SRPointerIsPressed(&pointer));
        SRPointerTick(&pointer, true);
    }
    assert(!SRPointerOwnsPosition(&pointer));

    // Background/cancellation drops every outstanding press.
    SRPointerBegin(&pointer, 12, 34);
    SRPointerTick(&pointer, true);
    SRPointerTick(&pointer, true);
    SRPointerReset(&pointer);
    assert(!SRPointerOwnsPosition(&pointer) && !SRPointerIsPressed(&pointer));

    // A gamepad-to-pointer handover must finish before a click is delivered.
    SRPointerBegin(&pointer, 75, 85);
    SRPointerEnd(&pointer, 75, 85);
    SRPointerTick(&pointer, false);
    for (int frame = 0; frame < 5; ++frame) {
        SRPointerTick(&pointer, false);
        assert(pointer.phase == SRPointerHover && !SRPointerIsPressed(&pointer));
    }
    SRPointerTick(&pointer, true);
    assert(pointer.phase == SRPointerHover);
    SRPointerTick(&pointer, true);
    assert(SRPointerIsPressed(&pointer) && pointer.x == 75 && pointer.y == 85);
    SRPointerReset(&pointer);

    // If focus cannot be acquired, do not turn an old tap into a late action.
    SRPointerBegin(&pointer, 12, 34);
    SRPointerTick(&pointer, false);
    for (int frame = 0; frame < 12; ++frame) SRPointerTick(&pointer, false);
    assert(pointer.focusTimedOut && !SRPointerIsPressed(&pointer));
    SRPointerTick(&pointer, true);
    assert(!SRPointerOwnsPosition(&pointer));
    SRPointerEnd(&pointer, 12, 34);
    assert(!SRPointerOwnsPosition(&pointer));
    return 0;
}

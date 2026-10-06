#pragma once
#include <stdbool.h>
#include <stdint.h>

typedef enum {
    SRContextMenu,
    SRContextMap,
    SRContextDriving
} SRGameContext;

void SRBindGameContext(void *game);
SRGameContext SRReadGameContext(void);
bool SRGameFrame(uint32_t *frame);
unsigned SRGamePointerFlags(void);
void SRLogGameContext(void);
bool SRPointerFocusReady(void);

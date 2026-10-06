#import <Foundation/Foundation.h>

BOOL SRTouchInputStart(void);
void SRTouchSteer(float value);
void SRTouchPedal(BOOL throttle, float value);
void SRTouchLook(float x, float y);
void SRTouchInputReset(void);
NSDictionary *SRTouchInputTest(void);

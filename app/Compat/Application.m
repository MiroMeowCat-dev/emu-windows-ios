#import <UIKit/UIKit.h>

@interface SRNSApplication : NSObject
@property(nonatomic) NSUInteger presentationOptions;
@end

id NSApp;

@implementation SRNSApplication
+ (instancetype)sharedApplication {
    static SRNSApplication *application;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ application = [self new]; });
    return application;
}
- (BOOL)isActive { return UIApplication.sharedApplication.applicationState == UIApplicationStateActive; }
- (void)setPresentationOptions:(NSUInteger)options {
    // The observed Mac request (0xA) hides the Dock and menu bar. iOS has
    // neither; SDL's real borderless/fullscreen flags control its status bar.
    if (options & ~(NSUInteger)0xA) {
        [NSException raise:NSInvalidArgumentException format:@"Unsupported presentation options: %lu", (unsigned long)options];
    }
    _presentationOptions = options;
    for (UIScene *scene in UIApplication.sharedApplication.connectedScenes) {
        if (![scene isKindOfClass:UIWindowScene.class]) continue;
        for (UIWindow *window in ((UIWindowScene *)scene).windows) {
            [window.rootViewController setNeedsStatusBarAppearanceUpdate];
        }
    }
}
@end

__attribute__((constructor)) static void RegisterApplication(void) {
    NSApp = [SRNSApplication sharedApplication];
}

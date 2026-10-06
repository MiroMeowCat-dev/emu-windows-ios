#import <UIKit/UIKit.h>
#include <SDL2/SDL.h>
#include <stdio.h>
#include <math.h>
#import "TouchInput.h"
#include "GameContext.h"
void SRReleaseAllOverlayKeys(void);

static int (*sendVirtualKey)(Uint8, SDL_Scancode);
static NSURL *LayoutURL(void) {
    return [NSURL fileURLWithPath:[NSHomeDirectory() stringByAppendingPathComponent:@"Documents/touch-controls-layout.plist"]];
}

static BOOL SaveLayout(NSDictionary *layout, NSURL *url) {
    NSError *error = nil;
    NSData *data = [NSPropertyListSerialization dataWithPropertyList:layout format:NSPropertyListBinaryFormat_v1_0 options:0 error:&error];
    BOOL saved = data && [data writeToURL:url options:NSDataWritingAtomic error:&error];
    if (!saved) NSLog(@"Touch layout save failed: %@", error);
    return saved;
}

static NSMutableDictionary *LoadLayout(NSURL *url) {
    NSDictionary *layout = [NSDictionary dictionaryWithContentsOfURL:url];
    NSMutableDictionary *valid = [NSMutableDictionary new];
    for (NSString *key in layout) {
        id point = layout[key];
        if (![key isKindOfClass:NSString.class] || ![point isKindOfClass:NSArray.class] || [point count] != 2) continue;
        if (![point[0] isKindOfClass:NSNumber.class] || ![point[1] isKindOfClass:NSNumber.class]) continue;
        double x = [point[0] doubleValue], y = [point[1] doubleValue];
        if (isfinite(x) && isfinite(y) && x >= 0 && x <= 1 && y >= 0 && y <= 1) valid[key] = point;
    }
    return valid;
}
static UIColor *Amber(void) { return [UIColor colorWithRed:1 green:0.69 blue:0.3 alpha:1]; }
static UIColor *Panel(void) { return [UIColor colorWithWhite:0.06 alpha:0.18]; }

static void Surface(UIView *view, CGFloat radius) {
    view.backgroundColor = Panel();
    view.layer.cornerRadius = radius;
    view.layer.borderWidth = 1;
    view.layer.borderColor = [UIColor colorWithWhite:1 alpha:0.14].CGColor;
}

static UIImage *Symbol(NSString *name) {
    UIImageSymbolConfiguration *config = [UIImageSymbolConfiguration configurationWithPointSize:21 weight:UIImageSymbolWeightMedium];
    return [UIImage systemImageNamed:name withConfiguration:config];
}

// Draw the familiar spacebar mark independently of the installed symbol font.
static UIImage *SpaceSymbol(void) {
    UIGraphicsImageRenderer *renderer = [[UIGraphicsImageRenderer alloc] initWithSize:CGSizeMake(26, 18)];
    return [[renderer imageWithActions:^(UIGraphicsImageRendererContext *context) {
        UIBezierPath *path = [UIBezierPath bezierPath];
        [path moveToPoint:CGPointMake(2, 5)];
        [path addLineToPoint:CGPointMake(2, 13)];
        [path addLineToPoint:CGPointMake(24, 13)];
        [path addLineToPoint:CGPointMake(24, 5)];
        path.lineWidth = 2;
        path.lineCapStyle = kCGLineCapRound;
        path.lineJoinStyle = kCGLineJoinRound;
        [UIColor.whiteColor setStroke];
        [path stroke];
    }] imageWithRenderingMode:UIImageRenderingModeAlwaysTemplate];
}

@interface SRActionButton : UIButton
@property(nonatomic) BOOL primary;
@property(nonatomic) BOOL inputHeld;
@end
@implementation SRActionButton
- (BOOL)pointInside:(CGPoint)point withEvent:(UIEvent *)event {
    return CGRectContainsPoint(self.bounds, point);
}
- (void)setInputHeld:(BOOL)inputHeld {
    _inputHeld = inputHeld;
    [self setHighlighted:self.highlighted];
}
- (void)setHighlighted:(BOOL)highlighted {
    [super setHighlighted:highlighted];
    BOOL active = highlighted || self.inputHeld;
    self.backgroundColor = active ? [Amber() colorWithAlphaComponent:0.22] : Panel();
    self.tintColor = active ? [Amber() colorWithAlphaComponent:0.95] :
        self.primary ? [Amber() colorWithAlphaComponent:0.65] : [UIColor colorWithWhite:1 alpha:0.44];
    self.layer.borderColor = (active ? [Amber() colorWithAlphaComponent:0.6] : [UIColor colorWithWhite:1 alpha:0.14]).CGColor;
}
@end

typedef NS_ENUM(NSInteger, SRPadKind) { SRSteeringPad, SRCameraPad };

@interface SRAnalogPad : UIControl
@property(nonatomic) SRPadKind kind;
@property(nonatomic) CGPoint value;
@property(nonatomic) CGPoint origin;
@property(nonatomic) BOOL layoutEditing;
@property(nonatomic, copy) void (^changed)(CGPoint);
- (instancetype)initWithKind:(SRPadKind)kind;
- (void)reset;
@end

@implementation SRAnalogPad
- (instancetype)initWithKind:(SRPadKind)kind {
    if ((self = [super initWithFrame:CGRectZero])) {
        _kind = kind;
        self.backgroundColor = UIColor.clearColor;
        self.opaque = NO;
        self.exclusiveTouch = NO;
        self.isAccessibilityElement = YES;
        self.accessibilityLabel = kind == SRSteeringPad ? @"Steering" : @"Camera";
    }
    return self;
}
static float Axis(CGFloat value) {
    float clamped = fmaxf(-1, fminf(1, value));
    return fabsf(clamped) < 0.08f ? 0 : copysignf((fabsf(clamped) - 0.08f) / 0.92f, clamped);
}
- (void)setPoint:(CGPoint)point {
    CGPoint center = CGPointMake(CGRectGetMidX(self.bounds), CGRectGetMidY(self.bounds));
    CGFloat travel = self.bounds.size.width * (self.kind == SRSteeringPad ? 0.35 : 0.29);
    // A steering gesture starts at neutral wherever the thumb lands.
    if (self.kind == SRSteeringPad) center.x = self.origin.x;
    self.value = CGPointMake(Axis((point.x - center.x) / travel),
                            self.kind == SRCameraPad ? Axis((point.y - center.y) / travel) : 0);
    if (self.kind == SRCameraPad) {
        CGFloat magnitude = MAX(1, hypot(self.value.x, self.value.y));
        self.value = CGPointMake(self.value.x / magnitude, self.value.y / magnitude);
    }
    if (self.changed) self.changed(self.value);
    [self setNeedsDisplay];
}
- (BOOL)beginTrackingWithTouch:(UITouch *)touch withEvent:(UIEvent *)event {
    if (self.layoutEditing) return NO;
    self.highlighted = YES;
    self.origin = [touch locationInView:self];
    [self setPoint:[touch locationInView:self]];
    return YES;
}
- (BOOL)continueTrackingWithTouch:(UITouch *)touch withEvent:(UIEvent *)event {
    if (self.layoutEditing) return NO;
    [self setPoint:[touch locationInView:self]];
    return YES;
}
- (void)endTrackingWithTouch:(UITouch *)touch withEvent:(UIEvent *)event { [self reset]; }
- (void)cancelTrackingWithEvent:(UIEvent *)event { [self reset]; }
- (void)reset {
    self.value = CGPointZero;
    self.highlighted = NO;
    if (self.changed) self.changed(CGPointZero);
    [self setNeedsDisplay];
}
- (void)drawRect:(CGRect)rect {
    BOOL steering = self.kind == SRSteeringPad;
    CGPoint center = CGPointMake(CGRectGetMidX(rect), CGRectGetMidY(rect));
    if (steering && self.highlighted) center.x = self.origin.x;
    CGRect body = CGRectInset(rect, 4, 4);
    UIBezierPath *outline = steering ? [UIBezierPath bezierPathWithRoundedRect:body cornerRadius:body.size.height / 2] :
                                      [UIBezierPath bezierPathWithOvalInRect:body];
    [[UIColor colorWithWhite:0.04 alpha:self.highlighted ? 0.2 : 0.10] setFill]; [outline fill];
    [[UIColor colorWithWhite:1 alpha:self.highlighted ? 0.3 : 0.14] setStroke];
    outline.lineWidth = 1; [outline stroke];
    if (steering) {
        UIBezierPath *rail = [UIBezierPath bezierPath];
        [rail moveToPoint:CGPointMake(24, center.y)];
        [rail addLineToPoint:CGPointMake(rect.size.width - 24, center.y)];
        [[UIColor colorWithWhite:1 alpha:0.12] setStroke]; [rail stroke];
        [rail removeAllPoints];
        [rail moveToPoint:CGPointMake(center.x, center.y - 5)];
        [rail addLineToPoint:CGPointMake(center.x, center.y + 5)];
        [rail stroke];
    }
    CGFloat diameter = steering ? 34 : 28;
    CGFloat travel = rect.size.width * (steering ? 0.35 : 0.29);
    CGFloat knobX = MAX(diameter / 2 + 4, MIN(rect.size.width - diameter / 2 - 4, center.x + self.value.x * travel));
    CGRect knob = CGRectMake(knobX - diameter / 2,
                             center.y + self.value.y * travel - diameter / 2, diameter, diameter);
    UIBezierPath *thumb = [UIBezierPath bezierPathWithOvalInRect:knob];
    [(self.highlighted ? [Amber() colorWithAlphaComponent:0.58] : [UIColor colorWithWhite:1 alpha:0.19]) setFill]; [thumb fill];
    [[UIColor colorWithWhite:1 alpha:self.highlighted ? 0.45 : 0.22] setStroke]; [thumb stroke];
}
@end

static UIImage *PedalSymbol(BOOL throttle) {
    UIGraphicsImageRenderer *renderer = [[UIGraphicsImageRenderer alloc] initWithSize:CGSizeMake(30, 32)];
    return [[renderer imageWithActions:^(UIGraphicsImageRendererContext *context) {
        CGRect body = throttle ? CGRectMake(8, 2, 14, 28) : CGRectMake(2, 7, 26, 18);
        UIBezierPath *path = [UIBezierPath bezierPathWithRoundedRect:body cornerRadius:3];
        path.lineWidth = 1.7;
        [UIColor.whiteColor setStroke]; [path stroke];
        [path removeAllPoints];
        for (int i = 0; i < 3; ++i) {
            if (throttle) {
                [path moveToPoint:CGPointMake(12, 9 + i * 6)];
                [path addLineToPoint:CGPointMake(18, 9 + i * 6)];
            } else {
                [path moveToPoint:CGPointMake(9 + i * 6, 12)];
                [path addLineToPoint:CGPointMake(9 + i * 6, 20)];
            }
        }
        path.lineCapStyle = kCGLineCapRound;
        [path stroke];
    }] imageWithRenderingMode:UIImageRenderingModeAlwaysTemplate];
}

@interface SRMenuController : UIViewController
@property(nonatomic) BOOL driving;
@property(nonatomic) SRGameContext context;
@property(nonatomic) BOOL controlsHidden;
@property(nonatomic) BOOL dockCollapsed;
@property(nonatomic) BOOL layoutEditing;
@property(nonatomic) UIEdgeInsets previewInsets;
@property(nonatomic, strong) UIView *dock;
@property(nonatomic, strong) NSArray<SRActionButton *> *menuKeys;
@property(nonatomic, strong) SRActionButton *modeButton, *foldButton, *pauseButton, *editButton, *resetButton;
@property(nonatomic, strong) SRActionButton *backButton;
@property(nonatomic, strong) SRActionButton *space, *functions, *map, *throttle, *brake;
@property(nonatomic, strong) SRActionButton *zoomIn, *zoomOut;
@property(nonatomic, strong) SRAnalogPad *steering, *camera;
@property(nonatomic, strong) NSMutableDictionary *savedLayout;
@property(nonatomic, strong) NSURL *layoutURL;
@property(nonatomic, strong) NSMutableSet<SRActionButton *> *heldKeyButtons;
@property(nonatomic, strong) UIImpactFeedbackGenerator *feedback;
- (void)showDriving:(BOOL)driving;
- (void)applyContext:(SRGameContext)context;
@end

@implementation SRMenuController
- (UIInterfaceOrientationMask)supportedInterfaceOrientations { return UIInterfaceOrientationMaskLandscape; }
- (BOOL)prefersStatusBarHidden { return YES; }
- (BOOL)prefersHomeIndicatorAutoHidden { return self.driving; }
- (NSArray<UIView *> *)movableControls { return @[self.steering, self.camera, self.throttle, self.brake, self.space, self.functions, self.map]; }
- (SRActionButton *)button:(NSString *)name symbol:(NSString *)symbol key:(SDL_Scancode)key primary:(BOOL)primary {
    SRActionButton *button = [SRActionButton buttonWithType:UIButtonTypeCustom];
    button.primary = primary;
    Surface(button, 17);
    button.tag = key;
    button.exclusiveTouch = NO;
    button.accessibilityLabel = name;
    [button setImage:Symbol(symbol) forState:UIControlStateNormal];
    [button setHighlighted:NO];
    if (key != SDL_SCANCODE_UNKNOWN) {
        [button addTarget:self action:@selector(keyDown:) forControlEvents:UIControlEventTouchDown];
        [button addTarget:self action:@selector(keyUp:) forControlEvents:UIControlEventTouchUpInside | UIControlEventTouchUpOutside | UIControlEventTouchCancel];
    }
    return button;
}
- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = UIColor.clearColor;
    self.view.opaque = NO;
    self.view.multipleTouchEnabled = YES;
    if (!self.layoutURL) self.layoutURL = LayoutURL();
    self.savedLayout = LoadLayout(self.layoutURL);
    self.heldKeyButtons = [NSMutableSet new];
    self.feedback = [[UIImpactFeedbackGenerator alloc] initWithStyle:UIImpactFeedbackStyleSoft];
    self.dock = [UIView new]; Surface(self.dock, 23);
    self.menuKeys = @[[self button:@"Left" symbol:@"chevron.left" key:SDL_SCANCODE_LEFT primary:NO],
        [self button:@"Up" symbol:@"chevron.up" key:SDL_SCANCODE_UP primary:NO],
        [self button:@"Down" symbol:@"chevron.down" key:SDL_SCANCODE_DOWN primary:NO],
        [self button:@"Right" symbol:@"chevron.right" key:SDL_SCANCODE_RIGHT primary:NO],
        [self button:@"Enter" symbol:@"return" key:SDL_SCANCODE_RETURN primary:YES],
        [self button:@"Space / confirm" symbol:@"space" key:SDL_SCANCODE_SPACE primary:YES],
        [self button:@"Back" symbol:@"arrow.uturn.backward" key:SDL_SCANCODE_ESCAPE primary:NO]];
    [self.menuKeys[5] setImage:SpaceSymbol() forState:UIControlStateNormal];
    for (UIView *button in self.menuKeys) [self.dock addSubview:button];
    [self.view addSubview:self.dock];
    self.modeButton = [self button:@"Hide controls" symbol:@"eye.slash" key:SDL_SCANCODE_UNKNOWN primary:NO];
    [self.modeButton addTarget:self action:@selector(toggleControlsVisibility) forControlEvents:UIControlEventTouchUpInside];
    self.foldButton = [self button:@"Show keyboard" symbol:@"keyboard" key:SDL_SCANCODE_UNKNOWN primary:NO];
    [self.foldButton addTarget:self action:@selector(toggleDock) forControlEvents:UIControlEventTouchUpInside];
    self.pauseButton = [self button:@"Pause" symbol:@"pause.fill" key:SDL_SCANCODE_ESCAPE primary:NO];
    self.backButton = [self button:@"Back" symbol:@"arrow.uturn.backward" key:SDL_SCANCODE_ESCAPE primary:NO];
    self.editButton = [self button:@"Move controls" symbol:@"arrow.up.and.down.and.arrow.left.and.right" key:SDL_SCANCODE_UNKNOWN primary:NO];
    [self.editButton addTarget:self action:@selector(toggleLayoutEditing) forControlEvents:UIControlEventTouchUpInside];
    self.resetButton = [self button:@"Reset control positions" symbol:@"arrow.counterclockwise" key:SDL_SCANCODE_UNKNOWN primary:NO];
    [self.resetButton addTarget:self action:@selector(resetLayout) forControlEvents:UIControlEventTouchUpInside];
    for (UIView *view in @[self.modeButton, self.foldButton, self.pauseButton, self.backButton, self.editButton, self.resetButton]) [self.view addSubview:view];
    self.zoomIn = [self button:@"Zoom in" symbol:@"plus.magnifyingglass" key:SDL_SCANCODE_UNKNOWN primary:NO];
    self.zoomOut = [self button:@"Zoom out" symbol:@"minus.magnifyingglass" key:SDL_SCANCODE_UNKNOWN primary:NO];
    self.zoomIn.tag = 1;
    self.zoomOut.tag = -1;
    for (SRActionButton *button in @[self.zoomIn, self.zoomOut]) {
        [button addTarget:self action:@selector(zoom:) forControlEvents:UIControlEventTouchUpInside];
        [self.view addSubview:button];
    }
    self.steering = [[SRAnalogPad alloc] initWithKind:SRSteeringPad];
    self.steering.changed = ^(CGPoint value) { SRTouchSteer(value.x); };
    self.steering.accessibilityIdentifier = @"steering";
    self.camera = [[SRAnalogPad alloc] initWithKind:SRCameraPad];
    self.camera.changed = ^(CGPoint value) {
        CGFloat strength = MIN(1, hypot(value.x, value.y));
        SRTouchLook(value.x * strength * 0.65, value.y * strength * 0.65);
    };
    self.camera.accessibilityIdentifier = @"camera";
    self.throttle = [self button:@"Throttle" symbol:@"chevron.up" key:SDL_SCANCODE_UNKNOWN primary:NO];
    self.brake = [self button:@"Brake and reverse" symbol:@"chevron.down" key:SDL_SCANCODE_UNKNOWN primary:NO];
    self.throttle.tag = 1;
    self.brake.tag = 0;
    self.throttle.accessibilityIdentifier = @"throttle";
    self.brake.accessibilityIdentifier = @"brake";
    for (SRActionButton *pedal in @[self.throttle, self.brake]) {
        [pedal setImage:PedalSymbol(pedal.tag == 1) forState:UIControlStateNormal];
        [pedal addTarget:self action:@selector(pedalDown:) forControlEvents:UIControlEventTouchDown];
        [pedal addTarget:self action:@selector(pedalUp:) forControlEvents:UIControlEventTouchUpInside | UIControlEventTouchUpOutside | UIControlEventTouchCancel];
    }
    self.space = [self button:@"Space" symbol:@"space" key:SDL_SCANCODE_SPACE primary:NO];
    [self.space setImage:SpaceSymbol() forState:UIControlStateNormal];
    self.space.accessibilityIdentifier = @"space";
    self.functions = [self button:@"Actions" symbol:@"wrench.and.screwdriver" key:SDL_SCANCODE_V primary:NO];
    self.functions.accessibilityIdentifier = @"actions";
    self.map = [self button:@"Map" symbol:@"map" key:SDL_SCANCODE_M primary:NO];
    self.map.accessibilityIdentifier = @"map";
    for (UIView *view in self.movableControls) {
        [self.view addSubview:view];
        UIPanGestureRecognizer *drag = [[UIPanGestureRecognizer alloc] initWithTarget:self action:@selector(moveControl:)];
        drag.maximumNumberOfTouches = 1;
        drag.enabled = NO;
        [view addGestureRecognizer:drag];
    }
    [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(willResignActive) name:UIApplicationWillResignActiveNotification object:nil];
    [self applyContext:SRContextMenu];
}
- (UIEdgeInsets)controlInsets {
    return UIEdgeInsetsEqualToEdgeInsets(self.previewInsets, UIEdgeInsetsZero) ? self.view.safeAreaInsets : self.previewInsets;
}
- (CGPoint)clampCenter:(CGPoint)center forView:(UIView *)view {
    UIEdgeInsets inset = self.controlInsets;
    CGSize size = self.view.bounds.size, control = view.bounds.size;
    return CGPointMake(MAX(inset.left + 8 + control.width / 2, MIN(size.width - inset.right - 8 - control.width / 2, center.x)),
                       MAX(76 + control.height / 2, MIN(size.height - MAX(24, inset.bottom + 8) - control.height / 2, center.y)));
}
- (void)viewDidLayoutSubviews {
    [super viewDidLayoutSubviews];
    CGSize size = self.view.bounds.size;
    UIEdgeInsets insets = self.controlInsets;
    CGFloat left = MAX(16, insets.left + 10), right = size.width - MAX(16, insets.right + 10);
    self.modeButton.frame = CGRectMake(left, 12, 48, 48);
    self.editButton.frame = CGRectMake(left + 56, 12, 48, 48);
    self.resetButton.frame = CGRectMake(left + 112, 12, 48, 48);
    self.foldButton.frame = CGRectMake(right - 48, 12, 48, 48);
    self.pauseButton.frame = CGRectMake(right - 48, 12, 48, 48);
    self.backButton.frame = CGRectMake(right - 104, 12, 48, 48);
    self.zoomOut.frame = CGRectMake(left, size.height - MAX(68, insets.bottom + 62), 48, 48);
    self.zoomIn.frame = CGRectMake(left + 56, self.zoomOut.frame.origin.y, 48, 48);
    CGFloat dockWidth = self.menuKeys.count * 54 + 6;
    self.dock.frame = CGRectMake((size.width - dockWidth) / 2, size.height - MAX(68, insets.bottom + 62), dockWidth, 58);
    CGFloat x = 6;
    for (NSUInteger i = 0; i < self.menuKeys.count; ++i) {
        self.menuKeys[i].frame = CGRectMake(x, 5, 48, 48);
        x += 54;
    }
    // UIKit points, not the game's render pixels. Lowering render resolution
    // must not shrink the controls or move their touch targets.
    CGFloat scale = MAX(44.0 / 48.0, MIN(1.15, MIN(size.width / 912.0, size.height / 420.0)));
    CGFloat key = 48 * scale, pedalWidth = 64 * scale, pedalHeight = 80 * scale;
    CGFloat rowX = MAX(left + key / 2, round(size.width * 0.12 / 4) * 4);
    CGFloat rowY = round(size.height * 0.495 / 4) * 4;
    NSArray<UIView *> *actions = @[self.map, self.functions, self.space];
    for (NSUInteger i = 0; i < actions.count; ++i)
        actions[i].frame = CGRectMake(rowX + i * 72 * scale - key / 2, rowY - key / 2, key, key);
    self.steering.bounds = CGRectMake(0, 0, 200 * scale, 72 * scale);
    self.steering.center = CGPointMake(rowX + 72 * scale, round(size.height * 0.68 / 4) * 4);
    self.camera.bounds = CGRectMake(0, 0, 88 * scale, 88 * scale);
    self.camera.center = CGPointMake(round(size.width * 0.835 / 4) * 4, round(size.height * 0.477 / 4) * 4);
    // Put both pedals inboard of the game's right-hand transmission/AWD HUD.
    CGFloat pedalY = round(size.height * 0.84 / 4) * 4;
    self.brake.frame = CGRectMake(round(size.width * 0.652 / 4) * 4 - pedalWidth / 2,
                                 pedalY - pedalHeight / 2, pedalWidth, pedalHeight);
    self.throttle.frame = CGRectMake(round(size.width * 0.734 / 4) * 4 - pedalWidth / 2,
                                    pedalY - pedalHeight / 2, pedalWidth, pedalHeight);
    for (UIView *view in self.movableControls) {
        NSArray *saved = self.savedLayout[view.accessibilityIdentifier];
        if (saved.count == 2) view.center = CGPointMake([saved[0] doubleValue] * size.width, [saved[1] doubleValue] * size.height);
        view.center = [self clampCenter:view.center forView:view];
    }
}
- (void)showDriving:(BOOL)driving {
    self.driving = driving;
    for (UIView *view in self.movableControls) view.hidden = !driving;
    self.dock.hidden = self.controlsHidden || driving || self.dockCollapsed;
    self.pauseButton.hidden = !driving;
    self.backButton.hidden = self.controlsHidden || driving;
    self.editButton.hidden = !driving;
    self.resetButton.hidden = YES;
    self.zoomIn.hidden = self.zoomOut.hidden = self.controlsHidden || self.context != SRContextMap;
    self.foldButton.hidden = self.controlsHidden || driving;
    [self.modeButton setImage:Symbol(self.controlsHidden ? @"eye" : @"eye.slash") forState:UIControlStateNormal];
    self.modeButton.accessibilityLabel = self.controlsHidden ? @"Show controls" : @"Hide controls";
    [self updateFoldButton];
    [self setNeedsUpdateOfHomeIndicatorAutoHidden];
    [self.view setNeedsLayout];
}
- (void)applyContext:(SRGameContext)context {
    if (self.layoutEditing) [self toggleLayoutEditing];
    [self releaseInputs];
    self.context = context;
    self.dockCollapsed = YES;
    BOOL driving = context == SRContextDriving && !self.controlsHidden;
    if (driving && !SRTouchInputStart()) {
        driving = NO;
        fprintf(stderr, "TouchInput: unable to create virtual gamepad: %s\n", SDL_GetError());
    }
    [self showDriving:driving];
}
- (void)toggleControlsVisibility {
    self.controlsHidden = !self.controlsHidden;
    [self applyContext:self.context];
}
- (void)updateFoldButton {
    [self.foldButton setImage:Symbol(self.dock.hidden ? @"keyboard" : @"keyboard.chevron.compact.down") forState:UIControlStateNormal];
    self.foldButton.accessibilityLabel = self.dock.hidden ? @"Show keyboard" : @"Hide keyboard";
}
- (void)toggleDock {
    if (self.layoutEditing) return;
    if (!self.dock.hidden) {
        for (SRActionButton *button in self.menuKeys) [self keyUp:button];
    }
    self.dock.hidden = !self.dock.hidden;
    self.dockCollapsed = self.dock.hidden;
    [self updateFoldButton];
}
- (void)zoom:(SRActionButton *)button {
    if (self.context != SRContextMap) return;
    SDL_Window *window = SDL_GetKeyboardFocus();
    if (!window) return;
    SDL_Event event = {0};
    event.type = SDL_MOUSEWHEEL;
    event.wheel.windowID = SDL_GetWindowID(window);
    event.wheel.which = SDL_TOUCH_MOUSEID;
    event.wheel.y = (Sint32)button.tag;
    event.wheel.preciseY = (float)button.tag;
    event.wheel.direction = SDL_MOUSEWHEEL_NORMAL;
    SDL_PushEvent(&event);
}
- (void)toggleLayoutEditing {
    [self releaseInputs];
    if (self.layoutEditing) SaveLayout(self.savedLayout, self.layoutURL);
    self.layoutEditing = !self.layoutEditing;
    self.steering.layoutEditing = self.camera.layoutEditing = self.layoutEditing;
    self.resetButton.hidden = !self.layoutEditing;
    self.view.backgroundColor = self.layoutEditing ? [UIColor colorWithWhite:0 alpha:0.12] : UIColor.clearColor;
    [self.editButton setImage:Symbol(self.layoutEditing ? @"checkmark" : @"arrow.up.and.down.and.arrow.left.and.right") forState:UIControlStateNormal];
    self.editButton.accessibilityLabel = self.layoutEditing ? @"Done moving controls" : @"Move controls";
    self.editButton.primary = self.layoutEditing;
    [self.editButton setHighlighted:NO];
    for (UIView *view in self.movableControls) {
        for (UIGestureRecognizer *gesture in view.gestureRecognizers) gesture.enabled = self.layoutEditing;
        view.layer.borderWidth = self.layoutEditing ? 1.5 : ([view isKindOfClass:SRAnalogPad.class] ? 0 : 1);
        view.layer.cornerRadius = [view isKindOfClass:SRAnalogPad.class] ? view.bounds.size.height / 2 : 17;
        view.layer.borderColor = (self.layoutEditing ? [Amber() colorWithAlphaComponent:0.75] : [UIColor colorWithWhite:1 alpha:0.14]).CGColor;
    }
}
- (void)moveControl:(UIPanGestureRecognizer *)gesture {
    if (!self.layoutEditing) return;
    UIView *view = gesture.view;
    CGPoint delta = [gesture translationInView:self.view];
    view.center = [self clampCenter:CGPointMake(view.center.x + delta.x, view.center.y + delta.y) forView:view];
    [gesture setTranslation:CGPointZero inView:self.view];
    self.savedLayout[view.accessibilityIdentifier] = @[@(view.center.x / self.view.bounds.size.width), @(view.center.y / self.view.bounds.size.height)];
    if (gesture.state == UIGestureRecognizerStateEnded || gesture.state == UIGestureRecognizerStateCancelled)
        SaveLayout(self.savedLayout, self.layoutURL);
}
- (void)resetLayout {
    if (!self.layoutEditing) return;
    [self.savedLayout removeAllObjects];
    SaveLayout(self.savedLayout, self.layoutURL);
    [self.view setNeedsLayout];
}
- (void)willResignActive {
    [self releaseInputs];
    SaveLayout(self.savedLayout, self.layoutURL);
}
- (void)releaseInputs {
    SRTouchInputReset();
    [self.steering reset];
    [self.camera reset];
    for (SRActionButton *button in self.heldKeyButtons.allObjects) [self keyUp:button];
    SRReleaseAllOverlayKeys();
    self.throttle.inputHeld = self.brake.inputHeld = NO;
    [self.throttle setHighlighted:NO];
    [self.brake setHighlighted:NO];
}
- (void)pedalDown:(SRActionButton *)button {
    if (self.layoutEditing) return;
    button.inputHeld = YES;
    SRTouchPedal(button.tag == 1, 1);
}
- (void)pedalUp:(SRActionButton *)button {
    button.inputHeld = NO;
    SRTouchPedal(button.tag == 1, 0);
}
- (BOOL)isKeyHeld:(SDL_Scancode)key {
    for (SRActionButton *button in self.heldKeyButtons) if (button.tag == key) return YES;
    return NO;
}
- (void)keyDown:(SRActionButton *)button {
    if (self.layoutEditing || !sendVirtualKey) return;
    if ([self.heldKeyButtons containsObject:button]) return;
    BOOL alreadyHeld = [self isKeyHeld:(SDL_Scancode)button.tag];
    [self.heldKeyButtons addObject:button];
    button.inputHeld = YES;
    if (getenv("EMU_DIAGNOSTICS")) fprintf(stderr, "OverlayKey: down %s\n", SDL_GetScancodeName((SDL_Scancode)button.tag));
    [self.feedback impactOccurredWithIntensity:0.3];
    if (!alreadyHeld) sendVirtualKey(SDL_PRESSED, (SDL_Scancode)button.tag);
}
- (void)keyUp:(SRActionButton *)button {
    if (![self.heldKeyButtons containsObject:button]) return;
    [self.heldKeyButtons removeObject:button];
    button.inputHeld = NO;
    if (getenv("EMU_DIAGNOSTICS")) fprintf(stderr, "OverlayKey: up %s\n", SDL_GetScancodeName((SDL_Scancode)button.tag));
    if (sendVirtualKey && ![self isKeyHeld:(SDL_Scancode)button.tag])
        sendVirtualKey(SDL_RELEASED, (SDL_Scancode)button.tag);
}
@end

@interface SRMenuWindow : UIWindow @end
static SRMenuWindow *menuWindow;
@implementation SRMenuWindow
- (UIView *)hitTest:(CGPoint)point withEvent:(UIEvent *)event {
    UIView *hit = [super hitTest:point withEvent:event];
    SRMenuController *controller = (SRMenuController *)self.rootViewController;
    if (controller.layoutEditing) return hit;
    if (hit && [hit isDescendantOfView:controller.dock]) return hit;
    for (UIView *view = hit; view && view != self; view = view.superview)
        if ([view isKindOfClass:UIControl.class]) return hit;
    return nil;
}
@end

void SRInstallMenuControls(UIWindowScene *scene, int (*sendKey)(Uint8, SDL_Scancode)) {
    if (menuWindow || !sendKey) return;
    sendVirtualKey = sendKey;
    menuWindow = [[SRMenuWindow alloc] initWithWindowScene:scene];
    menuWindow.frame = scene.coordinateSpace.bounds;
    menuWindow.windowLevel = UIWindowLevelNormal + 1;
    menuWindow.rootViewController = [SRMenuController new];
    menuWindow.backgroundColor = UIColor.clearColor;
    menuWindow.opaque = NO;
    menuWindow.hidden = NO;
}

void SRHideMenuControls(void) {
    [(SRMenuController *)menuWindow.rootViewController releaseInputs];
    menuWindow.hidden = YES;
    menuWindow = nil;
}

void SRUpdateControlsContext(SRGameContext context) {
    SRMenuController *controller = (SRMenuController *)menuWindow.rootViewController;
    if (controller && controller.context != context) [controller applyContext:context];
}

static unsigned testKeyPresses, testKeyReleases;
static int TestKey(Uint8 state, SDL_Scancode key) {
    if (state == SDL_PRESSED) ++testKeyPresses;
    else ++testKeyReleases;
    return 1;
}

static void SaveControlsPreview(SRMenuController *controller) {
    CGSize size = controller.view.bounds.size;
    UIGraphicsImageRendererFormat *format = [UIGraphicsImageRendererFormat defaultFormat];
    format.scale = 2;
    UIGraphicsImageRenderer *renderer = [[UIGraphicsImageRenderer alloc]
        initWithSize:CGSizeMake(size.width, size.height * 3) format:format];
    [controller.savedLayout removeAllObjects];
    UIImage *image = [renderer imageWithActions:^(UIGraphicsImageRendererContext *context) {
        NSArray *titles = @[@"DRIVING", @"MAP", @"MENU"];
        SRGameContext modes[] = {SRContextDriving, SRContextMap, SRContextMenu};
        for (NSUInteger i = 0; i < 3; ++i) {
            controller.context = modes[i];
            [controller showDriving:modes[i] == SRContextDriving];
            [controller.view layoutIfNeeded];
            CGContextSaveGState(context.CGContext);
            CGContextTranslateCTM(context.CGContext, 0, i * size.height);
            [[UIColor colorWithWhite:0.14 alpha:1] setFill];
            UIRectFill(CGRectMake(0, 0, size.width, size.height));
            [titles[i] drawAtPoint:CGPointMake(size.width / 2 - 35, 24) withAttributes:@{
                NSFontAttributeName:[UIFont monospacedSystemFontOfSize:14 weight:UIFontWeightMedium],
                NSForegroundColorAttributeName:[UIColor colorWithWhite:1 alpha:0.5]}];
            [controller.view.layer renderInContext:context.CGContext];
            CGContextRestoreGState(context.CGContext);
        }
    }];
    NSString *path = [NSHomeDirectory() stringByAppendingPathComponent:@"Documents/controls-preview.png"];
    [UIImagePNGRepresentation(image) writeToFile:path atomically:YES];
}

NSDictionary *SRTouchLayoutTest(UIWindowScene *scene) {
    // Never overwrite the player's real layout during a diagnostic check.
    NSURL *testLayoutURL = [NSURL fileURLWithPath:[NSTemporaryDirectory() stringByAppendingPathComponent:NSUUID.UUID.UUIDString]];
    SRMenuController *first = [SRMenuController new];
    first.layoutURL = testLayoutURL;
    SRMenuWindow *window = [[SRMenuWindow alloc] initWithWindowScene:scene];
    window.frame = scene.coordinateSpace.bounds;
    window.rootViewController = first;
    window.hidden = NO;
    [first showDriving:YES];
    first.savedLayout[@"steering"] = @[@0.3, @0.7];
    [first.view setNeedsLayout];
    [window layoutIfNeeded]; [first.view layoutIfNeeded];
    CGPoint center = CGPointMake(CGRectGetMidX(window.bounds), CGRectGetMidY(window.bounds));
    BOOL passesThrough = [window hitTest:center withEvent:nil] == nil;
    BOOL capturesControls = [window hitTest:first.modeButton.center withEvent:nil] == first.modeButton;
    BOOL saved = SaveLayout(first.savedLayout, first.layoutURL);
    NSDictionary *disk = [NSDictionary dictionaryWithContentsOfURL:testLayoutURL];
    SRMenuController *second = [SRMenuController new];
    second.layoutURL = testLayoutURL;
    second.view.frame = first.view.bounds;
    second.previewInsets = first.controlInsets;
    [second showDriving:YES];
    [second.view layoutIfNeeded];
    BOOL restored = [first.savedLayout isEqualToDictionary:disk] && [second.savedLayout isEqualToDictionary:disk];
    for (NSUInteger i = 0; i < first.movableControls.count; ++i) {
        CGPoint a = first.movableControls[i].center, b = second.movableControls[i].center;
        restored = restored && fabs(a.x - b.x) < 1 && fabs(a.y - b.y) < 1;
    }
    [first toggleLayoutEditing];
    BOOL editCaptures = [window hitTest:center withEvent:nil] != nil;
    [first toggleLayoutEditing];
    BOOL exitPassesThrough = [window hitTest:center withEvent:nil] == nil;

    int (*savedSender)(Uint8, SDL_Scancode) = sendVirtualKey;
    sendVirtualKey = TestKey;
    testKeyPresses = testKeyReleases = 0;
    [first keyDown:first.pauseButton];
    [first keyDown:first.menuKeys.lastObject];
    [first keyUp:first.pauseButton];
    BOOL sharedKey = testKeyPresses == 1 && testKeyReleases == 0;
    [first keyUp:first.menuKeys.lastObject];
    sharedKey = sharedKey && testKeyReleases == 1;
    [first pedalDown:first.throttle];
    [first.throttle setHighlighted:NO];
    BOOL heldVisual = first.throttle.inputHeld;
    [first keyDown:first.space];
    [first applyContext:SRContextMap];
    BOOL mapControls = first.steering.hidden && first.camera.hidden && first.throttle.hidden && first.brake.hidden &&
                       !first.zoomIn.hidden && !first.zoomOut.hidden && first.dock.hidden && !first.backButton.hidden;
    BOOL releasedOnContextChange = first.heldKeyButtons.count == 0 && !first.throttle.inputHeld;
    [first applyContext:SRContextMenu];
    BOOL menuControls = first.zoomIn.hidden && first.zoomOut.hidden && first.dock.hidden && !first.foldButton.hidden;
    [first toggleDock];
    BOOL optionalKeyboard = !first.dock.hidden && first.menuKeys.count == 7 && first.menuKeys[5].tag == SDL_SCANCODE_SPACE;
    [first toggleDock];
    optionalKeyboard = optionalKeyboard && first.dock.hidden;
    sendVirtualKey = savedSender;
    SaveControlsPreview(first);

    window.hidden = YES;
    [NSFileManager.defaultManager removeItemAtURL:testLayoutURL error:nil];
    return @{@"savedToDisk":@(saved), @"restoredPositions":@(restored), @"savedControls":@(disk.count),
             @"gameTouchesPassThrough":@(passesThrough), @"controlsReceiveTouches":@(capturesControls),
             @"editingCapturesTouches":@(editCaptures), @"exitRestoresTouches":@(exitPassesThrough),
             @"sharedKeysReleasedOnce":@(sharedKey), @"heldPedalStaysHighlighted":@(heldVisual),
             @"mapControls":@(mapControls), @"menuControls":@(menuControls),
             @"keyboardOnlyWhenRequested":@(optionalKeyboard),
             @"contextChangeReleasesInputs":@(releasedOnContextChange),
             @"passed":@(saved && restored && passesThrough && capturesControls && editCaptures && exitPassesThrough &&
                         sharedKey && heldVisual && mapControls && menuControls && optionalKeyboard && releasedOnContextChange)};
}

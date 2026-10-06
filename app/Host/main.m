#import <UIKit/UIKit.h>
#import "GameLauncher.h"
#import "SDLCheck.h"
#import "ResourceCheck.h"
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>

static void SaveReport(NSDictionary *values, NSString *filename, BOOL complete) {
    NSMutableDictionary *report = [values mutableCopy];
    const char *token = getenv("EMU_CHECK_TOKEN");
    report[@"token"] = token ? @(token) : @"";
    report[@"complete"] = @(complete);
    NSString *path = [[NSHomeDirectory() stringByAppendingPathComponent:@"Documents"] stringByAppendingPathComponent:filename];
    [[NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:nil]
        writeToFile:path options:NSDataWritingAtomic error:nil];
}

@interface EmuController : UIViewController <UIDocumentPickerDelegate>
@property(nonatomic, strong) UITextView *status;
@property(nonatomic, strong) UIStackView *actions;
@property(nonatomic) BOOL started;
@property(nonatomic) BOOL busy;
- (void)start;
- (void)showWindowsMenu;
- (void)setActionsEnabled:(BOOL)enabled;
- (void)importFolder;
- (void)verifyFiles;
- (void)runDiagnostic;
- (void)launchFromMenu;
@end

@implementation EmuController
- (UIInterfaceOrientationMask)supportedInterfaceOrientations { return UIInterfaceOrientationMaskLandscape; }
- (UIInterfaceOrientation)preferredInterfaceOrientationForPresentation { return UIInterfaceOrientationLandscapeRight; }
- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = UIColor.systemBackgroundColor;
    self.status = [[UITextView alloc] init];
    self.status.editable = NO;
    self.status.font = [UIFont systemFontOfSize:19 weight:UIFontWeightRegular];
    self.status.text = @"Starting SnowRunner…";
    self.status.translatesAutoresizingMaskIntoConstraints = NO;
    [self.view addSubview:self.status];
    UILayoutGuide *area = self.view.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[
        [self.status.leadingAnchor constraintEqualToAnchor:area.leadingAnchor constant:24],
        [self.status.trailingAnchor constraintEqualToAnchor:area.trailingAnchor constant:-24],
        [self.status.topAnchor constraintEqualToAnchor:area.topAnchor constant:16],
        [self.status.bottomAnchor constraintEqualToAnchor:area.bottomAnchor constant:-16]
    ]];
}
- (void)viewDidAppear:(BOOL)animated { [super viewDidAppear:animated]; [self start]; }
- (void)setActionsEnabled:(BOOL)enabled {
    BOOL diagnosticOnly = [NSBundle.mainBundle.infoDictionary[@"EmuDiagnosticOnly"] boolValue];
    for (UIButton *button in self.actions.arrangedSubviews) {
        button.enabled = enabled && !(diagnosticOnly && button.tag == 3);
    }
}
- (void)showWindowsMenu {
    self.actions = [[UIStackView alloc] init];
    self.actions.axis = UILayoutConstraintAxisHorizontal;
    self.actions.spacing = 12;
    self.actions.distribution = UIStackViewDistributionFillEqually;
    self.actions.translatesAutoresizingMaskIntoConstraints = NO;
    NSArray *titles = @[@"Import folder", @"Verify files", @"Device check", @"Start game"];
    SEL selectors[] = {@selector(importFolder), @selector(verifyFiles), @selector(runDiagnostic), @selector(launchFromMenu)};
    for (NSUInteger index = 0; index < titles.count; ++index) {
        UIButton *button = [UIButton buttonWithType:UIButtonTypeSystem];
        button.configuration = [UIButtonConfiguration filledButtonConfiguration];
        [button setTitle:titles[index] forState:UIControlStateNormal];
        button.tag = index;
        [button addTarget:self action:selectors[index] forControlEvents:UIControlEventTouchUpInside];
        [self.actions addArrangedSubview:button];
    }
    [self.view addSubview:self.actions];
    UILayoutGuide *area = self.view.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[
        [self.actions.leadingAnchor constraintEqualToAnchor:area.leadingAnchor constant:24],
        [self.actions.trailingAnchor constraintEqualToAnchor:area.trailingAnchor constant:-24],
        [self.actions.bottomAnchor constraintEqualToAnchor:area.bottomAnchor constant:-16],
        [self.actions.heightAnchor constraintEqualToConstant:48]
    ]];
    // Leave room for the actions without replacing the Mac automation layout.
    self.status.contentInset = UIEdgeInsetsMake(0, 0, 72, 0);
    [self setActionsEnabled:YES];
    self.status.text = [NSBundle.mainBundle.infoDictionary[@"EmuDiagnosticOnly"] boolValue] ?
        @"Emu device check\n\nThis package has no game binaries. Tap Device check to test SDL, Metal and input adapters.\n\nWhen game files are available, create a game IPA with the same Bundle ID and signing account to update this app." :
        @"SnowRunner · Windows workflow\n\n1. Prepare SnowRunner.emuresources on Windows.\n2. Put that folder on a USB drive or a location available in the iPhone Files app.\n3. Tap Import folder and select the folder. Keep this app open during import.\n4. Tap Start game after verification.\n\nDocuments and logs are also available through file sharing. Repeating import resumes verified files.";
}
- (void)importFolder {
    if (self.busy) return;
    UIDocumentPickerViewController *picker = [[UIDocumentPickerViewController alloc] initForOpeningContentTypes:@[UTTypeFolder] asCopy:NO];
    picker.delegate = self;
    picker.allowsMultipleSelection = NO;
    [self presentViewController:picker animated:YES completion:nil];
}
- (void)documentPicker:(UIDocumentPickerViewController *)controller didPickDocumentsAtURLs:(NSArray<NSURL *> *)urls {
    NSURL *folder = urls.firstObject;
    if (!folder || self.busy) return;
    BOOL scoped = [folder startAccessingSecurityScopedResource];
    self.busy = YES;
    [self setActionsEnabled:NO];
    UIApplication.sharedApplication.idleTimerDisabled = YES;
    self.status.text = @"Importing and verifying resources…\n\nKeep this app open. A USB drive avoids storing a second full copy on the iPhone.";
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
        NSDictionary *result = EmuImportResources(folder, ^(NSUInteger count, NSUInteger total, NSString *file) {
            dispatch_async(dispatch_get_main_queue(), ^{
                self.status.text = [NSString stringWithFormat:@"Import: %lu / %lu\n\n%@\n\nKeep this app open.", (unsigned long)count, (unsigned long)total, file];
            });
        });
        if (scoped) [folder stopAccessingSecurityScopedResource];
        SaveReport(result, @"resource-import.json", YES);
        dispatch_async(dispatch_get_main_queue(), ^{
            self.busy = NO;
            [self setActionsEnabled:YES];
            UIApplication.sharedApplication.idleTimerDisabled = NO;
            self.status.text = [result[@"passed"] boolValue] ? @"Resources imported and verified. Tap Start game." :
                [NSString stringWithFormat:@"Import stopped. Completed files are retained; select the same folder to resume.\n\n%@", result[@"errors"]];
        });
    });
}
- (void)verifyFiles {
    if (self.busy) return;
    self.busy = YES;
    [self setActionsEnabled:NO];
    UIApplication.sharedApplication.idleTimerDisabled = YES;
    self.status.text = @"Verifying resources… Keep this app open.";
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
        NSDictionary *result = EmuVerifyResources(^(NSUInteger count, NSUInteger total, NSString *file) {
            dispatch_async(dispatch_get_main_queue(), ^{
                self.status.text = [NSString stringWithFormat:@"Verify: %lu / %lu\n\n%@", (unsigned long)count, (unsigned long)total, file];
            });
        });
        SaveReport(result, @"resource-check.json", YES);
        dispatch_async(dispatch_get_main_queue(), ^{
            self.busy = NO;
            [self setActionsEnabled:YES];
            UIApplication.sharedApplication.idleTimerDisabled = NO;
            self.status.text = [result[@"passed"] boolValue] ? @"All resources verified. Tap Start game." :
                [NSString stringWithFormat:@"Import missing or damaged resources.\n\n%@", result[@"errors"]];
        });
    });
}
- (void)runDiagnostic {
    if (self.busy) return;
    self.busy = YES;
    [self setActionsEnabled:NO];
    self.status.text = @"Checking SDL, Metal and input adapters…";
    RunSDLCheck(self.view.window, ^(NSDictionary *result, NSString *message) {
        SaveReport(result, @"sdl-check.json", YES);
        self.busy = NO;
        [self setActionsEnabled:YES];
        self.status.text = message;
    });
}
- (void)launchFromMenu {
    if (self.busy || [NSBundle.mainBundle.infoDictionary[@"EmuDiagnosticOnly"] boolValue]) return;
    NSArray *missing = EmuMissingResources();
    if (missing.count) {
        self.status.text = [NSString stringWithFormat:@"%lu resources are not ready. Import a prepared folder or tap Verify files for files copied earlier.", (unsigned long)missing.count];
        return;
    }
    self.busy = YES;
    [self setActionsEnabled:NO];
    CFRunLoopPerformBlock(CFRunLoopGetMain(), kCFRunLoopCommonModes, ^{
        NSDictionary *result = LaunchGame();
        [self.view.window makeKeyAndVisible];
        SaveReport(result, @"launch-error.json", YES);
        self.busy = NO;
        [self setActionsEnabled:YES];
        self.status.text = [NSString stringWithFormat:@"Game stopped.\n\n%@\n\nLogs are in Documents (file sharing).", result[@"error"] ?: result];
    });
    CFRunLoopWakeUp(CFRunLoopGetMain());
}
- (void)start {
    if (self.started || self.view.window.windowScene.activationState != UISceneActivationStateForegroundActive) return;
    self.started = YES;
    NSString *mode = getenv("EMU_MODE") ? @(getenv("EMU_MODE")) : @"game";
    BOOL directoriesReady = EmuCreateResourceDirectories();
    if ([mode isEqualToString:@"game"] && [NSBundle.mainBundle.infoDictionary[@"EmuWindowsMenu"] boolValue]) {
        [self showWindowsMenu];
        return;
    }
    if ([mode isEqualToString:@"maintenance"]) {
        NSDictionary *disk = [NSFileManager.defaultManager attributesOfFileSystemForPath:NSHomeDirectory() error:nil];
        SaveReport(@{@"passed":@(directoriesReady && disk[NSFileSystemFreeSize] != nil),
                     @"availableBytes":disk[NSFileSystemFreeSize] ?: @0}, @"maintenance-ready.json", YES);
        UIApplication.sharedApplication.idleTimerDisabled = YES;
        self.status.text = @"Ready to transfer game files.\n\nFollow the progress on your Mac. When copying finishes, run:\n\n./emu launch";
        return;
    }
    if ([mode isEqualToString:@"verify-resources"]) {
        UIApplication.sharedApplication.idleTimerDisabled = YES;
        self.status.text = @"Checking game files…\n\nKeep this app open.";
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
            NSDictionary *result = EmuVerifyResources(^(NSUInteger count, NSUInteger total, NSString *file) {
                SaveReport(@{@"checkedFiles":@(count), @"totalFiles":@(total)}, @"resource-check.json", NO);
                dispatch_async(dispatch_get_main_queue(), ^{
                    self.status.text = [NSString stringWithFormat:@"Checking game files: %lu / %lu\n\n%@", (unsigned long)count, (unsigned long)total, file.lastPathComponent];
                });
            });
            SaveReport(result, @"resource-check.json", YES);
            dispatch_async(dispatch_get_main_queue(), ^{
                UIApplication.sharedApplication.idleTimerDisabled = NO;
                self.status.text = [result[@"passed"] boolValue] ? @"All game files verified.\n\nRun ./emu launch on your Mac, then open the game." :
                    [NSString stringWithFormat:@"Some game files need copying.\n\nRun ./emu resources on your Mac.\n\n%@", result[@"errors"]];
            });
        });
        return;
    }
    CFRunLoopPerformBlock(CFRunLoopGetMain(), kCFRunLoopCommonModes, ^{
        if ([mode isEqualToString:@"check"]) {
            self.status.text = @"Checking SDL, graphics and touch controls…";
            RunSDLCheck(self.view.window, ^(NSDictionary *result, NSString *message) {
                SaveReport(result, @"sdl-check.json", YES);
                self.status.text = message;
            });
            return;
        }
        NSArray *missing = EmuMissingResources();
        if (missing.count) {
            self.status.text = [NSString stringWithFormat:@"Game files are not ready (%lu files).\n\nOn your Mac, run:\n./emu resources\n\nIf the files were copied earlier, check them with:\n./emu resources --verify", (unsigned long)missing.count];
            return;
        }
        NSDictionary *result = LaunchGame();
        [self.view.window makeKeyAndVisible];
        SaveReport(result, @"launch-error.json", YES);
        self.status.text = [NSString stringWithFormat:@"SnowRunner stopped.\n\n%@\n\nRun ./emu logs on your Mac for details.", result[@"error"] ?: result];
    });
    CFRunLoopWakeUp(CFRunLoopGetMain());
}
@end

@interface SceneDelegate : UIResponder <UIWindowSceneDelegate>
@property(nonatomic, strong) UIWindow *window;
@end
@implementation SceneDelegate
- (void)sceneDidBecomeActive:(UIScene *)scene { [(EmuController *)self.window.rootViewController start]; }
- (void)scene:(UIScene *)scene willConnectToSession:(UISceneSession *)session options:(UISceneConnectionOptions *)options {
    self.window = [[UIWindow alloc] initWithWindowScene:(UIWindowScene *)scene];
    self.window.rootViewController = [EmuController new];
    [self.window makeKeyAndVisible];
    UIWindowSceneGeometryPreferencesIOS *geometry = [[UIWindowSceneGeometryPreferencesIOS alloc] initWithInterfaceOrientations:UIInterfaceOrientationMaskLandscape];
    [(UIWindowScene *)scene requestGeometryUpdateWithPreferences:geometry errorHandler:^(NSError *error) { NSLog(@"Orientation: %@", error); }];
}
@end
@interface AppDelegate : UIResponder <UIApplicationDelegate> @end
@implementation AppDelegate
- (UISceneConfiguration *)application:(UIApplication *)application configurationForConnectingSceneSession:(UISceneSession *)session options:(UISceneConnectionOptions *)options {
    UISceneConfiguration *configuration = [[UISceneConfiguration alloc] initWithName:@"Default" sessionRole:session.role];
    configuration.delegateClass = SceneDelegate.class;
    return configuration;
}
@end
int main(int argc, char *argv[]) {
    @autoreleasepool { return UIApplicationMain(argc, argv, nil, NSStringFromClass(AppDelegate.class)); }
}

#define SDL_MAIN_HANDLED
#import "GameLauncher.h"
#include <SDL2/SDL.h>
#include <dlfcn.h>
#include <os/proc.h>
#include <mach/mach.h>
#include <fcntl.h>
#include <unistd.h>

static void Stage(NSString *text) {
    NSString *path = [NSHomeDirectory() stringByAppendingPathComponent:@"Documents/guest-load.log"];
    FILE *file = fopen(path.fileSystemRepresentation, "a");
    if (file) { fprintf(file, "%s\n", text.UTF8String); fclose(file); }
    NSLog(@"CLIENT_LOAD %@", text);
}

static void StartMemoryLog(void) {
    static dispatch_source_t timer;
    if (timer) return;
    NSString *path = [NSHomeDirectory() stringByAppendingPathComponent:@"Documents/game-memory.jsonl"];
    [NSData.data writeToFile:path atomically:YES];
    timer = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0,
                                   dispatch_get_global_queue(QOS_CLASS_UTILITY, 0));
    dispatch_source_set_timer(timer, DISPATCH_TIME_NOW, 2 * NSEC_PER_SEC, NSEC_PER_SEC / 4);
    dispatch_source_set_event_handler(timer, ^{
        @autoreleasepool {
            task_vm_info_data_t memory = {0};
            mach_msg_type_number_t count = TASK_VM_INFO_COUNT;
            if (task_info(mach_task_self(), TASK_VM_INFO, (task_info_t)&memory, &count) != KERN_SUCCESS) return;
            uint64_t available = os_proc_available_memory();
            FILE *file = fopen(path.fileSystemRepresentation, "a");
            if (file) {
                fprintf(file, "{\"time\":%.3f,\"pid\":%d,\"footprintBytes\":%llu,\"availableBytes\":%llu,\"estimatedBudgetBytes\":%llu}\n",
                        NSDate.date.timeIntervalSince1970, getpid(),
                        (unsigned long long)memory.phys_footprint, (unsigned long long)available,
                        (unsigned long long)(memory.phys_footprint + available));
                fclose(file);
            }
        }
    });
    dispatch_resume(timer);
}

NSDictionary *LaunchGame(void) {
    [NSData.data writeToFile:[NSHomeDirectory() stringByAppendingPathComponent:@"Documents/guest-load.log"] atomically:YES];
    Stage(@"START");
    NSMutableDictionary *result = [NSMutableDictionary dictionary];
    result[@"time"] = [[NSISO8601DateFormatter new] stringFromDate:NSDate.date];
    result[@"gameMainCalled"] = @NO;
    result[@"availableProcessMemoryBeforeBytes"] = @(os_proc_available_memory());
    if (getenv("EMU_DIAGNOSTICS")) StartMemoryLog();
    NSString *resources = [NSHomeDirectory() stringByAppendingPathComponent:@"Documents/SnowRunner/SnowRunner.app/Contents/Resources"];
    if (![NSFileManager.defaultManager changeCurrentDirectoryPath:resources]) {
        result[@"error"] = @"Cannot open the game resource directory.";
        return result;
    }
    setenv("SNOW_RESOURCE_ROOT", resources.fileSystemRepresentation, 1);
    NSString *console = [NSHomeDirectory() stringByAppendingPathComponent:@"Documents/guest-console.log"];
    int fd = open(console.fileSystemRepresentation, O_CREAT | O_TRUNC | O_WRONLY, 0600);
    if (fd >= 0) {
        dup2(fd, STDOUT_FILENO); dup2(fd, STDERR_FILENO); close(fd);
        setvbuf(stdout, NULL, _IONBF, 0);
        setvbuf(stderr, NULL, _IONBF, 0);
    }
    Stage(@"RESOURCE_ROOT_READY");
    NSString *frameworks = NSBundle.mainBundle.privateFrameworksPath;
    NSString *sdlBridge = [frameworks stringByAppendingPathComponent:@"SDLBridge.framework/SDLBridge"];
    setenv("SDL_DYNAMIC_API", sdlBridge.fileSystemRepresentation, 1);
    SDL_SetMainReady();
    SDL_SetHint(SDL_HINT_ORIENTATIONS, "LandscapeLeft LandscapeRight");
    SDL_SetHint(SDL_HINT_TOUCH_MOUSE_EVENTS, "1");

    for (NSString *name in @[@"MacCompat", @"SteamAPI", @"EOS", @"GameClient"]) {
        NSString *relative = [NSString stringWithFormat:@"%@.framework/%@", name, name];
        NSString *path = [frameworks stringByAppendingPathComponent:relative];
        Stage([@"DLOPEN " stringByAppendingString:name]);
        void *handle = dlopen(path.fileSystemRepresentation, RTLD_NOW | RTLD_LOCAL | RTLD_FIRST);
        result[name] = @(handle != NULL);
        if (!handle) {
            const char *error = dlerror();
            result[@"error"] = error ? @(error) : @"Unknown library loading error";
            Stage(result[@"error"]);
            return result;
        }
        Stage([@"LOADED " stringByAppendingString:name]);
        if ([name isEqualToString:@"GameClient"]) {
            int (*entry)(int, char **) = dlsym(handle, "main");
            result[@"gameMainFound"] = @(entry != NULL);
            Stage([NSString stringWithFormat:@"MAIN_FOUND %d", entry != NULL]);
            if (entry) {
                char program[] = "SnowRunner";
                char *arguments[] = {program, NULL};
                Stage(@"MAIN_CALL");
                result[@"gameMainCalled"] = @YES;
                int code = entry(1, arguments);
                void *bridge = dlopen(sdlBridge.fileSystemRepresentation, RTLD_NOW | RTLD_LOCAL | RTLD_NOLOAD);
                void (*hideControls)(void) = bridge ? dlsym(bridge, "SRHideMenuControls") : NULL;
                if (hideControls) hideControls();
                if (bridge) dlclose(bridge);
                result[@"gameMainReturnCode"] = @(code);
                Stage([NSString stringWithFormat:@"MAIN_RETURN %d", code]);
            }
        }
    }
    result[@"availableProcessMemoryAfterBytes"] = @(os_proc_available_memory());
    Stage(@"FINISHED");
    return result;
}

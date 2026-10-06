#import <Foundation/Foundation.h>

NSArray<NSDictionary *> *EmuResourceManifest(void);
NSString *EmuResourceRoot(void);
BOOL EmuCreateResourceDirectories(void);
NSArray<NSString *> *EmuMissingResources(void);
NSDictionary *EmuVerifyResources(void (^progress)(NSUInteger, NSUInteger, NSString *));
NSDictionary *EmuImportResources(NSURL *folder, void (^progress)(NSUInteger, NSUInteger, NSString *));

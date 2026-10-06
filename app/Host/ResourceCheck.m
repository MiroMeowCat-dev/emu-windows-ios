#import "ResourceCheck.h"
#import <CommonCrypto/CommonDigest.h>

NSArray<NSDictionary *> *EmuResourceManifest(void) {
    NSURL *url = [NSBundle.mainBundle URLForResource:@"resources" withExtension:@"json"];
    NSData *data = url ? [NSData dataWithContentsOfURL:url] : nil;
    NSDictionary *manifest = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
    if (![manifest[@"files"] isKindOfClass:NSArray.class]) return nil;
    return [manifest[@"files"] arrayByAddingObjectsFromArray:manifest[@"generated_files"] ?: @[]];
}

NSString *EmuResourceRoot(void) {
    return [NSHomeDirectory() stringByAppendingPathComponent:@"Documents/SnowRunner/SnowRunner.app/Contents/Resources"];
}

static NSString *ReceiptPath(void) {
    return [NSHomeDirectory() stringByAppendingPathComponent:@"Documents/emu-resources.json"];
}

static NSString *ResourcePath(NSString *relative) {
    if (![relative isKindOfClass:NSString.class] || !relative.length || relative.isAbsolutePath ||
        [relative.pathComponents containsObject:@".."] || [relative containsString:@"\\"] || [relative containsString:@":"])
        return nil;
    return [EmuResourceRoot() stringByAppendingPathComponent:relative];
}

BOOL EmuCreateResourceDirectories(void) {
    NSArray *manifest = EmuResourceManifest();
    if (!manifest.count) return NO;
    for (NSDictionary *item in manifest) {
        NSString *path = ResourcePath(item[@"path"]);
        if (!path || ![NSFileManager.defaultManager createDirectoryAtPath:path.stringByDeletingLastPathComponent
            withIntermediateDirectories:YES attributes:nil error:nil]) return NO;
    }
    return YES;
}

NSArray<NSString *> *EmuMissingResources(void) {
    NSData *data = [NSData dataWithContentsOfFile:ReceiptPath()];
    NSDictionary *receipt = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
    if (![receipt isKindOfClass:NSDictionary.class] || ![receipt[@"version"] isEqual:@1] ||
        ![receipt[@"files"] isKindOfClass:NSDictionary.class]) receipt = nil;
    NSMutableArray *missing = [NSMutableArray new];
    NSArray *manifest = EmuResourceManifest();
    if (!manifest.count) return @[@"Bundled resource manifest"];
    for (NSDictionary *item in manifest) {
        NSString *relative = item[@"path"], *path = ResourcePath(relative);
        NSDictionary *attributes = path ? [NSFileManager.defaultManager attributesOfItemAtPath:path error:nil] : nil;
        NSDictionary *saved = receipt[@"files"][relative];
        if (![saved isKindOfClass:NSDictionary.class]) saved = nil;
        if (!attributes || [attributes[NSFileSize] unsignedLongLongValue] != [item[@"bytes"] unsignedLongLongValue] ||
            ![saved[@"sha256"] isEqual:item[@"sha256"]] || ![saved[@"bytes"] isEqual:item[@"bytes"]]) [missing addObject:relative];
    }
    return missing;
}

static NSString *FileHash(NSString *path) {
    NSInputStream *stream = [NSInputStream inputStreamWithFileAtPath:path];
    if (!stream) return nil;
    [stream open];
    CC_SHA256_CTX context;
    CC_SHA256_Init(&context);
    uint8_t buffer[64 * 1024];
    NSInteger count;
    while ((count = [stream read:buffer maxLength:sizeof(buffer)]) > 0) CC_SHA256_Update(&context, buffer, (CC_LONG)count);
    [stream close];
    if (count < 0) return nil;
    uint8_t digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256_Final(digest, &context);
    NSMutableString *hex = [NSMutableString new];
    for (NSUInteger i = 0; i < sizeof(digest); ++i) [hex appendFormat:@"%02x", digest[i]];
    return hex;
}

NSDictionary *EmuVerifyResources(void (^progress)(NSUInteger, NSUInteger, NSString *)) {
    NSArray *manifest = EmuResourceManifest();
    NSMutableArray *errors = [NSMutableArray new];
    NSMutableDictionary *files = [NSMutableDictionary new];
    NSUInteger checked = 0;
    if (!manifest.count) [errors addObject:@"Bundled resource manifest is missing"];
    for (NSDictionary *item in manifest) {
        @autoreleasepool {
            NSString *relative = item[@"path"], *path = ResourcePath(relative);
            NSDictionary *attributes = path ? [NSFileManager.defaultManager attributesOfItemAtPath:path error:nil] : nil;
            if (!attributes || [attributes[NSFileSize] unsignedLongLongValue] != [item[@"bytes"] unsignedLongLongValue]) {
                [errors addObject:[@"Missing or wrong size: " stringByAppendingString:relative]];
            } else if (![FileHash(path) isEqual:item[@"sha256"]]) {
                [errors addObject:[@"Checksum mismatch: " stringByAppendingString:relative]];
            } else {
                files[relative] = @{@"bytes":item[@"bytes"], @"sha256":item[@"sha256"]};
            }
            ++checked;
            if (progress) progress(checked, manifest.count, relative);
        }
    }
    NSError *error = nil;
    NSData *receipts = [NSJSONSerialization dataWithJSONObject:@{@"version":@1, @"files":files} options:0 error:&error];
    if (!receipts || ![receipts writeToFile:ReceiptPath() options:NSDataWritingAtomic error:&error])
        [errors addObject:error.localizedDescription ?: @"Cannot save resource receipts"];
    return @{@"passed":@(errors.count == 0), @"errors":errors, @"checkedFiles":@(checked), @"totalFiles":@(manifest.count)};
}

static BOOL CopyVerifiedResource(NSString *source, NSString *destination, NSDictionary *item, NSError **error) {
    NSFileManager *manager = NSFileManager.defaultManager;
    NSString *partial = [destination.stringByDeletingLastPathComponent stringByAppendingPathComponent:
                         [NSString stringWithFormat:@".emu-%@.partial", NSUUID.UUID.UUIDString]];
    BOOL copied = NO;
    if ([item[@"text"] isKindOfClass:NSString.class]) {
        NSData *text = [item[@"text"] dataUsingEncoding:NSUTF8StringEncoding];
        copied = [text writeToFile:partial options:0 error:error];
    } else {
        NSFileCoordinator *coordinator = [[NSFileCoordinator alloc] initWithFilePresenter:nil];
        __block NSError *copyError = nil;
        __block BOOL success = NO;
        [coordinator coordinateReadingItemAtURL:[NSURL fileURLWithPath:source] options:0 error:error
                                    byAccessor:^(NSURL *url) {
            success = [manager copyItemAtURL:url toURL:[NSURL fileURLWithPath:partial] error:&copyError];
        }];
        copied = success;
        if (!copied && error && !*error) *error = copyError;
    }
    NSDictionary *attributes = copied ? [manager attributesOfItemAtPath:partial error:error] : nil;
    if (!attributes || ![attributes[NSFileSize] isEqual:item[@"bytes"]] || ![FileHash(partial) isEqual:item[@"sha256"]]) {
        [manager removeItemAtPath:partial error:nil];
        return NO;
    }
    BOOL committed;
    if ([manager fileExistsAtPath:destination]) {
        committed = [manager replaceItemAtURL:[NSURL fileURLWithPath:destination]
                               withItemAtURL:[NSURL fileURLWithPath:partial] backupItemName:nil
                                     options:0 resultingItemURL:nil error:error];
    } else {
        committed = [manager moveItemAtPath:partial toPath:destination error:error];
    }
    if (!committed) [manager removeItemAtPath:partial error:nil];
    return committed;
}

NSDictionary *EmuImportResources(NSURL *folder, void (^progress)(NSUInteger, NSUInteger, NSString *)) {
    NSArray *manifest = EmuResourceManifest();
    NSMutableArray *errors = [NSMutableArray new];
    NSData *receiptData = [NSData dataWithContentsOfFile:ReceiptPath()];
    NSDictionary *receipt = receiptData ? [NSJSONSerialization JSONObjectWithData:receiptData options:0 error:nil] : nil;
    NSDictionary *previous = [receipt isKindOfClass:NSDictionary.class] && [receipt[@"version"] isEqual:@1] &&
                            [receipt[@"files"] isKindOfClass:NSDictionary.class] ? receipt[@"files"] : @{};
    NSMutableDictionary *files = [previous mutableCopy];
    if (!manifest.count || !EmuCreateResourceDirectories()) {
        return @{@"passed":@NO, @"errors":@[@"Cannot create resource directories"], @"checkedFiles":@0};
    }
    NSUInteger checked = 0;
    for (NSDictionary *item in manifest) {
        @autoreleasepool {
            NSString *relative = item[@"path"], *destination = ResourcePath(relative);
            NSError *error = nil;
            if (!destination) {
                [errors addObject:@"Invalid bundled resource path"];
                break;
            }
            NSDictionary *attributes = [NSFileManager.defaultManager attributesOfItemAtPath:destination error:nil];
            // Rehash existing files instead of relying on old receipts. This also
            // resumes correctly after the app is interrupted during import.
            BOOL ready = [attributes[NSFileSize] isEqual:item[@"bytes"]] && [FileHash(destination) isEqual:item[@"sha256"]];
            if (!ready) {
                [files removeObjectForKey:relative];
                NSData *invalidated = [NSJSONSerialization dataWithJSONObject:@{@"version":@1, @"files":files} options:0 error:&error];
                if (!invalidated || ![invalidated writeToFile:ReceiptPath() options:NSDataWritingAtomic error:&error]) {
                    [errors addObject:error.localizedDescription ?: @"Cannot invalidate resource receipt"];
                    break;
                }
                NSDictionary *disk = [NSFileManager.defaultManager attributesOfFileSystemForPath:NSHomeDirectory() error:&error];
                if (!disk || [disk[NSFileSystemFreeSize] unsignedLongLongValue] < [item[@"bytes"] unsignedLongLongValue] + 64 * 1024 * 1024) {
                    [errors addObject:@"Not enough iPhone storage for the next resource file"];
                    break;
                }
                NSString *source = [[folder.path stringByAppendingPathComponent:@"Resources"] stringByAppendingPathComponent:relative];
                ready = CopyVerifiedResource(source, destination, item, &error);
            }
            if (!ready) {
                [errors addObject:[NSString stringWithFormat:@"%@: %@", relative, error.localizedDescription ?: @"Missing file or checksum mismatch"]];
                break;
            }
            files[relative] = @{@"bytes":item[@"bytes"], @"sha256":item[@"sha256"]};
            NSData *saved = [NSJSONSerialization dataWithJSONObject:@{@"version":@1, @"files":files} options:0 error:&error];
            if (!saved || ![saved writeToFile:ReceiptPath() options:NSDataWritingAtomic error:&error]) {
                [errors addObject:error.localizedDescription ?: @"Cannot save resource receipt"];
                break;
            }
            ++checked;
            if (progress) progress(checked, manifest.count, relative);
        }
    }
    return @{@"passed":@(errors.count == 0), @"errors":errors, @"checkedFiles":@(checked), @"totalFiles":@(manifest.count)};
}

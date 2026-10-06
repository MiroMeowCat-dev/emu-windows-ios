"""Validate local game libraries, retarget copies, and build native adapters."""
import json
import plistlib
import re
import shutil
import struct
import tempfile
from pathlib import Path

from .common import BUILD, ROOT, UserError, fingerprint, read_json, run, sdk_path, sha256, write_json, toolchain_key
from .macho import commands, sections, code_hash, string_command, replace_commands, verify_fingerprint, patch_instructions
from .sdl import ensure_sdl
from .source import game_metadata, validated_binary

ROUTED = {"Cocoa", "AppKit", "Carbon", "ForceFeedback", "CoreServices", "CoreGraphics", "CoreVideo", "IOKit", "Metal", "Foundation", "AudioUnit"}
VENDOR = BUILD / "Vendor"
GENERATED = BUILD / "generated"
COMPAT = ROOT / "app/Compat"


def framework_info(directory, name):
    directory.mkdir(parents=True, exist_ok=True)
    info = {"CFBundleIdentifier": "local.emu." + name.lower(), "CFBundleExecutable": name,
            "CFBundleName": name, "CFBundlePackageType": "FMWK", "CFBundleVersion": "1",
            "CFBundleShortVersionString": "0.1", "MinimumOSVersion": "17.0",
            "CFBundleSupportedPlatforms": ["iPhoneOS"]}
    (directory / "Info.plist").write_bytes(plistlib.dumps(info))


def validate_game(game, directory):
    manifest = read_json(ROOT / "data/supported-game.json")
    game_metadata(game, manifest)
    prepared = []
    for entry in manifest["binaries"]:
        data = validated_binary(game, entry)
        target = directory / entry["framework"]
        target.write_bytes(data)
        prepared.append((entry, target))
    return manifest, prepared


def retarget(data, name):
    updated, rpath_added, changed = [], False, []
    for kind, offset, command in commands(data):
        if kind == 0x32:
            if struct.unpack_from("<I", command, 8)[0] != 1:
                raise UserError("Expected an original macOS library.")
            struct.pack_into("<III", command, 8, 2, 17 << 16, 27 << 16)
        # Preserve the shipped Steam API's other load commands exactly.
        if name == "SteamAPI":
            updated.append(command)
            continue
        if kind == 0xD:
            command = string_command(kind, command[8:24], "@rpath/{0}.framework/{0}".format(name))
        if kind in (0xC, 0x80000018, 0x8000001F):
            at = struct.unpack_from("<I", command, 8)[0]
            old = command[at:].split(b"\0")[0].decode()
            new = re.sub(r"/Versions/[^/]+/", "/", old)
            framework = next((x for x in ROUTED if "/{}.framework/".format(x) in old), None)
            if framework or old == "/usr/lib/libSystem.B.dylib":
                route = "Compat" + (framework or "System")
                new = "@rpath/{0}.framework/{0}".format(route)
            elif old == "/usr/lib/libcurl.4.dylib":
                # The pinned binary has no curl imports. Preserve its ordinal
                # slot with an existing library, without inventing curl APIs.
                new = "@rpath/MacCompat.framework/MacCompat"
            elif old.endswith("libEOSSDK-Mac-Shipping.dylib"):
                new = "@rpath/EOS.framework/EOS"
            elif old.endswith("libsteam_api.dylib"):
                new = "@rpath/SteamAPI.framework/SteamAPI"
            command = string_command(kind, command[8:24], new)
            if new != old:
                changed.append([old, new])
        if kind == 0x8000001C:
            if rpath_added:
                continue
            command = string_command(kind, struct.pack("<I", 12), "@loader_path/..")
            rpath_added = True
        updated.append(command)
    replace_commands(data, updated)
    names = {}
    if name != "SteamAPI":
        for section, offset, size in sections(data):
            if section == "__objc_classname":
                for raw in bytes(data[offset:offset + size]).split(b"\0"):
                    if raw.startswith(b"SDL"):
                        names[raw] = b"SRM" + raw[3:]
                    elif raw.startswith(b"METAL_"):
                        names[raw] = b"SRMTL_" + raw[6:]
        # Include string-based class lookups, not just the ObjC name section.
        # Whole-file fingerprints restrict this operation to the verified build.
        for old, new in names.items():
            data = data.replace(old, new)
    return data, changed


def patch_library(entry, unsigned_data, manifest):
    """Shared conversion, guarded by the upstream prepared file fingerprints."""
    data, changes = retarget(bytearray(unsigned_data), entry["framework"])
    if code_hash(data) != entry["original_text_sha256"]:
        raise UserError("Metadata conversion unexpectedly changed CPU instructions.")
    if entry["framework"] == "GameClient":
        for patch in manifest["config_patches"]:
            offset = int(patch["offset"], 0)
            old, new = (patch["old"] + "\0").encode(), (patch["new"] + "\0").encode()
            if len(old) != len(new) or data.count(old) != 1 or data[offset:offset + len(old)] != old:
                raise UserError("Unexpected Steam configuration binding; no output was written.")
            data[offset:offset + len(old)] = new
        patch_instructions(data, manifest["instruction_patches"])
    if code_hash(data) != entry["prepared_text_sha256"]:
        raise UserError("Prepared CPU-code hash mismatch; no output was written.")
    verify_fingerprint(data, entry["prepared_arm64_sha256"], entry["framework"] + " prepared")
    return data, {"framework": entry["framework"], "text_sha256": code_hash(data), "changed_library_paths": changes}


def prepare_library(entry, path, manifest):
    run(["codesign", "--remove-signature", path], capture=True)
    data, report = patch_library(entry, path.read_bytes(), manifest)
    path.write_bytes(data)
    path.chmod(0o755)
    return report


def build_compatibility(sdk):
    symbols = {x["symbol"]: x for x in read_json(ROOT / "data/desktop-symbols.json")}
    implemented = set(re.findall(r"\b(CG\w+)\s*\(", (COMPAT / "Displays.m").read_text()))
    source = (ROOT / "tools/unsupported-template.m").read_text().splitlines()
    aliases = []
    classes = sorted({s.split("$_", 1)[1] for s in symbols if s.startswith("_OBJC_")})
    for name in classes:
        if name not in {"NSScreen", "NSApplication"}:
            source += ["@interface SR{} : SRMissingDesktopObject @end".format(name), "@implementation SR{} @end".format(name)]
        for kind in ["CLASS", "METACLASS"]:
            aliases.append("-Wl,-alias,_OBJC_{0}_$_SR{1},_OBJC_{0}_$_{1}".format(kind, name))
    for index, (symbol, item) in enumerate(sorted(symbols.items())):
        if symbol.startswith("_OBJC_") or symbol in ["dyld_stub_binder", "_AudioUnitSetProperty", "_NSApp"] or symbol[1:] in implemented:
            continue
        assembler = json.dumps(symbol)
        if symbol == "_NSAppKitVersionNumber":
            source.append("double sr_appkit_version __asm__(%s) = 0.0;" % assembler)
        elif (symbol.startswith("_NS") and symbol != "_NSRectFill") or symbol.startswith("_k"):
            source.append("NSString *const sr_constant_%d __asm__(%s) = @%s;" % (index, assembler, json.dumps(item["value"])))
        elif symbol == "_syslog$DARWIN_EXTSN":
            source += ['void sr_syslog(int priority, const char *format, ...) __asm__(%s);' % assembler,
                       'void sr_syslog(int priority, const char *format, ...) { va_list args; va_start(args, format); vsyslog(priority, format, args); va_end(args); }']
        else:
            source += ['void sr_missing_%d(void) __asm__(%s) __attribute__((noreturn));' % (index, assembler),
                       'void sr_missing_%d(void) { Stop(%s, __builtin_return_address(0)); }' % (index, assembler)]
    GENERATED.mkdir(parents=True, exist_ok=True)
    provider = GENERATED / "MacLoadDiagnostics.m"
    provider.write_text("\n".join(source) + "\n")
    target = VENDOR / "MacCompat.framework"
    framework_info(target, "MacCompat")
    args = ["xcrun", "clang", "-target", "arm64-apple-ios17.0", "-isysroot", sdk, "-fobjc-arc", "-O0", "-dynamiclib", provider]
    args += [COMPAT / name for name in ["Displays.m", "MetalDeviceInfo.m", "Application.m", "MetalPresentation.m", "FileDiagnostics.c"]]
    args += ["-framework", "QuartzCore", "-Wl,-install_name,@rpath/MacCompat.framework/MacCompat", "-o", target / "MacCompat"]
    for name in ["Foundation", "CoreFoundation", "UIKit", "CoreGraphics", "CoreVideo", "Metal", "IOKit", "AudioToolbox", "MobileCoreServices"]:
        args.append("-Wl,-reexport_framework," + name)
    args += ["-Wl,-reexport_library," + str(sdk / "usr/lib/libSystem.tbd")] + aliases
    run(args, log=BUILD / "logs/compat-build.log")
    route_source = GENERATED / "FrameworkRoute.c"
    route_source.write_text("/* Re-export the verified compatibility provider. */\n")
    for original in sorted(ROUTED | {"System"}):
        name = "Compat" + original
        target = VENDOR / (name + ".framework")
        framework_info(target, name)
        run(["xcrun", "clang", "-target", "arm64-apple-ios17.0", "-isysroot", sdk, "-dynamiclib", route_source,
             "-F", VENDOR, "-Wl,-reexport_framework,MacCompat", "-Wl,-install_name,@rpath/{0}.framework/{0}".format(name),
             "-o", target / name], log=BUILD / "logs" / (name + ".log"))


def missing_game_exports(source, symbols):
    requested = set(re.findall(r'\b(?:dlsym|GameSymbol)\s*\(\s*game\s*,\s*"([^"]+)"\s*\)', source))
    exported = set()
    for line in symbols.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[-2].isupper() and fields[-2] != "U":
            exported.add(fields[-1].removeprefix("_"))
    return sorted(requested - exported)


def build_bridge(sdk, verify_game=True):
    # Check the actual external symbol table, not debug names that dlsym cannot
    # resolve. The game-state adapter must also work in a signed release image.
    source = "\n".join(path.read_text() for path in COMPAT.iterdir() if path.suffix in {".c", ".m"})
    if verify_game:
        symbols = run(["xcrun", "nm", "-gU", VENDOR / "GameClient.framework/GameClient"], capture=True)
        missing = missing_game_exports(source, symbols)
        if missing:
            raise UserError("The game-state adapter requires unavailable exports: " + ", ".join(missing))
    target = VENDOR / "SDLBridge.framework"
    framework_info(target, "SDLBridge")
    args = ["xcrun", "clang", "-target", "arm64-apple-ios17.0", "-isysroot", sdk, "-O2", "-fobjc-arc", "-F", VENDOR]
    for name in ["UIKit", "SDL2", "CoreGraphics", "QuartzCore", "GameController"]:
        args += ["-framework", name]
    args += ["-dynamiclib"] + [COMPAT / n for n in ["SDLBridge.m", "GameContext.c", "MenuControls.m", "TouchInput.m"]]
    args += ["-Wl,-install_name,@rpath/SDLBridge.framework/SDLBridge", "-o", target / "SDLBridge"]
    run(args, log=BUILD / "logs/bridge-build.log")


def build_adapters():
    key = preparation_key()
    print("Building native compatibility libraries...")
    sdk = sdk_path()
    build_compatibility(sdk)
    build_bridge(sdk)
    outputs = {str(p.relative_to(BUILD)): sha256(p)
               for p in VENDOR.rglob("*") if p.is_file()}
    if preparation_key() != key:
        raise UserError("Adapter sources changed during the build. Run ./emu build again after editing finishes.")
    write_json(BUILD / "prepared.json", {"key": key, "outputs": outputs})


def prepare(game):
    game = Path(game)
    BUILD.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="game-", dir=BUILD) as temporary:
        manifest, binaries = validate_game(game, Path(temporary))
        print("Game: all three ARM64 libraries match the supported build.")
        ensure_sdl()
        marker = BUILD / "prepared.json"
        if prepared_current():
            print("Adapters: prepared frameworks are current.")
            return
        if marker.exists():
            marker.unlink()
        # All inputs were validated before the first output replacement.
        reports = []
        for entry, path in binaries:
            reports.append(prepare_library(entry, path, manifest))
        VENDOR.mkdir(parents=True, exist_ok=True)
        for entry, path in binaries:
            target = VENDOR / (entry["framework"] + ".framework")
            framework_info(target, entry["framework"])
            shutil.copy2(path, target / entry["framework"])
        write_json(BUILD / "reports/binary-check.json", reports)
        build_adapters()
        print("Prepared frameworks in build/Vendor.")


def prepared_current():
    marker = BUILD / "prepared.json"
    sdl = VENDOR / "SDL2.framework/SDL2"
    if not marker.exists() or not sdl.exists():
        return False
    saved = read_json(marker)
    key = preparation_key()
    outputs = saved.get("outputs", {})
    return saved.get("key") == key and bool(outputs) and all((BUILD / p).is_file() and sha256(BUILD / p) == h for p, h in outputs.items())


def preparation_key():
    inputs = [p for p in COMPAT.iterdir() if p.suffix in {".m", ".c", ".h", ".inc"}]
    inputs += [ROOT / "tools" / name for name in ["prepare.py", "macho.py", "source.py", "sdl.py", "common.py", "unsupported-template.m"]]
    inputs += [ROOT / "data" / name for name in ["supported-game.json", "desktop-symbols.json", "sdl.json"]]
    inputs += [ROOT / "patches/sdl2-ios.patch"]
    return fingerprint(inputs) + toolchain_key() + sha256(VENDOR / "SDL2.framework/SDL2")


def cached_game_is_valid():
    for item in read_json(ROOT / "data/supported-game.json")["binaries"]:
        path = VENDOR / (item["framework"] + ".framework") / item["framework"]
        if not path.is_file() or sha256(path) != item["prepared_arm64_sha256"]:
            return False
    return True


def ensure_prepared(game):
    if prepared_current():
        return
    if not cached_game_is_valid():
        prepare(game)
        return
    # Rebuild our adapters without needing to extract the proprietary libraries
    # again. This also allows re-signing after Steam updates or removes the game.
    print("Using verified prepared game libraries; refreshing native adapters...")
    marker = BUILD / "prepared.json"
    if marker.exists():
        marker.unlink()
    ensure_sdl()
    # Recreate metadata too, so a missing Info.plist is recoverable from cache.
    for item in read_json(ROOT / "data/supported-game.json")["binaries"]:
        framework_info(VENDOR / (item["framework"] + ".framework"), item["framework"])
    build_adapters()

"""Build ONLY the open-source iOS runtime on an Apple-hosted macOS runner."""
import json
import os
import platform
import plistlib
import shutil
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .common import BUILD, ROOT, UserError, run, sdk_path, sha256
from .prepare import VENDOR, build_bridge, build_compatibility
from .sdl import ensure_sdl
from .windows import APP_ROOT, CORE_FRAMEWORKS, contract_key, inspect_runtime, zip_app


def build_runtime(output=None):
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise UserError("Public iOS runtime compilation requires a macOS ARM64 runner. Use the included GitHub Actions workflow.")
    version = run(["xcrun", "--sdk", "iphoneos", "--show-sdk-version"], capture=True)
    if int(version.split(".")[0]) < 27:
        raise UserError("This upstream build targets SDK 27. Select the xcode-27 runner or Xcode 27 locally.")
    output = Path(output).resolve() if output else BUILD / "releases/emu-ios-runtime.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    start_key = contract_key()
    ensure_sdl()
    sdk = sdk_path()
    build_compatibility(sdk)
    # No game is uploaded or fabricated. The pinned input/output SHA checks in
    # Windows assembly bind the bridge to the same originally audited game build.
    build_bridge(sdk, verify_game=False)
    with tempfile.TemporaryDirectory(prefix=".emu-runtime-", dir=output.parent) as directory:
        directory = Path(directory)
        app = directory / APP_ROOT
        app.mkdir(parents=True)
        arguments = ["xcrun", "clang", "-target", "arm64-apple-ios17.0", "-isysroot", sdk,
                     "-O2", "-fobjc-arc", "-fmodules", "-F", VENDOR]
        arguments += [ROOT / "app/Host" / name for name in ["main.m", "GameLauncher.m", "SDLCheck.m", "ResourceCheck.m"]]
        for name in ["UIKit", "Foundation", "CoreFoundation", "Metal", "QuartzCore", "SDL2", "UniformTypeIdentifiers"]:
            arguments += ["-framework", name]
        arguments += ["-Wl,-rpath,@executable_path/Frameworks", "-o", app / "SnowRunner"]
        run(arguments, log=BUILD / "logs/runtime-host.log")
        # Ad-hoc signing requires no account/certificate and carries the memory
        # request for downstream Windows signers. It is not installable signing.
        run(["codesign", "--force", "--sign", "-", "--entitlements", ROOT / "app/Host/Memory.entitlements",
             app / "SnowRunner"], capture=True)
        info = plistlib.loads((ROOT / "app/Host/Info.plist").read_bytes())
        info.update(CFBundleExecutable="SnowRunner", CFBundleIdentifier="local.emu.snowrunner",
                    CFBundleName="SnowRunner", MinimumOSVersion="17.0", UIDeviceFamily=[1, 2],
                    CFBundleSupportedPlatforms=["iPhoneOS"], DTPlatformName="iphoneos",
                    DTSDKName="iphoneos" + version, EmuWindowsMenu=True, EmuDiagnosticOnly=True)
        (app / "Info.plist").write_bytes(plistlib.dumps(info))
        shutil.copy2(ROOT / "data/resources.json", app / "resources.json")
        shutil.copy2(ROOT / "app/Host/Memory.entitlements", app / "Memory.entitlements")
        shutil.copy2(ROOT / "LICENSE", app / "EMU-LICENSE.txt")
        shutil.copy2(ROOT / "third_party/SDL-LICENSE.txt", app / "SDL-LICENSE.txt")
        for name in sorted(CORE_FRAMEWORKS):
            # Dereference framework links in the public bundle for portable ZIPs.
            shutil.copytree(VENDOR / (name + ".framework"), app / "Frameworks" / (name + ".framework"))
        if contract_key() != start_key:
            raise UserError("Runtime source files changed during compilation; rebuild after editing finishes.")
        files = {path.relative_to(directory).as_posix(): {"bytes": path.stat().st_size, "sha256": sha256(path)}
                 for path in sorted(app.rglob("*")) if path.is_file()}
        manifest = {"format_version": 1, "contract_key": start_key, "files": files,
                    "sdk": version, "xcode": run(["xcodebuild", "-version"], capture=True),
                    "source_commit": os.environ.get("GITHUB_SHA", ""), "includes_game_content": False,
                    "signing_state": "unsigned", "device_tested": False}
        result = directory / "runtime.zip"
        zip_app(directory, result)
        with ZipFile(result, "a", compression=ZIP_DEFLATED) as archive:
            archive.writestr("runtime.json", json.dumps(manifest, indent=2).encode("utf-8"))
        inspect_runtime(result)
        result.replace(output)
    print("Public runtime: " + str(output))
    print("SHA-256: " + sha256(output))
    return output


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    try:
        build_runtime(parser.parse_args().output)
    except (UserError, OSError) as error:
        parser.exit(1, str(error) + "\n")

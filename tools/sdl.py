"""Fetch and build the exact SDL source used by the experiment."""
from pathlib import Path
import shutil
import tarfile

from .common import BUILD, ROOT, UserError, fingerprint, read_json, run, sha256, write_json, toolchain_key


def safe_extract(archive, destination):
    destination = Path(destination).resolve()
    with tarfile.open(archive) as source:
        members = source.getmembers()
        for member in members:
            target = (destination / member.name).resolve()
            if not target.is_relative_to(destination):
                raise UserError("Archive path escapes the SDL directory: " + member.name)
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise UserError("Unsupported archive entry: " + member.name)
            if member.issym() or member.islnk():
                link = (target.parent / member.linkname if member.issym() else destination / member.linkname).resolve()
                if not link.is_relative_to(destination):
                    raise UserError("Archive link escapes the SDL directory: " + member.name)
        source.extractall(destination)


def ensure_sdl():
    pin = read_json(ROOT / "data/sdl.json")
    patch = ROOT / "patches/sdl2-ios.patch"
    key = fingerprint([ROOT / "data/sdl.json", patch, Path(__file__), ROOT / "tools/common.py"]) + toolchain_key()
    marker = BUILD / "sdl-built.json"
    target = BUILD / "Vendor/SDL2.framework"
    if marker.exists() and target.joinpath("SDL2").exists():
        saved = read_json(marker)
        outputs = saved.get("outputs", {})
        if saved.get("key") == key and outputs and all(
                (target / path).is_file() and sha256(target / path) == value
                for path, value in outputs.items()):
            print("SDL: prepared framework is current.")
            return
    archive = BUILD / "downloads" / (pin["directory"] + ".tar.gz")
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists() or sha256(archive) != pin["sha256"]:
        print("Downloading SDL {} from its official release...".format(pin["version"]))
        partial = archive.with_suffix(".download")
        run(["curl", "--fail", "--location", "--retry", "3", "--output", partial, pin["url"]])
        if sha256(partial) != pin["sha256"]:
            partial.unlink()
            raise UserError("SDL archive checksum mismatch. Nothing was extracted or built.")
        partial.replace(archive)
    source_root = BUILD / "sdl-source"
    if source_root.exists():
        shutil.rmtree(source_root)
    source_root.mkdir(parents=True)
    safe_extract(archive, source_root)
    source = source_root / pin["directory"]
    run(["patch", "-p1", "--batch", "--input", patch], cwd=source, log=BUILD / "logs/sdl-patch.log")
    print("Building native SDL for iOS (first build takes a few minutes)...")
    run(["xcodebuild", "-project", source / "Xcode/SDL/SDL.xcodeproj", "-scheme", "Framework-iOS",
         "-configuration", "Release", "-sdk", "iphoneos", "-destination", "generic/platform=iOS",
         "-derivedDataPath", BUILD / "sdl-derived", "CODE_SIGNING_ALLOWED=NO",
         "ARCHS=arm64", "IPHONEOS_DEPLOYMENT_TARGET=17.0", "build"], log=BUILD / "logs/sdl-build.log")
    product = BUILD / "sdl-derived/Build/Products/Release-iphoneos/SDL2.framework"
    symbols = run(["xcrun", "nm", "-gU", product / "SDL2"], capture=True)
    if "_SDL_SendVirtualKeyboardKey" not in symbols:
        raise UserError("The SDL virtual-keyboard export is missing; check the SDL patch log.")
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(product, target, symlinks=True)
    outputs = {str(path.relative_to(target)): sha256(path)
               for path in target.rglob("*") if path.is_file()}
    write_json(marker, {"key": key, "outputs": outputs})

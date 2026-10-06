"""Create a portable source toolkit from an allowlist, without games or settings."""
import hashlib
import json
from pathlib import Path
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .common import BUILD, ROOT, UserError, sha256


FILES = ["emu", "emu.cmd", "emu-windows.cmd", "emu_windows.py", ".gitignore", "README.md", "LICENSE", "config.example.json",
         "Config/Base.xcconfig", "Config/Local.xcconfig.example",
         "data/supported-game.json", "data/resources.json", "data/desktop-symbols.json", "data/sdl.json",
         "patches/sdl2-ios.patch", "third_party/SDL-LICENSE.txt",
         "docs/ROADMAP-zh.md", "docs/QUICKSTART-zh.md", "docs/WINDOWS-zh.md", ".github/workflows/windows-runtime.yml"]
PATTERNS = ["tools/*.py", "tools/unsupported-template.m", "app/Host/*.m", "app/Host/*.h",
            "app/Host/*.plist", "app/Host/*.entitlements", "app/Compat/*.m", "app/Compat/*.h",
            "app/Compat/*.c", "app/Compat/*.inc", "tests/test_*.py", "tests/touch_pointer.c",
            "SnowRunner.xcodeproj/project.pbxproj", "SnowRunner.xcodeproj/xcshareddata/xcschemes/*.xcscheme"]


def toolkit_sources(root):
    root = Path(root).resolve()
    paths = {root / name for name in FILES}
    for pattern in PATTERNS:
        paths.update(root.glob(pattern))
    if any(not path.is_file() for path in paths):
        raise UserError("Toolkit sources are incomplete; use the full project checkout.")
    if any(not path.resolve().is_relative_to(root) for path in paths):
        raise UserError("Toolkit sources cannot link outside the project checkout.")
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix())


def toolkit(output=None):
    root = ROOT.resolve()
    destination = (Path(output).expanduser() if output else BUILD / "releases/emu-toolkit.zip").resolve()
    if destination.suffix.lower() != ".zip":
        raise UserError("The toolkit output must have a .zip extension.")
    sources = toolkit_sources(root)
    entries = {path.relative_to(root).as_posix(): path.read_bytes() for path in sources}
    manifest = {"format_version": 1, "includes_game_content": False, "includes_personal_settings": False,
                "files": [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                          for name, data in entries.items()]}
    entries["toolkit-manifest.json"] = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".emu-toolkit-", dir=destination.parent) as directory:
        temporary = Path(directory) / "toolkit.zip"
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
            for name, data in entries.items():
                info = ZipInfo("emu-toolkit/" + name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (0o100755 if name == "emu" else 0o100644) << 16
                info.compress_type = ZIP_DEFLATED
                archive.writestr(info, data)
        with ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise UserError("Toolkit archive failed its integrity check.")
        temporary.replace(destination)
    print("Portable source toolkit: " + str(destination))
    print("SHA-256: " + sha256(destination))
    return destination

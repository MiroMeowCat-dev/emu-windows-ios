"""Portable, read-only input classification before the Mac-only build workflow."""
import plistlib
import struct
from pathlib import Path

from .common import ROOT, UserError, read_json


PE_MACHINES = {0x014C: "x86", 0x8664: "x86-64", 0xAA64: "ARM64"}


def inspect_input(path):
    path = Path(path).expanduser()
    if path.is_dir():
        info_path = path / "Contents/Info.plist"
        if path.suffix.lower() != ".app" or not info_path.is_file():
            raise UserError("Expected a macOS .app with Contents/Info.plist: " + str(path))
        try:
            info = plistlib.loads(info_path.read_bytes())
        except (OSError, ValueError) as error:
            raise UserError("Cannot read app metadata: " + str(error)) from error
        manifest = read_json(ROOT / "data/supported-game.json")
        name = info.get("CFBundleName") or path.stem
        version = info.get("CFBundleShortVersionString", "unknown")
        build = info.get("CFBundleVersion", "unknown")
        print("macOS app: {} ({} / {})".format(name, version, build))
        if path.stem == "SnowRunner" and (version, build) == (manifest["version"], manifest["bundle_version"]):
            print("Version metadata matches the supported SnowRunner build.")
            print('Run python emu preflight --game "{}" to validate ARM64 binaries and resource sizes.'.format(path))
        else:
            print("This app is not the pinned SnowRunner build. It needs a separate compatibility port.")
        return
    if not path.is_file():
        raise UserError("Input not found: " + str(path))
    with path.open("rb") as stream:
        header = stream.read(64)
        if header[:2] == b"MZ" and len(header) >= 64:
            stream.seek(struct.unpack_from("<I", header, 60)[0])
            signature = stream.read(6)
            if len(signature) < 6 or signature[:4] != b"PE\0\0":
                raise UserError("The file has an MZ header but no valid PE header.")
            machine = struct.unpack_from("<H", signature, 4)[0]
            print("Windows PE executable: " + PE_MACHINES.get(machine, "machine 0x{:04x}".format(machine)))
            print("This project cannot run Windows executables. It requires the pinned macOS ARM64 SnowRunner.app.")
            return
        if header[:4] == b"\xcf\xfa\xed\xfe" and len(header) >= 8:
            cpu = struct.unpack_from("<I", header, 4)[0]
            print("Mach-O executable: " + ("ARM64" if cpu == 0x0100000C else "CPU 0x{:08x}".format(cpu)))
            print("A matching CPU alone is insufficient; this project supports only the pinned SnowRunner libraries.")
            return
    raise UserError("Unrecognized input. Choose a Windows .exe or macOS .app.")

"""Portable assembly, Apple signature layout, and safe resource staging."""
import hashlib
import json
import platform
import plistlib
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from tools import windows
from tools.common import ROOT, UserError, read_json, write_json
from tools.macho import commands, remove_signature
from tools.package import check_package


def ios_fixture(filetype=6, platform_id=2):
    # Structural fixture only. It is not runnable game/runtime content.
    build = struct.pack("<IIIIII", 0x32, 24, platform_id, 17 << 16, 27 << 16, 0)
    return struct.pack("<IIIIIIII", 0xFEEDFACF, 0x0100000C, 0, filetype, 1, len(build), 0, 0) + build


def runtime_fixture(path, key=None):
    root = windows.APP_ROOT
    files = {root + "SnowRunner": ios_fixture(2),
             root + "Info.plist": plistlib.dumps({"CFBundleExecutable": "SnowRunner", "CFBundleIdentifier": "local.emu.snowrunner"}),
             root + "resources.json": (ROOT / "data/resources.json").read_bytes()}
    for name in windows.CORE_FRAMEWORKS:
        directory = root + "Frameworks/" + name + ".framework/"
        files[directory + name] = ios_fixture()
        files[directory + "Info.plist"] = plistlib.dumps({"CFBundleExecutable": name})
    manifest = {"format_version": 1, "contract_key": key or windows.contract_key(),
                "files": {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in files.items()}}
    with ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("runtime.json", json.dumps(manifest))


class SignatureTests(unittest.TestCase):
    def signed_fixture(self):
        # Manual layout: header+3 commands, string pool ending at 500, 12 bytes
        # alignment, signature 512..544. __LINKEDIT has a 16 KB virtual size.
        segment = struct.pack("<II16sQQQQIIII", 0x19, 72, b"__LINKEDIT", 0x4000, 0x4000, 480, 64, 1, 1, 0, 0)
        symbols = struct.pack("<IIIIII", 2, 24, 480, 0, 480, 20)
        signature = struct.pack("<IIII", 0x1D, 16, 512, 32)
        header = struct.pack("<IIIIIIII", 0xFEEDFACF, 0x0100000C, 0, 6, 3, 112, 0, 0)
        return (header + segment + symbols + signature).ljust(480, b"\0") + b"strings".ljust(20, b"\0") + b"\0" * 12 + b"signature".ljust(32, b"\0")

    def test_strip_signature_compacts_commands_trims_padding_preserves_vmsize(self):
        original = self.signed_fixture()
        result = remove_signature(original)
        self.assertEqual(len(result), 500)
        self.assertEqual(struct.unpack_from("<II", result, 16), (2, 96))
        self.assertEqual(struct.unpack_from("<Q", result, 32 + 32)[0], 0x4000)
        self.assertEqual(struct.unpack_from("<Q", result, 32 + 48)[0], 20)
        self.assertEqual(result[128:144], b"\0" * 16)
        self.assertEqual(result[144:500], original[144:500])
        self.assertEqual([kind for kind, _, _ in commands(result)], [0x19, 2])

    def test_nonterminal_signature_rejected_and_input_unchanged(self):
        original = bytearray(self.signed_fixture() + b"trailing payload")
        before = bytes(original)
        with self.assertRaises(UserError):
            remove_signature(original)
        self.assertEqual(original, before)

    @unittest.skipUnless(platform.system() == "Darwin" and shutil.which("xcrun"), "Apple comparison needs the macOS CI runner")
    def test_matches_actual_apple_codesign_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "fixture.c"
            source.write_text("int fixture(void) { return 42; }\n")
            signed = root / "signed.dylib"
            subprocess.run(["xcrun", "clang", "-arch", "arm64", "-dynamiclib", str(source), "-o", str(signed)], check=True, capture_output=True)
            subprocess.run(["codesign", "--force", "--sign", "-", str(signed)], check=True, capture_output=True)
            portable = remove_signature(signed.read_bytes())
            subprocess.run(["codesign", "--remove-signature", str(signed)], check=True, capture_output=True)
            self.assertEqual(bytes(portable), signed.read_bytes())


class RuntimeTests(unittest.TestCase):
    def test_game_library_conversion_reaches_exact_independent_prepared_fingerprint(self):
        # SteamAPI fixture with actual __text and signed __LINKEDIT layout.
        text = bytearray(152)
        struct.pack_into("<II16sQQQQIIII", text, 0, 0x19, 152, b"__TEXT", 0, 0x4000, 0, 528, 5, 5, 1, 0)
        struct.pack_into("<16s16sQQI", text, 72, b"__text", b"__TEXT", 512, 4, 512)
        linkedit = struct.pack("<II16sQQQQIIII", 0x19, 72, b"__LINKEDIT", 0x4000, 0x4000, 528, 48, 1, 1, 0, 0)
        build = struct.pack("<IIIIII", 0x32, 24, 1, 17 << 16, 27 << 16, 0)
        symtab = struct.pack("<IIIIII", 2, 24, 528, 0, 528, 16)
        signature = struct.pack("<IIII", 0x1D, 16, 544, 32)
        code = struct.pack("<I", 0xD65F03C0)
        original = bytearray((struct.pack("<IIIIIIII", 0xFEEDFACF, 0x0100000C, 0, 6, 5, 288, 0, 0)
                              + text + linkedit + build + symtab + signature).ljust(512, b"\0") + code + b"\0" * 12 + b"string pool".ljust(16, b"\0") + b"signed".ljust(32, b"\0"))
        # Build the expected bytes independently of retarget/remove_signature.
        expected = bytearray(original[:544])
        struct.pack_into("<II", expected, 16, 4, 272)
        struct.pack_into("<Q", expected, 32 + 152 + 48, 16)
        struct.pack_into("<I", expected, 32 + 152 + 72 + 8, 2)
        expected[304:320] = b"\0" * 16
        entry = {"source": "libsteam_api.dylib", "framework": "SteamAPI",
                 "arm64_sha256": hashlib.sha256(original).hexdigest(),
                 "original_text_sha256": hashlib.sha256(code).hexdigest(),
                 "prepared_text_sha256": hashlib.sha256(code).hexdigest(),
                 "prepared_arm64_sha256": hashlib.sha256(expected).hexdigest()}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture_root = root / "toolkit"
            write_json(fixture_root / "data/supported-game.json", {"version": "53.5", "bundle_version": "111", "binaries": [entry]})
            resources = fixture_root / "data/resources.json"
            resources.write_bytes((ROOT / "data/resources.json").read_bytes())
            game = root / "owned.app"
            frameworks = game / "Contents/Frameworks"
            frameworks.mkdir(parents=True)
            source = frameworks / entry["source"]
            source.write_bytes(original)
            (game / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": "53.5", "CFBundleVersion": "111"}))
            runtime = root / "runtime.zip"
            runtime_fixture(runtime)
            output = root / "game.ipa"
            with patch.object(windows, "ROOT", fixture_root), patch("subprocess.run", side_effect=AssertionError("Apple tools must not run")):
                windows.assemble(runtime, output, game=game, progress=lambda _: None)
            with ZipFile(output) as archive:
                self.assertEqual(archive.read(windows.APP_ROOT + "Frameworks/SteamAPI.framework/SteamAPI"), bytes(expected))
            self.assertEqual(source.read_bytes(), bytes(original))
            self.assertFalse(read_json(output.with_suffix(".json"))["diagnostic_only"])

    def test_diagnostic_ipa_assembles_on_windows_without_subprocess_or_game(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime.zip"
            runtime_fixture(runtime)
            output = root / "check.ipa"
            with patch("subprocess.run", side_effect=AssertionError("No external build/signing tools allowed")):
                windows.assemble(runtime, output, progress=lambda _: None)
                metadata = check_package(output)
            self.assertEqual(metadata["bundle_id"], "local.emu.snowrunner")
            self.assertTrue(read_json(output.with_suffix(".json"))["diagnostic_only"])
            with ZipFile(output) as archive:
                info = plistlib.loads(archive.read(windows.APP_ROOT + "Info.plist"))
                self.assertTrue(info["EmuDiagnosticOnly"])
                self.assertTrue(info["EmuWindowsMenu"])
                self.assertFalse(any("GameClient.framework/" in name for name in archive.namelist()))
                self.assertEqual(archive.getinfo(windows.APP_ROOT + "SnowRunner").external_attr >> 16 & 0o777, 0o755)

    def test_version_mismatch_and_corruption_preserve_existing_ipa(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime.zip"
            output = root / "previous.ipa"
            output.write_bytes(b"previous content")
            runtime_fixture(runtime, key="other version")
            with self.assertRaisesRegex(UserError, "different source versions"):
                windows.assemble(runtime, output, progress=lambda _: None)
            self.assertEqual(output.read_bytes(), b"previous content")
            runtime_fixture(runtime)
            with ZipFile(runtime) as source:
                content = {name: source.read(name) for name in source.namelist()}
            content[windows.APP_ROOT + "SnowRunner"] += b"corrupt"
            # Preserve size to exercise hash, not only size checks.
            content[windows.APP_ROOT + "SnowRunner"] = content[windows.APP_ROOT + "SnowRunner"][-56:]
            with ZipFile(runtime, "w") as archive:
                for name, data in content.items():
                    archive.writestr(name, data)
            with self.assertRaisesRegex(UserError, "checksum mismatch"):
                windows.assemble(runtime, output, progress=lambda _: None)
            self.assertEqual(output.read_bytes(), b"previous content")

    def test_path_traversal_and_simulator_binary_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "runtime.zip"
            runtime_fixture(runtime)
            with ZipFile(runtime, "a") as archive:
                archive.writestr("Payload/SnowRunner.app/../../escape", b"escape")
            with self.assertRaises(UserError):
                windows.inspect_runtime(runtime)
            with self.assertRaisesRegex(UserError, "physical iOS"):
                windows.validate_ios_binary(ios_fixture(platform_id=7), 6)

    def test_contract_is_identical_for_crlf_and_lf_checkouts(self):
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory)
            patterns = ["app/Host/*", "app/Compat/*", "data/*.json", "patches/*", "tools/*"]
            for pattern in patterns:
                for path in ROOT.glob(pattern):
                    if path.is_file():
                        destination = copied / path.relative_to(ROOT)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
            self.assertEqual(windows.contract_key(ROOT), windows.contract_key(copied))


class StagingTests(unittest.TestCase):
    def test_streamed_resources_resume_and_repair_corruption_without_touching_saves(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "game.app"
            resources = app / "Contents/Resources"
            resources.mkdir(parents=True)
            original = b"known fixture resource"
            (resources / "fixture.pak").write_bytes(original)
            (resources / "save.dat").write_bytes(b"private save")
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": "53.5", "CFBundleVersion": "111"}))
            fixture_root = root / "toolkit"
            write_json(fixture_root / "data/supported-game.json", {"version": "53.5", "bundle_version": "111"})
            write_json(fixture_root / "data/resources.json", {"files": [{"path": "fixture.pak", "bytes": len(original), "sha256": hashlib.sha256(original).hexdigest()}]})
            output = root / "staged.emuresources"
            with patch.object(windows, "ROOT", fixture_root), patch.object(windows, "contract_key", return_value="test"):
                windows.stage_resources(app, output, progress=lambda _: None)
                staged = output / "Resources/fixture.pak"
                before = staged.stat().st_mtime_ns
                windows.stage_resources(app, output, progress=lambda _: None)
                self.assertEqual(before, staged.stat().st_mtime_ns)
                staged.write_bytes(b"X" * len(original))
                windows.stage_resources(app, output, progress=lambda _: None)
                self.assertEqual(staged.read_bytes(), original)
                (resources / "fixture.pak").write_bytes(b"Y" * len(original))
                staged.write_bytes(b"Z" * len(original))
                with self.assertRaisesRegex(UserError, "checksum mismatch"):
                    windows.stage_resources(app, output, progress=lambda _: None)
                self.assertEqual(staged.read_bytes(), b"Z" * len(original))
            self.assertFalse((output / "Resources/save.dat").exists())
            self.assertEqual((resources / "save.dat").read_bytes(), b"private save")


if __name__ == "__main__":
    unittest.main()

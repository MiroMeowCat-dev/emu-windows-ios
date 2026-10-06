"""Portable ARM64 extraction and source checks using synthetic Mach-O fixtures."""
import hashlib
from pathlib import Path
import plistlib
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools import prepare, source
from tools.common import UserError, write_json
from tools.macho import arm64_slice


def dylib():
    code = b"\x1f\x20\x03\xd5"
    header = struct.pack("<8I", 0xFEEDFACF, 0x0100000C, 0, 6, 1, 152, 0, 0)
    segment = struct.pack("<II16sQQQQiiII", 0x19, 152, b"__TEXT", 0, 188, 0, 188, 7, 5, 1, 0)
    section = struct.pack("<16s16sQQIIIIIIII", b"__text", b"__TEXT", 184, 4, 184, 2, 0, 0, 0, 0, 0, 0)
    return header + segment + section + code


def universal(slices, wide=False, endian=">"):
    magic = 0xCAFEBABF if wide else 0xCAFEBABE
    table = bytearray(struct.pack(endian + "II", magic, len(slices)))
    contents = bytearray(8 + len(slices) * (32 if wide else 20))
    for cpu, data in slices:
        offset = (len(contents) + 15) & ~15
        contents.extend(b"\0" * (offset - len(contents)))
        contents.extend(data)
        fields = (cpu, 0, offset, len(data), 4) + ((0,) if wide else ())
        table.extend(struct.pack(endian + ("IIQQII" if wide else "IIIII"), *fields))
    contents[:len(table)] = table
    return bytes(contents)


def fixture_game(root):
    app = root / "SnowRunner.app"
    libraries = app / "Contents/Frameworks"
    libraries.mkdir(parents=True)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
        "CFBundleShortVersionString": "53.5", "CFBundleVersion": "111"}))
    binary = dylib()
    (libraries / "fixture.dylib").write_bytes(universal([(0x0100000C, binary)]))
    manifest = {"game": "SnowRunner", "version": "53.5", "bundle_version": "111",
                "binaries": [{"source": "fixture.dylib", "framework": "GameClient",
                              "arm64_sha256": hashlib.sha256(binary).hexdigest(),
                              "original_text_sha256": hashlib.sha256(binary[-4:]).hexdigest()}]}
    write_json(root / "data/supported-game.json", manifest)
    resources = app / "Contents/Resources"
    resources.mkdir()
    (resources / "fixture.pak").write_bytes(b"original")
    files = [{"path": "fixture.pak", "bytes": 8, "sha256": hashlib.sha256(b"original").hexdigest()}]
    return app, binary, files


class SliceTests(unittest.TestCase):
    def test_thin_and_universal_variants_extract_identical_bytes(self):
        arm = dylib()
        intel = bytearray(arm)
        struct.pack_into("<I", intel, 4, 0x01000007)
        self.assertEqual(arm64_slice(arm), arm)
        for wide in [False, True]:
            for endian in [">", "<"]:
                with self.subTest(wide=wide, endian=endian):
                    container = universal([(0x01000007, intel), (0x0100000C, arm)], wide, endian)
                    self.assertEqual(arm64_slice(container), arm)

    def test_rejects_truncation_wrong_cpu_and_ambiguous_slices(self):
        arm = dylib()
        for binary in [b"short", universal([(0x0100000C, arm)])[:-1],
                       universal([(0x01000007, arm)]),
                       universal([(0x0100000C, arm), (0x0100000C, arm)])]:
            with self.subTest(size=len(binary)), self.assertRaises(UserError):
                arm64_slice(binary)

    def test_rejects_slices_overlapping_table_or_each_other(self):
        arm = dylib()
        table_overlap = bytearray(universal([(0x0100000C, arm)]))
        struct.pack_into(">I", table_overlap, 16, 16)
        overlap = bytearray(universal([(0x0100000C, arm), (0x01000007, arm)]))
        first = struct.unpack_from(">I", overlap, 16)[0]
        struct.pack_into(">I", overlap, 36, first)
        for binary in [table_overlap, overlap]:
            with self.assertRaises(UserError):
                arm64_slice(binary)

    def test_rejects_cpu_mismatch_inside_selected_slice(self):
        other = bytearray(dylib())
        struct.pack_into("<I", other, 4, 0x01000007)
        with self.assertRaisesRegex(UserError, "does not contain"):
            arm64_slice(universal([(0x0100000C, other)]))


class SourceTests(unittest.TestCase):
    def test_full_check_passes_without_apple_tools_or_source_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app, binary, files = fixture_game(root)
            before = {p: p.read_bytes() for p in app.rglob("*") if p.is_file()}
            with patch.object(source, "ROOT", root), patch.object(source, "manifest_files", return_value=files):
                report = source.preflight(app, full_resources=True)
            self.assertTrue(report["all_content_verified"])
            self.assertFalse(report["device_tested"])
            self.assertEqual(before, {p: p.read_bytes() for p in app.rglob("*") if p.is_file()})
            self.assertEqual(report["binaries"][0]["sha256"], hashlib.sha256(binary).hexdigest())

    def test_same_size_corruption_requires_full_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app, _, files = fixture_game(root)
            (app / "Contents/Resources/fixture.pak").write_bytes(b"damaged!")
            with patch.object(source, "ROOT", root), patch.object(source, "manifest_files", return_value=files):
                quick = source.preflight(app)
                full = source.preflight(app, full_resources=True)
            self.assertTrue(quick["passed"])
            self.assertFalse(quick["all_content_verified"])
            self.assertFalse(full["passed"])
            self.assertIn("checksum mismatch", full["errors"][0])

    def test_reports_binary_and_resource_problems_together(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app, _, files = fixture_game(root)
            (app / "Contents/Frameworks/fixture.dylib").unlink()
            (app / "Contents/Resources/fixture.pak").unlink()
            with patch.object(source, "ROOT", root), patch.object(source, "manifest_files", return_value=files):
                report = source.preflight(app)
            self.assertFalse(report["passed"])
            self.assertEqual(len(report["errors"]), 2)

    def test_mac_prepare_uses_the_same_verified_slice_without_lipo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app, binary, _ = fixture_game(root)
            output = root / "extracted"
            output.mkdir()
            with patch.object(prepare, "ROOT", root), patch.object(prepare, "run", side_effect=AssertionError("Apple tool called")):
                _, libraries = prepare.validate_game(app, output)
            self.assertEqual(libraries[0][1].read_bytes(), binary)


if __name__ == "__main__":
    unittest.main()

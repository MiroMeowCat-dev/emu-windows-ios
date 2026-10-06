"""Safety checks for version-locked binary preparation and resource resume."""
import hashlib
import io
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest

from tools.common import UserError
from tools.macho import commands, validate_dylib, verify_fingerprint, patch_instructions
from tools.resources import transfer_plan, safe_relative
from tools.device import BUNDLE_RESOURCES
from tools.sdl import safe_extract


class MachOTests(unittest.TestCase):
    def header(self, count=0, size=0, cpu=0x0100000C, kind=6):
        return bytearray(struct.pack("<8I", 0xFEEDFACF, cpu, 0, kind, count, size, 0, 0))

    def test_rejects_wrong_architecture_and_executable(self):
        for data in [self.header(cpu=0x01000007), self.header(kind=2)]:
            with self.assertRaises(UserError):
                validate_dylib(data)

    def test_rejects_truncated_commands(self):
        with self.assertRaises(UserError):
            list(commands(self.header(count=1, size=16) + b"\0" * 8))

    def test_rejects_command_outside_table(self):
        with self.assertRaises(UserError):
            list(commands(self.header(count=1, size=8) + struct.pack("<II", 0x32, 40)))

    def test_unknown_binary_is_rejected(self):
        original = b"known supported input"
        expected = hashlib.sha256(original).hexdigest()
        verify_fingerprint(original, expected, "fixture")
        with self.assertRaisesRegex(UserError, "Unsupported"):
            verify_fingerprint(original[:-1] + b"!", expected, "fixture")

    def test_patch_batch_validates_before_mutating(self):
        data = bytearray(struct.pack("<II", 0x94000000, 0x94000001))
        before = bytes(data)
        patches = [{"offset": "0", "old_word": "0x94000000", "new_word": "0x94000002"},
                   {"offset": "4", "old_word": "0x940000ff", "new_word": "0x94000003"}]
        with self.assertRaises(UserError):
            patch_instructions(data, patches)
        self.assertEqual(bytes(data), before)

    def test_patch_changes_only_selected_word(self):
        data = bytearray(b"head" + struct.pack("<I", 0x94000000) + b"tail")
        patch_instructions(data, [{"offset": "4", "old_word": "0x94000000", "new_word": "0x94000002"}])
        self.assertEqual(bytes(data), b"head" + struct.pack("<I", 0x94000002) + b"tail")


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.item = {"path": "preload/paks/client/test.pak", "bytes": 12, "sha256": "abc"}
        self.listing = {BUNDLE_RESOURCES + self.item["path"]: 12}

    def test_same_size_without_completion_receipt_is_retried(self):
        self.assertEqual(transfer_plan([self.item], self.listing, {"files": {}}), [self.item])

    def test_completed_matching_file_is_skipped(self):
        receipt = {"files": {self.item["path"]: {"bytes": 12, "sha256": "abc"}}}
        self.assertEqual(transfer_plan([self.item], self.listing, receipt), [])

    def test_changed_source_or_device_size_is_not_skipped(self):
        receipt = {"files": {self.item["path"]: {"bytes": 12, "sha256": "wrong"}}}
        self.assertEqual(transfer_plan([self.item], self.listing, receipt), [self.item])
        receipt["files"][self.item["path"]]["sha256"] = "abc"
        self.assertEqual(transfer_plan([self.item], {BUNDLE_RESOURCES + self.item["path"]: 11}, receipt), [self.item])

    def test_paths_cannot_escape_resources_into_saves(self):
        for path in ["../sandbox/save.dat", "/tmp/file", "a/../../b", "a\\b", "C:/escape", "C:escape", "file:stream", ""]:
            with self.assertRaises(UserError):
                safe_relative(path)


class ArchiveTests(unittest.TestCase):
    def archive(self, directory, name, link=None):
        path = Path(directory) / "source.tar"
        with tarfile.open(path, "w") as stream:
            item = tarfile.TarInfo(name)
            if link is not None:
                item.type = tarfile.SYMTYPE
                item.linkname = link
                stream.addfile(item)
            else:
                item.size = 4
                stream.addfile(item, io.BytesIO(b"test"))
        return path

    def test_parent_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = self.archive(temporary, "../escape")
            with self.assertRaises(UserError):
                safe_extract(source, Path(temporary) / "out")

    def test_outside_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = self.archive(temporary, "SDL/link", "../../outside")
            with self.assertRaises(UserError):
                safe_extract(source, Path(temporary) / "out")

    def test_regular_file_extracts(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = self.archive(temporary, "SDL/file")
            destination = Path(temporary) / "out"
            safe_extract(source, destination)
            self.assertEqual((destination / "SDL/file").read_bytes(), b"test")


if __name__ == "__main__":
    unittest.main()

"""Checks for the portable preflight and the single-command first run."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import plistlib
import struct
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from tools import cli
from tools import package
from tools.common import UserError
from tools.common import sha256, write_json


class InspectionTests(unittest.TestCase):
    def test_windows_executable_is_identified_without_mac_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "game.exe"
            data = bytearray(128)
            data[:2] = b"MZ"
            struct.pack_into("<I", data, 60, 64)
            data[64:70] = b"PE\0\0" + struct.pack("<H", 0x8664)
            path.write_bytes(data)
            output = io.StringIO()
            with redirect_stdout(output):
                cli.command(cli.parser().parse_args(["inspect", str(path)]))
            self.assertIn("Windows PE executable: x86-64", output.getvalue())
            self.assertIn("cannot run Windows executables", output.getvalue())

    def test_matching_app_version_is_only_a_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "SnowRunner.app"
            info = app / "Contents/Info.plist"
            info.parent.mkdir(parents=True)
            info.write_bytes(plistlib.dumps({"CFBundleShortVersionString": "53.5",
                                              "CFBundleVersion": "111"}))
            output = io.StringIO()
            with redirect_stdout(output):
                cli.command(cli.parser().parse_args(["inspect", str(app)]))
            self.assertIn("preflight --game", output.getvalue())

    def test_bad_executable_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.exe"
            path.write_bytes(b"MZ" + b"\0" * 62)
            with self.assertRaisesRegex(UserError, "no valid PE header"):
                cli.inspect_input(path)


class StartTests(unittest.TestCase):
    def test_start_from_empty_settings_runs_all_steps_in_order(self):
        settings = {"game": "/owned/SnowRunner.app", "team": "TEAM123456",
                    "bundle_id": "local.test.snowrunner", "device": ""}
        calls = []
        args = cli.parser().parse_args(["start", "--diagnostics"])
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(cli, "CONFIG", Path(directory) / "missing.json"), \
             patch.object(cli.platform, "system", return_value="Darwin"), \
             patch.object(cli.platform, "machine", return_value="arm64"), \
             patch.object(cli, "setup", side_effect=lambda _: calls.append("setup")), \
             patch.object(cli, "config", return_value=settings), \
             patch.object(cli.device, "select_device", return_value="phone"), \
             patch.object(cli, "build", side_effect=lambda _: calls.append("build") or "app"), \
             patch.object(cli.device, "install", side_effect=lambda *_: calls.append("install")), \
             patch.object(cli.resources, "transfer", side_effect=lambda _: calls.append("resources")), \
             patch.object(cli, "launch_game", side_effect=lambda *_, **__: calls.append("launch")):
            cli.command(args)
        self.assertEqual(calls, ["setup", "build", "install", "resources", "launch"])
        self.assertEqual(settings["device"], "phone")


class PackageTests(unittest.TestCase):
    def archive(self, path, executable="GuestProgram", bundle="local.test.snowrunner"):
        with ZipFile(path, "w") as archive:
            root = "Payload/Guest.app/"
            archive.writestr(root + "Info.plist", plistlib.dumps({"CFBundleIdentifier": bundle,
                                                                "CFBundleExecutable": executable}))
            archive.writestr(root + executable, b"fixture executable")
            archive.writestr(root + "embedded.mobileprovision", b"fixture profile")

    def test_portable_check_uses_metadata_and_detects_modified_package(self):
        with tempfile.TemporaryDirectory() as directory:
            ipa = Path(directory) / "Guest.ipa"
            self.archive(ipa)
            metadata = package.validate_ipa(ipa)
            self.assertEqual(metadata["executable"], "GuestProgram")
            write_json(ipa.with_suffix(".json"), dict(metadata, format_version=1, ipa_sha256=sha256(ipa)))
            self.assertEqual(package.check_package(ipa), metadata)
            with ipa.open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(UserError, "checksum mismatch"):
                package.check_package(ipa)

    def test_failed_export_keeps_existing_package_and_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "Guest.app"
            app.mkdir()
            (app / "embedded.mobileprovision").write_bytes(b"profile")
            output = root / "previous.ipa"
            output.write_bytes(b"previous working package")
            receipt = output.with_suffix(".json")
            write_json(receipt, {"format_version": 1, "ipa_sha256": sha256(output)})
            previous_receipt = receipt.read_bytes()

            def broken_export(arguments, capture=False):
                if arguments[:2] == ["ditto", "-c"]:
                    Path(arguments[-1]).write_bytes(b"invalid archive")

            with patch.object(package, "run", side_effect=broken_export):
                with self.assertRaises(UserError):
                    package.export_ipa(app, {"bundle_id": "local.test.snowrunner"}, output)
            self.assertEqual(output.read_bytes(), b"previous working package")
            self.assertEqual(receipt.read_bytes(), previous_receipt)

    def test_export_does_not_overwrite_unrelated_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "Guest.app"
            app.mkdir()
            receipt = root / "metadata.json"
            write_json(receipt, {"other": "important data"})
            before = receipt.read_bytes()
            with patch.object(package, "run") as run, self.assertRaisesRegex(UserError, "unrelated JSON"):
                package.export_ipa(app, {}, root / "metadata.ipa")
            run.assert_not_called()
            self.assertEqual(receipt.read_bytes(), before)

    def test_output_cannot_replace_a_receipt_or_modify_signed_app(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "Guest.app"
            app.mkdir()
            for output in [Path(directory) / "receipt.json", app / "inside.ipa"]:
                with patch.object(package, "run") as run, self.assertRaises(UserError):
                    package.export_ipa(app, {}, output)
                run.assert_not_called()

    def test_archive_paths_cannot_escape_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            ipa = Path(directory) / "unsafe.ipa"
            self.archive(ipa)
            with ZipFile(ipa, "a") as archive:
                archive.writestr("../escaped", b"content")
            with self.assertRaisesRegex(UserError, "invalid path"):
                package.validate_ipa(ipa)

    def test_export_writes_app_only_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "SnowRunner.app"
            app.mkdir()
            (app / "SnowRunner").write_bytes(b"signed fixture")
            (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "local.test.snowrunner",
                                                            "CFBundleExecutable": "SnowRunner"}))
            (app / "embedded.mobileprovision").write_bytes(b"fixture profile")
            calls = []

            def fake_run(arguments, capture=False):
                calls.append(arguments)
                if arguments[:2] == ["ditto", "-c"]:
                    with ZipFile(arguments[-1], "w") as archive:
                        archive.write(app / "SnowRunner", "Payload/SnowRunner.app/SnowRunner")
                        archive.write(app / "Info.plist", "Payload/SnowRunner.app/Info.plist")
                        archive.write(app / "embedded.mobileprovision", "Payload/SnowRunner.app/embedded.mobileprovision")
                elif arguments[0] == "ditto":
                    Path(arguments[2]).mkdir()
                    (Path(arguments[2]) / "SnowRunner").write_bytes(b"signed fixture")

            with patch.object(package, "BUILD", root), patch.object(package, "run", side_effect=fake_run):
                result = package.export_ipa(app, {"bundle_id": "local.test.snowrunner"})
            self.assertTrue(result.is_file())
            self.assertEqual(package.read_json(result.with_suffix(".json"))["includes_game_resources"], False)
            self.assertEqual([call[0] for call in calls], ["codesign", "ditto", "codesign", "ditto"])


if __name__ == "__main__":
    unittest.main()

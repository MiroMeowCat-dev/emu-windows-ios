"""Regression checks for interrupted transfers and reusable prepared libraries."""
from contextlib import ExitStack, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import device, prepare, resources
from tools.common import ROOT, UserError, read_json, write_json


class TransferTests(unittest.TestCase):
    def test_verification_timeout_resets_when_the_phone_makes_progress(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            elapsed = [0]
            reports = iter([
                {"token": "current", "checkedFiles": 1, "totalFiles": 3, "complete": False},
                {"token": "current", "checkedFiles": 2, "totalFiles": 3, "complete": False},
                {"token": "current", "checkedFiles": 3, "totalFiles": 3, "complete": True, "passed": True},
            ])

            def copy_report(settings, source, destination):
                write_json(destination, next(reports))

            def wait(seconds):
                elapsed[0] += 70

            stack.enter_context(patch.object(device, "BUILD", Path(temporary)))
            stack.enter_context(patch.object(device.uuid, "uuid4")).return_value.hex = "current"
            stack.enter_context(patch.object(device, "launch"))
            stack.enter_context(patch.object(device, "files", return_value={"Documents/report.json": 100}))
            stack.enter_context(patch.object(device, "copy_from", side_effect=copy_report))
            stack.enter_context(patch.object(device.time, "monotonic", side_effect=lambda: elapsed[0]))
            stack.enter_context(patch.object(device.time, "sleep", side_effect=wait))
            stack.enter_context(redirect_stdout(io.StringIO()))
            result = device.run_check({}, "verify-resources", "report.json", timeout=100)
            self.assertTrue(result["passed"])
            self.assertGreater(elapsed[0], 100)

    def test_interrupted_replacement_cannot_reuse_an_old_receipt(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            content = b"complete archive"
            item = {"path": "preload/test.pak", "bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest()}
            source = root / "game/Contents/Resources" / item["path"]
            source.parent.mkdir(parents=True)
            source.write_bytes(content)
            remote_path = device.BUNDLE_RESOURCES + item["path"]
            remote = {device.RECEIPTS: json.dumps({"version": 1, "files": {
                item["path"]: {"bytes": len(content), "sha256": "old hash"}
            }}).encode()}
            interrupted = True

            def copy_to(settings, path, destination):
                if destination == remote_path and interrupted:
                    # CoreDevice can leave a same-sized, incomplete destination.
                    remote[destination] = b"\0" * len(content)
                    raise UserError("Cable disconnected")
                remote[destination] = Path(path).read_bytes()

            def copy_from(settings, source, destination):
                Path(destination).write_bytes(remote[source])

            for module in (device, resources):
                stack.enter_context(patch.object(module, "BUILD", root / "build"))
            (root / "build").mkdir()
            stack.enter_context(patch.object(resources, "manifest_files", return_value=[item]))
            stack.enter_context(patch.object(device, "files", side_effect=lambda settings: {
                path: len(data) for path, data in remote.items()}))
            stack.enter_context(patch.object(device, "copy_from", side_effect=copy_from))
            stack.enter_context(patch.object(device, "copy_to", side_effect=copy_to))
            stack.enter_context(patch.object(device, "run_check", return_value={
                "passed": True, "availableBytes": 1024 ** 3}))
            stack.enter_context(redirect_stdout(io.StringIO()))
            settings = {"game": str(root / "game")}

            with self.assertRaisesRegex(UserError, "Cable disconnected"):
                resources.transfer(settings)
            receipt = json.loads(remote[device.RECEIPTS])
            self.assertNotIn(item["path"], receipt["files"])
            self.assertEqual(resources.pending_files(settings), [item])

            interrupted = False
            resources.transfer(settings)
            self.assertEqual(remote[remote_path], content)
            self.assertEqual(resources.pending_files(settings), [])

    def test_malformed_receipts_stop_before_any_device_write(self):
        for damaged in ("{", "[]", '{"version":1,"files":[]}', '{"version":2,"files":{}}'):
            with self.subTest(receipt=damaged), tempfile.TemporaryDirectory() as temporary:
                def copy_from(settings, source, destination):
                    Path(destination).write_text(damaged)

                with patch.object(device, "BUILD", Path(temporary)), \
                     patch.object(device, "files", return_value={device.RECEIPTS: len(damaged)}), \
                     patch.object(device, "copy_from", side_effect=copy_from), \
                     patch.object(device, "copy_to") as write, \
                     patch.object(device, "run_check") as launch:
                    with self.assertRaisesRegex(UserError, "resources --verify"):
                        resources.transfer({"game": "/missing"})
                    write.assert_not_called()
                    launch.assert_not_called()


class PreparedLibraryTests(unittest.TestCase):
    def test_dynamic_lookups_require_exported_symbols(self):
        source = 'dlsym(game, "_LocalGetter"); GameSymbol( game,\n "_WorldObject" );'
        symbols = '00000000 t __LocalGetter\n00000010 D __WorldObject\n'
        self.assertEqual(prepare.missing_game_exports(source, symbols), ["_LocalGetter"])
        self.assertEqual(prepare.missing_game_exports(source, symbols.replace('t __Local', 'T __Local')), [])

    def test_verified_cache_can_refresh_without_original_game(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            vendor = root / "Vendor"
            library = vendor / "GameClient.framework/GameClient"
            library.parent.mkdir(parents=True)
            library.write_bytes(b"verified prepared game")
            manifest = root / "supported-game.json"
            write_json(manifest, {"binaries": [{"framework": "GameClient",
                "prepared_arm64_sha256": hashlib.sha256(library.read_bytes()).hexdigest()}]})
            stack.enter_context(patch.object(prepare, "BUILD", root))
            stack.enter_context(patch.object(prepare, "VENDOR", vendor))
            stack.enter_context(patch.object(prepare, "read_json", return_value=read_json(manifest)))
            stack.enter_context(patch.object(prepare, "prepared_current", return_value=False))
            stack.enter_context(patch.object(prepare, "ensure_sdl"))
            stack.enter_context(patch.object(prepare, "sdk_path", return_value=Path("/SDK")))
            stack.enter_context(patch.object(prepare, "preparation_key", return_value="new toolchain"))
            adapters = stack.enter_context(patch.object(prepare, "build_compatibility"))
            bridge = stack.enter_context(patch.object(prepare, "build_bridge"))
            original = stack.enter_context(patch.object(prepare, "prepare"))
            stack.enter_context(redirect_stdout(io.StringIO()))

            prepare.ensure_prepared(root / "absent-original.app")
            original.assert_not_called()
            adapters.assert_called_once()
            bridge.assert_called_once()
            self.assertTrue((root / "prepared.json").is_file())

            library.write_bytes(b"damaged prepared game")
            self.assertFalse(prepare.cached_game_is_valid())
            prepare.ensure_prepared(root / "absent-original.app")
            original.assert_called_once()


class ManifestTests(unittest.TestCase):
    def test_generated_resources_match_their_fingerprints(self):
        for item in resources.manifest_files():
            self.assertEqual(resources.safe_relative(item["path"]), item["path"])
            if "text" in item:
                data = item["text"].encode("utf-8")
                self.assertEqual(len(data), item["bytes"])
                self.assertEqual(hashlib.sha256(data).hexdigest(), item["sha256"])
        paths = [item["path"] for item in resources.manifest_files()]
        self.assertEqual(len(paths), len(set(paths)))

    def test_sdl_names_match_every_abi_table_index(self):
        directory = ROOT / "app/Compat"
        names = re.findall(r'"(SDL_\w+)"', (directory / "SDL2264Names.inc").read_text())
        indices = re.findall(r"index_(SDL_\w+)\s*=\s*(\d+)",
                             (directory / "SDL2264Indices.h").read_text())
        self.assertEqual(len(names), 833)
        self.assertEqual(len(set(names)), 833)
        self.assertEqual(indices, [(name, str(index)) for index, name in enumerate(names)])


class TouchPointerTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("cc"), "C compiler is not installed on this host")
    def test_real_c_pointer_logic(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / ("touch-pointer-test.exe" if os.name == "nt" else "touch-pointer-test")
            # MinGW on the Windows runner has no address/undefined sanitizer
            # runtime. Execute the C assertions there, and sanitize on macOS.
            sanitizers = [] if os.name == "nt" else ["-fsanitize=address,undefined"]
            compilation = subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror"] + sanitizers +
                            [str(ROOT / "tests/touch_pointer.c"), "-o", str(binary)], capture_output=True, text=True)
            self.assertEqual(compilation.returncode, 0, compilation.stdout + compilation.stderr)
            subprocess.run([str(binary)], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()

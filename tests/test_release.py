"""Verify source releases do not collect local settings, game files or credentials."""
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from tools import release


class ToolkitTests(unittest.TestCase):
    def test_allowlist_excludes_local_data_and_produces_reproducible_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in release.FILES + ["tools/cli.py", "app/Host/main.m"]:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"source fixture")
            for name in ["config.local.json", "Config/Local.xcconfig", "secret.p12",
                         "build/Vendor/GameClient.framework/GameClient", "SnowRunner.app/game.pak",
                         "docs/private-notes.md"]:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"PRIVATE DATA")
            output = root / "releases/toolkit.zip"
            with patch.object(release, "ROOT", root), redirect_stdout(io.StringIO()):
                release.toolkit(output)
                original = output.read_bytes()
                release.toolkit(output)
            self.assertEqual(output.read_bytes(), original)
            with ZipFile(output) as archive:
                manifest = json.loads(archive.read("emu-toolkit/toolkit-manifest.json"))
                self.assertFalse(manifest["includes_game_content"])
                self.assertFalse(manifest["includes_personal_settings"])
                for item in manifest["files"]:
                    data = archive.read("emu-toolkit/" + item["path"])
                    self.assertNotEqual(data, b"PRIVATE DATA")
                    self.assertEqual(len(data), item["bytes"])
                    self.assertEqual(hashlib.sha256(data).hexdigest(), item["sha256"])
                self.assertEqual(archive.getinfo("emu-toolkit/emu").external_attr >> 16 & 0o777, 0o755)


if __name__ == "__main__":
    unittest.main()

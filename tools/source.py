"""Portable validation of the owner's macOS game files; no Apple tools or writes."""
import hashlib
from pathlib import Path
import plistlib

from .common import ROOT, UserError, read_json, sha256
from .macho import arm64_slice, code_hash, validate_dylib, verify_fingerprint
from .resources import manifest_files, safe_relative


def game_metadata(game, manifest):
    try:
        info = plistlib.loads((Path(game) / "Contents/Info.plist").read_bytes())
    except (OSError, ValueError) as error:
        raise UserError("Cannot read SnowRunner.app/Contents/Info.plist: " + str(error)) from error
    if not isinstance(info, dict):
        raise UserError("The game's Info.plist must be a dictionary.")
    expected = (manifest["version"], manifest["bundle_version"])
    actual = (info.get("CFBundleShortVersionString"), info.get("CFBundleVersion"))
    if actual != expected:
        raise UserError("Unsupported SnowRunner version {} ({}); expected {} ({}).".format(*actual, *expected))
    return info


def validated_binary(game, entry):
    source = Path(game) / "Contents/Frameworks" / entry["source"]
    if not source.is_file():
        raise UserError("Missing game library: " + str(source))
    data = arm64_slice(source.read_bytes())
    verify_fingerprint(data, entry["arm64_sha256"], entry["framework"])
    validate_dylib(data)
    if code_hash(data) != entry["original_text_sha256"]:
        raise UserError("Unexpected code section: " + entry["framework"])
    return data


def preflight(game, full_resources=False, progress=None):
    """Return all source problems. Size-only results never claim content verification."""
    game = Path(game).expanduser().resolve()
    manifest = read_json(ROOT / "data/supported-game.json")
    report = {"format_version": 1, "game": manifest["game"],
              "expected_version": manifest["version"], "expected_build": manifest["bundle_version"],
              "resource_check": "sha256" if full_resources else "size",
              "binaries": [], "resources": [], "errors": []}
    try:
        game_metadata(game, manifest)
        report["metadata_matches"] = True
    except (UserError, OSError) as error:
        report["metadata_matches"] = False
        report["errors"].append(str(error))
    for entry in manifest["binaries"]:
        item = {"path": entry["source"], "framework": entry["framework"]}
        if progress:
            progress("Checking binary: " + entry["source"])
        try:
            data = validated_binary(game, entry)
            item.update(status="verified", bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        except (UserError, OSError) as error:
            item.update(status="failed", error=str(error))
            report["errors"].append(str(error))
        report["binaries"].append(item)
    expected = manifest_files()
    base = game / "Contents/Resources"
    for index, entry in enumerate(expected, 1):
        relative = safe_relative(entry["path"])
        item = {"path": relative, "bytes": entry["bytes"], "sha256": entry["sha256"]}
        if progress:
            progress("[{}/{}] Checking resource: {}".format(index, len(expected), relative))
        try:
            if "text" in entry:
                data = entry["text"].encode("utf-8")
                if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                    raise UserError("Generated resource manifest mismatch: " + relative)
                item["status"] = "generated"
            else:
                source = base / relative
                if not source.is_file() or source.stat().st_size != entry["bytes"]:
                    raise UserError("Missing or wrong-sized resource: " + relative)
                if full_resources and sha256(source) != entry["sha256"]:
                    raise UserError("Resource checksum mismatch: " + relative)
                item["status"] = "verified" if full_resources else "size_ok"
        except (UserError, OSError) as error:
            item.update(status="failed", error=str(error))
            report["errors"].append(str(error))
        report["resources"].append(item)
    report["resource_bytes"] = sum(item["bytes"] for item in expected)
    report["phone_free_bytes_for_fresh_copy"] = report["resource_bytes"] + 512 * 1024 * 1024
    report["passed"] = not report["errors"]
    report["all_content_verified"] = report["passed"] and full_resources
    report["device_tested"] = False
    return report

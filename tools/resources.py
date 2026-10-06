"""Explicit, resumable transfer of the complete installed resource set."""
from pathlib import Path, PurePosixPath

from .common import BUILD, ROOT, UserError, read_json, sha256, write_json
from . import device


def manifest_files():
    manifest = read_json(ROOT / "data/resources.json")
    return manifest["files"] + manifest.get("generated_files", [])


def safe_relative(path):
    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts or "\\" in path or ":" in path or "\0" in path or not value.parts:
        raise UserError("Invalid resource path: " + path)
    return value.as_posix()


def transfer_plan(expected, listing, receipts):
    completed = receipts.get("files", {})
    pending = []
    for item in expected:
        relative = safe_relative(item["path"])
        previous = completed.get(relative, {})
        if not isinstance(previous, dict):
            previous = {}
        if (listing.get(device.BUNDLE_RESOURCES + relative) == item["bytes"] and
                previous.get("bytes") == item["bytes"] and previous.get("sha256") == item["sha256"]):
            continue
        pending.append(item)
    return pending


def installed_files(settings):
    try:
        return device.files(settings)
    except UserError as error:
        raise UserError("Cannot access the app container. Run ./emu install first, and keep the phone connected and unlocked.\n" + str(error)) from error


def pending_files(settings):
    listing = installed_files(settings)
    return transfer_plan(manifest_files(), listing, device.read_receipts(settings, listing))


def verify(settings):
    size = sum(item["bytes"] for item in manifest_files()) / 1e9
    print("Verifying {:.2f} GB on the phone without re-copying files.".format(size))
    result = device.run_check(settings, "verify-resources", "resource-check.json", timeout=900)
    if not result.get("passed"):
        missing = result.get("errors", [])
        raise UserError("Resource verification found {} problem(s).\n{}\nRun ./emu resources to transfer missing or damaged files."
                        .format(len(missing), "\n".join(map(str, missing[:8]))))
    print("All resource checksums match. Completion receipts were saved on the phone.")


def transfer(settings, dry_run=False):
    expected = manifest_files()
    listing = installed_files(settings)
    receipts = device.read_receipts(settings, listing)
    pending = transfer_plan(expected, listing, receipts)
    total = sum(item["bytes"] for item in pending)
    print("Resources: {} ready, {} to copy ({:.2f} GB).".format(len(expected) - len(pending), len(pending), total / 1e9))
    if dry_run:
        for item in pending:
            print("  {} ({:.1f} MB)".format(item["path"], item["bytes"] / 1e6))
        return
    if not pending:
        return
    base = Path(settings["game"]) / "Contents/Resources"
    for item in pending:
        if "text" not in item:
            source = base / safe_relative(item["path"])
            if not source.is_file() or source.stat().st_size != item["bytes"]:
                raise UserError("Missing or wrong-sized original resource: " + str(source))
    # The maintenance screen stops the game from reading archives during copying.
    # It also creates only the resource directories, never the save directories.
    ready = device.run_check(settings, "maintenance", "maintenance-ready.json", timeout=120)
    if not ready.get("passed"):
        raise UserError("The app could not prepare its resource directory. See ./emu logs.")
    required = total + 512 * 1024 * 1024
    available = ready.get("availableBytes", 0)
    if available < required:
        raise UserError("Not enough free space: {:.2f} GB available, {:.2f} GB needed for this transfer.".format(available / 1e9, required / 1e9))
    source_cache = BUILD / "resource-source-checks.json"
    checked = read_json(source_cache) if source_cache.exists() else {}
    for index, item in enumerate(pending, 1):
        relative = safe_relative(item["path"])
        if "text" in item:
            source = BUILD / "generated-resources" / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(item["text"])
        else:
            source = base / relative
        stat = source.stat()
        stamp = {"path": str(source.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": item["sha256"]}
        if checked.get(relative) != stamp:
            print("Checking source: " + relative, flush=True)
            if sha256(source) != item["sha256"]:
                raise UserError("Source resource checksum mismatch: {}. Verify your game files in Steam.".format(relative))
            checked[relative] = stamp
            write_json(source_cache, checked)
        print("[{}/{}] Copying {} ({:.2f} GB)...".format(index, len(pending), relative, item["bytes"] / 1e9), flush=True)
        # Invalidate any old success BEFORE writing the archive. A failed copy
        # may leave a preallocated file with the correct size but wrong contents.
        receipts["files"].pop(relative, None)
        local_receipts = BUILD / "reports/emu-resources.json"
        write_json(local_receipts, receipts)
        device.copy_to(settings, local_receipts, device.RECEIPTS)
        device.copy_to(settings, source, device.BUNDLE_RESOURCES + relative)
        if device.files(settings).get(device.BUNDLE_RESOURCES + relative) != item["bytes"]:
            raise UserError("Device size mismatch after copying " + relative)
        # Mark a file only AFTER CoreDevice reports success and size is checked.
        # An interrupted or preallocated same-size file without a receipt is retried.
        receipts["files"][relative] = {"bytes": item["bytes"], "sha256": item["sha256"]}
        local_receipts = BUILD / "reports/emu-resources.json"
        write_json(local_receipts, receipts)
        device.copy_to(settings, local_receipts, device.RECEIPTS)
    print("Resources complete. Run ./emu launch.")

"""CoreDevice operations. Every write stays inside the configured app container."""
from datetime import datetime
import json
from pathlib import Path
import tempfile
import time
import uuid

from .common import BUILD, UserError, read_json, run

BUNDLE_RESOURCES = "Documents/SnowRunner/SnowRunner.app/Contents/Resources/"
RECEIPTS = "Documents/emu-resources.json"


def query(arguments, timeout=120):
    BUILD.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="device-", dir=BUILD) as temporary:
        output = Path(temporary) / "result.json"
        run(["xcrun", "devicectl"] + list(arguments) + ["--timeout", str(timeout), "--json-output", output], capture=True, timeout=timeout + 20)
        data = read_json(output)
        if data.get("info", {}).get("outcome") != "success":
            raise UserError("CoreDevice failed: " + json.dumps(data.get("error", {})))
        return data.get("result", {})


def devices():
    result = []
    for item in query(["list", "devices"]).get("devices", []):
        properties = item.get("properties", {})
        hardware = properties.get("hardware", item.get("hardwareProperties", {}))
        state = properties.get("state", item.get("deviceProperties", {}))
        software = properties.get("software", item.get("deviceProperties", {}))
        identifier = hardware.get("udid")
        if not identifier or hardware.get("reality", "physical") != "physical":
            continue
        version = software.get("osVersionNumber", "")
        if isinstance(version, dict):
            version = version.get("stringValue", "")
        result.append({"id": identifier, "name": state.get("name", "iOS device"),
                       "model": hardware.get("marketingName", ""), "os": version})
    return result


def select_device(settings):
    if settings.get("device"):
        return settings["device"]
    found = devices()
    if len(found) == 1:
        return found[0]["id"]
    raise UserError("Connect one iPhone by USB, or set device in config.local.json. See ./emu devices.")


def container_arguments(settings):
    if not settings.get("bundle_id"):
        raise UserError("Set bundle_id with ./emu setup before accessing the phone.")
    return ["--device", select_device(settings), "--domain-type", "appDataContainer",
            "--domain-identifier", settings["bundle_id"]]


def files(settings):
    entries = query(["device", "info", "files"] + container_arguments(settings) + ["--subdirectory", "Documents"]).get("files", [])
    return {"Documents/" + entry["relativePath"]: entry.get("metadata", {}).get("size", 0)
            for entry in entries if not entry.get("resources", {}).get("isDirectory")}


def copy_from(settings, source, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    query(["device", "copy", "from"] + container_arguments(settings) + ["--source", source, "--destination", str(destination)], timeout=1800)


def copy_to(settings, source, destination):
    query(["device", "copy", "to"] + container_arguments(settings) + ["--source", str(source), "--destination", destination], timeout=1800)


def read_receipts(settings, listing):
    if RECEIPTS not in listing:
        return {"version": 1, "files": {}}
    with tempfile.TemporaryDirectory(prefix="receipts-", dir=BUILD) as temporary:
        path = Path(temporary) / "receipts.json"
        copy_from(settings, RECEIPTS, path)
        try:
            value = json.loads(path.read_text())
            if value.get("version") == 1 and isinstance(value.get("files"), dict):
                return value
        except (ValueError, AttributeError):
            pass
    raise UserError("Resource completion records are damaged. Run ./emu resources --verify to recover them without re-copying the game.")


def install(settings, app):
    print("Installing an update; existing game files and saves are kept...")
    query(["device", "install", "app", "--device", select_device(settings), str(app)], timeout=300)


def launch(settings, mode="game", diagnostics=False, token=None):
    environment = {"EMU_MODE": mode}
    if diagnostics:
        environment["EMU_DIAGNOSTICS"] = "1"
    if token:
        environment["EMU_CHECK_TOKEN"] = token
    return query(["device", "process", "launch", "--device", select_device(settings), "--terminate-existing",
                  "--environment-variables", json.dumps(environment), settings["bundle_id"]])


def run_check(settings, mode, filename, timeout=600):
    token = uuid.uuid4().hex
    launch(settings, mode=mode, token=token)
    target = BUILD / "reports" / filename
    deadline = time.monotonic() + timeout
    last_progress = None
    while time.monotonic() < deadline:
        listing = files(settings)
        remote = "Documents/" + filename
        if remote in listing:
            copy_from(settings, remote, target)
            result = read_json(target)
            if result.get("token") == token:
                progress = result.get("checkedFiles")
                if progress is not None and progress != last_progress:
                    print("Checked {} / {} resource files.".format(progress, result.get("totalFiles")), flush=True)
                    last_progress = progress
                    # Large transfers/checks may take longer than the initial
                    # timeout. Stop only if the phone stops making progress.
                    deadline = time.monotonic() + timeout
                if result.get("complete", True):
                    return result
        time.sleep(2)
    raise UserError("Device check timed out. Keep the phone unlocked and the app in front; see ./emu logs.")


def logs(settings):
    directory = BUILD / "logs" / datetime.now().strftime("device-%Y%m%d-%H%M%S")
    known = {"guest-console.log", "guest-load.log", "game-memory.jsonl", "sdl-check.json", "resource-check.json", "sdl-stage.log", "launch-error.json", "maintenance-ready.json", "controls-preview.png"}
    count = 0
    for path in files(settings):
        relative = path[len("Documents/"):]
        if relative in known or relative.startswith("SnowRunner/sandbox/base/logs/"):
            copy_from(settings, path, directory / relative)
            count += 1
    print("Saved {} log files to {}".format(count, directory))


def backup(settings):
    directory = BUILD / "backups" / datetime.now().strftime("saves-%Y%m%d-%H%M%S")
    listing = files(settings)
    storage = "Documents/SnowRunner/sandbox/base/storage/"
    count = 0
    for path in listing:
        if path.startswith(storage):
            copy_from(settings, path, directory / "storage" / path[len(storage):])
            count += 1
        elif path == "Documents/touch-controls-layout.plist":
            copy_from(settings, path, directory / "touch-controls-layout.plist")
            count += 1
    if not count:
        raise UserError("No saves or control layout were found in this app container.")
    print("Saved {} files to {}".format(count, directory))

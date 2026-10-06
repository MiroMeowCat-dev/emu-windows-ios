"""Small shared helpers; no packages beyond Python's standard library."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else ROOT
BUILD = WORKSPACE / ("output" if getattr(sys, "frozen", False) else "build")
CONFIG = WORKSPACE / "config.local.json"
DEFAULT_GAME = Path.home() / "Library/Application Support/Steam/steamapps/common/SnowRunner/SnowRunner.app"


class UserError(Exception):
    """An actionable setup/build error, shown without a Python traceback."""


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise UserError("Cannot read {}: {}".format(path, error)) from error


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(arguments, cwd=None, log=None, capture=False, timeout=None):
    arguments = [str(item) for item in arguments]
    if log:
        log = Path(log)
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w") as stream:
            result = subprocess.run(arguments, cwd=cwd or ROOT, stdout=stream,
                                    stderr=subprocess.STDOUT, text=True, timeout=timeout)
        output = "\n".join(log.read_text(errors="replace").splitlines()[-18:])
    else:
        result = subprocess.run(arguments, cwd=cwd or ROOT, text=True, timeout=timeout,
                                stdout=subprocess.PIPE if capture else None,
                                stderr=subprocess.PIPE if capture else None)
        output = (result.stdout or "") + (result.stderr or "")
    if result.returncode:
        hint = "\nFull log: {}".format(log) if log else ""
        raise UserError("{} failed ({}).\n{}{}".format(arguments[0], result.returncode, output.strip(), hint))
    return result.stdout.strip() if capture and result.stdout else ""


def config(required=True):
    if not CONFIG.exists():
        if required:
            raise UserError("Run ./emu setup first (or copy config.example.json to config.local.json).")
        return {"game": str(DEFAULT_GAME), "team": "", "bundle_id": "", "device": ""}
    value = read_json(CONFIG)
    if not isinstance(value, dict) or any(not isinstance(value.get(k, ""), str) for k in ["game", "team", "bundle_id", "device"]):
        raise UserError("config.local.json must be an object with string values for game, team, bundle_id and device.")
    value["game"] = str(Path(value.get("game", str(DEFAULT_GAME))).expanduser().resolve())
    return value


def sdk_path():
    return Path(run(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], capture=True))


def fingerprint(paths):
    """Content-based cache key; changing tools/patches invalidates prepared output."""
    digest = hashlib.sha256()
    for path in sorted(map(Path, paths)):
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def toolchain_key():
    """Xcode may be updated in place without changing its installation path."""
    return "\n".join([str(sdk_path()),
        run(["xcrun", "--sdk", "iphoneos", "--show-sdk-version"], capture=True),
        run(["xcodebuild", "-version"], capture=True)])

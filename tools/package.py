"""Export signed app-only IPAs and verify archive integrity on any computer."""
from pathlib import Path, PurePosixPath
import plistlib
import tempfile
from zipfile import BadZipFile, ZipFile

from .common import BUILD, ROOT, UserError, read_json, run, sha256, write_json


def validate_ipa(path, require_profile=True):
    """Check layout and CRCs; this does not validate Apple's code signature."""
    try:
        with ZipFile(path) as ipa:
            names = ipa.namelist()
            if len(names) != len(set(names)):
                raise UserError("IPA archive contains duplicate entries.")
            for name in names:
                relative = PurePosixPath(name)
                if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
                    raise UserError("IPA archive contains an invalid path.")
            info_paths = [name for name in names if len(PurePosixPath(name).parts) == 3
                          and name.startswith("Payload/") and name.endswith(".app/Info.plist")]
            if len(info_paths) != 1:
                raise UserError("IPA must contain exactly one Payload/*.app/Info.plist.")
            info_path = info_paths[0]
            if ipa.getinfo(info_path).file_size > 1024 * 1024:
                raise UserError("IPA Info.plist is too large.")
            info = plistlib.loads(ipa.read(info_path))
            if not isinstance(info, dict):
                raise UserError("IPA Info.plist must be a dictionary.")
            executable = info.get("CFBundleExecutable")
            bundle = info.get("CFBundleIdentifier")
            if not isinstance(executable, str) or not executable or executable in {".", ".."} or any(
                    character in executable for character in "/\\:\0"):
                raise UserError("IPA has an invalid CFBundleExecutable.")
            if not isinstance(bundle, str) or not bundle:
                raise UserError("IPA has no CFBundleIdentifier.")
            root = info_path.rsplit("/", 1)[0] + "/"
            required = [root + executable]
            if require_profile:
                required.append(root + "embedded.mobileprovision")
            for name in required:
                if name not in names or ipa.getinfo(name).is_dir() or not ipa.getinfo(name).file_size:
                    raise UserError("IPA archive is missing its executable or provisioning profile.")
            if ipa.testzip() is not None:
                raise UserError("IPA archive is damaged.")
            return {"bundle_id": bundle, "executable": executable,
                    "app_version": str(info.get("CFBundleShortVersionString", "")),
                    "app_build": str(info.get("CFBundleVersion", ""))}
    except (BadZipFile, ValueError, EOFError) as error:
        raise UserError("IPA export is not a valid archive: " + str(error)) from error


def check_package(path, receipt=None):
    path = Path(path).expanduser().resolve()
    receipt_path = Path(receipt).expanduser().resolve() if receipt else path.with_suffix(".json")
    saved = read_json(receipt_path)
    if not isinstance(saved, dict) or saved.get("format_version") != 1:
        raise UserError("Unsupported package receipt. Export again with ./emu package.")
    if sha256(path) != saved.get("ipa_sha256"):
        raise UserError("IPA checksum mismatch. The package differs from its export receipt.")
    metadata = validate_ipa(path, require_profile=saved.get("signing_state") != "unsigned")
    if metadata["bundle_id"] != saved.get("bundle_id") or metadata["executable"] != saved.get("executable"):
        raise UserError("IPA metadata differs from its export receipt.")
    return metadata


def export_ipa(app, settings, output=None):
    app = Path(app).resolve()
    if not app.is_dir():
        raise UserError("Signed app not found: " + str(app))
    destination = (Path(output).expanduser() if output else BUILD / "exports/SnowRunner.ipa").resolve()
    if destination.suffix.lower() != ".ipa":
        raise UserError("The package output must have an .ipa extension.")
    if app == destination or app in destination.parents:
        raise UserError("IPA output must be outside the signed app bundle.")
    if settings.get("game"):
        original = Path(settings["game"]).expanduser().resolve()
        if original == destination or original in destination.parents:
            raise UserError("IPA output must be outside the original game app.")
    receipt_path = destination.with_suffix(".json")
    if receipt_path.exists():
        saved = read_json(receipt_path)
        if not isinstance(saved, dict) or saved.get("format_version") != 1 or not isinstance(saved.get("ipa_sha256"), str):
            raise UserError("This output would replace an unrelated JSON file. Choose another IPA path.")
    if not (app / "embedded.mobileprovision").is_file():
        raise UserError("The app has no embedded provisioning profile; build it with device signing first.")
    game = read_json(ROOT / "data/supported-game.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    run(["codesign", "--verify", "--deep", "--strict", app], capture=True)
    # Staging beside the destination keeps the final replacement atomic, even
    # when --output is on another disk. A failed export retains any old IPA.
    with tempfile.TemporaryDirectory(prefix=".emu-ipa-", dir=destination.parent) as directory:
        staging = Path(directory)
        payload = staging / "Payload"
        payload.mkdir()
        copy = payload / app.name
        run(["ditto", app, copy], capture=True)
        run(["codesign", "--verify", "--deep", "--strict", copy], capture=True)
        archive = staging / "SnowRunner.ipa"
        run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", payload, archive], capture=True)
        metadata = validate_ipa(archive)
        if metadata["bundle_id"] != settings.get("bundle_id"):
            raise UserError("Built app bundle ID differs from your settings. Rebuild before exporting.")
        receipt = dict(metadata, format_version=1, game=game["game"],
                       game_version=game["version"], game_build=game["bundle_version"],
                       ipa_sha256=sha256(archive), includes_game_resources=False)
        archive.replace(destination)
        write_json(receipt_path, receipt)
    print("Signed app package: " + str(destination))
    print("The game resources are separate. Run ./emu resources on the target phone before playing.")
    return destination

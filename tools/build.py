"""Xcode configuration and signing; no personal values are committed."""
import re
from pathlib import Path

from .common import BUILD, ROOT, UserError, run
from .prepare import ensure_prepared

APP = BUILD / "DerivedData/Build/Products/Debug-iphoneos/SnowRunner.app"


def validate_settings(settings, signing=True):
    team = settings.get("team", "")
    bundle = settings.get("bundle_id", "")
    if signing and not re.fullmatch(r"[A-Z0-9]{10}", team):
        raise UserError("Set a 10-character Apple Development team ID with ./emu setup --team YOURTEAMID.")
    if bundle and not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", bundle):
        raise UserError("bundle_id must be a reverse-DNS identifier, for example dev.yourname.emu.snowrunner.")
    if signing and (not bundle or "yourname" in bundle):
        raise UserError("Choose your own bundle_id with ./emu setup --bundle-id dev.yourname.emu.snowrunner.")


def write_local_settings(settings, signing=True):
    validate_settings(settings, signing)
    text = "// Generated from config.local.json. Do not commit.\n"
    text += "DEVELOPMENT_TEAM = {}\n".format(settings.get("team", ""))
    text += "PRODUCT_BUNDLE_IDENTIFIER = {}\n".format(settings.get("bundle_id") or "local.emu.snowrunner")
    (ROOT / "Config/Local.xcconfig").write_text(text)


def build(settings, unsigned=False):
    write_local_settings(settings, signing=not unsigned)
    ensure_prepared(Path(settings["game"]))
    print("Building {}app...".format("unsigned " if unsigned else "and signing the "), flush=True)
    destination = "generic/platform=iOS"
    if not unsigned and settings.get("device"):
        destination = "id=" + settings["device"]
    arguments = ["xcodebuild", "-project", ROOT / "SnowRunner.xcodeproj", "-scheme", "SnowRunner",
                 "-configuration", "Debug", "-destination", destination,
                 "-derivedDataPath", BUILD / "DerivedData", "CODE_SIGNING_ALLOWED=" + ("NO" if unsigned else "YES")]
    if not unsigned:
        arguments += ["-allowProvisioningUpdates", "-allowProvisioningDeviceRegistration"]
    run(arguments + ["build"], log=BUILD / "logs/app-build.log")
    if not APP.is_dir():
        raise UserError("Xcode did not create the expected app: " + str(APP))
    if not unsigned:
        run(["codesign", "--verify", "--deep", "--strict", APP], capture=True)
    print("App: " + str(APP))
    return APP

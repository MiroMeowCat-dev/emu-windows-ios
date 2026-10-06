"""Portable, local assembly of an iOS app from a public runtime and owned files."""
import hashlib
import json
import plistlib
import re
import shutil
import stat
import struct
import tempfile
from pathlib import Path
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile, ZipInfo

from .common import ROOT, UserError, read_json, sha256, write_json
from .macho import CPU_TYPE_ARM64, commands, remove_signature
from .package import validate_ipa
from .prepare import ROUTED, framework_info, patch_library
from .resources import safe_relative
from .source import game_metadata, validated_binary

APP_ROOT = "Payload/SnowRunner.app/"
CORE_FRAMEWORKS = {"SDL2", "SDLBridge", "MacCompat"} | {"Compat" + name for name in ROUTED | {"System"}}
GAME_FRAMEWORKS = {"GameClient", "EOS", "SteamAPI"}
MAX_RUNTIME_BYTES = 512 * 1024 * 1024


def contract_key(root=ROOT):
    """Stable across Git checkouts with Windows CRLF and POSIX LF endings."""
    root = Path(root)
    paths = []
    for pattern in ["app/Host/*", "app/Compat/*", "data/*.json", "patches/sdl2-ios.patch"]:
        paths.extend(path for path in root.glob(pattern) if path.is_file())
    paths += [root / "tools" / name for name in ["windows.py", "runtime.py", "prepare.py", "macho.py",
                                                "sdl.py", "unsupported-template.m"]]
    digest = hashlib.sha256()
    for path in sorted(set(paths), key=lambda item: item.relative_to(root).as_posix()):
        name = path.relative_to(root).as_posix().encode("utf-8")
        data = path.read_bytes().replace(b"\r\n", b"\n")
        digest.update(struct.pack("<I", len(name)) + name + struct.pack("<Q", len(data)) + data)
    return digest.hexdigest()


def validate_ios_binary(data, filetype):
    table = list(commands(data))
    if struct.unpack_from("<I", data, 4)[0] != CPU_TYPE_ARM64 or struct.unpack_from("<I", data, 12)[0] != filetype:
        raise UserError("Runtime requires native ARM64 iOS executables/frameworks.")
    builds = [command for kind, _, command in table if kind == 0x32]
    if len(builds) != 1 or len(builds[0]) < 24 or struct.unpack_from("<I", builds[0], 8)[0] != 2:
        raise UserError("Runtime binary is not built for physical iOS devices.")


def inspect_runtime(path, destination=None, progress=None):
    """Verify checksums and the source contract before extracting any file.

    Checksums establish integrity, not publisher identity. Use an artifact from
    your own reviewed cloud build. No ZIP content is ever executed on Windows.
    """
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            names = [item.filename for item in entries]
            if len(names) > 4000 or len(names) != len({name.casefold().rstrip("/") for name in names}):
                raise UserError("Runtime has too many files or duplicate paths.")
            for item in entries:
                name = safe_relative(item.filename)
                if name != item.filename.rstrip("/") or any(part.rstrip(". ") != part for part in name.split("/")):
                    raise UserError("Noncanonical runtime path: " + item.filename)
                reserved = {"con", "prn", "aux", "nul"} | {prefix + str(n) for prefix in ["com", "lpt"] for n in range(1, 10)}
                if any(part.split(".")[0].casefold() in reserved or any(ord(c) < 32 for c in part) for part in name.split("/")):
                    raise UserError("Runtime path is not a regular Windows filename.")
                if stat.S_ISLNK(item.external_attr >> 16):
                    raise UserError("Runtime archive must not contain symbolic links.")
                if not (item.filename.startswith(APP_ROOT) or item.filename == "runtime.json"):
                    raise UserError("Unexpected file in runtime: " + item.filename)
            files = {item.filename: item for item in entries if not item.is_dir()}
            if "runtime.json" not in files or files["runtime.json"].file_size > 1024 * 1024:
                raise UserError("Select emu-ios-runtime.zip, not the outer GitHub artifact ZIP.")
            if sum(item.file_size for item in entries) > MAX_RUNTIME_BYTES:
                raise UserError("Public runtime exceeds the 512 MB limit.")
            manifest = json.loads(archive.read("runtime.json"))
            if not isinstance(manifest, dict) or manifest.get("format_version") != 1 or manifest.get("contract_key") != contract_key():
                raise UserError("Runtime and Windows tool are from different source versions. Rebuild the runtime with this toolkit.")
            expected = manifest.get("files")
            if not isinstance(expected, dict) or set(expected) != set(files) - {"runtime.json"}:
                raise UserError("Runtime file inventory differs from its manifest.")
            for name in expected:
                if any(("/" + framework + ".framework/") in name for framework in GAME_FRAMEWORKS):
                    raise UserError("Public runtime must not contain proprietary game frameworks.")
                if "_CodeSignature/" in name or name.endswith("embedded.mobileprovision"):
                    raise UserError("Use a public runtime without personal signing material.")
                item = expected[name]
                if not isinstance(item, dict) or item.get("bytes") != files[name].file_size:
                    raise UserError("Invalid runtime size record: " + name)
                with archive.open(name) as stream:
                    digest = hashlib.sha256()
                    for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                        digest.update(block)
                if digest.hexdigest() != item.get("sha256"):
                    raise UserError("Runtime checksum mismatch: " + name)
            info = plistlib.loads(archive.read(APP_ROOT + "Info.plist"))
            if not isinstance(info, dict) or info.get("CFBundleExecutable") != "SnowRunner":
                raise UserError("Invalid runtime app metadata.")
            validate_ios_binary(archive.read(APP_ROOT + "SnowRunner"), 2)
            for name in sorted(CORE_FRAMEWORKS):
                binary = APP_ROOT + "Frameworks/{0}.framework/{0}".format(name)
                metadata = APP_ROOT + "Frameworks/{}.framework/Info.plist".format(name)
                if binary not in files or metadata not in files:
                    raise UserError("Runtime is missing framework " + name)
                validate_ios_binary(archive.read(binary), 6)
                framework = plistlib.loads(archive.read(metadata))
                if framework.get("CFBundleExecutable") != name:
                    raise UserError("Runtime has invalid framework metadata: " + name)
            if archive.read(APP_ROOT + "resources.json").replace(b"\r\n", b"\n") != (ROOT / "data/resources.json").read_bytes().replace(b"\r\n", b"\n"):
                raise UserError("Runtime resource manifest differs from the toolkit.")
            if destination:
                destination = Path(destination).resolve()
                for name in expected:
                    target = (destination / name).resolve()
                    if not target.is_relative_to(destination):
                        raise UserError("Runtime path escapes output directory.")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(name) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output, 4 * 1024 * 1024)
                    target.chmod(0o755 if name.endswith("/SnowRunner") or any(
                        name.endswith("/{0}.framework/{0}".format(f)) for f in CORE_FRAMEWORKS) else 0o644)
            if progress:
                progress("运行库校验完成（完整性和版本匹配；未验证发布者身份）。")
            return manifest
    except (BadZipFile, ValueError, EOFError, KeyError, AttributeError, struct.error) as error:
        raise UserError("Invalid runtime archive: " + str(error)) from error


def zip_app(directory, output):
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted((Path(directory) / "Payload").rglob("*")):
            if not path.is_file():
                continue
            name = path.relative_to(directory).as_posix()
            info = ZipInfo(name)
            info.create_system = 3
            executable = path.name == "SnowRunner" or path.parent.name == path.name + ".framework"
            info.external_attr = (0o100755 if executable else 0o100644) << 16
            info.compress_type = ZIP_DEFLATED
            with path.open("rb") as source, archive.open(info, "w", force_zip64=True) as target:
                shutil.copyfileobj(source, target, 4 * 1024 * 1024)


def assemble(runtime, output, game=None, bundle_id="local.emu.snowrunner", progress=print):
    output, runtime = Path(output).expanduser().resolve(), Path(runtime).expanduser().resolve()
    if not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+){2,}", bundle_id):
        raise UserError("Bundle ID must have at least three dot-separated components, such as local.emu.snowrunner.")
    if output.suffix.lower() != ".ipa" or output == runtime:
        raise UserError("Choose a separate .ipa output file.")
    receipt = output.with_suffix(".json")
    if receipt.exists():
        previous = read_json(receipt)
        if not isinstance(previous, dict) or previous.get("windows_package") != 1:
            raise UserError("Output would overwrite unrelated JSON. Choose another IPA filename.")
    if game:
        game = Path(game).expanduser().resolve()
        if output.is_relative_to(game) or receipt.is_relative_to(game):
            raise UserError("Output must be outside the original game directory.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".emu-assemble-", dir=output.parent) as temporary:
        temporary = Path(temporary)
        manifest = inspect_runtime(runtime, temporary, progress)
        app = temporary / APP_ROOT
        reports = []
        if game:
            pin = read_json(ROOT / "data/supported-game.json")
            game_metadata(game, pin)
            for entry in pin["binaries"]:
                progress("处理并校验 " + entry["framework"] + "…")
                original = validated_binary(game, entry)
                data, report = patch_library(entry, remove_signature(original), pin)
                framework = app / "Frameworks" / (entry["framework"] + ".framework")
                framework_info(framework, entry["framework"])
                (framework / entry["framework"]).write_bytes(data)
                reports.append(report)
        info_path = app / "Info.plist"
        info = plistlib.loads(info_path.read_bytes())
        info.update(CFBundleIdentifier=bundle_id, EmuWindowsMenu=True, EmuDiagnosticOnly=not bool(game))
        info["CFBundleDisplayName"] = "Emu Check" if not game else "SnowRunner"
        info_path.write_bytes(plistlib.dumps(info))
        package = temporary / "assembled.ipa"
        zip_app(temporary, package)
        metadata = validate_ipa(package, require_profile=False)
        saved = dict(metadata, format_version=1, windows_package=1, signing_state="unsigned",
                     ipa_sha256=sha256(package), runtime_contract=manifest["contract_key"],
                     diagnostic_only=not bool(game), includes_game_resources=False,
                     device_tested=False, binaries=reports,
                     required_entitlements={"com.apple.developer.kernel.increased-memory-limit": True})
        # The receipt hash detects an interrupted two-file commit on the next check.
        package.replace(output)
        write_json(receipt, saved)
    progress("IPA 已生成，尚未签名：" + str(output))
    progress("使用 Windows 侧载工具签名安装；Apple ID 只在侧载工具中填写。")
    return output


def stage_resources(game, output, progress=print):
    """Create a folder the iPhone document picker can import from USB/Files.

    Re-hash existing outputs on resume, stream and verify copies before replace,
    never include saves, and never trust the generated receipt as content proof.
    """
    game, output = Path(game).expanduser().resolve(), Path(output).expanduser().resolve()
    if output.is_relative_to(game) or game.is_relative_to(output):
        raise UserError("Resource staging must use a separate directory outside the original game.")
    if output.suffix != ".emuresources":
        raise UserError("Choose a folder ending in .emuresources (not a ZIP file).")
    game_metadata(game, read_json(ROOT / "data/supported-game.json"))
    manifest = read_json(ROOT / "data/resources.json")
    items = manifest["files"] + manifest.get("generated_files", [])
    marker = output / "emu-resources-manifest.json"
    if output.exists() and (not marker.is_file() or read_json(marker).get("windows_resources") != 1):
        raise UserError("Output is an existing unrelated directory. Choose a new .emuresources folder.")
    for item in items:
        relative = safe_relative(item["path"])
        source = (game / "Contents/Resources" / relative).resolve()
        if not source.is_relative_to(game / "Contents/Resources"):
            raise UserError("Resource source links outside the game: " + relative)
        if "text" not in item and (not source.is_file() or source.stat().st_size != item["bytes"]):
            raise UserError("Missing or wrong-sized resource: " + relative)
    output.mkdir(parents=True, exist_ok=True)
    write_json(marker, {"windows_resources": 1, "complete": False, "contract_key": contract_key()})
    total = len(items)
    for index, item in enumerate(items, 1):
        relative = item["path"]
        target = (output / "Resources" / relative).resolve()
        if not target.is_relative_to(output):
            raise UserError("Resource output links outside staging folder: " + relative)
        progress("资源 {}/{}：{}".format(index, total, relative))
        if target.is_file() and target.stat().st_size == item["bytes"] and sha256(target) == item["sha256"]:
            continue
        required = item["bytes"] + 64 * 1024 * 1024
        if shutil.disk_usage(output).free < required:
            raise UserError("Not enough staging disk space for " + relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("wb", prefix=".emu-", dir=target.parent, delete=False) as stream:
            partial = Path(stream.name)
            try:
                if "text" in item:
                    stream.write(item["text"].encode("utf-8"))
                else:
                    with (game / "Contents/Resources" / relative).open("rb") as source:
                        shutil.copyfileobj(source, stream, 4 * 1024 * 1024)
                stream.close()
                if partial.stat().st_size != item["bytes"] or sha256(partial) != item["sha256"]:
                    raise UserError("Resource checksum mismatch; previous output retained: " + relative)
                partial.replace(target)
            finally:
                if partial.exists():
                    partial.unlink()
    write_json(marker, {"windows_resources": 1, "complete": True, "contract_key": contract_key(),
                        "files": items, "resource_bytes": sum(item["bytes"] for item in items)})
    progress("资源准备完成：" + str(output))
    return output

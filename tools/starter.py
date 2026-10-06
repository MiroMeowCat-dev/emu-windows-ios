"""Combine this build's Windows EXE and real public runtime, then verify the EXE."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .common import BUILD, UserError, read_json, sha256, write_json
from .package import check_package
from .windows import contract_key, inspect_runtime


def starter(portable, runtime, output=None):
    if os.name != "nt":
        raise UserError("The starter verification must run on Windows.")
    portable, runtime = Path(portable).resolve(), Path(runtime).resolve()
    manifest = inspect_runtime(runtime)
    output = Path(output).resolve() if output else BUILD / "releases/EmuWindows-starter.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".emu-starter-", dir=output.parent) as directory:
        directory = Path(directory)
        # Exercise a Unicode path as well as a machine with Python off PATH.
        staging = directory / "中文路径"
        with ZipFile(portable) as archive:
            names = archive.namelist()
            if (len(names) != len(set(names)) or sum(i.file_size for i in archive.infolist()) > 512 * 1024 * 1024
                    or any(not name.startswith("EmuWindows/") or "\\" in name or ":" in name
                           or any(part in {"", ".", ".."} for part in name.split("/")) for name in names)):
                raise UserError("Unexpected portable archive paths or size.")
            if archive.testzip():
                raise UserError("Portable archive failed its CRC check.")
            archive.extractall(staging)
        app = staging / "EmuWindows"
        executable = app / "EmuWindows.exe"
        if not executable.is_file() or read_json(app / "build-info.json").get("contract_key") != contract_key():
            raise UserError("Windows EXE and runtime source versions differ.")
        (app / "runtime").mkdir()
        shutil.copy2(runtime, app / "runtime/emu-ios-runtime.zip")
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env["PATH"] = os.path.join(env["SYSTEMROOT"], "System32")
        smoke = directory / "smoke.json"
        subprocess.run([str(executable), "--smoke-report", str(smoke)], env=env, check=True, timeout=60)
        checks = read_json(smoke)
        if (checks.get("contract_key") != contract_key() or not checks.get("gui_initialized")
                or Path(checks.get("detected_runtime", "")).resolve() != (app / "runtime/emu-ios-runtime.zip").resolve()):
            raise UserError("Starter GUI did not find its matching runtime.")
        diagnostic = app / "diagnostic/EmuCheck-unsigned.ipa"
        subprocess.run([str(executable), "--cli", "windows-build", "--runtime", str(app / "runtime/emu-ios-runtime.zip"),
                        "--output", str(diagnostic)], env=env, check=True, timeout=180)
        check_package(diagnostic)
        receipt = read_json(diagnostic.with_suffix(".json"))
        if receipt.get("diagnostic_only") is not True or receipt.get("binaries") or receipt.get("signing_state") != "unsigned":
            raise UserError("Unexpected diagnostic receipt.")
        write_json(app / "starter-check.json", {"contract_key": contract_key(), "runtime_source_commit": manifest.get("source_commit"),
                   "windows_source_commit": read_json(app / "build-info.json").get("source_commit"),
                   "real_ios_runtime_built": True, "frozen_exe_assembled_real_runtime": True,
                   "gui_found_bundled_runtime": True, "python_removed_from_path": True, "unicode_path_passed": True,
                   "diagnostic_sha256": sha256(diagnostic), "device_tested": False, "includes_game_content": False,
                   "signing_state": "unsigned"})
        info = read_json(app / "build-info.json")
        info["ios_runtime_included"] = True
        write_json(app / "build-info.json", info)
        (app / "START-HERE.txt").write_text(
            "Emu Windows 0.2 preview\n\n"
            "1. Open EmuWindows.exe. The public iOS runtime is already included.\n"
            "2. No game needed: diagnostic/EmuCheck-unsigned.ipa is ready for signing.\n"
            "3. Sign and install with a Windows sideloading tool, then tap Device check.\n"
            "4. Read WINDOWS-zh.md for Chinese instructions and supported game details.\n\n"
            "No game content, Apple account, certificate or installable signature is included.\n"
            "Windows .exe games are unsupported. Phone installation and gameplay remain untested.\n", encoding="utf-8")
        with ZipFile(directory / "starter.zip", "w", compression=ZIP_DEFLATED) as archive:
            for path in sorted(app.rglob("*")):
                if path.is_file():
                    archive.write(path, "EmuWindows/" + path.relative_to(app).as_posix())
        with ZipFile(directory / "starter.zip") as archive:
            if archive.testzip():
                raise UserError("Starter archive failed its CRC check.")
        (directory / "starter.zip").replace(output)
    print("Verified Windows starter: " + str(output))
    print("SHA-256: " + sha256(output))
    return output


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portable", required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        starter(args.portable, args.runtime, args.output)
    except (UserError, OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + "\n")

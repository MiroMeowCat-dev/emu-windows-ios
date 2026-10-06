"""Build a portable Windows GUI distribution; no global Python changes needed."""
import importlib.util
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .common import BUILD, ROOT, UserError, read_json, run, sha256, write_json
from .windows import contract_key


def freeze():
    if platform.system() != "Windows":
        raise UserError("Build the Windows EXE on Windows or the Windows GitHub Actions runner.")
    dependencies = BUILD / "packaging-deps"
    if dependencies.is_dir():
        sys.path.insert(0, str(dependencies))
    if not importlib.util.find_spec("PyInstaller"):
        raise UserError("Install build dependencies first: python -m pip install --target build/packaging-deps pyinstaller==6.22.3")
    # Use a small isolated search path: do not collect unrelated Anaconda/torch
    # packages from the developer's Python environment into this simple utility.
    env = dict(os.environ)
    env["PYTHONPATH"] = str(dependencies)
    arguments = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
                 "--name", "EmuWindows", "--distpath", str(BUILD / "windows-dist"),
                 "--workpath", str(BUILD / "pyinstaller-work"), "--specpath", str(BUILD / "pyinstaller-spec")]
    for name in ["app", "data", "patches", "docs"]:
        arguments += ["--add-data", str(ROOT / name) + ":" + name]
    # Source text is needed to calculate the cloud/desktop contract even when
    # modules are compiled into PyInstaller's internal archive.
    arguments += ["--add-data", str(ROOT / "tools") + ":tools", str(ROOT / "emu_windows.py")]
    import subprocess
    result = subprocess.run(arguments, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    log = BUILD / "logs/windows-freeze.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(result.stdout, encoding="utf-8")
    if result.returncode:
        raise UserError("PyInstaller failed. See " + str(log) + "\n" + result.stdout[-3000:])
    distribution = BUILD / "windows-dist/EmuWindows"
    for name in ["LICENSE", "third_party/SDL-LICENSE.txt", "docs/WINDOWS-zh.md"]:
        shutil.copy2(ROOT / name, distribution / Path(name).name)
    report = BUILD / "reports/windows-exe-smoke.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    if report.exists():
        report.unlink()
    process = subprocess.run([str(distribution / "EmuWindows.exe"), "--smoke-report", str(report)], timeout=60)
    if process.returncode or not report.is_file():
        raise UserError("Packaged EXE did not complete its GUI startup check.")
    checks = read_json(report)
    if checks.get("contract_key") != contract_key() or not all(checks.get(key) for key in ["frozen", "gui_initialized",
            "bundled_help", "game_action_disabled_without_files", "runtime_action_disabled_without_runtime"]):
        raise UserError("Packaged EXE resources or startup check failed.")
    write_json(distribution / "build-info.json", dict(checks, version="0.2-preview", device_tested=False,
               ios_runtime_included=False, source_commit="", supported_host="Windows x64", signing_included=False))
    release = BUILD / "releases/EmuWindows-portable.zip"
    release.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".emu-win-release-", dir=release.parent) as directory:
        temporary = Path(directory) / "portable.zip"
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
            for path in sorted(distribution.rglob("*")):
                if path.is_file():
                    archive.write(path, "EmuWindows/" + path.relative_to(distribution).as_posix())
        temporary.replace(release)
    print("Windows portable tool: " + str(release))
    print("SHA-256: " + sha256(release))
    return release


if __name__ == "__main__":
    try:
        freeze()
    except (UserError, OSError) as error:
        sys.exit(str(error))

"""Collect the pinned Conda runtime and validate the actual frozen application.

Run through build_win7.bat, after check_build_env.py has passed.  The only
third-party packages used here (PyInstaller and pefile) are build dependencies.
"""

import argparse
import json
import ntpath
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile


SUCCESS_MARKER = "M2507_GUI_SELF_TEST_OK"
RUNTIME_VERSION = "14.27.29016"


class PackagingError(RuntimeError):
    """A required resource or an executable validation is missing."""


def inside_prefix(path, prefix, description="Resource"):
    """Reject resources from other environments, including symlink escapes."""
    path = Path(path).resolve()
    prefix = Path(prefix).resolve()
    try:
        path.relative_to(prefix)
    except ValueError:
        raise PackagingError("{} is outside this Conda environment: {}".format(description, path))
    return path


def require_file(path, prefix, description="Required file"):
    path = inside_prefix(path, prefix, description)
    if not path.is_file():
        raise PackagingError("{} not found: {}".format(description, path))
    return path


def require_directory(path, prefix, description="Required directory"):
    path = inside_prefix(path, prefix, description)
    if not path.is_dir():
        raise PackagingError("{} not found: {}".format(description, path))
    return path


def discover_tk_libraries():
    """Ask the Tk instance that will be packaged, instead of guessing its layout."""
    import tkinter as tk

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        tcl_library = root.tk.call("info", "library")
        tk_library = root.tk.call("set", "tk_library")
        root.update_idletasks()
        return Path(str(tcl_library)), Path(str(tk_library))
    except Exception as exc:
        raise PackagingError("Cannot initialize the build environment's Tcl/Tk: {}".format(exc)) from exc
    finally:
        if root is not None:
            root.destroy()


def collect_tk_resources(prefix, tcl_library, tk_library):
    """Return explicit PyInstaller data and binary mappings for Tcl/Tk."""
    prefix = Path(prefix).resolve()
    tcl_library = require_directory(tcl_library, prefix, "Tcl library")
    tk_library = require_directory(tk_library, prefix, "Tk library")
    require_file(tcl_library / "init.tcl", prefix, "Tcl initialization script")
    require_file(tk_library / "tk.tcl", prefix, "Tk initialization script")
    tcl_modules = require_directory(tcl_library.parent / "tcl8", prefix, "Tcl modules")
    # PyInstaller 4.10's runtime hook specifically expects 'tcl' and 'tk'.
    datas = [(str(tcl_library), "tcl"), (str(tk_library), "tk"), (str(tcl_modules), "tcl8")]
    binaries = [
        (str(require_file(prefix / "python38.dll", prefix, "Python 3.8 DLL")), "."),
        (str(require_file(prefix / "Library" / "bin" / "tcl86t.dll", prefix, "Tcl DLL")), "."),
        (str(require_file(prefix / "Library" / "bin" / "tk86t.dll", prefix, "Tk DLL")), "."),
    ]
    return datas, binaries


def collect_runtime_dlls(prefix):
    """Collect only DLLs owned by the pinned Conda VC/UCRT runtime package.

    This package deliberately installs duplicate DLLs at the prefix root and in
    Library/bin.  One copy is sufficient; prefer the prefix-root copy and never
    collect unrelated DLLs from the rest of a potentially large Conda install.
    """
    prefix = Path(prefix).resolve()
    metadata = sorted((prefix / "conda-meta").glob("vs2015_runtime-*.json"))
    records = []
    for path in metadata:
        path = require_file(path, prefix, "Conda runtime metadata")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PackagingError("Cannot read Conda runtime metadata: {}".format(path)) from exc
        if record.get("name") == "vs2015_runtime":
            records.append(record)
    if len(records) != 1 or records[0].get("version") != RUNTIME_VERSION:
        raise PackagingError("Require exactly one installed vs2015_runtime={} package.".format(RUNTIME_VERSION))
    files = records[0].get("files")
    if not isinstance(files, list) or not all(isinstance(name, str) for name in files):
        raise PackagingError("Conda runtime metadata has no valid installed-file list.")

    candidates = {}
    for name in files:
        # Conda metadata uses '/' even on Windows.  Reject absolute/traversing
        # paths before resolution, including Windows syntax in Linux unit tests.
        relative = name.replace("\\", "/")
        if not relative.lower().endswith(".dll"):
            continue
        if ntpath.splitdrive(name)[0] or ntpath.isabs(name) or ".." in relative.split("/"):
            raise PackagingError("Invalid DLL path in Conda runtime metadata: {}".format(name))
        path = inside_prefix(prefix / relative, prefix, "Conda runtime DLL")
        candidates.setdefault(path.name.lower(), []).append(path)

    for required in ("vcruntime140.dll", "ucrtbase.dll"):
        if required not in candidates:
            raise PackagingError("Pinned runtime metadata does not provide {}.".format(required))

    binaries = []
    for name, paths in sorted(candidates.items()):
        paths.sort(key=lambda path: (len(path.relative_to(prefix).parts), str(path).lower()))
        found = next((path for path in paths if path.is_file()), None)
        if found is None:
            raise PackagingError("Pinned runtime DLL not found: {}".format(name))
        binaries.append((str(found), "."))
    return binaries


def pe_import_names(path):
    """Read imports without loading a Windows DLL into the build process."""
    import pefile

    try:
        pe = pefile.PE(str(path), fast_load=True)
        try:
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
            return [entry.dll.decode("ascii") for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])]
        finally:
            pe.close()
    except Exception as exc:
        raise PackagingError("Cannot inspect DLL imports for {}: {}".format(path, exc)) from exc


def collect_ffi_dlls(prefix, import_reader=pe_import_names):
    """Conda's ctypes may depend on libffi in Library/bin, outside DLLs."""
    prefix = Path(prefix).resolve()
    extension = require_file(prefix / "DLLs" / "_ctypes.pyd", prefix, "ctypes extension")
    binaries = []
    for name in import_reader(extension):
        if "ffi" not in name.lower() or not name.lower().endswith(".dll"):
            continue
        if ntpath.basename(name) != name:
            raise PackagingError("Unexpected libffi import name: {}".format(name))
        found = None
        for folder in (prefix, prefix / "Library" / "bin", prefix / "DLLs"):
            path = inside_prefix(folder / name, prefix, "libffi DLL")
            if path.is_file():
                found = path
                break
        if found is None:
            raise PackagingError("ctypes requires {}, missing from this Conda environment.".format(name))
        binaries.append((str(found), "."))
    return binaries


def isolated_environment(environ, local_app_data):
    """Build an ordinary Windows launch environment with no Conda assistance."""
    cleaned = {}
    for name, value in environ.items():
        upper = name.upper()
        if upper.startswith(("PYTHON", "CONDA", "_CONDA", "_CE_")):
            continue
        if upper in ("TCL_LIBRARY", "TK_LIBRARY", "TCLLIBPATH", "PATH", "LOCALAPPDATA"):
            continue
        cleaned[name] = value
    system_root = next((value for name, value in environ.items() if name.upper() == "SYSTEMROOT"), r"C:\Windows")
    cleaned["PATH"] = ";".join([
        ntpath.join(system_root, "System32"), system_root, ntpath.join(system_root, "System32", "Wbem")
    ])
    cleaned["LOCALAPPDATA"] = str(local_app_data)
    return cleaned


def _as_bytes(value):
    if value is None:
        return b""
    return value if isinstance(value, bytes) else str(value).encode("utf-8", errors="replace")


def run_frozen_self_test(executable, log_directory, environ=None, runner=subprocess.run):
    """Require a real full-GUI startup from the frozen EXE, without Conda PATH.

    Keep the isolated profile and both output streams under build/ even when
    validation fails.  A fresh profile prevents old success markers from masking
    a regression.  Windowed builds can report success through startup.log.
    """
    executable = Path(executable).resolve()
    log_directory = Path(log_directory).resolve()
    log_directory.mkdir(parents=True, exist_ok=True)
    if not executable.is_file():
        raise PackagingError("Frozen executable not found: {}".format(executable))
    profile = Path(tempfile.mkdtemp(prefix="self-test-profile-", dir=str(log_directory)))
    working_directory = profile / "working-directory"
    working_directory.mkdir()
    environment = isolated_environment(os.environ if environ is None else environ, profile)
    stdout_path = log_directory / "self-test.stdout.log"
    stderr_path = log_directory / "self-test.stderr.log"
    print("Frozen GUI self-test; logs: {}".format(log_directory), flush=True)
    try:
        result = runner(
            [str(executable), "--self-test"], cwd=str(working_directory), env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_bytes(_as_bytes(exc.stdout))
        stderr_path.write_bytes(_as_bytes(exc.stderr))
        raise PackagingError("Frozen GUI self-test timed out after 30 seconds. See {}".format(log_directory)) from exc
    except OSError as exc:
        stdout_path.write_bytes(b"")
        stderr_path.write_text(str(exc), encoding="utf-8")
        raise PackagingError("Cannot start the frozen EXE. See {}".format(log_directory)) from exc
    stdout_path.write_bytes(_as_bytes(result.stdout))
    stderr_path.write_bytes(_as_bytes(result.stderr))
    if result.returncode != 0:
        raise PackagingError("Frozen GUI self-test failed (exit {}). See {}".format(result.returncode, log_directory))
    marker_found = SUCCESS_MARKER.encode("ascii") in _as_bytes(result.stdout)
    if not marker_found:
        marker_found = any(SUCCESS_MARKER.encode("ascii") in path.read_bytes() for path in profile.rglob("*.log"))
    if not marker_found:
        raise PackagingError("Frozen GUI self-test returned without its success marker. See {}".format(log_directory))
    return profile


def build_command(repository, prefix, mode, tcl_library, tk_library):
    """Use explicit mappings first, so PyInstaller's TOC keeps these sources."""
    repository = Path(repository).resolve()
    prefix = Path(prefix).resolve()
    datas, binaries = collect_tk_resources(prefix, tcl_library, tk_library)
    binaries.extend(collect_runtime_dlls(prefix))
    binaries.extend(collect_ffi_dlls(prefix))
    build_directory = repository / "build" / "win64" / mode
    dist_directory = repository / "dist" / "win64" / mode
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--noupx",
        "--onefile" if mode == "onefile" else "--onedir",
        "--console" if mode == "debug" else "--windowed",
        "--name", "M2507_OTA", "--distpath", str(dist_directory),
        "--workpath", str(build_directory / "work"), "--specpath", str(build_directory),
        "--hidden-import", "serial.tools.list_ports_windows",
        "--runtime-hook", str(repository / "rthook_m2507_startup.py"),
    ]
    for folder in (prefix / "Library" / "bin", prefix / "DLLs"):
        command.extend(["--paths", str(require_directory(folder, prefix))])
    for source, destination in datas:
        command.extend(["--add-data", source + os.pathsep + destination])
    seen = set()
    for source, destination in binaries:
        name = Path(source).name.lower()
        if name not in seen:
            command.extend(["--add-binary", source + os.pathsep + destination])
            seen.add(name)
    command.append(str(repository / "m2507_launcher.py"))
    executable = dist_directory / "M2507_OTA.exe"
    if mode != "onefile":
        executable = dist_directory / "M2507_OTA" / "M2507_OTA.exe"
    return command, executable, build_directory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("debug", "onedir", "onefile"), default="onedir")
    args = parser.parse_args(argv)
    try:
        if sys.platform != "win32" or struct.calcsize("P") != 8 or sys.version_info[:3] != (3, 8, 10):
            raise PackagingError("Use the Windows x64 Conda Python 3.8.10 environment; run build_win7.bat.")
        prefix = Path(sys.prefix).resolve()
        if not os.environ.get("CONDA_PREFIX") or Path(os.environ["CONDA_PREFIX"]).resolve() != prefix:
            raise PackagingError("Activate the dedicated m2507_win7 Conda environment first.")
        repository = Path(__file__).resolve().parent
        for name in ("m2507_launcher.py", "rthook_m2507_startup.py", "run_diagnostics.bat"):
            if not (repository / name).is_file():
                raise PackagingError("Required project helper missing: {}".format(name))
        tcl_library, tk_library = discover_tk_libraries()
        command, executable, build_directory = build_command(repository, prefix, args.mode, tcl_library, tk_library)
        result = subprocess.run(command, cwd=str(repository))
        if result.returncode:
            raise PackagingError("PyInstaller failed (exit {}).".format(result.returncode))
        run_frozen_self_test(executable, build_directory)
        shutil.copy2(str(repository / "run_diagnostics.bat"), str(executable.parent / "run_diagnostics.bat"))
        print("Build and isolated frozen-GUI startup passed: {}".format(executable))
        print("Copy the whole output directory for onedir/debug; verify on Windows 7 SP1 x64 before release.")
        return 0
    except (PackagingError, OSError) as exc:
        print("ERROR: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

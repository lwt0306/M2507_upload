"""Fail before installation/packaging if the Windows Conda toolchain is wrong."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import struct
import sys


EXPECTED_PACKAGES = {
    "pyserial": "3.5",
    "pyinstaller": "4.10",
    "pyinstaller-hooks-contrib": "2022.3",
    "altgraph": "0.17.3",
    "pefile": "2023.2.7",
    "pywin32-ctypes": "0.2.2",
    "setuptools": "68.2.2",
    "pip": "23.3.2",
    "wheel": "0.41.3",
}


def main(runtime_only=False):
    errors = []
    if sys.platform != "win32":
        errors.append("Windows EXE must be built on Windows; cross-compiling is not supported.")
    if struct.calcsize("P") != 8:
        errors.append("This release targets Win7 SP1 x64; use a 64-bit Python/Conda environment.")
    if sys.version_info[:3] != (3, 8, 10):
        errors.append("Use Python 3.8.10, found " + sys.version.split()[0])
    prefix = os.environ.get("CONDA_PREFIX")
    if not prefix or Path(prefix).resolve() != Path(sys.prefix).resolve():
        errors.append("Activate the dedicated m2507_win7 Conda environment first.")

    if not runtime_only:
        for name, wanted in EXPECTED_PACKAGES.items():
            try:
                found = importlib.metadata.version(name)
                if found != wanted:
                    errors.append("{}: expected {}, found {}".format(name, wanted, found))
            except importlib.metadata.PackageNotFoundError:
                errors.append("Missing package: " + name)

    # Inspect metadata only; do not dump environment variables or credentials.
    for name, version in (("vs2015_runtime", "14.27.29016"), ("tk", "8.6.10")):
        records = list((Path(sys.prefix) / "conda-meta").glob(name + "-*.json"))
        found = [json.loads(path.read_text(encoding="utf-8")) for path in records]
        if not any(record.get("name") == name and record.get("version") == version for record in found):
            errors.append("Conda must provide {}={}; recreate from environment-win7.yml.".format(name, version))

    if not errors:
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            patchlevel = root.tk.call("info", "patchlevel")
            root.update_idletasks()
            root.destroy()
            print("Tcl/Tk:", patchlevel)
            if not runtime_only:
                import serial
                import serial.tools.list_ports_windows
                print("pyserial:", serial.VERSION)
        except Exception as exc:
            errors.append("Tkinter/serial import or GUI initialization failed: " + str(exc))

    if errors:
        for error in errors:
            print("ERROR:", error, file=sys.stderr)
        return 1
    print("Build interpreter:", sys.executable)
    print("Target: Windows {}-bit, Python 3.8.10".format(struct.calcsize("P") * 8))
    if runtime_only:
        print("Runtime preflight passed. Build dependencies may now be installed offline.")
    else:
        print("PyInstaller 4.10 preflight passed. Test the EXE on the actual Win7 SP1 target before release.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-only", action="store_true", help="Check Python/Conda/Tk before installing build packages")
    sys.exit(main(runtime_only=parser.parse_args().runtime_only))

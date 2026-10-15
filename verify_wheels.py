"""Verify the shipped Windows wheels and hash lock without network access."""
import hashlib
import json
from pathlib import Path
import re
import sys


def _normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def verify(wheel_dir, lock_file):
    wheel_dir, lock_file = Path(wheel_dir), Path(lock_file)
    manifest = json.loads((wheel_dir / "manifest.json").read_text(encoding="utf-8"))
    records = manifest["wheels"]
    expected = {}
    for record in records:
        filename = record["filename"]
        if not filename.endswith(".whl") or "/" in filename or "\\" in filename:
            raise ValueError("Invalid wheel filename: " + filename)
        name = _normalize(record["name"])
        if name in expected:
            raise ValueError("Duplicate manifest package: " + name)
        expected[name] = (record["version"], record["sha256"])
    locked = {}
    for line in lock_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s]+)\s+--hash=sha256:([a-f0-9]{64})", line)
        if match is None:
            raise ValueError("Invalid pinned requirement: " + line)
        name, version, digest = match.groups()
        name = _normalize(name)
        if name in locked:
            raise ValueError("Duplicate locked package: " + name)
        locked[name] = (version, digest)
    if not expected or expected != locked:
        raise ValueError("Wheel manifest and requirements-offline-win7.txt do not match")
    for record in records:
        path = wheel_dir / record["filename"]
        if not path.is_file():
            raise ValueError("Missing wheel: " + path.name + "; download the complete repository ZIP")
        if path.stat().st_size != record["size"]:
            raise ValueError("Wheel size mismatch: " + path.name + "; download it again")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != record["sha256"]:
            raise ValueError("Wheel SHA256 mismatch: " + path.name + "; download it again")
    return records


def main():
    root = Path(__file__).resolve().parent
    try:
        records = verify(root / "wheelhouse_win7_x64", root / "requirements-offline-win7.txt")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    for record in records:
        print("SHA256 OK:", record["filename"])
    print("Verified {} wheels. No network access was used.".format(len(records)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

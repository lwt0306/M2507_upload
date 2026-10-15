"""Verify both the shipped wheelhouse and rejection of broken offline bundles."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verify_wheels import verify


class OfflineWheelTests(unittest.TestCase):
    def test_shipped_bundle_matches_hashes_and_versions(self):
        records = verify(ROOT / 'wheelhouse_win7_x64', ROOT / 'requirements-offline-win7.txt')
        self.assertEqual(len(records), 9)
        self.assertIn(('pyinstaller', '4.10'), [(r['name'], r['version']) for r in records])

    def _fixture(self, directory):
        record = json.loads((ROOT / 'wheelhouse_win7_x64/manifest.json').read_text())['wheels'][0]
        wheel_dir = Path(directory) / 'wheels'
        wheel_dir.mkdir()
        (wheel_dir / 'manifest.json').write_text(json.dumps({'wheels': [record]}))
        lock = Path(directory) / 'requirements.txt'
        lock.write_text('{}=={} --hash=sha256:{}\n'.format(record['name'], record['version'], record['sha256']))
        return record, wheel_dir, lock

    def test_modified_wheel_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            record, wheel_dir, lock = self._fixture(directory)
            data = bytearray((ROOT / 'wheelhouse_win7_x64' / record['filename']).read_bytes())
            data[len(data) // 2] ^= 1
            (wheel_dir / record['filename']).write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                verify(wheel_dir, lock)

    def test_missing_wheel_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            _, wheel_dir, lock = self._fixture(directory)
            with self.assertRaisesRegex(ValueError, 'Missing wheel'):
                verify(wheel_dir, lock)

    def test_inconsistent_lock_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            record, wheel_dir, lock = self._fixture(directory)
            lock.write_text('{}==0.0 --hash=sha256:{}\n'.format(record['name'], record['sha256']))
            with self.assertRaisesRegex(ValueError, 'do not match'):
                verify(wheel_dir, lock)


if __name__ == '__main__':
    unittest.main()

"""Exercise real subprocess failures before importing any GUI dependencies."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EarlyStartupTests(unittest.TestCase):
    def run_child(self, code, directory, local_appdata=None):
        env = os.environ.copy()
        env.update(LOCALAPPDATA=str(local_appdata or directory), TEMP=str(directory), TMP=str(directory))
        # --self-test suppresses Windows native message boxes in intentional failures.
        return subprocess.run([sys.executable, '-c', "import sys; sys.argv.append('--self-test');\n" + code],
                              cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, encoding='utf-8', errors='replace', timeout=15)

    def test_unhandled_import_failure_is_saved_before_main(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_child('import m2507_bootstrap as b\nb.initialize()\nimport m2507_missing_dependency_sentinel', directory)
            self.assertNotEqual(result.returncode, 0)
            content = (Path(directory) / 'M2507OTA/startup.log').read_text(encoding='utf-8')
            self.assertIn('m2507_missing_dependency_sentinel', content)
            self.assertIn('Traceback', content)

    def test_windowed_streams_still_record_a_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_child('sys.stdout = sys.stderr = None\nimport m2507_bootstrap as b\nb.initialize()\nraise RuntimeError("windowed failure sentinel")', directory)
            self.assertNotEqual(result.returncode, 0)
            content = (Path(directory) / 'M2507OTA/startup.log').read_text(encoding='utf-8')
            self.assertIn('windowed failure sentinel', content)
            self.assertIn('Traceback', content)

    def test_invalid_primary_log_directory_uses_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / 'not-a-directory'
            invalid.write_text('existing user file', encoding='utf-8')
            result = self.run_child('import m2507_bootstrap as b\nb.initialize()\nb.log("fallback sentinel")', directory, invalid)
            self.assertEqual(result.returncode, 0, result.stderr)
            content = (Path(directory) / 'M2507OTA/startup.log').read_text(encoding='utf-8')
            self.assertIn('fallback sentinel', content)
            self.assertEqual(invalid.read_text(), 'existing user file')

    def test_missing_tk_bundle_is_recorded_by_early_runtime_hook(self):
        with tempfile.TemporaryDirectory() as directory:
            code = ('sys.frozen = True\n'
                    'sys._MEIPASS = ' + repr(directory) + '\n'
                    'import rthook_m2507_startup')
            result = self.run_child(code, directory)
            self.assertNotEqual(result.returncode, 0)
            content = (Path(directory) / 'M2507OTA/startup.log').read_text(encoding='utf-8')
            self.assertIn('Required bundled Tcl/Tk resource missing', content)
            self.assertIn('init.tcl', content)

    def test_launcher_catches_failure_to_import_the_application(self):
        with tempfile.TemporaryDirectory() as directory:
            code = ('import m2507_launcher\n'
                    'sys.modules["M2507_dual_core_ota_scrollable"] = None\n'
                    'sys.exit(m2507_launcher.main())')
            result = self.run_child(code, directory)
            self.assertEqual(result.returncode, 1)
            content = (Path(directory) / 'M2507OTA/startup.log').read_text(encoding='utf-8')
            self.assertIn('M2507_dual_core_ota_scrollable', content)
            self.assertIn('Traceback', content)

    def test_tk_initialization_failure_is_saved_even_without_a_tk_dialog(self):
        with tempfile.TemporaryDirectory() as directory:
            code = ('import M2507_dual_core_ota_scrollable as app\n'
                    'def fail(*args, **kwargs):\n'
                    '    raise app.tk.TclError("Tk loader failure sentinel")\n'
                    'app.tk.Tk = fail\n'
                    'sys.exit(app.main())')
            result = self.run_child(code, directory)
            self.assertEqual(result.returncode, 1)
            for filename in ('startup.log', 'error.log'):
                content = (Path(directory) / 'M2507OTA' / filename).read_text(encoding='utf-8')
                self.assertIn('Tk loader failure sentinel', content)
                self.assertIn('Traceback', content)


if __name__ == '__main__':
    unittest.main()

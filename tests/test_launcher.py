"""The frozen startup probe must fail on swallowed Tk callback exceptions."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import M2507_dual_core_ota_scrollable as app_module
import m2507_launcher


@unittest.skipUnless(sys.platform == 'win32' or os.environ.get('DISPLAY'), 'GUI requires a display')
class LauncherGuiTests(unittest.TestCase):
    def test_complete_gui_can_start_and_close(self):
        with patch.object(app_module.serial.tools.list_ports, 'comports', return_value=[]):
            self.assertEqual(m2507_launcher.self_test(app_module), 0)

    def _failing_application(self, during_destroy):
        app_class = app_module.DualCoreOtaUpgraderApp

        def construct(root):
            app = app_class(root)

            def fail(*args):
                raise RuntimeError('Tk callback failure sentinel')

            if during_destroy:
                root.bind('<Destroy>', lambda event: fail() if event.widget is root else None)
            else:
                root.after(10, fail)
            return app

        return construct

    def test_callback_failure_prevents_a_successful_probe(self):
        construct = self._failing_application(False)
        with patch.object(app_module.serial.tools.list_ports, 'comports', return_value=[]), \
                patch.object(app_module, 'DualCoreOtaUpgraderApp', side_effect=construct):
            with self.assertRaisesRegex(RuntimeError, 'Tk callback failure sentinel'):
                m2507_launcher.self_test(app_module)

    def test_destroy_callback_failure_also_prevents_success(self):
        construct = self._failing_application(True)
        with patch.object(app_module.serial.tools.list_ports, 'comports', return_value=[]), \
                patch.object(app_module, 'DualCoreOtaUpgraderApp', side_effect=construct):
            with self.assertRaisesRegex(RuntimeError, 'Tk callback failure sentinel'):
                m2507_launcher.self_test(app_module)


if __name__ == '__main__':
    unittest.main()

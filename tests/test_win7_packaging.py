"""Resource-selection and frozen-startup failure tests; no Windows APIs needed."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import package_win7 as packaging


class CondaFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="m2507-package-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.prefix = self.root / "conda"
        self.prefix.mkdir()
        self.tcl = self.prefix / "Library" / "lib" / "tcl8.6"
        self.tk = self.prefix / "Library" / "lib" / "tk8.6"
        for name in (
            "Library/lib/tcl8.6/init.tcl", "Library/lib/tk8.6/tk.tcl",
            "Library/lib/tcl8/8.5/msgcat-1.6.1.tm", "python38.dll",
            "Library/bin/tcl86t.dll", "Library/bin/tk86t.dll", "DLLs/_ctypes.pyd",
        ):
            self.make_file(name)

    def make_file(self, relative, content=b"fixture"):
        path = self.prefix / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def runtime_metadata(self, files=None, version=packaging.RUNTIME_VERSION):
        if files is None:
            files = ["vcruntime140.dll", "ucrtbase.dll"]
        metadata = self.prefix / "conda-meta" / "vs2015_runtime-fixture.json"
        metadata.parent.mkdir(exist_ok=True)
        metadata.write_text(json.dumps({
            "name": "vs2015_runtime", "version": version, "files": files,
        }), encoding="utf-8")
        return metadata

    def make_runtime(self):
        self.make_file("vcruntime140.dll")
        self.make_file("ucrtbase.dll")
        self.runtime_metadata()


class ResourceSelectionTests(CondaFixture):
    def test_actual_tk_paths_use_pyinstaller_410_destinations(self):
        datas, binaries = packaging.collect_tk_resources(self.prefix, self.tcl, self.tk)
        self.assertEqual([destination for _, destination in datas], ["tcl", "tk", "tcl8"])
        self.assertEqual({Path(source).name for source, _ in binaries}, {
            "python38.dll", "tcl86t.dll", "tk86t.dll",
        })

    def test_missing_tcl_initialization_aborts_instead_of_packaging_empty_data(self):
        (self.tcl / "init.tcl").unlink()
        with self.assertRaisesRegex(packaging.PackagingError, "initialization script"):
            packaging.collect_tk_resources(self.prefix, self.tcl, self.tk)

    def test_missing_tcl_modules_aborts(self):
        module = self.prefix / "Library/lib/tcl8/8.5/msgcat-1.6.1.tm"
        module.unlink()
        module.parent.rmdir()
        module.parent.parent.rmdir()
        with self.assertRaisesRegex(packaging.PackagingError, "Tcl modules"):
            packaging.collect_tk_resources(self.prefix, self.tcl, self.tk)

    def test_external_tk_installation_is_rejected(self):
        external = self.root / "other-tk"
        external.mkdir()
        (external / "tk.tcl").write_text("fixture", encoding="utf-8")
        with self.assertRaisesRegex(packaging.PackagingError, "outside"):
            packaging.collect_tk_resources(self.prefix, self.tcl, external)

    def test_resource_symlink_cannot_escape_conda_prefix(self):
        external = self.root / "other-python38.dll"
        external.write_bytes(b"fixture")
        path = self.prefix / "python38.dll"
        path.unlink()
        try:
            path.symlink_to(external)
        except OSError:
            self.skipTest("This platform does not permit symlinks")
        with self.assertRaisesRegex(packaging.PackagingError, "outside"):
            packaging.collect_tk_resources(self.prefix, self.tcl, self.tk)

    def test_runtime_is_metadata_owned_and_deduplicated_with_prefix_priority(self):
        root_runtime = self.make_file("vcruntime140.dll", b"preferred")
        self.make_file("Library/bin/vcruntime140.dll", b"duplicate")
        ucrt = self.make_file("ucrtbase.dll")
        self.make_file("Library/bin/unrelated-large-library.dll")
        self.runtime_metadata([
            "Library/bin/vcruntime140.dll", "ucrtbase.dll", "vcruntime140.dll",
        ])
        binaries = packaging.collect_runtime_dlls(self.prefix)
        self.assertEqual({Path(source) for source, _ in binaries}, {root_runtime, ucrt})

    def test_runtime_falls_back_to_its_own_other_installed_copy(self):
        alternate = self.make_file("Library/bin/vcruntime140.dll")
        self.make_file("ucrtbase.dll")
        self.runtime_metadata(["vcruntime140.dll", "Library/bin/vcruntime140.dll", "ucrtbase.dll"])
        binaries = packaging.collect_runtime_dlls(self.prefix)
        self.assertIn((str(alternate), "."), binaries)

    def test_unpinned_runtime_is_rejected(self):
        self.runtime_metadata(version="14.99.99999")
        with self.assertRaisesRegex(packaging.PackagingError, packaging.RUNTIME_VERSION):
            packaging.collect_runtime_dlls(self.prefix)

    def test_missing_runtime_dll_is_rejected(self):
        self.runtime_metadata()
        self.make_file("vcruntime140.dll")
        with self.assertRaisesRegex(packaging.PackagingError, "ucrtbase"):
            packaging.collect_runtime_dlls(self.prefix)

    def test_metadata_does_not_authorize_paths_outside_prefix(self):
        self.runtime_metadata(["../injected.dll", "vcruntime140.dll", "ucrtbase.dll"])
        with self.assertRaisesRegex(packaging.PackagingError, "Invalid DLL path"):
            packaging.collect_runtime_dlls(self.prefix)

    def test_libffi_import_is_collected_from_this_conda_environment(self):
        ffi = self.make_file("Library/bin/libffi-7.dll")
        binaries = packaging.collect_ffi_dlls(self.prefix, lambda _: ["KERNEL32.dll", "libffi-7.dll"])
        self.assertEqual(binaries, [(str(ffi), ".")])

    def test_unresolved_libffi_import_aborts(self):
        with self.assertRaisesRegex(packaging.PackagingError, "libffi-7"):
            packaging.collect_ffi_dlls(self.prefix, lambda _: ["libffi-7.dll"])

    def test_build_command_uses_launcher_runtime_hook_and_correct_layout(self):
        self.make_runtime()
        for mode in ("debug", "onedir", "onefile"):
            with self.subTest(mode=mode), mock.patch.object(packaging, "collect_ffi_dlls", return_value=[]):
                command, executable, work = packaging.build_command(
                    self.root, self.prefix, mode, self.tcl, self.tk,
                )
                self.assertEqual(command[-1], str(self.root / "m2507_launcher.py"))
                hook_position = command.index("--runtime-hook")
                self.assertEqual(command[hook_position + 1], str(self.root / "rthook_m2507_startup.py"))
                self.assertIn("--noupx", command)
                self.assertIn("--console" if mode == "debug" else "--windowed", command)
                self.assertIn("--onefile" if mode == "onefile" else "--onedir", command)
                paths = [command[i + 1] for i, item in enumerate(command) if item == "--paths"]
                self.assertEqual(paths, [str(self.prefix / "Library/bin"), str(self.prefix / "DLLs")])
                data_mappings = [command[i + 1] for i, item in enumerate(command) if item == "--add-data"]
                self.assertIn(str(self.tcl) + os.pathsep + "tcl", data_mappings)
                self.assertEqual(work, self.root / "build/win64" / mode)
                expected = self.root / "dist/win64" / mode
                if mode != "onefile":
                    expected /= "M2507_OTA"
                self.assertEqual(executable, expected / "M2507_OTA.exe")


class FrozenStartupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="m2507-frozen-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.executable = self.root / "M2507_OTA.exe"
        self.executable.write_bytes(b"fixture")
        self.logs = self.root / "build-logs"

    def run_self_test(self, runner, environ=None):
        return packaging.run_frozen_self_test(self.executable, self.logs, environ=environ or {}, runner=runner)

    def test_environment_removes_python_conda_and_tcl_influences(self):
        environment = {
            "SystemRoot": r"C:\Windows", "Path": r"D:\Anaconda;D:\Anaconda\envs\m2507\Library\bin",
            "CONDA_PREFIX": r"D:\Anaconda\envs\m2507", "_CONDA_EXE": r"D:\Anaconda\Scripts\conda.exe",
            "CONDA_PREFIX_1": r"D:\Anaconda", "_CE_CONDA": "conda", "PYTHONPATH": "external",
            "PYTHONHOME": "external", "pythonstartup": "external.py", "TCL_LIBRARY": "external",
            "TK_LIBRARY": "external", "TCLLIBPATH": "external", "LOCALAPPDATA": "old-profile",
            "KEEP_ME": "fixture",
        }
        cleaned = packaging.isolated_environment(environment, "new-profile")
        self.assertEqual(cleaned, {
            "SystemRoot": r"C:\Windows", "KEEP_ME": "fixture", "LOCALAPPDATA": "new-profile",
            "PATH": r"C:\Windows\System32;C:\Windows;C:\Windows\System32\Wbem",
        })

    def test_console_marker_and_exit_zero_are_success(self):
        def runner(command, **kwargs):
            self.assertEqual(command, [str(self.executable), "--self-test"])
            self.assertEqual(kwargs["timeout"], 30)
            working_directory = Path(kwargs["cwd"])
            self.assertTrue(working_directory.is_dir())
            self.assertNotEqual(working_directory, self.executable.parent)
            return subprocess.CompletedProcess(command, 0, (packaging.SUCCESS_MARKER + "\n").encode(), b"")
        profile = self.run_self_test(runner)
        self.assertTrue(profile.is_dir())
        self.assertIn(packaging.SUCCESS_MARKER, (self.logs / "self-test.stdout.log").read_text())

    def test_windowed_success_can_be_recorded_in_startup_log(self):
        def runner(command, **kwargs):
            logfile = Path(kwargs["env"]["LOCALAPPDATA"]) / "M2507OTA" / "startup.log"
            logfile.parent.mkdir()
            logfile.write_text(packaging.SUCCESS_MARKER, encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, b"", b"")
        profile = self.run_self_test(runner)
        self.assertTrue((profile / "M2507OTA/startup.log").is_file())

    def test_nonzero_exit_keeps_output_and_aborts_even_with_marker(self):
        def runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, packaging.SUCCESS_MARKER.encode(), b"startup failure")
        with self.assertRaisesRegex(packaging.PackagingError, "exit 1"):
            self.run_self_test(runner)
        self.assertEqual((self.logs / "self-test.stderr.log").read_bytes(), b"startup failure")

    def test_exit_zero_without_marker_is_a_failure(self):
        with self.assertRaisesRegex(packaging.PackagingError, "success marker"):
            self.run_self_test(lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, b"", b""))

    def test_old_success_log_cannot_mask_a_new_failure(self):
        old = self.logs / "self-test-profile-old"
        old.mkdir(parents=True)
        (old / "startup.log").write_text(packaging.SUCCESS_MARKER, encoding="utf-8")
        with self.assertRaisesRegex(packaging.PackagingError, "success marker"):
            self.run_self_test(lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, b"", b""))

    def test_timeout_keeps_partial_output(self):
        def runner(command, **kwargs):
            raise subprocess.TimeoutExpired(command, 30, output=b"half-started", stderr=b"hung")
        with self.assertRaisesRegex(packaging.PackagingError, "timed out"):
            self.run_self_test(runner)
        self.assertEqual((self.logs / "self-test.stdout.log").read_bytes(), b"half-started")
        self.assertEqual((self.logs / "self-test.stderr.log").read_bytes(), b"hung")

    def test_os_loader_failure_is_reported_and_saved(self):
        def runner(command, **kwargs):
            raise OSError("loader cannot start this binary")
        with self.assertRaisesRegex(packaging.PackagingError, "Cannot start"):
            self.run_self_test(runner)
        self.assertIn("loader cannot start", (self.logs / "self-test.stderr.log").read_text())


if __name__ == "__main__":
    unittest.main()

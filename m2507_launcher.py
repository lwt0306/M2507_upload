"""Frozen entry point: log first, then import the GUI and serial dependencies."""
import sys

import m2507_bootstrap


def self_test(app_module):
    root = app_module.tk.Tk()
    root.withdraw()
    callback_errors = []

    def record_callback_exception(exc_type, exc_value, exc_tb):
        # Tk normally prints callback failures and lets update() succeed.
        callback_errors.append((exc_value, exc_tb))

    root.report_callback_exception = record_callback_exception
    app = None
    try:
        app = app_module.DualCoreOtaUpgraderApp(root)
        root.update_idletasks()
        root.update()
        # Exercise the first UI-queue timer as well as synchronous construction.
        root.after(100, root.quit)
        root.mainloop()
        if not root.winfo_exists():
            raise RuntimeError("The application window was not created")
        # Inspect actual controls as well as the Tcl interpreter to detect UI failures.
        if not app.btn_start.winfo_exists() or not app.txt_log.winfo_exists():
            raise RuntimeError("The upgrade controls or log view were not created")
    finally:
        if app is not None:
            app.on_close()
        else:
            # A constructor can fail after registering a Tcl timer.
            for callback in root.tk.call("after", "info"):
                root.after_cancel(callback)
            root.destroy()
    if callback_errors:
        exc_value, exc_tb = callback_errors[0]
        raise exc_value.with_traceback(exc_tb)
    print("M2507_GUI_SELF_TEST_OK", flush=True)
    return 0


def main():
    m2507_bootstrap.initialize()
    try:
        # Keep this import inside the protected startup section.
        import M2507_dual_core_ota_scrollable as app_module
        m2507_bootstrap.log("Application dependencies imported successfully.")
        if "--self-test" in sys.argv[1:]:
            return self_test(app_module)
        result = app_module.main()
        if result:
            m2507_bootstrap.log("GUI startup returned an error; inspect error.log in the same log directory.")
        return result
    except Exception:
        m2507_bootstrap.report_exception(*sys.exc_info())
        return 1


if __name__ == "__main__":
    sys.exit(main())

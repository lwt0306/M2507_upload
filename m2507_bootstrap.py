"""Record errors before tkinter, serial, and PyInstaller's Tk runtime hook run.

Only standard-library modules are used; this module must stay independent of Tk.
Native failures before Python loads are captured by run_diagnostics.bat instead.
"""
import os
import sys

_log_stream = None
_log_path = None
_initialized = False


class _Tee:
    def __init__(self, original, log_stream):
        self.original = original
        self.log_stream = log_stream

    @property
    def encoding(self):
        return getattr(self.original, "encoding", None) or "utf-8"

    def write(self, value):
        if self.original is not None:
            try:
                self.original.write(value)
            except (OSError, ValueError, UnicodeError):
                pass
        try:
            self.log_stream.write(value)
            self.log_stream.flush()
        except (OSError, ValueError, UnicodeError):
            pass
        return len(value)

    def flush(self):
        for stream in (self.original, self.log_stream):
            if stream is not None:
                try:
                    stream.flush()
                except (OSError, ValueError):
                    pass

    def isatty(self):
        return False

    def fileno(self):
        return self.log_stream.fileno()


def log(message):
    if _log_stream is not None:
        try:
            _log_stream.write(str(message) + "\n")
            _log_stream.flush()
        except (OSError, ValueError, UnicodeError):
            pass


def log_path():
    return _log_path


def _open_log():
    seen = set()
    for variable in ("LOCALAPPDATA", "TEMP", "TMP", None):
        if variable is not None:
            base = os.environ.get(variable)
        else:
            try:
                import tempfile
                base = tempfile.gettempdir()
            except Exception:
                continue
        if not base:
            continue
        directory = os.path.join(base, "M2507OTA")
        if directory in seen:
            continue
        seen.add(directory)
        path = os.path.join(directory, "startup.log")
        try:
            os.makedirs(directory, exist_ok=True)
            # Rotate once at process startup; never rotate an open Windows file.
            if os.path.isfile(path) and os.path.getsize(path) > 1024 * 1024:
                try:
                    os.replace(path, path + ".1")
                except OSError:
                    pass
            stream = open(path, "a", encoding="utf-8", errors="backslashreplace", buffering=1)
            return path, stream
        except (OSError, ValueError):
            continue
    return None, None


def _native_error(message):
    if sys.platform != "win32" or "--self-test" in sys.argv:
        return
    try:
        import ctypes
        box = ctypes.windll.user32.MessageBoxW
        box.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        box.restype = ctypes.c_int
        location = _log_path or "日志目录不可写，请使用 run_diagnostics.bat。"
        box(None, str(message) + "\n\n启动日志：" + location,
            "M2507 启动失败", 0x10)
    except Exception:
        # ctypes itself may be the missing DLL; preserve the original error.
        pass


def report_exception(exc_type, exc_value, exc_tb, show_dialog=True):
    try:
        import traceback
        traceback.print_exception(exc_type, exc_value, exc_tb, file=sys.stderr)
    except Exception:
        log("{}: {}".format(getattr(exc_type, "__name__", exc_type), exc_value))
    if show_dialog:
        _native_error("{}: {}".format(getattr(exc_type, "__name__", exc_type), exc_value))


def initialize():
    global _initialized, _log_path, _log_stream
    if _initialized:
        return _log_path
    _initialized = True
    _log_path, _log_stream = _open_log()
    if _log_stream is not None:
        sys.stdout = _Tee(sys.stdout, _log_stream)
        sys.stderr = _Tee(sys.stderr, _log_stream)
    sys.excepthook = report_exception
    log("\n=== M2507 Python startup ===")
    log("Python: " + sys.version.replace("\n", " "))
    log("Executable: " + sys.executable)
    log("Frozen: " + str(bool(getattr(sys, "frozen", False))))
    log("Bundle directory: " + str(getattr(sys, "_MEIPASS", "source checkout")))
    if _log_stream is not None:
        try:
            import faulthandler
            faulthandler.enable(file=_log_stream, all_threads=True)
        except Exception as exc:
            log("Native traceback capture unavailable: " + str(exc))
    return _log_path

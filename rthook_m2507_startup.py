"""PyInstaller custom runtime hooks run before its built-in Tk hook."""
import os
import sys

import m2507_bootstrap

m2507_bootstrap.initialize()
m2507_bootstrap.log("Early runtime hook installed before Tcl/Tk initialization.")
try:
    if getattr(sys, "frozen", False):
        for resource in (os.path.join("tcl", "init.tcl"), os.path.join("tk", "tk.tcl")):
            path = os.path.join(sys._MEIPASS, resource)
            if not os.path.isfile(path):
                raise FileNotFoundError("Required bundled Tcl/Tk resource missing: " + path)
except Exception:
    m2507_bootstrap.report_exception(*sys.exc_info())
    raise

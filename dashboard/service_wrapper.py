"""Windows Service wrapper for the NetOps Dashboard.

Usage:
  dashboard-service.exe install        Install the service
  dashboard-service.exe --startup auto install   Install with auto-start
  dashboard-service.exe start          Start the service
  dashboard-service.exe stop           Stop the service
  dashboard-service.exe remove         Uninstall the service
  dashboard-service.exe run            Run Flask directly in console (for debugging)
"""

import os
import sys
import threading
import logging
import traceback

# Ensure the exe's directory is on sys.path FIRST — critical for frozen mode
# SCM starts services with cwd=C:\Windows\System32, so modules won't be found otherwise
if getattr(sys, "frozen", False):
    _exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    if _exe_dir not in sys.path:
        sys.path.insert(0, _exe_dir)
    os.chdir(_exe_dir)

import win32serviceutil
import win32service
import win32event
import servicemanager

SERVICE_NAME = "SystemControlDashboard"


def _setup_crash_log():
    """Set up a file logger that captures crashes before Flask logging is configured."""
    from runtime import LOG_DIR
    log_file = LOG_DIR / "service_crash.log"
    handler = logging.FileHandler(str(log_file), encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    return handler


class DashboardService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = "NetOps Dashboard"
    _svc_description_ = "Home Network Management Dashboard — serves on port 9000"

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.server_thread = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        logging.info("Service stop requested")
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        try:
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
            _setup_crash_log()
            logging.info("Service starting (pid=%d, exe=%s)", os.getpid(), sys.executable)
            self.main()
        except Exception:
            msg = traceback.format_exc()
            logging.critical("Service crashed during startup:\n%s", msg)
            try:
                servicemanager.LogErrorMsg(f"{self._svc_name_} crashed:\n{msg}")
            except Exception:
                pass
            raise

    def main(self):
        from runtime import APP_DIR, ENV_PATH, TEMPLATE_DIR, STATIC_DIR
        os.chdir(str(APP_DIR))
        logging.info("APP_DIR=%s, ENV_PATH=%s (exists=%s)", APP_DIR, ENV_PATH, ENV_PATH.exists())
        logging.info("TEMPLATE_DIR=%s (exists=%s)", TEMPLATE_DIR, TEMPLATE_DIR.exists())
        logging.info("STATIC_DIR=%s (exists=%s)", STATIC_DIR, STATIC_DIR.exists())

        # Load environment
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)

        # Import and start the Flask app
        logging.info("Importing Flask app...")
        from app import app, socketio

        port = int(os.environ.get("DASHBOARD_PORT", "9000"))
        logging.info("Starting Flask on 0.0.0.0:%d", port)

        self.server_thread = threading.Thread(
            target=lambda: socketio.run(app, host="0.0.0.0", port=port, debug=False),
            daemon=True,
        )
        self.server_thread.start()

        # Wait for stop signal
        win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
        logging.info("Service stopped")


def _run_console():
    """Run Flask directly in console mode — for debugging without installing as a service."""
    print("=" * 50)
    print("  NetOps Dashboard — Console Mode (not a service)")
    print("=" * 50)

    _setup_crash_log()

    from runtime import APP_DIR, ENV_PATH
    os.chdir(str(APP_DIR))

    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)

    from app import app, socketio

    port = int(os.environ.get("DASHBOARD_PORT", "9000"))
    print(f"\n  URL: http://localhost:{port}\n  Press Ctrl+C to stop.\n")
    socketio.run(app, host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].lower() == "run":
        # Console mode for debugging
        _run_console()
    elif len(sys.argv) == 1:
        # Called by Windows SCM — run as service
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(DashboardService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        # Called from command line — handle install/remove/start/stop
        win32serviceutil.HandleCommandLine(DashboardService)

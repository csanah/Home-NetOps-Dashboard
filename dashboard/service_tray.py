"""System tray icon that controls the Dashboard Windows service.

Colors: green=running, red=stopped, yellow=starting/stopping.
Right-click menu: Start, Stop, Restart, Open Dashboard, Install/Uninstall Service, Quit.
"""

import ctypes
import os
import sys
import threading
import time
import webbrowser

import pystray
from tray_icons import ICONS

SERVICE_NAME = "SystemControlDashboard"
URL = f"http://localhost:{os.environ.get('DASHBOARD_PORT', '9000')}"

icon = None
state = "stopped"  # stopped | starting | running


def set_state(new_state):
    global state
    state = new_state
    if icon:
        icon.icon = ICONS[state]
        icon.title = f"Dashboard: {state.capitalize()}"
        try:
            icon.visible = False
            icon.visible = True
        except Exception:
            pass


# ── Windows Service Control via SCM ──

def _query_service():
    """Query service status. Returns state int or None if not installed."""
    try:
        import win32serviceutil
        status = win32serviceutil.QueryServiceStatus(SERVICE_NAME)
        return status[1]  # dwCurrentState
    except Exception:
        return None


def _is_service_installed():
    return _query_service() is not None


def _is_service_running():
    import win32service
    s = _query_service()
    return s == win32service.SERVICE_RUNNING if s else False


def _sync_state():
    """Sync tray icon state with actual service status."""
    import win32service
    s = _query_service()
    if s is None or s == win32service.SERVICE_STOPPED:
        set_state("stopped")
    elif s == win32service.SERVICE_RUNNING:
        set_state("running")
    elif s in (win32service.SERVICE_START_PENDING, win32service.SERVICE_STOP_PENDING):
        set_state("starting")
    else:
        set_state("stopped")


def _poll_service():
    """Background thread: poll service status every 2 seconds."""
    while True:
        try:
            _sync_state()
        except Exception:
            pass
        time.sleep(2)


# ── Menu Actions ──

def start_service(_=None):
    try:
        import win32serviceutil
        set_state("starting")
        win32serviceutil.StartService(SERVICE_NAME)
    except Exception as e:
        print(f"Failed to start service: {e}")
        _sync_state()


def stop_service(_=None):
    try:
        import win32serviceutil
        set_state("starting")  # yellow while stopping
        win32serviceutil.StopService(SERVICE_NAME)
    except Exception as e:
        print(f"Failed to stop service: {e}")
    _sync_state()


def restart_service(_=None):
    try:
        import win32serviceutil
        set_state("starting")
        win32serviceutil.RestartService(SERVICE_NAME)
    except Exception as e:
        print(f"Failed to restart service: {e}")
    _sync_state()


def _get_service_exe():
    """Find the service exe path — next to this script/exe."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "dashboard-service.exe")


def _run_elevated(exe, args):
    """Run a command with UAC elevation (runas)."""
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", exe, args, None, 1
    )


def install_service(_=None):
    exe = _get_service_exe()
    if os.path.exists(exe):
        _run_elevated(exe, "--startup auto install")
        time.sleep(2)
        _sync_state()
    else:
        # Dev mode — use python
        _run_elevated(
            sys.executable,
            f'"{os.path.join(os.path.dirname(os.path.abspath(__file__)), "service_wrapper.py")}" --startup auto install',
        )
        time.sleep(2)
        _sync_state()


def uninstall_service(_=None):
    stop_service()
    time.sleep(1)
    exe = _get_service_exe()
    if os.path.exists(exe):
        _run_elevated(exe, "remove")
    else:
        _run_elevated(
            sys.executable,
            f'"{os.path.join(os.path.dirname(os.path.abspath(__file__)), "service_wrapper.py")}" remove',
        )
    time.sleep(2)
    _sync_state()


def open_dashboard(_=None):
    webbrowser.open(URL)


def quit_tray(_=None):
    # Quit tray only — does NOT stop the service
    if icon:
        icon.stop()


# ── Menu Visibility Helpers ──

def _service_not_running(item):
    return not _is_service_running()


def _service_running(item):
    return _is_service_running()


def _service_installed(item):
    return _is_service_installed()


def _service_not_installed(item):
    return not _is_service_installed()


# ── Main ──

def setup(tray_icon):
    tray_icon.visible = True
    _sync_state()
    # Auto-start service if installed but not running
    if _is_service_installed() and not _is_service_running():
        start_service()


def main():
    global icon

    menu = pystray.Menu(
        pystray.MenuItem("Start", start_service, visible=_service_not_running),
        pystray.MenuItem("Stop", stop_service, visible=_service_running),
        pystray.MenuItem("Restart", restart_service, visible=_service_running),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open Dashboard", open_dashboard, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Install Service", install_service, visible=_service_not_installed),
        pystray.MenuItem("Uninstall Service", uninstall_service, visible=_service_installed),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit Tray", quit_tray),
    )

    icon = pystray.Icon(
        name="dashboard",
        icon=ICONS["stopped"],
        title="Dashboard: Stopped",
        menu=menu,
    )

    # Start background poller
    threading.Thread(target=_poll_service, daemon=True).start()

    icon.run(setup)


if __name__ == "__main__":
    main()

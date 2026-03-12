"""System tray icon for the Dashboard server.

Colors: green=running, red=stopped, yellow=starting.
Right-click menu: Start, Stop, Restart, Open Dashboard, Quit.
"""

import os
import sys
import subprocess
import threading
import webbrowser
import time
import signal

import pystray
from tray_icons import ICONS

PYTHON = sys.executable
APP_DIR = os.path.dirname(os.path.abspath(__file__))
APP_SCRIPT = os.path.join(APP_DIR, "app.py")
URL = f"http://localhost:{os.environ.get('DASHBOARD_PORT', '9000')}"

server_proc = None
icon = None
state = "stopped"  # stopped | starting | running


def set_state(new_state):
    global state
    state = new_state
    if icon:
        icon.icon = ICONS[state]
        icon.title = f"Dashboard: {state.capitalize()}"
        # Force Windows to refresh the tray icon
        try:
            icon.visible = False
            icon.visible = True
        except Exception:
            pass


def health_check():
    """Poll the server until it responds, then set state to running."""
    import urllib.request
    for _ in range(30):
        time.sleep(0.5)
        try:
            urllib.request.urlopen(URL, timeout=2)
            set_state("running")
            return
        except Exception:
            pass
    # Timed out
    if state == "starting":
        set_state("stopped")


def kill_port_holders(port=9000):
    """Kill any process listening on the given port to prevent stacking."""
    try:
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "TCP"],
            creationflags=subprocess.CREATE_NO_WINDOW,
            text=True, timeout=5,
        )
        pids = set()
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and f":{port}" in parts[1] and parts[3] == "LISTENING":
                pid = int(parts[4])
                if pid != 0:
                    pids.add(pid)
        for pid in pids:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                creationflags=subprocess.CREATE_NO_WINDOW,
                capture_output=True, timeout=5,
            )
    except Exception:
        pass


def start_server(_=None):
    global server_proc
    if server_proc and server_proc.poll() is None:
        return  # already running

    set_state("starting")
    # Kill any stale instances on port 9000 before starting fresh
    kill_port_holders()
    time.sleep(0.3)
    server_proc = subprocess.Popen(
        [PYTHON, APP_SCRIPT],
        cwd=APP_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    threading.Thread(target=health_check, daemon=True).start()


def stop_server(_=None):
    global server_proc
    if server_proc and server_proc.poll() is None:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()
    server_proc = None
    set_state("stopped")


def restart_server(_=None):
    stop_server()
    time.sleep(0.5)
    start_server()


def open_dashboard(_=None):
    webbrowser.open(URL)


def quit_app(_=None):
    stop_server()
    if icon:
        icon.stop()


def setup(tray_icon):
    tray_icon.visible = True
    # Auto-start the server on launch
    start_server()


def main():
    global icon
    menu = pystray.Menu(
        pystray.MenuItem("Start", start_server),
        pystray.MenuItem("Stop", stop_server),
        pystray.MenuItem("Restart", restart_server),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open Dashboard", open_dashboard, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    )

    icon = pystray.Icon(
        name="dashboard",
        icon=ICONS["stopped"],
        title="Dashboard: Stopped",
        menu=menu,
    )
    icon.run(setup)


if __name__ == "__main__":
    main()

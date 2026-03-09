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

from PIL import Image, ImageDraw
import pystray

PYTHON = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "Programs", "Python", "Python312", "python.exe",
)
APP_DIR = os.path.dirname(os.path.abspath(__file__))
APP_SCRIPT = os.path.join(APP_DIR, "app.py")
URL = "http://localhost:9000"

server_proc = None
icon = None
state = "stopped"  # stopped | starting | running


def make_icon_image(color):
    """Draw a filled circle icon with a server symbol, 256x256 for clarity."""
    sz = 256
    img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Background circle
    draw.ellipse([8, 8, sz - 8, sz - 8], fill=color)
    # Server rack — three horizontal bars
    bar_w = 140
    bar_h = 36
    x0 = (sz - bar_w) // 2
    gap = 8
    total_h = bar_h * 3 + gap * 2
    y_start = (sz - total_h) // 2
    for i in range(3):
        y = y_start + i * (bar_h + gap)
        draw.rounded_rectangle([x0, y, x0 + bar_w, y + bar_h], radius=8, fill="white")
        # Status dot on right side of each bar
        dot_r = 8
        dx = x0 + bar_w - 22
        dy = y + (bar_h - dot_r * 2) // 2
        draw.ellipse([dx, dy, dx + dot_r * 2, dy + dot_r * 2], fill=color)
    return img


ICONS = {
    "stopped": make_icon_image((220, 50, 50)),
    "starting": make_icon_image((220, 180, 30)),
    "running": make_icon_image((50, 200, 80)),
}


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

"""All-in-one Dashboard tray app.

Double-click to run: loads .env, starts Flask in a background thread,
shows a pystray tray icon, and auto-opens the browser.

Right-click menu: Start / Stop / Restart / Open Dashboard / Change Port / Quit
"""

import os
import sys
import threading
import webbrowser
import time
import subprocess
from pathlib import Path

# --- Path resolution (before any app imports) ---
FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    EXE_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", EXE_DIR))
    ENV_PATH = EXE_DIR / ".env"
    # Ensure the dashboard package dir is on sys.path so `import app` works
    sys.path.insert(0, str(BUNDLE_DIR))
    sys.path.insert(0, str(EXE_DIR))
else:
    APP_DIR = Path(__file__).resolve().parent
    ENV_PATH = APP_DIR.parent / ".env"

# --- Auto-create .env from .env.example on first launch ---
if not ENV_PATH.exists():
    example = EXE_DIR / ".env.example" if FROZEN else Path(__file__).resolve().parent.parent / ".env.example"
    if example.exists():
        import shutil
        shutil.copy2(example, ENV_PATH)

# --- Load .env FIRST (before any app imports) ---
from dotenv import load_dotenv
load_dotenv(ENV_PATH)

import pystray
from tray_icons import ICONS

# --- Globals ---
icon = None
state = "stopped"  # stopped | starting | running
server_thread = None
flask_started = threading.Event()
_socketio_ref = None  # will hold reference to socketio for clean shutdown


def _get_log_dir():
    """Get the directory for crash logs — next to exe in frozen mode, dashboard/ in dev."""
    if FROZEN:
        d = EXE_DIR / "logs"
    else:
        d = Path(__file__).resolve().parent / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _log_crash(context, error_text):
    """Write crash info to log file and show a Windows MessageBox."""
    try:
        log_path = _get_log_dir() / "startup_crash.log"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} [{context}] ---\n{error_text}\n")
    except Exception:
        log_path = "unknown"
    # Show MessageBox (works even with console=False)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            f"Dashboard failed to start:\n\n{error_text[:800]}\n\nLog: {log_path}",
            "Dashboard Error",
            0x10,  # MB_ICONERROR
        )
    except Exception:
        pass


# --- Start with Windows (Startup folder shortcut) ---
def _get_startup_dir():
    """Windows Startup folder path."""
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _startup_shortcut_path():
    return _get_startup_dir() / "NetOps Dashboard.lnk"


def _is_startup_enabled():
    return _startup_shortcut_path().exists()


def toggle_startup(_=None):
    """Create or remove a Windows Startup folder shortcut."""
    shortcut_path = _startup_shortcut_path()
    if shortcut_path.exists():
        shortcut_path.unlink()
    else:
        _create_shortcut(shortcut_path)


def _create_shortcut(shortcut_path):
    """Create a .lnk shortcut pointing to the current exe (or python script)."""
    try:
        work_dir = str(EXE_DIR if FROZEN else Path(__file__).resolve().parent)
        if FROZEN:
            target = str(sys.executable)
        else:
            target = str(sys.executable)
        ps_cmd = (
            f'$ws = New-Object -ComObject WScript.Shell; '
            f'$s = $ws.CreateShortcut("{shortcut_path}"); '
            f'$s.TargetPath = "{target}"; '
        )
        if not FROZEN:
            ps_cmd += f'$s.Arguments = \'"{__file__}"\'; '
        ps_cmd += (
            f'$s.WorkingDirectory = "{work_dir}"; '
            f'$s.Description = "NetOps Dashboard"; '
            f'$s.Save()'
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            capture_output=True, timeout=10,
        )
    except Exception:
        pass


def get_port():
    return int(os.environ.get("DASHBOARD_PORT", "9000"))


def get_url():
    return f"http://localhost:{get_port()}"



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


# --- Kill stale port holders ---
def kill_port_holders(port):
    """Kill any process listening on the given port (except ourselves)."""
    my_pid = os.getpid()
    try:
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "TCP"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            text=True, timeout=5,
        )
        pids = set()
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and f":{port}" in parts[1] and parts[3] == "LISTENING":
                pid = int(parts[4])
                if pid != 0 and pid != my_pid:
                    pids.add(pid)
        for pid in pids:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                capture_output=True, timeout=5,
            )
    except Exception:
        pass


# --- Flask server in thread ---
def start_flask():
    """Import and run the Flask app in a daemon thread."""
    global _socketio_ref
    try:
        import app as flask_app
        _socketio_ref = flask_app.socketio
        port = get_port()
        flask_started.set()
        flask_app.socketio.run(
            flask_app.app,
            host="0.0.0.0",
            port=port,
            debug=False,
            use_reloader=False,
            log_output=False,
            allow_unsafe_werkzeug=True,
        )
    except Exception:
        import traceback
        err = traceback.format_exc()
        _log_crash("Flask server error", err)
        flask_started.set()  # unblock health check
        set_state("stopped")


def health_check_and_open():
    """Wait for Flask to respond, then set state to running and open browser."""
    import urllib.request
    flask_started.wait(timeout=10)
    url = get_url()
    for _ in range(30):
        time.sleep(0.5)
        try:
            urllib.request.urlopen(url, timeout=2)
            set_state("running")
            webbrowser.open(url)
            return
        except Exception:
            pass
    if state == "starting":
        set_state("stopped")


def start_server(_=None):
    global server_thread
    if state == "running":
        return

    set_state("starting")
    kill_port_holders(get_port())
    time.sleep(0.3)

    flask_started.clear()
    server_thread = threading.Thread(target=start_flask, daemon=True)
    server_thread.start()
    threading.Thread(target=health_check_and_open, daemon=True).start()


def stop_server(_=None):
    global _socketio_ref
    if _socketio_ref:
        try:
            _socketio_ref.stop()
        except Exception:
            pass
    set_state("stopped")


def restart_server(_=None):
    """Restart by launching new process and exiting."""
    _relaunch()


def open_dashboard(_=None):
    webbrowser.open(get_url())


# --- Change Port dialog (tkinter) ---
def change_port(_=None):
    def _show_dialog():
        import tkinter as tk
        from tkinter import simpledialog, messagebox
        root = tk.Tk()
        root.withdraw()
        current = get_port()
        new_port = simpledialog.askinteger(
            "Change Port",
            f"Current port: {current}\nEnter new port:",
            initialvalue=current,
            minvalue=1024,
            maxvalue=65535,
            parent=root,
        )
        root.destroy()
        if new_port and new_port != current:
            _update_env_port(new_port)
            messagebox.showinfo("Port Changed", f"Port changed to {new_port}.\nRestarting dashboard...")
            _relaunch()

    # Run in a separate thread so the tray menu doesn't block
    threading.Thread(target=_show_dialog, daemon=True).start()


def _update_env_port(new_port):
    """Read .env, replace/add DASHBOARD_PORT line, write back."""
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    found = False
    for i, line in enumerate(lines):
        if line.startswith("DASHBOARD_PORT="):
            lines[i] = f"DASHBOARD_PORT={new_port}"
            found = True
            break
    if not found:
        lines.append(f"DASHBOARD_PORT={new_port}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ["DASHBOARD_PORT"] = str(new_port)


def _relaunch():
    """Launch a new instance and exit this one."""
    stop_server()
    time.sleep(0.5)  # let Flask release the port
    if FROZEN:
        subprocess.Popen([sys.executable] + sys.argv)
    else:
        subprocess.Popen([sys.executable, __file__] + sys.argv[1:])
    os._exit(0)


def quit_app(_=None):
    stop_server()
    if icon:
        icon.stop()
    # Force exit to kill any remaining daemon threads
    os._exit(0)


def setup(tray_icon):
    tray_icon.visible = True
    start_server()


def main():
    global icon
    menu = pystray.Menu(
        pystray.MenuItem("Start", start_server),
        pystray.MenuItem("Stop", stop_server),
        pystray.MenuItem("Restart", restart_server),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open Dashboard", open_dashboard, default=True),
        pystray.MenuItem("Change Port", change_port),
        pystray.MenuItem(
            "Start with Windows",
            toggle_startup,
            checked=lambda item: _is_startup_enabled(),
        ),
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
    try:
        main()
    except Exception:
        import traceback
        _log_crash("Startup", traceback.format_exc())

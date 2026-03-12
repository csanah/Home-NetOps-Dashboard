import json
import logging
import os
import re
import subprocess
import tempfile
import threading

from runtime import PROJECT_ROOT, DATA_DIR

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 200

CLAUDE_CMD = os.environ.get("CLAUDE_CMD_PATH", "") or os.path.join(
    os.environ.get("APPDATA", ""), "npm", "claude.cmd"
)

_claude_md_path = str(PROJECT_ROOT / "CLAUDE.md")


def detect_claude_cli():
    """Check if the Claude CLI executable exists on disk."""
    found = os.path.isfile(CLAUDE_CMD)
    return {"found": found, "path": CLAUDE_CMD}


_cli_detection = detect_claude_cli()


def _load_claude_md():
    """Load and clean CLAUDE.md content for chat relay context."""
    content = ""
    try:
        with open(_claude_md_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Strip sections meant for main Claude Code session (not chat relay)
        content = re.sub(
            r"## On Session Start\n.*?(?=\n## )", "", content, flags=re.DOTALL
        )
        content = re.sub(
            r"## Quick Commands\n.*?(?=\n## )", "", content, flags=re.DOTALL
        )
    except Exception as e:
        logger.debug("Failed to load CLAUDE.md: %s", e)
    return content


def _build_admin_prompt(content):
    """Build the admin system prompt from CLAUDE.md content."""
    return (
        "You are a READ-ONLY network monitoring assistant. "
        "Your role is to CHECK and REPORT on system status — never to make changes.\n\n"
        "RULES:\n"
        "- Only run read-only commands: status checks, log reads, API queries, pings\n"
        "- NEVER edit files, write files, restart services, modify configs, or run destructive commands\n"
        "- NEVER use rm, kill, systemctl restart, reboot, or similar\n"
        "- If asked to make a change, explain this is a monitoring-only interface\n\n"
        "Systems and access details:\n\n"
        + content
    )


_claude_md_content = _load_claude_md()
ADMIN_SYSTEM_PROMPT = _build_admin_prompt(_claude_md_content)


def reload_system_prompt():
    """Reload CLAUDE.md and rebuild the admin system prompt."""
    global _claude_md_content, ADMIN_SYSTEM_PROMPT
    _claude_md_content = _load_claude_md()
    ADMIN_SYSTEM_PROMPT = _build_admin_prompt(_claude_md_content)

HISTORY_FILE = str(DATA_DIR / "chat_history.json")


def _load_history():
    """Load chat history from disk."""
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_history(messages):
    """Save chat history to disk atomically (write to temp file, then rename)."""
    dir_path = os.path.dirname(HISTORY_FILE)
    os.makedirs(dir_path, exist_ok=True)

    # Backup existing file before overwriting
    if os.path.exists(HISTORY_FILE):
        try:
            import shutil
            shutil.copy2(HISTORY_FILE, HISTORY_FILE + ".backup")
        except (IOError, OSError) as e:
            logger.debug("History backup failed: %s", e)

    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, HISTORY_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class ClaudeSession:
    """Manages a persistent Claude CLI subprocess behind a WebSocket interface."""

    def __init__(self, socketio, namespace):
        """Initialize session state, load persisted history, bind to SocketIO namespace."""
        self.socketio = socketio
        self.namespace = namespace
        self.active = False
        self.stop_event = threading.Event()
        self.process = None
        self.lock = threading.Lock()
        self.project_dir = str(PROJECT_ROOT)
        self.messages = _load_history()
        self.mode = "admin"
        self.generating = False
        # Track connected WebSocket SIDs for broadcasting
        self.connected_sids = set()
        # Buffer output chunks while no clients are connected
        self._output_buffer = []
        self._buffer_lock = threading.Lock()

    def add_client(self, sid):
        """Register a connected WebSocket client."""
        self.connected_sids.add(sid)

    def remove_client(self, sid):
        """Unregister a disconnected WebSocket client (session keeps running)."""
        self.connected_sids.discard(sid)

    def has_clients(self):
        """Check if any WebSocket clients are connected for output delivery."""
        return len(self.connected_sids) > 0

    def _trim_history(self):
        """Keep only the last MAX_HISTORY_MESSAGES messages."""
        if len(self.messages) > MAX_HISTORY_MESSAGES:
            self.messages = self.messages[-MAX_HISTORY_MESSAGES:]

    def get_history(self):
        """Return the full message history for replay."""
        return list(self.messages)

    def flush_buffer(self, sid):
        """Send any buffered output to a reconnecting client."""
        with self._buffer_lock:
            chunks = list(self._output_buffer)
        for chunk in chunks:
            self.socketio.emit("output", chunk, namespace=self.namespace, to=sid)

    def _emit_output(self, data):
        """Emit output to connected clients, or buffer if none connected."""
        if self.has_clients():
            self.socketio.emit("output", data, namespace=self.namespace)
        else:
            with self._buffer_lock:
                self._output_buffer.append(data)

    def start(self):
        """Activate the session so it can accept messages."""
        self.active = True
        self.stop_event.clear()
        self.socketio.emit(
            "session_status", {"status": "started"}, namespace=self.namespace
        )

    def set_mode(self, mode):
        """No-op; only read-only admin mode is supported for safety."""
        pass

    def clear(self):
        """Wipe conversation history from memory, disk, and output buffer."""
        self.messages = []
        _save_history(self.messages)
        self._output_buffer.clear()
        self.socketio.emit("history_cleared", {}, namespace=self.namespace)

    def send(self, message):
        """Queue a user message for processing in a background thread."""
        if not self.active or self.generating:
            return
        self.stop_event.clear()
        threading.Thread(target=self._run_command, args=(message,), daemon=True).start()

    def cancel(self):
        """Kill current generation but keep session alive."""
        self.stop_event.set()
        self._kill_process()
        self.generating = False
        self.socketio.emit("generation_stopped", {}, namespace=self.namespace)

    def stop(self):
        """Shut down the session entirely, killing any running subprocess."""
        self.stop_event.set()
        self.active = False
        self._kill_process()
        self.generating = False
        self.socketio.emit(
            "session_status", {"status": "stopped"}, namespace=self.namespace
        )

    def _kill_process(self):
        """Force-kill the Claude CLI process tree."""
        with self.lock:
            if self.process and self.process.poll() is None:
                try:
                    # taskkill /T kills the entire process tree. Plain terminate()
                    # only kills the .cmd wrapper, leaving the underlying node
                    # process (and its children) orphaned and holding resources.
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception as e:
                    logger.debug("taskkill failed for PID %s: %s", self.process.pid, e)
                    try:
                        self.process.kill()
                    except Exception as e2:
                        logger.debug("process.kill() also failed: %s", e2)
            self.process = None

    def _build_prompt(self, message):
        """Build the full prompt with conversation history."""
        parts = []

        # Admin mode: prepend system context
        if self.mode == "admin" and ADMIN_SYSTEM_PROMPT:
            parts.append("[System context]\n" + ADMIN_SYSTEM_PROMPT + "\n")

        # Add conversation history
        if self.messages:
            parts.append("[Previous conversation]")
            for msg in self.messages:
                role = "User" if msg["role"] == "user" else "Assistant"
                parts.append(f"{role}: {msg['content']}")
            parts.append("")

        # Current message
        parts.append("[Current message]")
        parts.append(message)

        return "\n".join(parts)

    def _run_command(self, message):
        """Spawn Claude CLI, stream output to clients, and persist the exchange."""
        self.generating = True
        # Clear output buffer for this new generation
        with self._buffer_lock:
            self._output_buffer.clear()
        self.socketio.emit("generation_started", {}, namespace=self.namespace)

        full_response = []

        try:
            prompt = self._build_prompt(message)

            # Append user message to history AFTER building prompt (to avoid duplication)
            self.messages.append({"role": "user", "content": message})
            self._trim_history()
            _save_history(self.messages)

            # Claude CLI refuses to start if CLAUDECODE is set, because it
            # detects it's already running inside another Claude session.
            # We must strip it so the relay can spawn its own independent CLI process.
            env = os.environ.copy()
            env.pop("CLAUDECODE", None)

            cmd = [CLAUDE_CMD, "-p", "--dangerously-skip-permissions",
                   "--disallowedTools", "Edit,Write,NotebookEdit"]
            # Prompt passed via stdin to avoid Windows 8191-char command line limit

            with self.lock:
                self.process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=os.environ.get("USERPROFILE", self.project_dir),
                    env=env,
                )
                process = self.process

            # Write prompt to stdin and close it
            try:
                process.stdin.write(prompt.encode("utf-8"))
                process.stdin.close()
            except Exception as e:
                logger.debug("Failed to write prompt to stdin: %s", e)

            # Read stdout in chunks
            def read_stdout(pipe):
                try:
                    while True:
                        chunk = pipe.read(512)
                        if not chunk:
                            break
                        text = chunk.decode("utf-8", errors="replace")
                        full_response.append(text)
                        if not self.stop_event.is_set():
                            self._emit_output(
                                {"stream": "stdout", "data": text},
                            )
                except Exception as e:
                    logger.debug("stdout read error: %s", e)

            def read_stderr(pipe):
                try:
                    while True:
                        chunk = pipe.read(512)
                        if not chunk:
                            break
                        text = chunk.decode("utf-8", errors="replace")
                        if not self.stop_event.is_set():
                            self._emit_output(
                                {"stream": "stderr", "data": text},
                            )
                except Exception as e:
                    logger.debug("stderr read error: %s", e)

            stdout_thread = threading.Thread(
                target=read_stdout, args=(process.stdout,), daemon=True
            )
            stderr_thread = threading.Thread(
                target=read_stderr, args=(process.stderr,), daemon=True
            )
            stdout_thread.start()
            stderr_thread.start()

            try:
                process.wait(timeout=300)
            except subprocess.TimeoutExpired:
                self._kill_process()
                self._emit_output(
                    {"stream": "error", "data": "Error: Claude CLI timed out after 5 minutes\n"},
                )
            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)

            with self.lock:
                self.process = None

            # Save assistant response to history and persist
            response_text = "".join(full_response).strip()
            if response_text:
                self.messages.append({"role": "assistant", "content": response_text})
                self._trim_history()
                _save_history(self.messages)

            if not self.stop_event.is_set():
                self.socketio.emit(
                    "generation_complete", {}, namespace=self.namespace
                )

        except FileNotFoundError:
            self._emit_output(
                {"stream": "error", "data": "Error: claude CLI not found in PATH\n"},
            )
        except Exception as e:
            self._emit_output(
                {"stream": "error", "data": f"Error: {e}\n"},
            )
        finally:
            self.generating = False

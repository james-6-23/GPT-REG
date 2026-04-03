import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

from reg_gpt.config import RUNTIME_LOG_PATH, SCRIPT_DIR, ensure_runtime_layout
from reg_gpt.runtime_state import RUNTIME_STATE_PATH, mark_runtime_starting, mark_runtime_stopped, read_runtime_state

ENTRY_SCRIPT = os.path.join(SCRIPT_DIR, "openai_reg.py")
LOG_FILE = RUNTIME_LOG_PATH
ensure_runtime_layout()


def _fmt_ts(ts: float | None) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _pid_exists(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except Exception:
        return False
    return True


class RuntimeProcessManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: Optional[subprocess.Popen] = None
        self._log_fp = None
        self._started_at: Optional[float] = None
        self._last_exit_code: Optional[int] = None

    def _refresh(self) -> None:
        if self._process is None:
            return
        code = self._process.poll()
        if code is None:
            return
        pid = self._process.pid
        self._last_exit_code = code
        self._process = None
        if self._log_fp:
            try:
                self._log_fp.close()
            except Exception:
                pass
            self._log_fp = None
        self._started_at = None
        mark_runtime_stopped(code, f"主程序已退出（PID={pid}）")

    def status(self) -> Dict[str, Any]:
        with self._lock:
            self._refresh()
            runtime_state = read_runtime_state()
            running = self._process is not None
            pid = self._process.pid if self._process else None

            if not running:
                state_pid = runtime_state.get("pid")
                if runtime_state.get("running") and _pid_exists(state_pid):
                    running = True
                    pid = int(state_pid)
                elif runtime_state.get("running"):
                    mark_runtime_stopped(runtime_state.get("last_exit_code"), "主程序未运行")
                    runtime_state = read_runtime_state()

            return {
                "running": running,
                "pid": pid,
                "entry_script": ENTRY_SCRIPT,
                "started_at": runtime_state.get("started_at") or _fmt_ts(self._started_at),
                "log_file": LOG_FILE,
                "last_exit_code": None if running else runtime_state.get("last_exit_code", self._last_exit_code),
                "message": (runtime_state.get("message") if running else (runtime_state.get("message") or "主程序未运行")) or ("主程序运行中" if running else "主程序未运行"),
                "phase": (runtime_state.get("phase", "running") if running else runtime_state.get("phase", "idle")),
                "mode": runtime_state.get("mode", "idle"),
                "attempts": runtime_state.get("attempts", 0),
                "successes": runtime_state.get("successes", 0),
                "failures": runtime_state.get("failures", 0),
                "workers_target": runtime_state.get("workers_target", 0),
                "workers_active": runtime_state.get("workers_active", 0),
                "max_success": runtime_state.get("max_success", 0),
                "once": runtime_state.get("once", False),
                "proxy": runtime_state.get("proxy", ""),
                "sleep_window": runtime_state.get("sleep_window", ""),
                "last_email": runtime_state.get("last_email", ""),
                "worker_slots": runtime_state.get("worker_slots", {}),
                "recent_events": runtime_state.get("recent_events", []),
                "runtime_state_path": RUNTIME_STATE_PATH,
            }

    def start(self) -> Dict[str, Any]:
        with self._lock:
            current_status = self.status()
            if current_status.get("running"):
                return {
                    "ok": False,
                    "message": f"主程序已在运行中（PID={current_status.get('pid')}）",
                    "status": current_status,
                }

            os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
            log_fp = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
            log_fp.write(f"\n===== WebGUI 启动主程序：{_fmt_ts(time.time())} =====\n")
            proc = subprocess.Popen(
                [sys.executable, "-u", ENTRY_SCRIPT, "--runtime-child"],
                cwd=SCRIPT_DIR,
                stdout=log_fp,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._process = proc
            self._log_fp = log_fp
            self._started_at = time.time()
            self._last_exit_code = None
            mark_runtime_starting(pid=proc.pid, entry_script=ENTRY_SCRIPT, log_file=LOG_FILE)
            return {
                "ok": True,
                "message": f"主程序已启动（PID={proc.pid}）",
                "status": self.status(),
            }

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            self._refresh()
            runtime_state = read_runtime_state()
            target_pid = self._process.pid if self._process else runtime_state.get("pid")
            target_pid = int(target_pid) if target_pid and str(target_pid).isdigit() else None

            if target_pid is None or not _pid_exists(target_pid):
                return {
                    "ok": False,
                    "message": "主程序当前未运行",
                    "status": self.status(),
                }

            proc = self._process
            if proc is not None:
                try:
                    proc.terminate()
                    proc.wait(timeout=8)
                except Exception:
                    try:
                        proc.kill()
                        proc.wait(timeout=5)
                    except Exception:
                        pass
                self._last_exit_code = proc.poll()
            else:
                try:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/PID", str(target_pid), "/T", "/F"],
                            check=False,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                    else:
                        os.kill(target_pid, signal.SIGKILL)
                except Exception:
                    pass
                self._last_exit_code = -15

            self._process = None
            if self._log_fp:
                try:
                    self._log_fp.close()
                except Exception:
                    pass
                self._log_fp = None
            self._started_at = None
            mark_runtime_stopped(self._last_exit_code, f"主程序已停止（PID={target_pid}）")
            return {
                "ok": True,
                "message": f"主程序已停止（PID={target_pid}）",
                "status": self.status(),
            }

    def clear_log(self) -> Dict[str, Any]:
        with self._lock:
            self._refresh()
            runtime_state = read_runtime_state()
            running = bool(self._process is not None or runtime_state.get("running"))
            try:
                if running:
                    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
                    if self._log_fp is not None:
                        self._log_fp.flush()
                        self._log_fp.seek(0)
                        self._log_fp.truncate(0)
                        self._log_fp.flush()
                    else:
                        with open(LOG_FILE, "w", encoding="utf-8", newline="\n"):
                            pass
                    message = "运行日志已清空，后续输出将继续写入"
                elif os.path.exists(LOG_FILE):
                    os.remove(LOG_FILE)
                    message = "运行日志已删除"
                else:
                    message = "当前没有运行日志"
                return {
                    "ok": True,
                    "message": message,
                    "status": self.status(),
                }
            except Exception as exc:
                return {
                    "ok": False,
                    "message": f"删除运行日志失败：{exc}",
                    "status": self.status(),
                }


process_manager = RuntimeProcessManager()

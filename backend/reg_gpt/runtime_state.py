import copy
import json
import os
import sys
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict

from reg_gpt.config import (
    CONFIG_PATH,
    LEGACY_RUNTIME_STATE_PATH,
    STATE_DIR,
    _copy_legacy_file_if_missing,
    ensure_runtime_layout,
)

RUNTIME_STATE_PATH = os.path.join(STATE_DIR, "runtime_state.json")
_state_lock = threading.Lock()
_MAX_EVENTS = 40
_MAX_SLOT_LINES = 3
_PERSIST_RETRY_DELAYS = (0.02, 0.05, 0.1, 0.2, 0.35, 0.5)

ensure_runtime_layout()
_copy_legacy_file_if_missing(LEGACY_RUNTIME_STATE_PATH, RUNTIME_STATE_PATH)


def _fmt_ts(ts: float | None = None) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _default_slot() -> Dict[str, Any]:
    return {
        "worker_id": 0,
        "status": "idle",
        "attempt": 0,
        "email": "",
        "updated_at": "",
        "lines": [],
    }


def _default_state() -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "updated_at": "",
        "running": False,
        "phase": "idle",
        "message": "主程序未运行",
        "pid": None,
        "entry_script": "",
        "log_file": "",
        "config_path": CONFIG_PATH,
        "started_at": "",
        "stopped_at": "",
        "last_exit_code": None,
        "mode": "idle",
        "workers_target": 0,
        "workers_active": 0,
        "max_success": 0,
        "once": False,
        "proxy": "",
        "sleep_window": "",
        "attempts": 0,
        "successes": 0,
        "failures": 0,
        "last_email": "",
        "worker_slots": {},
        "recent_events": [],
    }


def _is_retryable_state_io_error(exc: Exception) -> bool:
    if isinstance(exc, PermissionError):
        return True
    winerror = getattr(exc, "winerror", None)
    return winerror == 5


def _warn_state_io(action: str, exc: Exception) -> None:
    try:
        sys.__stderr__.write(f"[Warn] runtime_state {action} 失败: {exc}\n")
        sys.__stderr__.flush()
    except Exception:
        pass


def _normalize_state(data: Dict[str, Any] | None) -> Dict[str, Any]:
    state = _default_state()
    if not isinstance(data, dict):
        return state

    for key, value in data.items():
        if key == "worker_slots" and isinstance(value, dict):
            slots: Dict[str, Any] = {}
            for wid, slot in value.items():
                merged_slot = _default_slot()
                if isinstance(slot, dict):
                    merged_slot.update(slot)
                try:
                    merged_slot["worker_id"] = int(merged_slot.get("worker_id") or wid)
                except (TypeError, ValueError):
                    merged_slot["worker_id"] = 0
                lines = merged_slot.get("lines")
                merged_slot["lines"] = [str(line) for line in (lines or [])][- _MAX_SLOT_LINES :]
                slots[str(merged_slot["worker_id"] or wid)] = merged_slot
            state["worker_slots"] = slots
        elif key == "recent_events" and isinstance(value, list):
            events = []
            for item in value[-_MAX_EVENTS:]:
                if isinstance(item, dict):
                    events.append({
                        "timestamp": str(item.get("timestamp") or ""),
                        "message": str(item.get("message") or ""),
                    })
                else:
                    events.append({
                        "timestamp": "",
                        "message": str(item),
                    })
            state["recent_events"] = events
        else:
            state[key] = value
    return state


def _load_state_unlocked() -> Dict[str, Any]:
    if not os.path.exists(RUNTIME_STATE_PATH):
        return _default_state()
    last_exc: Exception | None = None
    for attempt, delay in enumerate(_PERSIST_RETRY_DELAYS, start=1):
        try:
            with open(RUNTIME_STATE_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return _normalize_state(data)
        except Exception as exc:
            last_exc = exc
            if _is_retryable_state_io_error(exc) and attempt < len(_PERSIST_RETRY_DELAYS):
                time.sleep(delay)
                continue
            break
    if last_exc is not None:
        _warn_state_io("读取", last_exc)
    return _default_state()


def _save_state_unlocked(state: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _normalize_state(state)
    normalized["updated_at"] = _fmt_ts(time.time())
    temp_path = f"{RUNTIME_STATE_PATH}.{os.getpid()}.{threading.get_ident()}.tmp"
    last_exc: Exception | None = None
    for attempt, delay in enumerate(_PERSIST_RETRY_DELAYS, start=1):
        try:
            with open(temp_path, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(normalized, fh, ensure_ascii=False, indent=2)
            os.replace(temp_path, RUNTIME_STATE_PATH)
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
            if _is_retryable_state_io_error(exc) and attempt < len(_PERSIST_RETRY_DELAYS):
                time.sleep(delay)
                continue
            break
    if last_exc is not None:
        _warn_state_io("写入", last_exc)
    return normalized


def read_runtime_state() -> Dict[str, Any]:
    with _state_lock:
        return copy.deepcopy(_load_state_unlocked())


def _mutate_state(mutator: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
    with _state_lock:
        state = _load_state_unlocked()
        mutator(state)
        return copy.deepcopy(_save_state_unlocked(state))


def initialize_runtime(
    *,
    pid: int,
    mode: str,
    workers_target: int,
    max_success: int,
    once: bool,
    proxy: str,
    sleep_min: int,
    sleep_max: int,
    entry_script: str,
    log_file: str,
) -> Dict[str, Any]:
    now = _fmt_ts(time.time())

    def mutate(state: Dict[str, Any]) -> None:
        state.update({
            "running": True,
            "phase": "running",
            "message": "主程序运行中",
            "pid": pid,
            "entry_script": entry_script,
            "log_file": log_file,
            "config_path": CONFIG_PATH,
            "started_at": now,
            "stopped_at": "",
            "last_exit_code": None,
            "mode": mode,
            "workers_target": workers_target,
            "workers_active": 0,
            "max_success": max_success,
            "once": once,
            "proxy": proxy,
            "sleep_window": f"{sleep_min} - {sleep_max} 秒",
            "attempts": 0,
            "successes": 0,
            "failures": 0,
            "last_email": "",
            "worker_slots": {
                str(wid): {
                    **_default_slot(),
                    "worker_id": wid,
                }
                for wid in range(1, max(1, workers_target) + 1)
            },
            "recent_events": [],
        })

    return _mutate_state(mutate)


def mark_runtime_starting(
    *,
    pid: int,
    entry_script: str,
    log_file: str,
) -> Dict[str, Any]:
    now = _fmt_ts(time.time())

    def mutate(state: Dict[str, Any]) -> None:
        fresh = _default_state()
        fresh.update({
            "running": True,
            "phase": "starting",
            "message": "主程序启动中",
            "pid": pid,
            "entry_script": entry_script,
            "log_file": log_file,
            "started_at": now,
            "stopped_at": "",
            "last_exit_code": None,
        })
        state.clear()
        state.update(fresh)

    return _mutate_state(mutate)


def append_event(message: str) -> Dict[str, Any]:
    text = str(message or "").strip()
    if not text:
        return read_runtime_state()

    def mutate(state: Dict[str, Any]) -> None:
        events = list(state.get("recent_events") or [])
        events.append({
            "timestamp": _fmt_ts(time.time()),
            "message": text,
        })
        state["recent_events"] = events[-_MAX_EVENTS:]

    return _mutate_state(mutate)


def update_worker_slot(
    wid: int,
    *,
    line: str | None = None,
    status: str | None = None,
    attempt: int | None = None,
    email: str | None = None,
) -> Dict[str, Any]:
    def mutate(state: Dict[str, Any]) -> None:
        slots = state.setdefault("worker_slots", {})
        slot = slots.setdefault(str(wid), _default_slot())
        slot["worker_id"] = wid
        if status is not None:
            slot["status"] = status
        if attempt is not None:
            slot["attempt"] = int(attempt)
        if email is not None:
            slot["email"] = str(email)
            if email:
                state["last_email"] = str(email)
        if line:
            lines = list(slot.get("lines") or [])
            lines.append(str(line))
            slot["lines"] = lines[-_MAX_SLOT_LINES:]
        slot["updated_at"] = _fmt_ts(time.time())

    return _mutate_state(mutate)


def update_summary(
    *,
    attempts: int | None = None,
    successes: int | None = None,
    failures: int | None = None,
    workers_active: int | None = None,
    message: str | None = None,
    phase: str | None = None,
    last_email: str | None = None,
) -> Dict[str, Any]:
    def mutate(state: Dict[str, Any]) -> None:
        if attempts is not None:
            state["attempts"] = int(attempts)
        if successes is not None:
            state["successes"] = int(successes)
        if failures is not None:
            state["failures"] = int(failures)
        if workers_active is not None:
            state["workers_active"] = int(workers_active)
        if message is not None:
            state["message"] = str(message)
        if phase is not None:
            state["phase"] = str(phase)
        if last_email is not None:
            state["last_email"] = str(last_email)

    return _mutate_state(mutate)


def mark_runtime_stopped(last_exit_code: int | None, message: str) -> Dict[str, Any]:
    def mutate(state: Dict[str, Any]) -> None:
        state["running"] = False
        state["phase"] = "stopped"
        state["message"] = str(message)
        state["last_exit_code"] = last_exit_code
        state["workers_active"] = 0
        state["stopped_at"] = _fmt_ts(time.time())
        slots = state.get("worker_slots") or {}
        for slot in slots.values():
            if slot.get("status") not in {"success", "failed"}:
                slot["status"] = "stopped"
                slot["updated_at"] = _fmt_ts(time.time())

    return _mutate_state(mutate)


def reset_runtime_state(message: str = "主程序未运行") -> Dict[str, Any]:
    def mutate(state: Dict[str, Any]) -> None:
        fresh = _default_state()
        fresh["message"] = message
        state.clear()
        state.update(fresh)

    return _mutate_state(mutate)

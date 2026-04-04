import copy
from datetime import datetime
from typing import Any, Dict

from .config import DB_PATH, ensure_runtime_layout
from .db import get_state, set_state

CPA_STATE_PATH = DB_PATH
_DB_KEY = "cpa_state"

ensure_runtime_layout()


def _default_state() -> Dict[str, Any]:
    return {
        "site_test": {},
        "remote_health": {},
        "health_task": {
            "task_id": "",
            "running": False,
            "task_type": "",
            "stage": "",
            "message": "",
            "probe_mode": "",
            "probe_workers": 0,
            "delete_workers": 0,
            "using_proxy": "",
            "started_at": "",
            "finished_at": "",
            "total": 0,
            "processed": 0,
            "cleanup_total": 0,
            "deleted_total": 0,
            "failed_total": 0,
            "summary": {
                "healthy": 0,
                "limited": 0,
                "unknown": 0,
                "unusable": 0,
                "disabled": 0,
                "untested": 0,
            },
            "recent_items": [],
            "selected_names": [],
        },
        "last_updated_at": "",
    }


def _utc_now_local() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_cpa_state() -> Dict[str, Any]:
    raw = get_state(_DB_KEY)
    if not raw:
        return _default_state()
    state = _default_state()
    state.update(raw)
    if not isinstance(state.get("remote_health"), dict):
        state["remote_health"] = {}
    if not isinstance(state.get("site_test"), dict):
        state["site_test"] = {}
    health_task = _default_state()["health_task"]
    if isinstance(state.get("health_task"), dict):
        health_task.update(state["health_task"])
    state["health_task"] = health_task
    return state


def write_cpa_state(state: Dict[str, Any]) -> Dict[str, Any]:
    payload = _default_state()
    payload.update(state or {})
    payload["last_updated_at"] = _utc_now_local()
    set_state(_DB_KEY, payload)
    return copy.deepcopy(payload)


def update_site_test(result: Dict[str, Any]) -> Dict[str, Any]:
    state = read_cpa_state()
    state["site_test"] = dict(result or {})
    return write_cpa_state(state)


def update_remote_health(entries: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    state = read_cpa_state()
    remote_health = dict(state.get("remote_health") or {})
    for name, value in (entries or {}).items():
        if not name:
            continue
        remote_health[str(name)] = dict(value or {})
    state["remote_health"] = remote_health
    return write_cpa_state(state)


def remove_remote_health(names: list[str]) -> Dict[str, Any]:
    state = read_cpa_state()
    remote_health = dict(state.get("remote_health") or {})
    for name in names or []:
        remote_health.pop(str(name), None)
    state["remote_health"] = remote_health
    return write_cpa_state(state)


def update_health_task(task: Dict[str, Any]) -> Dict[str, Any]:
    state = read_cpa_state()
    current = _default_state()["health_task"]
    if isinstance(state.get("health_task"), dict):
        current.update(state["health_task"])
    current.update(task or {})
    if not isinstance(current.get("summary"), dict):
        current["summary"] = _default_state()["health_task"]["summary"]
    if not isinstance(current.get("recent_items"), list):
        current["recent_items"] = []
    if not isinstance(current.get("selected_names"), list):
        current["selected_names"] = []
    state["health_task"] = current
    return write_cpa_state(state)


def read_health_task() -> Dict[str, Any]:
    state = read_cpa_state()
    task = _default_state()["health_task"]
    if isinstance(state.get("health_task"), dict):
        task.update(state["health_task"])
    return task

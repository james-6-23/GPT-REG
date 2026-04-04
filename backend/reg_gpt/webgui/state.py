import csv
import copy
import os
from datetime import datetime
from typing import Any, Dict, List

from reg_gpt.cpa_service import DEFAULT_ACCOUNTS_PER_PAGE, get_cpa_overview_data, get_remote_accounts_filtered_page
from reg_gpt.config import CONFIG_PATH, RUNTIME_ROOT, SCRIPT_DIR, load_or_create_config, normalize_config, save_config
from reg_gpt.email_registry import get_all_email_providers, get_enabled_email_providers
from reg_gpt.email_weight import domain_weight_summary, list_email_domain_weight_items
from reg_gpt.runtime_state import RUNTIME_STATE_PATH, read_runtime_state
from reg_gpt.storage import ACCOUNTS_CSV, OUTPUT_DIR, count_accounts_csv, recent_token_files
from reg_gpt.webgui.process_manager import LOG_FILE, process_manager


def _fmt_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def read_config() -> Dict[str, Any]:
    return normalize_config(load_or_create_config())


def _deep_merge_dict(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in (updates or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def write_config(data: Dict[str, Any]) -> Dict[str, Any]:
    current = read_config()
    merged = _deep_merge_dict(current, data or {})
    return save_config(merged)


def read_config_section(section: str) -> Dict[str, Any]:
    cfg = read_config()
    key = (section or "").strip().lower()
    if key == "basic":
        return {
            "webui": cfg["webui"],
            "config_path": CONFIG_PATH,
        }
    if key == "email":
        return {
            "email": cfg["email"],
            "providers": get_all_email_providers(cfg),
            "enabled_count": len(get_enabled_email_providers(cfg)),
        }
    if key == "email-domains":
        return {
            "email": {
                "weight": cfg["email"]["weight"],
            },
            "domain_weight_items": list_email_domain_weight_items(cfg),
            "domain_weight_summary": domain_weight_summary(cfg),
        }
    if key == "network":
        return {"network": cfg["network"]}
    if key == "cpa":
        return {"cpa": cfg["cpa"]}
    if key == "codex_proxy" or key == "codex-proxy":
        return {"codex_proxy": cfg["codex_proxy"]}
    if key == "runtime":
        return {
            "run": cfg["run"],
            "email": {
                "otp": cfg["email"]["otp"],
            },
        }
    raise KeyError(section)


def write_config_section(section: str, data: Dict[str, Any]) -> Dict[str, Any]:
    key = (section or "").strip().lower()
    if key == "basic":
        payload = {"webui": (data or {}).get("webui") or {}}
    elif key == "email":
        email_data = (data or {}).get("email") or {}
        # 同步顶层字段到 entries（前端编辑的是顶层字段，需要回写到 entries）
        providers = email_data.get("providers")
        if isinstance(providers, dict):
            for pname, pdata in providers.items():
                if not isinstance(pdata, dict):
                    continue
                entries = pdata.get("entries")
                if not isinstance(entries, list) or not entries:
                    continue
                ptype = str(pdata.get("type") or pname).strip().lower()
                parent_enabled = bool(pdata.get("enabled"))
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    # 同步 enabled
                    if parent_enabled and not entry.get("enabled"):
                        entry["enabled"] = True
                    # 同步顶层编辑的字段到 entry
                    if ptype == "tempmail_lol":
                        for fk in ("api_base", "api_key", "domain"):
                            if pdata.get(fk) is not None:
                                entry.setdefault(fk, pdata[fk])
                                if pdata[fk]:
                                    entry[fk] = pdata[fk]
                    elif ptype == "mailapi_pool":
                        for fk in ("api_base", "api_bases", "api_key", "domains"):
                            if pdata.get(fk) is not None:
                                entry.setdefault(fk, pdata[fk])
                                if pdata[fk]:
                                    entry[fk] = pdata[fk]
                    elif ptype == "duckmail":
                        for fk in ("api_base", "bearer", "email_domain"):
                            if pdata.get(fk) is not None:
                                entry.setdefault(fk, pdata[fk])
                                if pdata[fk]:
                                    entry[fk] = pdata[fk]
                    elif ptype == "lamail":
                        for fk in ("api_base", "api_key", "domain"):
                            if pdata.get(fk) is not None:
                                entry.setdefault(fk, pdata[fk])
                                if pdata[fk]:
                                    entry[fk] = pdata[fk]
                    elif ptype == "cloudflare":
                        for fk in ("worker_url", "email_domain", "api_secret"):
                            if pdata.get(fk) is not None:
                                entry.setdefault(fk, pdata[fk])
                                if pdata[fk]:
                                    entry[fk] = pdata[fk]
        payload = {"email": email_data}
    elif key == "email-domains":
        email_data = (data or {}).get("email") or {}
        payload = {
            "email": {
                "weight": (email_data.get("weight") or {}),
            },
        }
    elif key == "network":
        payload = {"network": (data or {}).get("network") or {}}
    elif key == "cpa":
        payload = {"cpa": (data or {}).get("cpa") or {}}
    elif key in ("codex_proxy", "codex-proxy"):
        payload = {"codex_proxy": (data or {}).get("codex_proxy") or {}}
    elif key == "runtime":
        email_data = (data or {}).get("email") or {}
        payload = {
            "run": (data or {}).get("run") or {},
            "email": {
                "otp": (email_data.get("otp") or {}),
            },
        }
    else:
        raise KeyError(section)
    saved = write_config(payload)
    return read_config_section(key)


def read_recent_accounts(limit: int = 20) -> List[Dict[str, Any]]:
    if not os.path.exists(ACCOUNTS_CSV):
        return []
    try:
        with open(ACCOUNTS_CSV, "r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
    except Exception:
        return []
    rows = rows[-limit:]
    rows.reverse()
    return rows


def read_logs(limit: int = 200) -> List[str]:
    if not os.path.exists(LOG_FILE):
        return [
            "当前还没有运行日志。",
            "通过 WebUI 启动主程序后，会自动生成 runtime.log 并在这里显示最近输出。",
        ]
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as fh:
            lines = [line.rstrip("\n") for line in fh.readlines()]
    except Exception as exc:
        return [f"读取日志失败：{exc}"]
    return lines[-limit:] or ["日志文件为空。"]


def _worker_slot_list() -> List[Dict[str, Any]]:
    state = read_runtime_state()
    slots = state.get("worker_slots") or {}
    items: List[Dict[str, Any]] = []
    for key, value in slots.items():
        item = dict(value or {})
        try:
            item["worker_id"] = int(item.get("worker_id") or key)
        except (TypeError, ValueError):
            item["worker_id"] = 0
        item["lines"] = list(item.get("lines") or [])
        items.append(item)
    items.sort(key=lambda item: item.get("worker_id", 0))
    return items


def build_dashboard_data() -> Dict[str, Any]:
    cfg = read_config()
    reg_mtime = _fmt_ts(os.path.getmtime(CONFIG_PATH)) if os.path.exists(CONFIG_PATH) else "未知"
    token_items = recent_token_files(limit=10)
    runtime_status = process_manager.status()
    return {
        "summary": {
            "proxy": cfg["network"]["proxy"] if cfg["network"]["enabled"] and cfg["network"]["proxy"] else "直连",
            "email_enabled": len(get_enabled_email_providers(cfg)),
            "workers": cfg["run"]["workers"],
            "max_success": cfg["run"]["max_success"],
            "sleep_window": f"{cfg['run']['sleep_min']} - {cfg['run']['sleep_max']} 秒",
            "token_count": len(token_items),
            "accounts_count": count_accounts_csv(),
            "config_updated_at": reg_mtime,
            "attempts": runtime_status.get("attempts", 0),
            "successes": runtime_status.get("successes", 0),
            "failures": runtime_status.get("failures", 0),
        },
        "runtime": {
            "running": runtime_status["running"],
            "mode": "WebUI 单入口控制",
            "message": runtime_status["message"],
            "pid": runtime_status["pid"],
            "started_at": runtime_status["started_at"],
            "last_exit_code": runtime_status["last_exit_code"],
            "phase": runtime_status.get("phase", "idle"),
            "workers_active": runtime_status.get("workers_active", 0),
            "last_email": runtime_status.get("last_email", ""),
        },
        "paths": {
            "script_dir": SCRIPT_DIR,
            "runtime_root": RUNTIME_ROOT,
            "entry_script": runtime_status.get("entry_script", ""),
            "config_path": CONFIG_PATH,
            "token_dir": OUTPUT_DIR,
            "accounts_csv": ACCOUNTS_CSV,
            "runtime_log": LOG_FILE,
            "runtime_state": RUNTIME_STATE_PATH,
        },
        "recent_tokens": token_items,
    }


def build_results_data() -> Dict[str, Any]:
    return {
        "recent_tokens": recent_token_files(limit=30),
        "recent_accounts": read_recent_accounts(limit=30),
    }


def build_cpa_overview() -> Dict[str, Any]:
    return get_cpa_overview_data()


def build_cpa_accounts(
    page: int = 1,
    per_page: int = DEFAULT_ACCOUNTS_PER_PAGE,
    health_status: str = "",
    provider: str = "",
    disabled_state: str = "",
    keyword: str = "",
    force_reload: bool = False,
) -> Dict[str, Any]:
    try:
        page_data = get_remote_accounts_filtered_page(
            page=page,
            per_page=per_page,
            health_status=health_status,
            provider=provider,
            disabled_state=disabled_state,
            keyword=keyword,
            force_reload=force_reload,
        )
        return {
            "ok": True,
            "accounts": page_data["accounts"],
            "pagination": page_data["pagination"],
            "filters": page_data.get("filters") or {},
            "filter_options": page_data.get("filter_options") or {},
            "message": "CPA 账号列表加载成功",
        }
    except Exception as exc:
        return {
            "ok": False,
            "accounts": [],
            "pagination": {
                "page": max(1, int(page or 1)),
                "per_page": max(1, int(per_page or DEFAULT_ACCOUNTS_PER_PAGE)),
                "total": 0,
                "total_pages": 1,
                "has_prev": False,
                "has_next": False,
            },
            "filters": {
                "health_status": str(health_status or "").strip().lower(),
                "provider": str(provider or "").strip().lower(),
                "disabled_state": str(disabled_state or "").strip().lower(),
                "keyword": str(keyword or "").strip(),
            },
            "filter_options": {
                "providers": [],
                "health_statuses": ["untested", "healthy", "limited", "unknown", "unusable"],
                "disabled_states": ["enabled", "disabled"],
            },
            "message": str(exc),
        }


def build_control_data() -> Dict[str, Any]:
    status = process_manager.status()
    log_exists = bool(status.get("running")) or os.path.exists(LOG_FILE)
    return {
        **status,
        "actions": [
            {"id": "start", "label": "启动主程序", "enabled": not status.get("running"), "variant": "primary"},
            {"id": "stop", "label": "停止主程序", "enabled": status.get("running"), "variant": "primary"},
            {"id": "restart", "label": "重启主程序", "enabled": status.get("running"), "variant": "primary"},
            {"id": "logs/delete", "label": "删除运行日志", "enabled": log_exists, "variant": "danger"},
        ],
        "worker_slots": _worker_slot_list(),
    }


def build_logs_data(limit: int = 200) -> Dict[str, Any]:
    runtime_state = read_runtime_state()
    return {
        "lines": read_logs(limit=limit),
        "recent_events": list(runtime_state.get("recent_events") or []),
        "running": runtime_state.get("running", False),
        "phase": runtime_state.get("phase", "idle"),
        "updated_at": runtime_state.get("updated_at", ""),
        "log_file": LOG_FILE,
        "state_file": RUNTIME_STATE_PATH,
    }

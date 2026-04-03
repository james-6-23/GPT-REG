import os
import queue
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from .config import load_or_create_config, normalize_config
from .cpa_client import CpaClient, CpaClientError
from .cpa_state import read_cpa_state, read_health_task, remove_remote_health, update_health_task, update_remote_health, update_site_test
from .health_probe import (
    CODEX_ACCOUNTS_CHECK_URL,
    CODEX_PROBE_MODEL,
    CODEX_USAGE_URL,
    OPENAI_HEALTH_API_URL,
    classify_codex_probe,
    classify_openai_probe,
    merge_auto_probe_results,
)
from .storage import read_accounts_table, update_account_row

SYNC_STATUS_OFF = "off"
SYNC_STATUS_MANUAL = "manual"
SYNC_STATUS_PENDING = "pending"
SYNC_STATUS_SYNCING = "syncing"
SYNC_STATUS_SYNCED = "synced"
SYNC_STATUS_FAILED = "failed"

_sync_queue: queue.Queue[str] = queue.Queue()
_sync_worker: Optional[threading.Thread] = None
_sync_worker_lock = threading.Lock()
_queued_paths: set[str] = set()
_queued_paths_lock = threading.Lock()
_health_task_thread: Optional[threading.Thread] = None
_health_task_lock = threading.Lock()

DEFAULT_ACCOUNTS_PER_PAGE = 50
MAX_ACCOUNTS_PER_PAGE = 500
HEALTH_TASK_RECENT_LIMIT = 120
ACCOUNT_HEALTH_FILTERS = {"healthy", "limited", "unknown", "unusable", "untested"}
ACCOUNT_DISABLED_FILTERS = {"enabled", "disabled"}

_FIXED_BAD_KEYWORDS = (
    "unauthorized",
    "unsupported_country_region_territory",
    "account_deactivated",
    "account_suspended",
    "access_terminated",
    "invalid_api_key",
    "policy_violation",
    "abuse",
    "deactivated",
    "suspended",
    "banned",
    "disabled",
)


class CpaServiceError(RuntimeError):
    pass


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _norm_path(value: str) -> str:
    return os.path.normcase(os.path.abspath(value or ""))


def _load_config(force_reload: bool = False) -> dict[str, Any]:
    return normalize_config(load_or_create_config(force_reload=force_reload))


def _resolve_proxy(cfg: dict[str, Any]) -> Optional[str]:
    cpa_cfg = cfg.get("cpa") or {}
    net_cfg = cfg.get("network") or {}
    mode = str(cpa_cfg.get("upload_proxy_mode") or "default").strip().lower()
    custom_proxy = str(cpa_cfg.get("custom_proxy") or "").strip() or None
    default_proxy = str(net_cfg.get("proxy") or "").strip() if net_cfg.get("enabled", True) else ""
    default_proxy = default_proxy or None

    if mode == "direct":
        return None
    if mode == "custom":
        proxy = custom_proxy
    else:
        proxy = default_proxy

    if proxy and "://" not in proxy:
        proxy = f"http://{proxy}"
    return proxy


def _cpa_cfg_ready(cpa_cfg: dict[str, Any]) -> bool:
    return bool(cpa_cfg.get("enabled") and str(cpa_cfg.get("management_url") or "").strip() and str(cpa_cfg.get("management_token") or "").strip())


def _build_client(force_reload: bool = False) -> CpaClient:
    cfg = _load_config(force_reload=force_reload)
    cpa_cfg = cfg.get("cpa") or {}
    if not _cpa_cfg_ready(cpa_cfg):
        raise CpaServiceError("请先在配置中心开启 CPA 并填写连接信息")
    try:
        return CpaClient(
            management_url=str(cpa_cfg.get("management_url") or "").strip(),
            management_token=str(cpa_cfg.get("management_token") or "").strip(),
            timeout=int(cpa_cfg.get("timeout") or 15),
            proxy=_resolve_proxy(cfg),
            verify=False,
        )
    except CpaClientError as exc:
        raise CpaServiceError(str(exc)) from exc


def _queue_status_for_current_config(cfg: dict[str, Any]) -> str:
    cpa_cfg = cfg.get("cpa") or {}
    if not cpa_cfg.get("enabled"):
        return SYNC_STATUS_OFF
    if not cpa_cfg.get("auto_sync_on_success"):
        return SYNC_STATUS_MANUAL
    if not str(cpa_cfg.get("management_url") or "").strip() or not str(cpa_cfg.get("management_token") or "").strip():
        return SYNC_STATUS_MANUAL
    return SYNC_STATUS_PENDING


def _iter_pending_local_rows(rows: Iterable[Dict[str, str]]) -> Iterable[Dict[str, str]]:
    for row in rows:
        token_file = str(row.get("token_file") or "").strip()
        if not token_file:
            continue
        if not os.path.exists(token_file):
            continue
        status = str(row.get("cpa_sync_status") or "").strip().lower()
        if status == SYNC_STATUS_SYNCED:
            continue
        yield row


def _account_cache_key(item: Dict[str, Any]) -> str:
    return str(item.get("name") or item.get("id") or "").strip()


def _account_id_from_item(item: Dict[str, Any]) -> str:
    id_token = item.get("id_token")
    if isinstance(id_token, dict):
        return str(id_token.get("chatgpt_account_id") or "").strip()
    return ""


def _infer_fixed_unusable_reason(item: Dict[str, Any]) -> str:
    text = str(item.get("status_message") or "").strip().lower()
    if not text:
        return ""
    for keyword in _FIXED_BAD_KEYWORDS:
        if keyword in text:
            return keyword
    return ""


def _api_call_openai(client: CpaClient, auth_index: str) -> tuple[str, int, str]:
    payload = client.api_call(
        auth_index=auth_index,
        method="GET",
        url=OPENAI_HEALTH_API_URL,
        header={
            "Authorization": "Bearer $TOKEN$",
            "Accept": "application/json",
            "User-Agent": "codex_cli_rs/0.101.0",
        },
    )
    return classify_openai_probe(payload.get("status_code", 0), payload.get("body", ""))


def _api_call_codex(client: CpaClient, auth_index: str, account_id: str, url: str, label: str) -> tuple[str, int, str]:
    headers = {
        "Authorization": "Bearer $TOKEN$",
        "Accept": "application/json",
        "User-Agent": "codex_cli_rs/0.101.0",
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id
    payload = client.api_call(
        auth_index=auth_index,
        method="GET",
        url=url,
        header=headers,
    )
    return classify_codex_probe(label, payload.get("status_code", 0), payload.get("body", ""))


def _probe_remote_account(client: CpaClient, item: Dict[str, Any], probe_mode: str) -> Dict[str, Any]:
    name = _account_cache_key(item)
    auth_index = str(item.get("auth_index") or "").strip()
    provider = str(item.get("provider") or item.get("type") or "").strip().lower()
    disabled = bool(item.get("disabled"))
    unavailable = bool(item.get("unavailable"))
    account_id = _account_id_from_item(item)
    now = _now_str()

    result = {
        "name": name,
        "provider": provider,
        "email": str(item.get("email") or "").strip(),
        "disabled": disabled,
        "unavailable": unavailable,
        "health_status": "unknown",
        "health_reason": "",
        "health_http_status": 0,
        "health_checked_at": now,
        "status": str(item.get("status") or ""),
        "status_message": str(item.get("status_message") or ""),
    }

    if not auth_index:
        result["health_reason"] = "missing_auth_index"
        return result

    fixed_reason = _infer_fixed_unusable_reason(item)
    if fixed_reason:
        result["health_status"] = "unusable"
        result["health_reason"] = fixed_reason
        return result

    if disabled:
        result["health_reason"] = "disabled_account"
        return result

    mode = str(probe_mode or "auto").strip().lower() or "auto"

    try:
        if provider != "codex":
            status, code, reason = _api_call_openai(client, auth_index)
        elif mode == "openai":
            status, code, reason = _api_call_openai(client, auth_index)
        elif mode == "codex":
            usage_res = _api_call_codex(client, auth_index, account_id, CODEX_USAGE_URL, "codex_usage")
            if usage_res[0] in ("healthy", "limited", "unusable"):
                status, code, reason = usage_res
            else:
                status, code, reason = _api_call_codex(client, auth_index, account_id, CODEX_ACCOUNTS_CHECK_URL, "codex_accounts_check")
        else:
            openai_res = _api_call_openai(client, auth_index)
            usage_res = _api_call_codex(client, auth_index, account_id, CODEX_USAGE_URL, "codex_usage")
            if usage_res[0] in ("healthy", "limited", "unusable"):
                codex_res = usage_res
            else:
                codex_res = _api_call_codex(client, auth_index, account_id, CODEX_ACCOUNTS_CHECK_URL, "codex_accounts_check")
            status, code, reason = merge_auto_probe_results(openai_res, codex_res, prefer_codex=bool(account_id))
    except Exception as exc:
        status, code, reason = "unknown", 0, f"probe_failed:{exc}"

    result["health_status"] = status
    result["health_http_status"] = int(code or 0)
    result["health_reason"] = reason
    return result


def _summarize_health(items: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    stats = {
        "healthy": 0,
        "limited": 0,
        "unknown": 0,
        "unusable": 0,
        "disabled": 0,
        "untested": 0,
    }
    for item in items:
        if item.get("disabled"):
            stats["disabled"] += 1
        status = str(item.get("health_status") or "").strip().lower()
        if status in stats:
            stats[status] += 1
        elif not status:
            stats["untested"] += 1
        else:
            stats["unknown"] += 1
    return stats


def _empty_health_summary() -> Dict[str, int]:
    return {
        "healthy": 0,
        "limited": 0,
        "unknown": 0,
        "unusable": 0,
        "disabled": 0,
        "untested": 0,
    }


def _normalize_names(names: Optional[List[str]]) -> List[str]:
    unique: List[str] = []
    seen: set[str] = set()
    for raw in names or []:
        name = str(raw or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        unique.append(name)
    return unique


def _normalize_health_filter(health_status: Any) -> str:
    value = str(health_status or "").strip().lower()
    return value if value in ACCOUNT_HEALTH_FILTERS else ""


def _normalized_account_health_status(item: Dict[str, Any]) -> str:
    status = str(item.get("health_status") or "").strip().lower()
    return status if status in ACCOUNT_HEALTH_FILTERS else "untested"


def _account_provider_value(item: Dict[str, Any]) -> str:
    return str(item.get("provider") or item.get("type") or "").strip().lower()


def _normalize_provider_filter(provider: Any) -> str:
    return str(provider or "").strip().lower()


def _normalize_disabled_filter(disabled_state: Any) -> str:
    value = str(disabled_state or "").strip().lower()
    return value if value in ACCOUNT_DISABLED_FILTERS else ""


def _matches_account_keyword(item: Dict[str, Any], keyword: str) -> bool:
    if not keyword:
        return True
    target = keyword.strip().lower()
    if not target:
        return True
    name = str(item.get("name") or "").strip().lower()
    email = str(item.get("email") or "").strip().lower()
    return target in name or target in email


def _normalize_page(value: Any, default: int = 1) -> int:
    try:
        page = int(value)
    except (TypeError, ValueError):
        return max(1, default)
    return max(1, page)


def _normalize_per_page(value: Any, default: int = DEFAULT_ACCOUNTS_PER_PAGE) -> int:
    try:
        per_page = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(MAX_ACCOUNTS_PER_PAGE, per_page))


def _normalize_worker_count(value: Any, default: int) -> int:
    try:
        workers = int(value)
    except (TypeError, ValueError):
        workers = default
    return max(1, min(64, workers))


def _build_health_runtime_settings(force_reload: bool = False) -> Dict[str, Any]:
    cfg = _load_config(force_reload=force_reload)
    cpa_cfg = cfg.get("cpa") or {}
    return {
        "config": cfg,
        "probe_mode": str(cpa_cfg.get("health_probe_mode") or "auto").strip().lower() or "auto",
        "probe_workers": _normalize_worker_count(cpa_cfg.get("probe_workers"), 12),
        "delete_workers": _normalize_worker_count(cpa_cfg.get("delete_workers"), 8),
        "using_proxy": _resolve_proxy(cfg) or "",
    }


def _account_health_cache_payload(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "health_status": str(item.get("health_status") or ""),
        "health_reason": str(item.get("health_reason") or ""),
        "health_http_status": int(item.get("health_http_status") or 0),
        "health_checked_at": str(item.get("health_checked_at") or ""),
    }


def _recent_item_payload(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": str(item.get("name") or ""),
        "email": str(item.get("email") or ""),
        "provider": str(item.get("provider") or item.get("type") or ""),
        "health_status": str(item.get("health_status") or ""),
        "health_http_status": int(item.get("health_http_status") or 0),
        "health_reason": str(item.get("health_reason") or ""),
        "health_checked_at": str(item.get("health_checked_at") or ""),
        "status": str(item.get("status") or ""),
        "disabled": bool(item.get("disabled")),
    }


def _push_recent_item(items: List[Dict[str, Any]], item: Dict[str, Any], limit: int = HEALTH_TASK_RECENT_LIMIT) -> List[Dict[str, Any]]:
    recent = list(items or [])
    recent.append(_recent_item_payload(item))
    if len(recent) > limit:
        recent = recent[-limit:]
    return recent


def _apply_summary_increment(summary: Dict[str, int], item: Dict[str, Any]) -> None:
    if item.get("disabled"):
        summary["disabled"] = int(summary.get("disabled") or 0) + 1
    status = str(item.get("health_status") or "").strip().lower()
    if status in summary:
        summary[status] = int(summary.get(status) or 0) + 1
    elif not status:
        summary["untested"] = int(summary.get("untested") or 0) + 1
    else:
        summary["unknown"] = int(summary.get("unknown") or 0) + 1


def _probe_exception_result(item: Dict[str, Any], exc: Exception) -> Dict[str, Any]:
    return {
        "name": _account_cache_key(item),
        "provider": str(item.get("provider") or item.get("type") or "").strip().lower(),
        "email": str(item.get("email") or "").strip(),
        "disabled": bool(item.get("disabled")),
        "unavailable": bool(item.get("unavailable")),
        "health_status": "unknown",
        "health_reason": f"probe_failed:{exc}",
        "health_http_status": 0,
        "health_checked_at": _now_str(),
        "status": str(item.get("status") or ""),
        "status_message": str(item.get("status_message") or ""),
    }


def _resolve_remote_items(client: CpaClient, names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    items = client.list_auth_files()
    name_set = set(_normalize_names(names))
    if name_set:
        items = [item for item in items if _account_cache_key(item) in name_set]
    return items


def _run_remote_health_check_internal(
    client: CpaClient,
    items: List[Dict[str, Any]],
    *,
    probe_mode: str,
    probe_workers: int,
    progress_callback=None,
) -> Dict[str, Any]:
    total = len(items)
    summary = _empty_health_summary()
    health_map: Dict[str, Dict[str, Any]] = {}
    recent_items: List[Dict[str, Any]] = []
    result_slots: List[Optional[Dict[str, Any]]] = [None] * total

    if total <= 0:
        return {
            "total": 0,
            "summary": summary,
            "items": [],
            "health_map": {},
            "probe_mode": probe_mode,
            "probe_model": CODEX_PROBE_MODEL,
            "checked_at": _now_str(),
            "probe_workers": probe_workers,
            "recent_items": [],
        }

    with ThreadPoolExecutor(max_workers=probe_workers, thread_name_prefix="reg-gpt-cpa-probe") as executor:
        future_map = {
            executor.submit(_probe_remote_account, client, item, probe_mode): (index, item)
            for index, item in enumerate(items)
        }
        processed = 0
        for future in as_completed(future_map):
            index, item = future_map[future]
            try:
                checked = future.result()
            except Exception as exc:
                checked = _probe_exception_result(item, exc)

            merged = dict(item or {})
            merged.update(checked)
            result_slots[index] = merged

            key = _account_cache_key(item)
            if key:
                health_map[key] = _account_health_cache_payload(merged)

            processed += 1
            _apply_summary_increment(summary, merged)
            recent_items = _push_recent_item(recent_items, merged)

            if progress_callback:
                progress_callback({
                    "processed": processed,
                    "total": total,
                    "item": merged,
                    "summary": dict(summary),
                    "recent_items": list(recent_items),
                })

    results = [item for item in result_slots if item is not None]
    return {
        "total": total,
        "summary": dict(summary),
        "items": results,
        "health_map": health_map,
        "probe_mode": probe_mode,
        "probe_model": CODEX_PROBE_MODEL,
        "checked_at": _now_str(),
        "probe_workers": probe_workers,
        "recent_items": recent_items,
    }


def _cleanup_remote_accounts_internal(
    client: CpaClient,
    names: List[str],
    *,
    delete_workers: int,
    progress_callback=None,
) -> Dict[str, Any]:
    targets = _normalize_names(names)
    total = len(targets)
    deleted_total = 0
    removed_names: List[str] = []
    failed: List[Dict[str, Any]] = []

    if total <= 0:
        return {
            "matched_total": 0,
            "deleted_total": 0,
            "failed_total": 0,
            "removed_names": [],
            "failed": [],
            "delete_workers": delete_workers,
        }

    with ThreadPoolExecutor(max_workers=delete_workers, thread_name_prefix="reg-gpt-cpa-delete") as executor:
        future_map = {executor.submit(client.delete_auth_file, name): name for name in targets}
        processed = 0
        for future in as_completed(future_map):
            name = future_map[future]
            ok = False
            error_message = ""
            try:
                future.result()
                ok = True
                deleted_total += 1
                removed_names.append(name)
            except Exception as exc:
                error_message = str(exc)
                failed.append({"name": name, "error": error_message})

            processed += 1
            if progress_callback:
                progress_callback({
                    "processed": processed,
                    "total": total,
                    "name": name,
                    "ok": ok,
                    "error": error_message,
                    "deleted_total": deleted_total,
                    "failed_total": len(failed),
                })

    return {
        "matched_total": total,
        "deleted_total": deleted_total,
        "failed_total": len(failed),
        "removed_names": removed_names,
        "failed": failed,
        "delete_workers": delete_workers,
    }


def _health_stage_label(stage: str) -> str:
    labels = {
        "": "未开始",
        "queued": "已启动",
        "loading": "读取账号列表中",
        "probing": "健康检测中",
        "cleanup": "清理不可用账号中",
        "cleanup_cached": "按已标记状态直接清理",
        "completed": "已完成",
        "failed": "执行失败",
        "interrupted": "任务中断",
    }
    return labels.get(str(stage or "").strip().lower(), str(stage or "未开始"))


def _decorate_health_task_status(task: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(task or {})
    if not payload.get("task_id"):
        payload.setdefault("message", "尚未执行健康检测任务")

    stage = str(payload.get("stage") or "").strip().lower()
    if stage == "cleanup" and int(payload.get("cleanup_total") or 0) > 0:
        progress_current = int(payload.get("deleted_total") or 0) + int(payload.get("failed_total") or 0)
        progress_total = int(payload.get("cleanup_total") or 0)
    else:
        progress_current = int(payload.get("processed") or 0)
        progress_total = int(payload.get("total") or 0)

    progress_percent = 0
    if progress_total > 0:
        progress_percent = min(100, max(0, round(progress_current * 100 / progress_total)))
    elif not payload.get("running") and payload.get("task_id"):
        progress_percent = 100

    payload["stage_label"] = _health_stage_label(stage)
    payload["progress_current"] = progress_current
    payload["progress_total"] = progress_total
    payload["progress_percent"] = progress_percent
    payload["proxy_label"] = payload.get("using_proxy") or "直连"
    payload["selected_total"] = len(_normalize_names(payload.get("selected_names") or []))
    return payload


def test_cpa_connection(force_reload: bool = False) -> Dict[str, Any]:
    cfg = _load_config(force_reload=force_reload)
    cpa_cfg = cfg.get("cpa") or {}
    if not cpa_cfg.get("enabled"):
        raise CpaServiceError("请先在配置中心开启 CPA")

    client = _build_client(force_reload=force_reload)
    try:
        result = client.test_connection()
    except Exception as exc:
        update_site_test({
            "ok": False,
            "message": str(exc),
            "checked_at": _now_str(),
        })
        raise

    result["checked_at"] = _now_str()
    update_site_test(result)
    return result


def list_remote_accounts(force_reload: bool = False) -> List[Dict[str, Any]]:
    client = _build_client(force_reload=force_reload)
    items = client.list_auth_files()
    cache = read_cpa_state().get("remote_health") or {}
    merged: List[Dict[str, Any]] = []
    for item in items:
        name = _account_cache_key(item)
        entry = dict(item or {})
        if isinstance(cache.get(name), dict):
            entry.update({
                "health_status": cache[name].get("health_status", ""),
                "health_reason": cache[name].get("health_reason", ""),
                "health_http_status": cache[name].get("health_http_status", 0),
                "health_checked_at": cache[name].get("health_checked_at", ""),
            })
        merged.append(entry)
    merged.sort(key=lambda x: str(x.get("updated_at") or x.get("modtime") or x.get("name") or ""), reverse=True)
    return merged


def get_remote_accounts_page(page: int = 1, per_page: int = DEFAULT_ACCOUNTS_PER_PAGE, *, force_reload: bool = False) -> Dict[str, Any]:
    accounts = list_remote_accounts(force_reload=force_reload)
    total = len(accounts)
    per_page_value = _normalize_per_page(per_page)
    total_pages = max(1, (total + per_page_value - 1) // per_page_value) if total else 1
    page_value = min(_normalize_page(page), total_pages)
    start = (page_value - 1) * per_page_value
    end = start + per_page_value
    return {
        "accounts": accounts[start:end],
        "pagination": {
            "page": page_value,
            "per_page": per_page_value,
            "total": total,
            "total_pages": total_pages,
            "has_prev": page_value > 1,
            "has_next": page_value < total_pages,
        },
        "filters": {
            "health_status": "",
        },
    }


def get_remote_accounts_filtered_page(
    page: int = 1,
    per_page: int = DEFAULT_ACCOUNTS_PER_PAGE,
    *,
    health_status: str = "",
    provider: str = "",
    disabled_state: str = "",
    keyword: str = "",
    force_reload: bool = False,
) -> Dict[str, Any]:
    accounts = list_remote_accounts(force_reload=force_reload)
    provider_options = sorted({_account_provider_value(item) for item in accounts if _account_provider_value(item)})
    health_filter = _normalize_health_filter(health_status)
    provider_filter = _normalize_provider_filter(provider)
    disabled_filter = _normalize_disabled_filter(disabled_state)
    keyword_filter = str(keyword or "").strip()
    if health_filter:
        accounts = [item for item in accounts if _normalized_account_health_status(item) == health_filter]
    if provider_filter:
        accounts = [item for item in accounts if _account_provider_value(item) == provider_filter]
    if disabled_filter == "enabled":
        accounts = [item for item in accounts if not bool(item.get("disabled"))]
    elif disabled_filter == "disabled":
        accounts = [item for item in accounts if bool(item.get("disabled"))]
    if keyword_filter:
        accounts = [item for item in accounts if _matches_account_keyword(item, keyword_filter)]
    total = len(accounts)
    per_page_value = _normalize_per_page(per_page)
    total_pages = max(1, (total + per_page_value - 1) // per_page_value) if total else 1
    page_value = min(_normalize_page(page), total_pages)
    start = (page_value - 1) * per_page_value
    end = start + per_page_value
    return {
        "accounts": accounts[start:end],
        "pagination": {
            "page": page_value,
            "per_page": per_page_value,
            "total": total,
            "total_pages": total_pages,
            "has_prev": page_value > 1,
            "has_next": page_value < total_pages,
        },
        "filters": {
            "health_status": health_filter,
            "provider": provider_filter,
            "disabled_state": disabled_filter,
            "keyword": keyword_filter,
        },
        "filter_options": {
            "providers": provider_options,
            "health_statuses": ["untested", "healthy", "limited", "unknown", "unusable"],
            "disabled_states": ["enabled", "disabled"],
        },
    }


def get_cpa_overview_data(force_reload: bool = False) -> Dict[str, Any]:
    cfg = _load_config(force_reload=force_reload)
    cpa_cfg = cfg.get("cpa") or {}
    state = read_cpa_state()
    local_fields, local_rows = read_accounts_table()
    local_rows = list(local_rows)
    blank_status = _queue_status_for_current_config(cfg)

    local_stats = {
        "total": len(local_rows),
        "pending": 0,
        "syncing": 0,
        "synced": 0,
        "failed": 0,
        "manual": 0,
        "off": 0,
    }
    recent_syncs: List[Dict[str, Any]] = []
    for row in local_rows:
        status = str(row.get("cpa_sync_status") or "").strip().lower()
        if status in local_stats:
            local_stats[status] += 1
        elif not status:
            local_stats[blank_status if blank_status in local_stats else "pending"] += 1
        else:
            local_stats["failed"] += 1

    for row in reversed(local_rows[-30:]):

        if row.get("cpa_synced_at") or row.get("cpa_sync_message"):
            recent_syncs.append({
                "email": str(row.get("email") or ""),
                "token_file": str(row.get("token_file") or ""),
                "cpa_sync_status": str(row.get("cpa_sync_status") or ""),
                "cpa_synced_at": str(row.get("cpa_synced_at") or ""),
                "cpa_sync_message": str(row.get("cpa_sync_message") or ""),
            })
        if len(recent_syncs) >= 10:
            break

    if not _cpa_cfg_ready(cpa_cfg):
        return {
            "enabled": bool(cpa_cfg.get("enabled")),
            "configured": False,
            "message": "请先在配置中心开启 CPA 并填写连接信息",
            "site_test": state.get("site_test") or {},
            "local_stats": local_stats,
            "recent_syncs": recent_syncs,
            "remote_stats": _summarize_health([]),
            "remote_total": 0,
            "codex_total": 0,
            "accounts": [],
            "health_probe_mode": str(cpa_cfg.get("health_probe_mode") or "auto"),
            "health_task": get_remote_health_task_status(),
        }

    try:
        accounts = list_remote_accounts(force_reload=force_reload)
    except Exception as exc:
        return {
            "enabled": True,
            "configured": True,
            "message": str(exc),
            "site_test": state.get("site_test") or {},
            "local_stats": local_stats,
            "recent_syncs": recent_syncs,
            "remote_stats": _summarize_health([]),
            "remote_total": 0,
            "codex_total": 0,
            "accounts": [],
            "health_probe_mode": str(cpa_cfg.get("health_probe_mode") or "auto"),
            "health_task": get_remote_health_task_status(),
        }

    remote_stats = _summarize_health(accounts)
    codex_total = sum(1 for item in accounts if str(item.get("provider") or "").strip().lower() == "codex")
    return {
        "enabled": True,
        "configured": True,
        "message": "CPA 已连接",
        "site_test": state.get("site_test") or {},
        "local_stats": local_stats,
        "recent_syncs": recent_syncs,
        "remote_stats": remote_stats,
        "remote_total": len(accounts),
        "codex_total": codex_total,
        "accounts": accounts[:10],
        "health_probe_mode": str(cpa_cfg.get("health_probe_mode") or "auto"),
        "health_task": get_remote_health_task_status(),
    }


def enqueue_sync_token_file(token_file: str) -> Dict[str, Any]:
    path = _norm_path(token_file)
    if not path:
        return {"ok": False, "message": "token 文件路径为空"}

    cfg = _load_config(force_reload=False)
    status = _queue_status_for_current_config(cfg)
    status_message = {
        SYNC_STATUS_OFF: "CPA 未开启，暂不自动同步",
        SYNC_STATUS_MANUAL: "已保存到本地，等待手动同步到 CPA",
        SYNC_STATUS_PENDING: "已加入 CPA 同步队列",
    }.get(status, "已加入同步队列")

    update_account_row(path, {
        "cpa_sync_status": status,
        "cpa_sync_message": status_message,
    })

    if status != SYNC_STATUS_PENDING:
        return {"ok": True, "queued": False, "status": status}

    with _queued_paths_lock:
        if path in _queued_paths:
            return {"ok": True, "queued": False, "status": SYNC_STATUS_PENDING}
        _queued_paths.add(path)

    _sync_queue.put(path)
    _ensure_sync_worker()
    return {"ok": True, "queued": True, "status": SYNC_STATUS_PENDING}


def _ensure_sync_worker() -> None:
    global _sync_worker
    with _sync_worker_lock:
        if _sync_worker and _sync_worker.is_alive():
            return
        _sync_worker = threading.Thread(target=_sync_worker_loop, name="reg-gpt-cpa-sync", daemon=True)
        _sync_worker.start()


def _sync_worker_loop() -> None:
    while True:
        path = _sync_queue.get()
        try:
            update_account_row(path, {
                "cpa_sync_status": SYNC_STATUS_SYNCING,
                "cpa_sync_message": "正在同步到 CPA",
            })
            sync_token_file(path, force_reload=True)
        except Exception as exc:
            update_account_row(path, {
                "cpa_sync_status": SYNC_STATUS_FAILED,
                "cpa_sync_message": str(exc),
            })
        finally:
            with _queued_paths_lock:
                _queued_paths.discard(path)
            _sync_queue.task_done()


def sync_token_file(token_file: str, *, force_reload: bool = False) -> Dict[str, Any]:
    path = _norm_path(token_file)
    if not path or not os.path.exists(path):
        raise CpaServiceError(f"待同步 token 文件不存在: {token_file}")

    client = _build_client(force_reload=force_reload)
    file_name = os.path.basename(path)
    try:
        upload_result = client.upload_auth_file(path, name=file_name)
    except Exception as exc:
        update_account_row(path, {
            "cpa_sync_status": SYNC_STATUS_FAILED,
            "cpa_sync_message": str(exc),
        })
        raise CpaServiceError(str(exc)) from exc

    update_account_row(path, {
        "cpa_sync_status": SYNC_STATUS_SYNCED,
        "cpa_remote_name": file_name,
        "cpa_synced_at": _now_str(),
        "cpa_sync_message": "已成功同步到 CPA",
    })
    return upload_result


def sync_pending_local_accounts(limit: int = 0, *, force_reload: bool = False) -> Dict[str, Any]:
    _fields, rows = read_accounts_table()
    candidates = list(_iter_pending_local_rows(rows))
    if limit > 0:
        candidates = candidates[:limit]

    success = 0
    failed = 0
    results: List[Dict[str, Any]] = []
    for row in candidates:
        token_file = str(row.get("token_file") or "").strip()
        try:
            sync_token_file(token_file, force_reload=force_reload)
            success += 1
            results.append({
                "token_file": token_file,
                "status": SYNC_STATUS_SYNCED,
                "message": "同步成功",
            })
        except Exception as exc:
            failed += 1
            results.append({
                "token_file": token_file,
                "status": SYNC_STATUS_FAILED,
                "message": str(exc),
            })

    return {
        "total": len(candidates),
        "success": success,
        "failed": failed,
        "results": results,
    }


def get_remote_health_task_status() -> Dict[str, Any]:
    task = read_health_task()
    with _health_task_lock:
        running_thread = _health_task_thread
        alive = bool(running_thread and running_thread.is_alive())

    if task.get("running") and not alive:
        update_health_task({
            "running": False,
            "stage": "interrupted",
            "message": "后台健康任务已中断，可能是服务重启或异常退出",
            "finished_at": task.get("finished_at") or _now_str(),
        })
        task = read_health_task()

    return _decorate_health_task_status(task)


def _run_remote_health_task(task_id: str, names: List[str], cleanup: bool, force_reload: bool) -> None:
    global _health_task_thread
    current_thread = threading.current_thread()
    try:
        update_health_task({
            "task_id": task_id,
            "running": True,
            "stage": "loading",
            "message": "正在读取 CPA 账号列表",
        })

        client = _build_client(force_reload=force_reload)
        runtime = _build_health_runtime_settings(force_reload=force_reload)
        probe_mode = runtime["probe_mode"]
        probe_workers = runtime["probe_workers"]
        delete_workers = runtime["delete_workers"]
        using_proxy = runtime["using_proxy"]

        items = _resolve_remote_items(client, names)
        total = len(items)
        update_health_task({
            "task_id": task_id,
            "running": True,
            "stage": "probing" if total else "completed",
            "message": f"已加载 {total} 个账号，准备开始健康检测" if total else "没有匹配到可检测的 CPA 账号",
            "probe_mode": probe_mode,
            "probe_workers": probe_workers,
            "delete_workers": delete_workers,
            "using_proxy": using_proxy,
            "total": total,
            "processed": 0,
            "cleanup_total": 0,
            "deleted_total": 0,
            "failed_total": 0,
            "summary": _empty_health_summary(),
            "recent_items": [],
        })

        if total <= 0:
            update_health_task({
                "running": False,
                "stage": "completed",
                "message": "没有匹配到可检测的 CPA 账号",
                "finished_at": _now_str(),
            })
            return

        def on_probe_progress(payload: Dict[str, Any]) -> None:
            item = payload["item"]
            key = _account_cache_key(item)
            if key:
                update_remote_health({key: _account_health_cache_payload(item)})
            update_health_task({
                "task_id": task_id,
                "running": True,
                "stage": "probing",
                "message": f"正在检测：{key or item.get('email') or '-'}（{payload['processed']}/{payload['total']}）",
                "processed": payload["processed"],
                "total": payload["total"],
                "summary": payload["summary"],
                "recent_items": payload["recent_items"],
            })

        checked = _run_remote_health_check_internal(
            client,
            items,
            probe_mode=probe_mode,
            probe_workers=probe_workers,
            progress_callback=on_probe_progress,
        )
        if checked["health_map"]:
            update_remote_health(checked["health_map"])

        deleted_total = 0
        failed_total = 0
        cleanup_total = 0
        cleanup_failed: List[Dict[str, Any]] = []

        if cleanup:
            targets = [
                item for item in checked["items"]
                if str(item.get("health_status") or "").strip().lower() == "unusable"
            ]
            target_names = [_account_cache_key(item) for item in targets if _account_cache_key(item)]
            cleanup_total = len(target_names)

            update_health_task({
                "task_id": task_id,
                "running": True,
                "stage": "cleanup",
                "message": f"健康检测完成，开始清理不可用账号（0/{cleanup_total}）" if cleanup_total else "健康检测完成，未发现不可用账号",
                "processed": checked["total"],
                "total": checked["total"],
                "summary": checked["summary"],
                "cleanup_total": cleanup_total,
                "deleted_total": 0,
                "failed_total": 0,
                "recent_items": checked["recent_items"],
            })

            if cleanup_total > 0:
                def on_cleanup_progress(payload: Dict[str, Any]) -> None:
                    update_health_task({
                        "task_id": task_id,
                        "running": True,
                        "stage": "cleanup",
                        "message": f"正在清理：{payload['name']}（{payload['processed']}/{payload['total']}）",
                        "cleanup_total": payload["total"],
                        "deleted_total": payload["deleted_total"],
                        "failed_total": payload["failed_total"],
                    })

                cleanup_result = _cleanup_remote_accounts_internal(
                    client,
                    target_names,
                    delete_workers=delete_workers,
                    progress_callback=on_cleanup_progress,
                )
                deleted_total = cleanup_result["deleted_total"]
                failed_total = cleanup_result["failed_total"]
                cleanup_failed = cleanup_result["failed"]
                if cleanup_result["removed_names"]:
                    remove_remote_health(cleanup_result["removed_names"])

        final_message = (
            f"任务完成：检测 {checked['total']} 个账号，删除 {deleted_total} 个，删除失败 {failed_total} 个"
            if cleanup
            else f"任务完成：检测 {checked['total']} 个账号"
        )
        if cleanup and cleanup_total <= 0:
            final_message = f"任务完成：检测 {checked['total']} 个账号，未发现需要清理的不可用账号"

        update_health_task({
            "task_id": task_id,
            "running": False,
            "stage": "completed",
            "message": final_message,
            "finished_at": _now_str(),
            "probe_mode": checked["probe_mode"],
            "probe_workers": probe_workers,
            "delete_workers": delete_workers,
            "using_proxy": using_proxy,
            "total": checked["total"],
            "processed": checked["total"],
            "summary": checked["summary"],
            "recent_items": checked["recent_items"],
            "cleanup_total": cleanup_total,
            "deleted_total": deleted_total,
            "failed_total": failed_total,
        })

        if cleanup_failed:
            latest_recent = list((read_health_task().get("recent_items") or []))
            for item in cleanup_failed[-10:]:
                latest_recent.append({
                    "name": str(item.get("name") or ""),
                    "email": "",
                    "provider": "",
                    "health_status": "delete_failed",
                    "health_http_status": 0,
                    "health_reason": str(item.get("error") or ""),
                    "health_checked_at": _now_str(),
                    "status": "",
                    "disabled": False,
                })
            update_health_task({"recent_items": latest_recent[-HEALTH_TASK_RECENT_LIMIT:]})
    except Exception as exc:
        update_health_task({
            "task_id": task_id,
            "running": False,
            "stage": "failed",
            "message": str(exc),
            "finished_at": _now_str(),
        })
    finally:
        with _health_task_lock:
            if _health_task_thread is current_thread:
                _health_task_thread = None


def start_remote_health_task(
    names: Optional[List[str]] = None,
    *,
    cleanup: bool = False,
    force_reload: bool = False,
) -> Dict[str, Any]:
    global _health_task_thread
    _build_client(force_reload=force_reload)
    runtime = _build_health_runtime_settings(force_reload=force_reload)
    selected_names = _normalize_names(names)
    already_running = False

    with _health_task_lock:
        if _health_task_thread and _health_task_thread.is_alive():
            already_running = True
        else:
            task_id = uuid.uuid4().hex[:12]
            update_health_task({
                "task_id": task_id,
                "running": True,
                "task_type": "cleanup" if cleanup else "check",
                "stage": "queued",
                "message": "后台健康任务已启动，正在准备执行",
                "probe_mode": runtime["probe_mode"],
                "probe_workers": runtime["probe_workers"],
                "delete_workers": runtime["delete_workers"],
                "using_proxy": runtime["using_proxy"],
                "started_at": _now_str(),
                "finished_at": "",
                "total": 0,
                "processed": 0,
                "cleanup_total": 0,
                "deleted_total": 0,
                "failed_total": 0,
                "summary": _empty_health_summary(),
                "recent_items": [],
                "selected_names": selected_names,
            })
            thread = threading.Thread(
                target=_run_remote_health_task,
                args=(task_id, selected_names, cleanup, force_reload),
                name=f"reg-gpt-cpa-health-{task_id}",
                daemon=True,
            )
            _health_task_thread = thread
            thread.start()

    status = get_remote_health_task_status()
    status["started"] = not already_running
    return status


def run_remote_health_check(names: Optional[List[str]] = None, *, force_reload: bool = False) -> Dict[str, Any]:
    client = _build_client(force_reload=force_reload)
    runtime = _build_health_runtime_settings(force_reload=force_reload)
    items = _resolve_remote_items(client, names)

    checked = _run_remote_health_check_internal(
        client,
        items,
        probe_mode=runtime["probe_mode"],
        probe_workers=runtime["probe_workers"],
    )
    if checked["health_map"]:
        update_remote_health(checked["health_map"])
    checked["using_proxy"] = runtime["using_proxy"]
    return checked


def cleanup_unusable_remote_accounts(names: Optional[List[str]] = None, *, force_reload: bool = False) -> Dict[str, Any]:
    checked = run_remote_health_check(names=names, force_reload=force_reload)
    items = checked.get("items") or []
    target_names = [
        _account_cache_key(item)
        for item in items
        if str(item.get("health_status") or "").strip().lower() == "unusable" and _account_cache_key(item)
    ]

    client = _build_client(force_reload=force_reload)
    runtime = _build_health_runtime_settings(force_reload=force_reload)
    cleanup_result = _cleanup_remote_accounts_internal(
        client,
        target_names,
        delete_workers=runtime["delete_workers"],
    )

    if cleanup_result["removed_names"]:
        remove_remote_health(cleanup_result["removed_names"])

    return {
        "checked_total": checked.get("total", 0),
        "matched_total": cleanup_result["matched_total"],
        "deleted_total": cleanup_result["deleted_total"],
        "failed_total": cleanup_result["failed_total"],
        "failed": cleanup_result["failed"],
        "delete_workers": cleanup_result["delete_workers"],
        "checked": checked,
    }


def cleanup_marked_unusable_remote_accounts(names: Optional[List[str]] = None, *, force_reload: bool = False) -> Dict[str, Any]:
    scoped_names = set(_normalize_names(names))
    accounts = list_remote_accounts(force_reload=force_reload)
    scoped_accounts = [
        item for item in accounts
        if (not scoped_names or _account_cache_key(item) in scoped_names)
    ]
    target_items = [
        item for item in scoped_accounts
        if _normalized_account_health_status(item) == "unusable" and _account_cache_key(item)
    ]
    target_names = [_account_cache_key(item) for item in target_items]

    client = _build_client(force_reload=force_reload)
    runtime = _build_health_runtime_settings(force_reload=force_reload)
    cleanup_result = _cleanup_remote_accounts_internal(
        client,
        target_names,
        delete_workers=runtime["delete_workers"],
    )

    if cleanup_result["removed_names"]:
        remove_remote_health(cleanup_result["removed_names"])

    message = (
        f"已按当前标记直接清理 {cleanup_result['deleted_total']} 个不可用账号"
        if cleanup_result["matched_total"] > 0
        else "当前范围内没有已标记为不可用的账号"
    )
    if cleanup_result["failed_total"] > 0:
        message += f"，失败 {cleanup_result['failed_total']} 个"

    recent_items = [_recent_item_payload(item) for item in scoped_accounts[-HEALTH_TASK_RECENT_LIMIT:]]
    if cleanup_result["failed"]:
        for item in cleanup_result["failed"][-10:]:
            recent_items.append({
                "name": str(item.get("name") or ""),
                "email": "",
                "provider": "",
                "health_status": "delete_failed",
                "health_http_status": 0,
                "health_reason": str(item.get("error") or ""),
                "health_checked_at": _now_str(),
                "status": "",
                "disabled": False,
            })
        recent_items = recent_items[-HEALTH_TASK_RECENT_LIMIT:]

    now = _now_str()
    update_health_task({
        "task_id": uuid.uuid4().hex[:12],
        "running": False,
        "task_type": "cleanup_cached",
        "stage": "completed",
        "message": message,
        "probe_mode": runtime["probe_mode"],
        "probe_workers": runtime["probe_workers"],
        "delete_workers": runtime["delete_workers"],
        "using_proxy": runtime["using_proxy"],
        "started_at": now,
        "finished_at": now,
        "total": len(scoped_accounts),
        "processed": len(scoped_accounts),
        "summary": _summarize_health(scoped_accounts),
        "recent_items": recent_items,
        "selected_names": sorted(scoped_names),
        "cleanup_total": cleanup_result["matched_total"],
        "deleted_total": cleanup_result["deleted_total"],
        "failed_total": cleanup_result["failed_total"],
    })

    return {
        "scope_total": len(scoped_accounts),
        "matched_total": cleanup_result["matched_total"],
        "deleted_total": cleanup_result["deleted_total"],
        "failed_total": cleanup_result["failed_total"],
        "failed": cleanup_result["failed"],
        "delete_workers": cleanup_result["delete_workers"],
        "removed_names": cleanup_result["removed_names"],
        "message": message,
    }


def delete_remote_accounts(names: List[str], *, force_reload: bool = False) -> Dict[str, Any]:
    client = _build_client(force_reload=force_reload)
    deleted = 0
    failed: List[Dict[str, Any]] = []
    removed_names: List[str] = []

    for raw_name in names or []:
        name = str(raw_name or "").strip()
        if not name:
            continue
        try:
            client.delete_auth_file(name)
            deleted += 1
            removed_names.append(name)
        except Exception as exc:
            failed.append({"name": name, "error": str(exc)})

    if removed_names:
        remove_remote_health(removed_names)

    return {"deleted": deleted, "failed": failed}


def toggle_remote_accounts(names: List[str], disabled: bool, *, force_reload: bool = False) -> Dict[str, Any]:
    client = _build_client(force_reload=force_reload)
    success = 0
    failed: List[Dict[str, Any]] = []

    for raw_name in names or []:
        name = str(raw_name or "").strip()
        if not name:
            continue
        try:
            client.patch_auth_file_status(name, disabled)
            success += 1
        except Exception as exc:
            failed.append({"name": name, "error": str(exc)})

    return {"success": success, "failed": failed, "disabled": bool(disabled)}


def update_remote_account_fields(
    *,
    name: str,
    priority: Optional[int] = None,
    note: Optional[str] = None,
    force_reload: bool = False,
) -> Dict[str, Any]:
    client = _build_client(force_reload=force_reload)
    try:
        client.patch_auth_file_fields(name=name, priority=priority, note=note)
    except Exception as exc:
        raise CpaServiceError(str(exc)) from exc
    return {"ok": True, "name": name}

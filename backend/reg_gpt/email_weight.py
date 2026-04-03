import copy
import json
import os
import random
import threading
from datetime import datetime
from typing import Any, Dict, List

from reg_gpt.cfmail_pool import normalize_cfmail_accounts
from reg_gpt.config import STATE_DIR, ensure_runtime_layout, load_or_create_config, normalize_config

WEIGHT_STATE_PATH = os.path.join(STATE_DIR, "email_provider_weights.json")
_state_lock = threading.RLock()
_ENTRY_PROVIDER_TYPES = {"mailapi_pool", "cloudflare", "duckmail", "tempmail_lol", "lamail"}


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _provider_type(provider: Dict[str, Any]) -> str:
    return str(provider.get("type") or provider.get("name") or "").strip().lower()


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = _safe_text(value)
        if text:
            return text
    return ""


def _default_state() -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "updated_at": "",
        "providers": {},
    }


def _weight_settings(cfg: Dict[str, Any] | None = None) -> Dict[str, int]:
    runtime_cfg = normalize_config(cfg or load_or_create_config())
    weight_cfg = ((runtime_cfg.get("email") or {}).get("weight") or {})
    min_score = max(1, int(weight_cfg.get("min_score") or 20))
    max_score = max(min_score, int(weight_cfg.get("max_score") or 200))
    default_score = max(min_score, min(max_score, int(weight_cfg.get("default_score") or 100)))
    return {
        "default_score": default_score,
        "min_score": min_score,
        "max_score": max_score,
        "success_delta": max(1, int(weight_cfg.get("success_delta") or 8)),
        "failure_delta": max(1, int(weight_cfg.get("failure_delta") or 20)),
    }


def _default_item(key: str, label: str, settings: Dict[str, int]) -> Dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "score": int(settings["default_score"]),
        "disabled": False,
        "successes": 0,
        "failures": 0,
        "consecutive_successes": 0,
        "consecutive_failures": 0,
        "last_result": "",
        "last_reason": "",
        "last_success_at": "",
        "last_failed_at": "",
        "updated_at": "",
    }


def _load_state_unlocked() -> Dict[str, Any]:
    ensure_runtime_layout()
    if not os.path.exists(WEIGHT_STATE_PATH):
        return _default_state()
    try:
        with open(WEIGHT_STATE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return _default_state()
    if not isinstance(data, dict):
        return _default_state()
    state = _default_state()
    state.update(data)
    if not isinstance(state.get("providers"), dict):
        state["providers"] = {}
    return state


def _save_state_unlocked(state: Dict[str, Any]) -> Dict[str, Any]:
    ensure_runtime_layout()
    payload = _default_state()
    payload.update(state or {})
    payload["updated_at"] = _now_text()
    temp_path = f"{WEIGHT_STATE_PATH}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(temp_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(temp_path, WEIGHT_STATE_PATH)
    return payload


def _provider_weight_key(provider: Dict[str, Any]) -> str:
    provider_type = _provider_type(provider)
    provider_name = _first_non_empty(provider.get("provider_name"), provider.get("name"), provider_type)

    if provider_type == "cfmail":
        account_name = _first_non_empty(provider.get("_runtime_cfmail_account_name"), provider.get("profile"), "default")
        worker_domain = _first_non_empty(provider.get("worker_domain"), provider.get("_runtime_cfmail_api_base"))
        email_domain = _safe_text(provider.get("email_domain"))
        return f"cfmail::{provider_name}::{account_name.lower()}::{worker_domain.lower()}::{email_domain.lower()}"

    if provider_type == "mailapi_pool":
        weighted_domain = _safe_text(provider.get("_runtime_domain_weight_name"))
        api_base = _first_non_empty(provider.get("api_base"), *(provider.get("api_bases") or []))
        if weighted_domain:
            return f"mailapi_pool::{provider_name}::{api_base.lower()}::{weighted_domain.lower()}"
        domains = ",".join(sorted(_safe_text(item).lower() for item in (provider.get("domains") or []) if _safe_text(item)))
        return f"mailapi_pool::{provider_name}::{api_base.lower()}::{domains}"

    if provider_type == "cloudflare":
        return "cloudflare::{}::{}::{}".format(
            provider_name,
            _safe_text(provider.get("worker_url")).lower(),
            _safe_text(provider.get("email_domain")).lower(),
        )

    if provider_type == "duckmail":
        return "duckmail::{}::{}::{}".format(
            provider_name,
            _safe_text(provider.get("api_base")).lower(),
            _safe_text(provider.get("email_domain")).lower(),
        )

    if provider_type == "tempmail_lol":
        return f"tempmail_lol::{provider_name}::{_safe_text(provider.get('api_base')).lower()}"

    if provider_type == "lamail":
        return "lamail::{}::{}::{}".format(
            provider_name,
            _safe_text(provider.get("api_base")).lower(),
            _safe_text(provider.get("domain")).lower(),
        )

    entry_index = provider.get("entry_index")
    label = _first_non_empty(provider.get("entry_label"), provider.get("label"), provider_name)
    return f"{provider_type or 'provider'}::{provider_name}::{entry_index if entry_index is not None else 'default'}::{label.lower()}"


def _provider_label(provider: Dict[str, Any]) -> str:
    provider_type = _provider_type(provider)
    if provider_type == "cfmail":
        account_name = _first_non_empty(provider.get("_runtime_cfmail_account_name"), provider.get("profile"))
        base_label = _first_non_empty(provider.get("label"), provider.get("name"), "CFMail")
        return f"{base_label} / {account_name}" if account_name and account_name.lower() != "auto" else base_label
    if provider_type == "mailapi_pool":
        weighted_domain = _safe_text(provider.get("_runtime_domain_weight_name"))
        base_label = _first_non_empty(provider.get("entry_label"), provider.get("label"), provider.get("name"), "域名池邮箱")
        return f"{base_label} / {weighted_domain}" if weighted_domain else base_label
    return _first_non_empty(provider.get("entry_label"), provider.get("label"), provider.get("instance_name"), provider.get("name"), provider_type, "邮箱")


def get_provider_weight_info(provider: Dict[str, Any], cfg: Dict[str, Any] | None = None) -> Dict[str, Any]:
    key = _provider_weight_key(provider)
    label = _provider_label(provider)
    settings = _weight_settings(cfg)
    provider_type = _provider_type(provider)
    with _state_lock:
        state = _load_state_unlocked()
        item = state["providers"].get(key)
        if not isinstance(item, dict):
            aggregate_score: int | None = None
            if provider_type == "mailapi_pool" and not _safe_text(provider.get("_runtime_domain_weight_name")):
                domains = [str(item).strip() for item in (provider.get("domains") or []) if str(item).strip()]
                if domains:
                    scores = [
                        int(get_provider_weight_info({**dict(provider or {}), "_runtime_domain_weight_name": domain}, cfg=cfg).get("score") or settings["default_score"])
                        for domain in domains
                    ]
                    aggregate_score = max(scores) if scores else None
            elif provider_type == "cfmail" and isinstance(provider.get("accounts"), list):
                scores = [
                    int(get_provider_weight_info(_cfmail_weight_provider(account, dict(provider or {})), cfg=cfg).get("score") or settings["default_score"])
                    for account in normalize_cfmail_accounts(provider.get("accounts") or [])
                ]
                aggregate_score = max(scores) if scores else None
            base = _default_item(key, label, settings)
            if aggregate_score is not None:
                base["score"] = aggregate_score
            return copy.deepcopy(base)
        merged = _default_item(key, label, settings)
        merged.update(item)
        merged["label"] = label or merged["label"]
        try:
            merged["score"] = max(settings["min_score"], min(settings["max_score"], int(merged.get("score") or settings["default_score"])))
        except (TypeError, ValueError):
            merged["score"] = settings["default_score"]
        return copy.deepcopy(merged)


def annotate_provider_weight(provider: Dict[str, Any], cfg: Dict[str, Any] | None = None) -> Dict[str, Any]:
    info = get_provider_weight_info(provider, cfg=cfg)
    item = dict(provider or {})
    item["_runtime_email_weight_key"] = info["key"]
    item["_runtime_email_weight_label"] = info["label"]
    item["_runtime_email_weight_score"] = int(info["score"])
    return item


def record_email_otp_result(provider: Dict[str, Any], *, success: bool, reason: str = "", cfg: Dict[str, Any] | None = None) -> Dict[str, Any]:
    key = _provider_weight_key(provider)
    label = _provider_label(provider)
    now = _now_text()
    settings = _weight_settings(cfg)
    with _state_lock:
        state = _load_state_unlocked()
        providers = state.setdefault("providers", {})
        item = providers.get(key)
        if not isinstance(item, dict):
            item = _default_item(key, label, settings)
            providers[key] = item
        merged = _default_item(key, label, settings)
        merged.update(item)
        merged["label"] = label or merged["label"]
        score = int(merged.get("score") or settings["default_score"])
        if success:
            merged["successes"] = int(merged.get("successes") or 0) + 1
            merged["consecutive_successes"] = int(merged.get("consecutive_successes") or 0) + 1
            merged["consecutive_failures"] = 0
            score = min(settings["max_score"], score + settings["success_delta"])
            merged["last_result"] = "success"
            merged["last_reason"] = _safe_text(reason)[:200]
            merged["last_success_at"] = now
        else:
            merged["failures"] = int(merged.get("failures") or 0) + 1
            merged["consecutive_failures"] = int(merged.get("consecutive_failures") or 0) + 1
            merged["consecutive_successes"] = 0
            score = max(settings["min_score"], score - settings["failure_delta"])
            merged["last_result"] = "failure"
            merged["last_reason"] = _safe_text(reason)[:200]
            merged["last_failed_at"] = now
        merged["score"] = score
        merged["updated_at"] = now
        providers[key] = merged
        _save_state_unlocked(state)
        return copy.deepcopy(merged)


def is_domain_enabled(provider: Dict[str, Any], cfg: Dict[str, Any] | None = None) -> bool:
    info = get_provider_weight_info(provider, cfg=cfg)
    return not bool(info.get("disabled"))


def get_mailapi_enabled_domains(provider: Dict[str, Any], cfg: Dict[str, Any] | None = None) -> List[str]:
    domains = [str(item).strip() for item in (provider.get("domains") or []) if str(item).strip()]
    enabled: List[str] = []
    for domain in domains:
        item = dict(provider or {})
        item["_runtime_domain_weight_name"] = domain
        if is_domain_enabled(item, cfg=cfg):
            enabled.append(domain)
    return enabled


def provider_has_selectable_domain(provider: Dict[str, Any], cfg: Dict[str, Any] | None = None) -> bool:
    provider_type = _provider_type(provider)
    if provider_type == "mailapi_pool":
        return bool(get_mailapi_enabled_domains(provider, cfg=cfg))
    if provider_type == "cfmail":
        accounts = normalize_cfmail_accounts(provider.get("accounts") or [])
        for account in accounts:
            if not account.get("enabled"):
                continue
            if is_domain_enabled(_cfmail_weight_provider(account, dict(provider or {})), cfg=cfg):
                return True
        return False
    if provider_type in {"cloudflare", "duckmail", "lamail"}:
        domain = _first_non_empty(provider.get("email_domain"), provider.get("domain"))
        if not domain:
            return True
        return is_domain_enabled(provider, cfg=cfg)
    return True


def rank_email_providers(providers: List[Dict[str, Any]], cfg: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    settings = _weight_settings(cfg)
    ranked: List[Dict[str, Any]] = []
    for index, provider in enumerate(providers or []):
        item = annotate_provider_weight(provider, cfg=cfg)
        item["_runtime_email_order"] = index
        ranked.append(item)
    ranked.sort(key=lambda item: (-int(item.get("_runtime_email_weight_score") or settings["default_score"]), int(item.get("_runtime_email_order") or 0)))
    return ranked


def select_mailapi_domain(provider: Dict[str, Any], cfg: Dict[str, Any] | None = None) -> str:
    domains = get_mailapi_enabled_domains(provider, cfg=cfg)
    if not domains:
        return ""
    weighted: List[tuple[str, int]] = []
    for domain in domains:
        item = dict(provider or {})
        item["_runtime_domain_weight_name"] = domain
        info = get_provider_weight_info(item, cfg=cfg)
        weighted.append((domain, max(1, int(info.get("score") or 1))))
    choices = [item[0] for item in weighted]
    weights = [item[1] for item in weighted]
    return random.choices(choices, weights=weights, k=1)[0]


def _cfmail_weight_provider(account: Dict[str, Any], parent: Dict[str, Any]) -> Dict[str, Any]:
    worker_domain = _safe_text(account.get("worker_domain"))
    return {
        "type": "cfmail",
        "name": _first_non_empty(parent.get("name"), "cfmail"),
        "provider_name": _first_non_empty(parent.get("name"), "cfmail"),
        "label": _first_non_empty(account.get("name"), parent.get("label"), "CFMail"),
        "_runtime_cfmail_account_name": _safe_text(account.get("name")),
        "_runtime_cfmail_api_base": f"https://{worker_domain}" if worker_domain else "",
        "worker_domain": worker_domain,
        "email_domain": _safe_text(account.get("email_domain")),
    }


def list_email_weight_items(cfg: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    runtime_cfg = normalize_config(cfg or load_or_create_config())
    email_cfg = (runtime_cfg.get("email") or {})
    providers = email_cfg.get("providers") or {}
    items: List[Dict[str, Any]] = []

    for provider_name, provider in providers.items():
        provider_data = dict(provider or {})
        provider_type = _provider_type(provider_data)
        parent_enabled = bool(provider_data.get("enabled"))
        provider_data["name"] = provider_name
        provider_data["provider_name"] = provider_name

        if provider_type == "cfmail":
            accounts = normalize_cfmail_accounts(provider_data.get("accounts") or [])
            for index, account in enumerate(accounts):
                info = get_provider_weight_info(_cfmail_weight_provider(account, provider_data), cfg=runtime_cfg)
                info["provider_type"] = "cfmail"
                info["provider_name"] = provider_name
                info["entry_index"] = index
                info["enabled"] = bool(account.get("enabled"))
                info["entry_name"] = _safe_text(account.get("name"))
                items.append(info)
            continue

        if provider_type in _ENTRY_PROVIDER_TYPES:
            entries = provider_data.get("entries") or []
            if not isinstance(entries, list):
                entries = []
            if entries:
                for index, entry in enumerate(entries):
                    if not isinstance(entry, dict):
                        continue
                    instance = dict(provider_data)
                    instance.update(entry)
                    instance["entry_index"] = index
                    instance["entry_label"] = _first_non_empty(entry.get("label"), provider_data.get("label"), f"条目 {index + 1}")
                    info = get_provider_weight_info(instance, cfg=runtime_cfg)
                    info["provider_type"] = provider_type
                    info["provider_name"] = provider_name
                    info["entry_index"] = index
                    info["enabled"] = bool(entry.get("enabled"))
                    info["entry_name"] = instance["entry_label"]
                    items.append(info)
                continue

        info = get_provider_weight_info(provider_data, cfg=runtime_cfg)
        info["provider_type"] = provider_type or provider_name
        info["provider_name"] = provider_name
        info["entry_index"] = 0
        info["enabled"] = bool(provider_data.get("enabled"))
        info["entry_name"] = _first_non_empty(provider_data.get("label"), provider_name)
        items.append(info)

    items.sort(key=lambda item: (item.get("provider_type") or "", int(item.get("entry_index") or 0), item.get("label") or ""))
    return items


def list_email_domain_weight_items(cfg: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    runtime_cfg = normalize_config(cfg or load_or_create_config())
    providers = ((runtime_cfg.get("email") or {}).get("providers") or {})
    items: List[Dict[str, Any]] = []

    for provider_name, provider in providers.items():
        provider_data = dict(provider or {})
        provider_type = _provider_type(provider_data)
        parent_enabled = bool(provider_data.get("enabled"))
        provider_data["name"] = provider_name
        provider_data["provider_name"] = provider_name

        if provider_type == "mailapi_pool":
            entries = provider_data.get("entries") or []
            if not isinstance(entries, list):
                entries = []
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue
                for domain in [str(item).strip() for item in (entry.get("domains") or []) if str(item).strip()]:
                    domain_provider = dict(provider_data)
                    domain_provider.update(entry)
                    domain_provider["entry_index"] = index
                    domain_provider["entry_label"] = _first_non_empty(entry.get("label"), provider_data.get("label"), f"条目 {index + 1}")
                    domain_provider["_runtime_domain_weight_name"] = domain
                    info = get_provider_weight_info(domain_provider, cfg=runtime_cfg)
                    info["provider_type"] = "mailapi_pool"
                    info["provider_name"] = provider_name
                    info["entry_index"] = index
                    info["config_enabled"] = parent_enabled and bool(entry.get("enabled"))
                    info["active"] = bool(info["config_enabled"]) and not bool(info.get("disabled"))
                    info["enabled"] = info["active"]
                    info["domain"] = domain
                    info["source"] = domain_provider["entry_label"]
                    items.append(info)
            continue

        if provider_type == "cfmail":
            accounts = normalize_cfmail_accounts(provider_data.get("accounts") or [])
            for index, account in enumerate(accounts):
                domain_provider = _cfmail_weight_provider(account, provider_data)
                info = get_provider_weight_info(domain_provider, cfg=runtime_cfg)
                info["provider_type"] = "cfmail"
                info["provider_name"] = provider_name
                info["entry_index"] = index
                info["config_enabled"] = parent_enabled and bool(account.get("enabled"))
                info["active"] = bool(info["config_enabled"]) and not bool(info.get("disabled"))
                info["enabled"] = info["active"]
                info["domain"] = _safe_text(account.get("email_domain"))
                info["source"] = _first_non_empty(account.get("name"), provider_data.get("label"), "CFMail")
                items.append(info)
            continue

        if provider_type in {"cloudflare", "duckmail", "lamail"}:
            entries = provider_data.get("entries") or []
            if not isinstance(entries, list):
                entries = []
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue
                domain = _first_non_empty(entry.get("email_domain"), entry.get("domain"))
                if not domain:
                    continue
                domain_provider = dict(provider_data)
                domain_provider.update(entry)
                domain_provider["entry_index"] = index
                domain_provider["entry_label"] = _first_non_empty(entry.get("label"), provider_data.get("label"), f"条目 {index + 1}")
                info = get_provider_weight_info(domain_provider, cfg=runtime_cfg)
                info["provider_type"] = provider_type
                info["provider_name"] = provider_name
                info["entry_index"] = index
                info["config_enabled"] = parent_enabled and bool(entry.get("enabled"))
                info["active"] = bool(info["config_enabled"]) and not bool(info.get("disabled"))
                info["enabled"] = info["active"]
                info["domain"] = domain
                info["source"] = domain_provider["entry_label"]
                items.append(info)

    items.sort(key=lambda item: (str(item.get("domain") or ""), str(item.get("provider_type") or ""), int(item.get("entry_index") or 0)))
    return items


def domain_weight_summary(cfg: Dict[str, Any] | None = None) -> Dict[str, Any]:
    items = list_email_domain_weight_items(cfg)
    if not items:
        settings = _weight_settings(cfg)
        return {
            "count": 0,
            "enabled_count": 0,
            "max_score": settings["default_score"],
            "min_score": settings["default_score"],
            "avg_score": settings["default_score"],
        }
    scores = [int(item.get("score") or 0) for item in items]
    enabled_scores = [int(item.get("score") or 0) for item in items if item.get("active")]
    return {
        "count": len(items),
        "enabled_count": len(enabled_scores),
        "max_score": max(scores),
        "min_score": min(scores),
        "avg_score": round(sum(scores) / max(1, len(scores)), 1),
    }


def weight_summary(cfg: Dict[str, Any] | None = None) -> Dict[str, Any]:
    items = list_email_weight_items(cfg)
    if not items:
        settings = _weight_settings(cfg)
        return {
            "count": 0,
            "enabled_count": 0,
            "max_score": settings["default_score"],
            "min_score": settings["default_score"],
            "avg_score": settings["default_score"],
        }
    scores = [int(item.get("score") or 0) for item in items]
    enabled_scores = [int(item.get("score") or 0) for item in items if item.get("enabled")]
    return {
        "count": len(items),
        "enabled_count": len(enabled_scores),
        "max_score": max(scores),
        "min_score": min(scores),
        "avg_score": round(sum(scores) / max(1, len(scores)), 1),
    }


def reset_email_weight(key: str) -> Dict[str, Any]:
    target = _safe_text(key)
    if not target:
        raise ValueError("key 不能为空")
    settings = _weight_settings()
    with _state_lock:
        state = _load_state_unlocked()
        providers = state.setdefault("providers", {})
        item = providers.get(target)
        if isinstance(item, dict) and bool(item.get("disabled")):
            label = _safe_text(item.get("label")) or target
            reset_item = _default_item(target, label, settings)
            reset_item["disabled"] = True
            reset_item["updated_at"] = _now_text()
            providers[target] = reset_item
        else:
            providers.pop(target, None)
        _save_state_unlocked(state)
    return {"key": target, "reset": True}


def set_email_domain_enabled(key: str, enabled: bool) -> Dict[str, Any]:
    target = _safe_text(key)
    if not target:
        raise ValueError("key 不能为空")
    settings = _weight_settings()
    with _state_lock:
        state = _load_state_unlocked()
        providers = state.setdefault("providers", {})
        item = providers.get(target)
        if not isinstance(item, dict):
            item = _default_item(target, target, settings)
        merged = _default_item(target, str(item.get("label") or target), settings)
        merged.update(item)
        merged["disabled"] = not bool(enabled)
        merged["updated_at"] = _now_text()
        providers[target] = merged
        _save_state_unlocked(state)
        return {"key": target, "enabled": enabled}


def reset_all_email_weights() -> Dict[str, Any]:
    settings = _weight_settings()
    with _state_lock:
        state = _load_state_unlocked()
        providers = state.setdefault("providers", {})
        preserved_disabled: Dict[str, Any] = {}
        for key, item in providers.items():
            if not isinstance(item, dict) or not bool(item.get("disabled")):
                continue
            label = _safe_text(item.get("label")) or key
            reset_item = _default_item(key, label, settings)
            reset_item["disabled"] = True
            reset_item["updated_at"] = _now_text()
            preserved_disabled[key] = reset_item
        if preserved_disabled:
            _save_state_unlocked({"schema_version": 1, "providers": preserved_disabled})
        elif os.path.exists(WEIGHT_STATE_PATH):
            os.remove(WEIGHT_STATE_PATH)
    return {"reset_all": True}

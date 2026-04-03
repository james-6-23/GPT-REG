import random
from typing import Any, Dict, Iterable, List

from reg_gpt.cfmail_pool import normalize_cfmail_accounts
from reg_gpt.email_weight import provider_has_selectable_domain, rank_email_providers

_PROVIDERS_WITH_ENTRIES = {'mailapi_pool', 'cloudflare', 'duckmail', 'tempmail_lol', 'lamail'}


def _provider_type(provider: Dict[str, Any]) -> str:
    return str(provider.get('type') or provider.get('name') or '').strip().lower()


def _entry_list(provider: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries = provider.get('entries')
    if not isinstance(entries, list):
        return []
    return [dict(item) for item in entries if isinstance(item, dict)]


def get_all_email_providers(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    email_cfg = (cfg or {}).get('email') or {}
    providers = email_cfg.get('providers') or {}
    items: List[Dict[str, Any]] = []
    for provider_name, provider in providers.items():
        item = dict(provider or {})
        item['name'] = provider_name
        items.append(item)
    return items


def _provider_is_ready(provider: Dict[str, Any]) -> bool:
    provider_type = _provider_type(provider)
    if provider_type == 'mailapi_pool':
        domains = provider.get('domains') or []
        api_bases = provider.get('api_bases') or []
        has_api = bool(provider.get('api_base')) or (isinstance(api_bases, list) and any(str(item).strip() for item in api_bases))
        return bool(has_api and provider.get('api_key') and isinstance(domains, list) and any(str(item).strip() for item in domains))
    if provider_type == 'cfmail':
        accounts = normalize_cfmail_accounts(provider.get('accounts') or [])
        return any(
            account.get('enabled')
            and account.get('name')
            and account.get('worker_domain')
            and account.get('email_domain')
            and account.get('admin_password')
            for account in accounts
        )
    if provider_type == 'cloudflare':
        return bool(provider.get('worker_url') and provider.get('email_domain'))
    if provider_type == 'duckmail':
        return bool(provider.get('api_base') and provider.get('bearer') and provider.get('email_domain'))
    if provider_type == 'tempmail_lol':
        return bool(provider.get('api_base'))
    if provider_type == 'lamail':
        return bool(provider.get('api_base'))
    return False


def _iter_provider_instances(provider_name: str, provider: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    base = dict(provider or {})
    base['name'] = provider_name
    provider_type = _provider_type(base)
    parent_enabled = bool(base.get('enabled'))

    if provider_type not in _PROVIDERS_WITH_ENTRIES:
        yield base
        return

    entries = _entry_list(base)
    if not entries:
        yield base
        return

    for index, entry in enumerate(entries):
        instance = dict(base)
        instance.pop('entries', None)
        instance.update(entry)
        instance['enabled'] = parent_enabled and bool(entry.get('enabled'))
        instance['provider_name'] = provider_name
        instance['entry_index'] = index
        instance['entry_label'] = str(entry.get('label') or '').strip()
        instance['instance_name'] = f'{provider_name}:{index + 1}'
        if instance.get('entry_label'):
            instance['label'] = instance['entry_label']
        yield instance


def get_email_provider_instances(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    providers = (cfg or {}).get('email', {}).get('providers') or {}
    items: List[Dict[str, Any]] = []
    for provider_name, provider in providers.items():
        items.extend(list(_iter_provider_instances(str(provider_name), dict(provider or {}))))
    return items


def get_enabled_email_providers(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    enabled: List[Dict[str, Any]] = []
    for provider in get_email_provider_instances(cfg):
        if provider.get('enabled') and _provider_is_ready(provider) and provider_has_selectable_domain(provider, cfg=cfg):
            enabled.append(provider)
    return enabled


def choose_email_provider(cfg: Dict[str, Any]) -> Dict[str, Any] | None:
    enabled = get_enabled_email_providers(cfg)
    if not enabled:
        return None

    email_cfg = (cfg or {}).get('email') or {}
    selection_mode = str(email_cfg.get('selection_mode') or 'random_enabled').strip().lower()
    ranked = rank_email_providers(enabled, cfg=cfg)
    if selection_mode in {'first_enabled', 'prefer_first'}:
        return dict(ranked[0])
    weights = [max(1, int(item.get('_runtime_email_weight_score') or 100)) for item in ranked]
    return dict(random.choices(ranked, weights=weights, k=1)[0])


def describe_email_provider(provider: Dict[str, Any]) -> str:
    provider_type = _provider_type(provider)
    label = str(provider.get('label') or provider.get('name') or provider_type or '邮箱').strip()

    if provider_type == 'mailapi_pool':
        entries = _entry_list(provider)
        if entries:
            enabled_entries = [item for item in entries if item.get('enabled')]
            total_domains = sum(len([str(v).strip() for v in (item.get('domains') or []) if str(v).strip()]) for item in entries)
            return f'{label} ({len(enabled_entries)}/{len(entries)} 条 API 条目，{total_domains} 个域名)'
        domains = [str(item).strip() for item in (provider.get('domains') or []) if str(item).strip()]
        api_bases = [str(item).strip() for item in (provider.get('api_bases') or []) if str(item).strip()]
        site_text = f' / {len(api_bases)} 个站点' if api_bases else ''
        return f'{label} ({len(domains)} 个域名{site_text})'

    if provider_type == 'cfmail':
        accounts = normalize_cfmail_accounts(provider.get('accounts') or [])
        names = [account['name'] for account in accounts if account.get('enabled') and account.get('name')]
        detail = ','.join(names[:3]) if names else '未配置账号池'
        return f'{label} ({detail})'

    if provider_type in _PROVIDERS_WITH_ENTRIES:
        entries = _entry_list(provider)
        if entries:
            enabled_entries = [item for item in entries if item.get('enabled')]
            return f'{label} ({len(enabled_entries)}/{len(entries)} 条条目)'

    if provider_type in {'cloudflare', 'duckmail'}:
        domain = str(provider.get('email_domain') or '').strip()
        return f'{label} ({domain or "未配置域名"})'
    if provider_type == 'tempmail_lol':
        return f"{label} ({provider.get('api_base') or '未配置 API'})"
    if provider_type == 'lamail':
        domain = str(provider.get('domain') or '').strip()
        return f'{label} ({domain or "自动域名"})'
    return label

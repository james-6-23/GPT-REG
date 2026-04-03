from __future__ import annotations

import json
import math
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from curl_cffi import requests


@dataclass(frozen=True)
class CfmailAccount:
    name: str
    worker_domain: str
    email_domain: str
    admin_password: str
    enabled: bool = True


_SELECTION_LOCK = threading.Lock()
_FAILURE_LOCK = threading.Lock()
_INDEX_BY_SIGNATURE: Dict[str, int] = {}
_FAILURE_STATE: Dict[str, Dict[str, Any]] = {}


def normalize_host(value: Any) -> str:
    text = str(value or '').strip()
    if text.startswith('https://'):
        text = text[len('https://'):]
    elif text.startswith('http://'):
        text = text[len('http://'):]
    return text.strip().strip('/')


def _normalize_cfmail_account(raw: Dict[str, Any], index: int) -> Dict[str, Any]:
    item = raw or {}
    return {
        'name': str(item.get('name') or f'node-{index}').strip() or f'node-{index}',
        'worker_domain': normalize_host(item.get('worker_domain') or item.get('worker_url') or ''),
        'email_domain': normalize_host(item.get('email_domain') or ''),
        'admin_password': str(item.get('admin_password') or '').strip(),
        'enabled': bool(item.get('enabled', True)),
    }


def normalize_cfmail_accounts(raw_accounts: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_accounts, list):
        return []
    return [_normalize_cfmail_account(item or {}, index + 1) for index, item in enumerate(raw_accounts)]


def _provider_signature(provider: Dict[str, Any]) -> str:
    accounts = normalize_cfmail_accounts((provider or {}).get('accounts') or [])
    payload = [
        {
            'name': account['name'],
            'worker_domain': account['worker_domain'],
            'email_domain': account['email_domain'],
            'enabled': account['enabled'],
        }
        for account in accounts
    ]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _account_key(provider: Dict[str, Any], account_name: str) -> str:
    signature = str((provider or {}).get('_runtime_cfmail_signature') or _provider_signature(provider))
    return f"{signature}::{str(account_name or '').strip().lower()}"


def _cooldown_remaining(provider: Dict[str, Any], account_name: str) -> int:
    key = _account_key(provider, account_name)
    with _FAILURE_LOCK:
        state = _FAILURE_STATE.get(key) or {}
        cooldown_until = float(state.get('cooldown_until') or 0)
    remaining = int(math.ceil(cooldown_until - time.time()))
    return max(0, remaining)


def record_cfmail_success(provider: Dict[str, Any], account_name: str | None = None) -> None:
    name = str(account_name or (provider or {}).get('_runtime_cfmail_account_name') or '').strip()
    if not name:
        return
    key = _account_key(provider, name)
    with _FAILURE_LOCK:
        state = _FAILURE_STATE.setdefault(key, {'name': name})
        state['consecutive_failures'] = 0
        state['cooldown_until'] = 0
        state['last_error'] = ''
        state['last_success_at'] = time.time()


def record_cfmail_failure(provider: Dict[str, Any], reason: str = '', account_name: str | None = None) -> None:
    name = str(account_name or (provider or {}).get('_runtime_cfmail_account_name') or '').strip()
    if not name:
        return
    key = _account_key(provider, name)
    fail_threshold = max(1, int((provider or {}).get('fail_threshold', 3) or 3))
    cooldown_seconds = max(0, int((provider or {}).get('cooldown_seconds', 1800) or 1800))
    now = time.time()
    with _FAILURE_LOCK:
        state = _FAILURE_STATE.setdefault(key, {'name': name})
        state['consecutive_failures'] = int(state.get('consecutive_failures') or 0) + 1
        state['last_error'] = str(reason or '')[:300]
        state['last_failed_at'] = now
        if state['consecutive_failures'] >= fail_threshold:
            state['cooldown_until'] = max(float(state.get('cooldown_until') or 0), now + cooldown_seconds)
            state['consecutive_failures'] = 0


def _enabled_accounts(provider: Dict[str, Any]) -> List[Dict[str, Any]]:
    accounts = []
    for account in normalize_cfmail_accounts((provider or {}).get('accounts') or []):
        if not account.get('enabled'):
            continue
        if not account.get('name') or not account.get('worker_domain') or not account.get('email_domain') or not account.get('admin_password'):
            continue
        accounts.append(account)
    return accounts


def has_ready_cfmail_account(provider: Dict[str, Any]) -> bool:
    return bool(_enabled_accounts(provider))


def select_cfmail_account(provider: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from reg_gpt.email_weight import is_domain_enabled

    accounts = _enabled_accounts(provider)
    if not accounts:
        return None

    profile = str((provider or {}).get('profile') or 'auto').strip() or 'auto'
    if profile.lower() != 'auto':
        for account in accounts:
            if account['name'].lower() == profile.lower() and is_domain_enabled({
                'type': 'cfmail',
                'name': str((provider or {}).get('name') or 'cfmail'),
                'provider_name': str((provider or {}).get('name') or 'cfmail'),
                'label': account['name'],
                '_runtime_cfmail_account_name': account['name'],
                'worker_domain': account['worker_domain'],
                'email_domain': account['email_domain'],
            }):
                return account
        return None

    signature = _provider_signature(provider)
    with _SELECTION_LOCK:
        start_index = _INDEX_BY_SIGNATURE.get(signature, 0) % len(accounts)
        for offset in range(len(accounts)):
            index = (start_index + offset) % len(accounts)
            account = accounts[index]
            if not is_domain_enabled({
                'type': 'cfmail',
                'name': str((provider or {}).get('name') or 'cfmail'),
                'provider_name': str((provider or {}).get('name') or 'cfmail'),
                'label': account['name'],
                '_runtime_cfmail_account_name': account['name'],
                'worker_domain': account['worker_domain'],
                'email_domain': account['email_domain'],
            }):
                continue
            if _cooldown_remaining(provider, account['name']) > 0:
                continue
            _INDEX_BY_SIGNATURE[signature] = (index + 1) % len(accounts)
            return account
    return None


def _cfmail_headers(*, jwt: str = '', use_json: bool = False) -> Dict[str, str]:
    headers = {'Accept': 'application/json'}
    if use_json:
        headers['Content-Type'] = 'application/json'
    if jwt:
        headers['Authorization'] = f'Bearer {jwt}'
    return headers


def create_cfmail_email(
    provider: Dict[str, Any],
    *,
    proxy: str | None,
    impersonate: str,
) -> tuple[str, str, str]:
    account = select_cfmail_account(provider)
    if not account:
        raise RuntimeError('CFMail 没有可用账号池，请检查已启用账号与冷却状态')

    proxies: Any = {'http': proxy, 'https': proxy} if proxy else None
    local = f"oc{secrets.token_hex(5)}"

    try:
        resp = requests.post(
            f"https://{account['worker_domain']}/admin/new_address",
            headers={'x-admin-auth': account['admin_password'], **_cfmail_headers(use_json=True)},
            json={'enablePrefix': True, 'name': local, 'domain': account['email_domain']},
            proxies=proxies,
            impersonate=impersonate,
            timeout=15,
        )
    except Exception as exc:
        record_cfmail_failure(provider, f'new_address exception: {exc}', account['name'])
        raise RuntimeError(f'CFMail 创建邮箱请求异常: {exc}') from exc

    if resp.status_code != 200:
        record_cfmail_failure(provider, f'new_address status={resp.status_code}', account['name'])
        raise RuntimeError(f'CFMail 创建邮箱失败: {resp.status_code} - {resp.text[:200]}')

    try:
        data = resp.json() if resp.content else {}
    except Exception as exc:
        record_cfmail_failure(provider, 'new_address invalid json', account['name'])
        raise RuntimeError(f'CFMail 创建邮箱返回非 JSON: {exc}') from exc

    email = str(data.get('address') or '').strip()
    jwt = str(data.get('jwt') or '').strip()
    if not email or not jwt:
        record_cfmail_failure(provider, 'new_address incomplete data', account['name'])
        raise RuntimeError('CFMail 返回数据不完整（address 或 jwt 为空）')

    provider['_runtime_cfmail_api_base'] = f"https://{account['worker_domain']}"
    provider['_runtime_cfmail_account_name'] = account['name']
    provider['_runtime_cfmail_signature'] = _provider_signature(provider)
    provider['worker_domain'] = account['worker_domain']
    provider['email_domain'] = account['email_domain']
    return email, '', jwt


def fetch_cfmail_messages(
    provider: Dict[str, Any],
    mail_token: str,
    *,
    proxy: str | None,
    impersonate: str,
) -> List[Dict[str, Any]]:
    api_base = str((provider or {}).get('_runtime_cfmail_api_base') or '').strip()
    if not api_base or not mail_token:
        return []
    proxies: Any = {'http': proxy, 'https': proxy} if proxy else None
    try:
        resp = requests.get(
            f'{api_base}/api/mails',
            params={'limit': 12, 'offset': 0},
            headers=_cfmail_headers(jwt=mail_token, use_json=True),
            proxies=proxies,
            impersonate=impersonate,
            timeout=15,
        )
        if resp.status_code != 200:
            return []
        data = resp.json() if resp.content else {}
        messages = data.get('results', []) if isinstance(data, dict) else []
        return messages if isinstance(messages, list) else []
    except Exception:
        return []


def extract_cfmail_code(messages: List[Dict[str, Any]], email: str) -> Optional[str]:
    patterns = [
        r'Subject:\s*Your ChatGPT code is\s*(\d{6})',
        r'Your ChatGPT code is\s*(\d{6})',
        r'temporary verification code to continue:\s*(\d{6})',
        r'Verification code:?\s*(\d{6})',
        r'(?<![#&])\b(\d{6})\b',
    ]
    target = str(email or '').strip().lower()
    import re

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        recipient = str(msg.get('address') or '').strip().lower()
        if recipient and target and recipient != target:
            continue
        raw = str(msg.get('raw') or '')
        metadata = msg.get('metadata') or {}
        content = '\n'.join([recipient, raw, json.dumps(metadata, ensure_ascii=False)])
        if 'openai' not in content.lower() and 'chatgpt' not in content.lower():
            continue
        for pattern in patterns:
            match = re.search(pattern, content, re.I | re.S)
            if match:
                return match.group(1)
    return None

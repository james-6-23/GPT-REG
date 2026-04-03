import random
import re
import secrets
import string
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from curl_cffi import requests

from reg_gpt.cfmail_pool import (
    create_cfmail_email,
    extract_cfmail_code,
    fetch_cfmail_messages,
    record_cfmail_failure,
    record_cfmail_success,
)
from reg_gpt.email_weight import record_email_otp_result, select_mailapi_domain
from reg_gpt.mail_cf import build_cf_email, wait_for_cf_code


VERIFICATION_CODE_PATTERNS = [
    r"Verification code:?\s*(\d{6})",
    r"code is\s*(\d{6})",
    r"代码为[:：]?\s*(\d{6})",
    r"验证码[:：]?\s*(\d{6})",
    r">\s*(\d{6})\s*<",
    r"(?<![#&])\b(\d{6})\b",
]


def _generate_mail_password(length: int = 14) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(random.choice(chars) for _ in range(length))


def _provider_type(provider: Dict[str, Any]) -> str:
    return str(provider.get("type") or provider.get("name") or "").strip().lower()


def _extract_verification_code(email_content: str) -> Optional[str]:
    if not email_content:
        return None
    for pattern in VERIFICATION_CODE_PATTERNS:
        matches = re.findall(pattern, email_content, re.IGNORECASE)
        for code in matches:
            if code == "177010":
                continue
            return code
    return None


def _normalize_domain_patterns(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    items: List[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw or "").strip().lower()
        if not text:
            continue
        if text.startswith("https://"):
            text = text[len("https://"):]
        elif text.startswith("http://"):
            text = text[len("http://"):]
        wildcard = text.startswith("*.")
        if wildcard:
            text = text[2:]
        text = text.strip().strip("/").strip(".")
        if not text or "." not in text:
            continue
        value = f"*.{text}" if wildcard else text
        if value in seen:
            continue
        seen.add(value)
        items.append(value)
    return items


def _random_domain_label(min_length: int = 6, max_length: int = 10) -> str:
    length = random.randint(min_length, max_length)
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(length))


def _expand_domain_pattern(pattern: str) -> str:
    value = str(pattern or "").strip().lower()
    if value.startswith("*."):
        suffix = value[2:].strip(".")
        if suffix:
            return f"{_random_domain_label()}.{suffix}"
    return value


def _mailapi_base(provider: Dict[str, Any]) -> str:
    return str(provider.get("api_base") or provider.get("mail_api_url") or "").strip().rstrip("/")


def _mailapi_bases(provider: Dict[str, Any]) -> List[str]:
    raw = provider.get("api_bases")
    if isinstance(raw, str):
        raw = [item.strip() for item in raw.replace(",", "\n").splitlines() if item.strip()]
    items: List[str] = []
    seen: set[str] = set()
    if isinstance(raw, list):
        for value in raw:
            text = str(value or "").strip().rstrip("/")
            if not text:
                continue
            if not (text.startswith("https://") or text.startswith("http://")):
                text = f"https://{text.lstrip('/')}"
            if text in seen:
                continue
            seen.add(text)
            items.append(text)
    single = _mailapi_base(provider)
    if single and single not in seen:
        items.insert(0, single)
    return items


def _mailapi_candidate_bases(provider: Dict[str, Any]) -> List[str]:
    bases = _mailapi_bases(provider)
    if not bases:
        return []
    preferred = str(provider.get("_runtime_mailapi_base") or "").strip().rstrip("/")
    if preferred and preferred in bases:
        others = [item for item in bases if item != preferred]
        random.shuffle(others)
        return [preferred] + others
    candidates = list(bases)
    random.shuffle(candidates)
    return candidates


def _mailapi_headers(provider: Dict[str, Any]) -> Dict[str, str]:
    headers = {"Accept": "application/json"}
    api_key = str(provider.get("api_key") or provider.get("mail_api_key") or "").strip()
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def _mailapi_domain_pool(provider: Dict[str, Any]) -> List[str]:
    domains = provider.get("domains")
    if not isinstance(domains, list):
        domains = provider.get("enabled_email_domains")
    if not isinstance(domains, list):
        domains = provider.get("mail_domain_options")
    return _normalize_domain_patterns(domains or [])


def _mailapi_mailbox_variants(email: str) -> List[str]:
    value = str(email or "").strip().lower()
    if not value:
        return []
    variants = [value]
    local = value.split("@", 1)[0].strip()
    if local and local not in variants:
        variants.append(local)
    return variants


def _mailapi_message_sort_key(message: Dict[str, Any]) -> int:
    for key in ("posix-millis", "posixMillis", "createdAt", "receivedAt", "timestamp", "date"):
        raw = message.get(key)
        if raw in (None, ""):
            continue
        try:
            value = float(raw)
            if value < 10**11:
                value *= 1000
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _mailapi_message_id(message: Dict[str, Any]) -> str:
    for key in ("id", "_id", "messageId", "uuid", "posix-millis", "posixMillis", "createdAt", "receivedAt"):
        value = str(message.get(key) or "").strip()
        if value:
            return value
    return ""


def _mailapi_join_message_parts(*parts: Any) -> str:
    return "\n".join(str(part or "").strip() for part in parts if str(part or "").strip())


def _fetch_mailapi_messages(recipient: str, provider: Dict[str, Any], proxy: Optional[str], impersonate: str) -> List[Dict[str, Any]]:
    api_bases = _mailapi_candidate_bases(provider)
    if not api_bases or not recipient:
        return []
    proxies: Any = {"http": proxy, "https": proxy} if proxy else None
    for api_base in api_bases:
        try:
            resp = requests.get(
                f"{api_base}/api/v1/mailbox/{quote(recipient, safe='')}",
                headers=_mailapi_headers(provider),
                proxies=proxies,
                timeout=15,
                impersonate=impersonate,
            )
            if resp.status_code != 200:
                continue
            data = resp.json() if resp.content else []
            if isinstance(data, list):
                provider["_runtime_mailapi_base"] = api_base
                return data
        except Exception:
            continue
    return []


def _fetch_mailapi_message_detail(recipient: str, msg_id: str, provider: Dict[str, Any], proxy: Optional[str], impersonate: str) -> Optional[Dict[str, Any]]:
    api_bases = _mailapi_candidate_bases(provider)
    if not api_bases or not recipient or not msg_id:
        return None
    proxies: Any = {"http": proxy, "https": proxy} if proxy else None
    for api_base in api_bases:
        try:
            resp = requests.get(
                f"{api_base}/api/v1/mailbox/{quote(recipient, safe='')}/{quote(msg_id, safe='')}",
                headers=_mailapi_headers(provider),
                proxies=proxies,
                timeout=15,
                impersonate=impersonate,
            )
            if resp.status_code != 200:
                continue
            data = resp.json() if resp.content else {}
            if isinstance(data, dict):
                provider["_runtime_mailapi_base"] = api_base
                return data
        except Exception:
            continue
    return None


def _fetch_mailapi_message_text(recipient: str, msg_id: str, provider: Dict[str, Any], proxy: Optional[str], impersonate: str) -> str:
    api_bases = _mailapi_candidate_bases(provider)
    if not api_bases or not recipient or not msg_id:
        return ""
    proxies: Any = {"http": proxy, "https": proxy} if proxy else None
    for api_base in api_bases:
        try:
            resp = requests.get(
                f"{api_base}/api/v1/mailbox/{quote(recipient, safe='')}/{quote(msg_id, safe='')}/text",
                headers=_mailapi_headers(provider),
                proxies=proxies,
                timeout=15,
                impersonate=impersonate,
            )
            if resp.status_code != 200:
                continue
            provider["_runtime_mailapi_base"] = api_base
            return resp.text.strip()
        except Exception:
            continue
    return ""


def create_email_account(
    provider: Dict[str, Any],
    *,
    proxy: Optional[str],
    impersonate: str,
) -> Tuple[str, str, str]:
    provider_type = _provider_type(provider)
    proxies: Any = {"http": proxy, "https": proxy} if proxy else None

    if provider_type == "cfmail":
        return create_cfmail_email(provider, proxy=proxy, impersonate=impersonate)

    if provider_type == "cloudflare":
        email_domain = str(provider.get("email_domain") or "").strip()
        email = build_cf_email(email_domain)
        return email, "", ""

    if provider_type == "mailapi_pool":
        api_bases = _mailapi_bases(provider)
        domains = _mailapi_domain_pool(provider)
        if not api_bases:
            raise RuntimeError("域名池邮箱未配置 API Base")
        if not domains:
            raise RuntimeError("域名池邮箱未配置可用域名")
        local = f"oc{secrets.token_hex(5)}"
        selected_domain = select_mailapi_domain(provider)
        if not selected_domain:
            raise RuntimeError("域名池邮箱没有可用且已启用的域名，请检查域名状态")
        email_domain = _expand_domain_pattern(selected_domain)
        email = f"{local}@{email_domain}"
        provider["_runtime_mailapi_base"] = random.choice(api_bases)
        provider["_runtime_domain_weight_name"] = selected_domain
        provider["email_domain"] = selected_domain
        return email, "", email

    if provider_type == "duckmail":
        bearer = str(provider.get("bearer") or "").strip()
        api_base = str(provider.get("api_base") or "https://api.duckmail.sbs").strip().rstrip("/")
        email_domain = str(provider.get("email_domain") or "duckmail.sbs").strip() or "duckmail.sbs"
        if not bearer:
            raise RuntimeError("DuckMail 未配置 bearer")
        email_local = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(random.randint(8, 13)))
        email = f"{email_local}@{email_domain}"
        password = _generate_mail_password()
        session = requests.Session()
        session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        if proxies:
            session.proxies = proxies
        res = session.post(
            f"{api_base}/accounts",
            json={"address": email, "password": password},
            headers={"Authorization": f"Bearer {bearer}"},
            timeout=15,
            impersonate=impersonate,
        )
        if res.status_code not in (200, 201):
            raise RuntimeError(f"DuckMail 创建邮箱失败: {res.status_code} - {res.text[:200]}")
        time.sleep(0.5)
        token_res = session.post(
            f"{api_base}/token",
            json={"address": email, "password": password},
            timeout=15,
            impersonate=impersonate,
        )
        if token_res.status_code != 200:
            raise RuntimeError(f"DuckMail 获取 Token 失败: {token_res.status_code} - {token_res.text[:200]}")
        mail_token = str((token_res.json() or {}).get("token") or "").strip()
        if not mail_token:
            raise RuntimeError("DuckMail 返回 token 为空")
        return email, password, mail_token

    if provider_type == "tempmail_lol":
        api_base = str(provider.get("api_base") or "https://api.tempmail.lol/v2").strip().rstrip("/")
        resp = requests.post(
            f"{api_base}/inbox/create",
            json={},
            proxies=proxies,
            timeout=15,
            impersonate=impersonate,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"TempMail.lol 创建失败: {resp.status_code} - {resp.text[:200]}")
        data = resp.json() if resp.content else {}
        email = str(data.get("address") or data.get("email") or "").strip()
        mail_token = str(data.get("token") or "").strip()
        if not email or not mail_token:
            raise RuntimeError("TempMail.lol 返回数据不完整")
        return email, "", mail_token

    if provider_type == "lamail":
        api_base = str(provider.get("api_base") or "https://maliapi.215.im/v1").strip().rstrip("/")
        api_key = str(provider.get("api_key") or "").strip()
        domain = str(provider.get("domain") or "").strip()
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key
        payload: Dict[str, Any] = {}
        if domain:
            payload["domain"] = domain
        resp = requests.post(
            f"{api_base}/accounts",
            json=payload,
            headers=headers,
            proxies=proxies,
            timeout=15,
            impersonate=impersonate,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"LaMail 创建失败: {resp.status_code} - {resp.text[:200]}")
        data = resp.json() if resp.content else {}
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data.get("data") or data
        email = str(data.get("address") or data.get("email") or "").strip()
        mail_token = str(data.get("token") or "").strip()
        if not email or not mail_token:
            raise RuntimeError("LaMail 返回数据不完整")
        return email, "", mail_token

    raise RuntimeError(f"不支持的邮箱提供方: {provider_type}")


def _fetch_duckmail_messages(mail_token: str, provider: Dict[str, Any], proxy: Optional[str], impersonate: str) -> List[Dict[str, Any]]:
    api_base = str(provider.get("api_base") or "https://api.duckmail.sbs").strip().rstrip("/")
    proxies: Any = {"http": proxy, "https": proxy} if proxy else None
    try:
        resp = requests.get(
            f"{api_base}/messages",
            headers={"Authorization": f"Bearer {mail_token}"},
            proxies=proxies,
            timeout=15,
            impersonate=impersonate,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("hydra:member") or data.get("member") or data.get("data") or []
    except Exception:
        return []


def _fetch_duckmail_message_detail(msg_id: str, mail_token: str, provider: Dict[str, Any], proxy: Optional[str], impersonate: str) -> Optional[Dict[str, Any]]:
    api_base = str(provider.get("api_base") or "https://api.duckmail.sbs").strip().rstrip("/")
    proxies: Any = {"http": proxy, "https": proxy} if proxy else None
    msg_id = str(msg_id or "").strip()
    if msg_id.startswith("/messages/"):
        msg_id = msg_id.split("/")[-1]
    if not msg_id:
        return None
    try:
        resp = requests.get(
            f"{api_base}/messages/{msg_id}",
            headers={"Authorization": f"Bearer {mail_token}"},
            proxies=proxies,
            timeout=15,
            impersonate=impersonate,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        return None
    return None


def _fetch_tempmail_messages(mail_token: str, provider: Dict[str, Any], proxy: Optional[str], impersonate: str) -> List[Dict[str, Any]]:
    api_base = str(provider.get("api_base") or "https://api.tempmail.lol/v2").strip().rstrip("/")
    proxies: Any = {"http": proxy, "https": proxy} if proxy else None
    try:
        resp = requests.get(
            f"{api_base}/inbox",
            params={"token": mail_token},
            proxies=proxies,
            timeout=15,
            impersonate=impersonate,
        )
        if resp.status_code != 200:
            return []
        data = resp.json() if resp.content else {}
        emails = data.get("emails") if isinstance(data, dict) else []
        return emails if isinstance(emails, list) else []
    except Exception:
        return []


def _fetch_lamail_messages(mail_token: str, email: str, provider: Dict[str, Any], proxy: Optional[str], impersonate: str) -> List[Dict[str, Any]]:
    api_base = str(provider.get("api_base") or "https://maliapi.215.im/v1").strip().rstrip("/")
    proxies: Any = {"http": proxy, "https": proxy} if proxy else None
    headers = {"Accept": "application/json", "Authorization": f"Bearer {mail_token}"}
    api_key = str(provider.get("api_key") or "").strip()
    if api_key:
        headers["X-API-Key"] = api_key
    try:
        resp = requests.get(
            f"{api_base}/messages",
            params={"address": email},
            headers=headers,
            proxies=proxies,
            timeout=15,
            impersonate=impersonate,
        )
        if resp.status_code != 200:
            return []
        data = resp.json() if resp.content else {}
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data.get("data") or data
        messages = data.get("messages") if isinstance(data, dict) else []
        return messages if isinstance(messages, list) else []
    except Exception:
        return []


def _fetch_lamail_message_detail(mail_token: str, msg_id: str, provider: Dict[str, Any], proxy: Optional[str], impersonate: str) -> Optional[Dict[str, Any]]:
    api_base = str(provider.get("api_base") or "https://maliapi.215.im/v1").strip().rstrip("/")
    proxies: Any = {"http": proxy, "https": proxy} if proxy else None
    headers = {"Accept": "application/json", "Authorization": f"Bearer {mail_token}"}
    api_key = str(provider.get("api_key") or "").strip()
    if api_key:
        headers["X-API-Key"] = api_key
    try:
        resp = requests.get(
            f"{api_base}/messages/{msg_id}",
            headers=headers,
            proxies=proxies,
            timeout=15,
            impersonate=impersonate,
        )
        if resp.status_code != 200:
            return None
        data = resp.json() if resp.content else {}
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data.get("data") or data
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def wait_for_email_code(
    provider: Dict[str, Any],
    *,
    email: str,
    mail_token: str,
    proxy: Optional[str],
    tag: str,
    wid: int,
    poller: Any = None,
    step_logger=None,
    wait_logger=None,
    dim=None,
    green=None,
    yellow=None,
    red=None,
    timeout: int = 120,
    impersonate: str = "chrome",
    exclude_codes: Optional[set[str]] = None,
    seen_message_ids: Optional[set[str]] = None,
    not_before_ms: int = 0,
) -> str:
    provider_type = _provider_type(provider)
    excluded_codes = {str(item).strip() for item in (exclude_codes or set()) if str(item).strip()}
    if provider_type == "cloudflare":
        polls = max(1, int((timeout - 5) / 2))
        code = wait_for_cf_code(
            email=email,
            worker_url=str(provider.get("worker_url") or "").strip(),
            api_secret=str(provider.get("api_secret") or "").strip(),
            proxies={"http": proxy, "https": proxy} if proxy else None,
            tag=tag,
            wid=wid,
            poller=poller,
            step_logger=step_logger,
            wait_logger=wait_logger,
            dim=dim,
            green=green,
            yellow=yellow,
            red=red,
            poll_attempts=polls,
            initial_wait_seconds=5,
            poll_interval_seconds=2,
            exclude_codes=excluded_codes,
        )
        record_email_otp_result(provider, success=bool(code), reason="" if code else "otp timeout")
        return code

    start_time = time.time()
    seen_ids = seen_message_ids if seen_message_ids is not None else set()
    skipped_codes: set[str] = set()

    while time.time() - start_time < timeout:
        code = None
        if provider_type == "cfmail":
            messages = fetch_cfmail_messages(provider, mail_token, proxy=proxy, impersonate=impersonate)
            new_messages = []
            for msg in messages:
                msg_id = str(msg.get("id") or msg.get("createdAt") or msg.get("receivedAt") or "").strip()
                if msg_id and msg_id not in seen_ids:
                    seen_ids.add(msg_id)
                    new_messages.append(msg)
            if new_messages:
                code = extract_cfmail_code(new_messages, email)
        elif provider_type == "mailapi_pool":
            for recipient in _mailapi_mailbox_variants(mail_token or email):
                messages = _fetch_mailapi_messages(recipient, provider, proxy, impersonate)
                if not messages:
                    continue
                for msg in sorted(messages, key=_mailapi_message_sort_key, reverse=True):
                    msg_time = _mailapi_message_sort_key(msg)
                    if not_before_ms and msg_time and msg_time + 1000 < not_before_ms:
                        continue
                    msg_id = _mailapi_message_id(msg)
                    cache_key = f"{recipient}::{msg_id or _mailapi_join_message_parts(msg.get('subject'), msg.get('from'), msg.get('to'))}"
                    if cache_key in seen_ids:
                        continue
                    seen_ids.add(cache_key)

                    detail = _fetch_mailapi_message_detail(recipient, msg_id, provider, proxy, impersonate) if msg_id else None
                    text_body = _fetch_mailapi_message_text(recipient, msg_id, provider, proxy, impersonate) if msg_id else ""
                    content = _mailapi_join_message_parts(
                        msg.get("subject"),
                        msg.get("from"),
                        msg.get("to"),
                        msg.get("text"),
                        msg.get("html"),
                        msg.get("body"),
                        msg.get("header"),
                        detail.get("subject") if isinstance(detail, dict) else "",
                        detail.get("from") if isinstance(detail, dict) else "",
                        detail.get("to") if isinstance(detail, dict) else "",
                        detail.get("text") if isinstance(detail, dict) else "",
                        detail.get("html") if isinstance(detail, dict) else "",
                        detail.get("body") if isinstance(detail, dict) else "",
                        detail.get("header") if isinstance(detail, dict) else "",
                        text_body,
                    )
                    lower_content = content.lower()
                    if "openai" not in lower_content and "chatgpt" not in lower_content:
                        continue
                    code = _extract_verification_code(content)
                    if code in excluded_codes:
                        if code not in skipped_codes and wait_logger is not None:
                            wait_logger(wid, f"  跳过旧 OTP {code}，继续等待新邮件")
                            skipped_codes.add(code)
                        code = None
                        continue
                    if code:
                        break
                if code:
                    break
        elif provider_type == "duckmail":
            messages = _fetch_duckmail_messages(mail_token, provider, proxy, impersonate)
            if messages:
                first_msg = messages[0]
                msg_id = first_msg.get("id") or first_msg.get("@id")
                cache_key = f"duckmail::{msg_id or ''}"
                if msg_id and cache_key not in seen_ids:
                    seen_ids.add(cache_key)
                    detail = _fetch_duckmail_message_detail(str(msg_id), mail_token, provider, proxy, impersonate)
                    if detail:
                        content = detail.get("text") or detail.get("html") or ""
                        code = _extract_verification_code(str(content))
                        if code in excluded_codes:
                            code = None
        elif provider_type == "tempmail_lol":
            messages = _fetch_tempmail_messages(mail_token, provider, proxy, impersonate)
            new_messages = []
            for msg in sorted(messages, key=lambda x: x.get("date", 0), reverse=True):
                msg_id = str(msg.get("id") or msg.get("date") or msg.get("createdAt") or "").strip()
                if msg_id and msg_id not in seen_ids:
                    seen_ids.add(msg_id)
                    new_messages.append(msg)
            for msg in new_messages:
                content = " ".join([
                    str(msg.get("subject") or ""),
                    str(msg.get("body") or ""),
                    str(msg.get("html") or ""),
                    str(msg.get("from") or ""),
                ])
                if "openai" not in content.lower() and "chatgpt" not in content.lower():
                    continue
                code = _extract_verification_code(content)
                if code in excluded_codes:
                    code = None
                    continue
                if code:
                    break
        elif provider_type == "lamail":
            messages = _fetch_lamail_messages(mail_token, email, provider, proxy, impersonate)
            new_messages = []
            for msg in reversed(messages):
                msg_id = str(msg.get("id") or msg.get("createdAt") or msg.get("receivedAt") or "").strip()
                if msg_id and msg_id not in seen_ids:
                    seen_ids.add(msg_id)
                    new_messages.append(msg)
            for msg in new_messages:
                msg_id = str(msg.get("id") or "").strip()
                content = "\n".join([
                    str(msg.get("subject") or ""),
                    str(msg.get("text") or ""),
                    str(msg.get("html") or ""),
                    str(msg.get("from") or ""),
                ])
                if "openai" not in content.lower() and "chatgpt" not in content.lower() and msg_id:
                    detail = _fetch_lamail_message_detail(mail_token, msg_id, provider, proxy, impersonate)
                    if detail:
                        content = "\n".join([
                            str(detail.get("subject") or ""),
                            str(detail.get("text") or ""),
                            str(detail.get("html") or ""),
                            str(detail.get("from") or ""),
                        ])
                if "openai" not in content.lower() and "chatgpt" not in content.lower():
                    continue
                code = _extract_verification_code(content)
                if code in excluded_codes:
                    code = None
                    continue
                if code:
                    break

        if code and code in excluded_codes:
            if code not in skipped_codes and wait_logger is not None:
                wait_logger(wid, f"  跳过旧 OTP {code}，继续等待新邮件")
                skipped_codes.add(code)
            code = None

        if code:
            if provider_type == "cfmail":
                record_cfmail_success(provider)
            record_email_otp_result(provider, success=True)
            return code
        time.sleep(3)
    if provider_type == "cfmail":
        record_cfmail_failure(provider, "otp timeout")
    record_email_otp_result(provider, success=False, reason="otp timeout")
    return ""

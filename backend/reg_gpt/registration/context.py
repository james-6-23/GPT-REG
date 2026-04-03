import uuid
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

import reg_gpt.console as console


@dataclass
class RegistrationContext:
    proxy: Optional[str]
    provider: dict[str, Any]
    worker_url: str
    email_domain: str
    api_secret: str = ""
    poller: Any = None
    tag: str = ""
    wid: int = 0
    proxies: Any = None
    email: str = ""
    reg_password: str = ""
    fp: dict[str, Any] = field(default_factory=dict)
    chosen_imp: str = ""
    active_imp: str = ""
    impersonate_fallbacks: list[str] = field(default_factory=list)
    session: Any = None
    oauth: Any = None
    device_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    auth_session_logging_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    csrf_token: str = ""
    final_url: str = ""
    final_path: str = ""
    callback_url: str = ""
    mail_token: str = ""
    email_password: str = ""
    mail_seen_ids: set[str] = field(default_factory=set)
    tried_email_codes: set[str] = field(default_factory=set)
    otp_not_before_ms: int = 0
    otp_wait_timeout_seconds: int = 120
    otp_retry_wait_timeout_seconds: int = 60
    sentinel_tokens: dict[str, list[str]] = field(default_factory=dict)
    sentinel_so_tokens: dict[str, list[str]] = field(default_factory=dict)

    def pop_sentinel_token(self, flow: str) -> Optional[str]:
        tokens = self.sentinel_tokens.get(flow)
        if isinstance(tokens, list) and tokens:
            return tokens.pop(0)
        return None

    def pop_sentinel_so_token(self, flow: str) -> Optional[str]:
        tokens = self.sentinel_so_tokens.get(flow)
        if isinstance(tokens, list) and tokens:
            return tokens.pop(0)
        return None

    def effective_wid(self) -> int:
        return self.wid if self.wid > 0 else 1

    def build_cf_email(self) -> str:
        from reg_gpt.mail_cf import build_cf_email

        return build_cf_email(self.email_domain)

    def set_final_url(self, url: str) -> None:
        self.final_url = str(url or "").strip()
        self.final_path = urlparse(self.final_url).path if self.final_url else ""

    def step(self, label: str, value: str) -> None:
        line = f"  {console.dim(label):20s}  {value}"
        console.wlog(self.effective_wid(), line)

    def info(self, msg: str) -> None:
        line = f"{console.cyan('[·]')} {msg}"
        console.wlog(self.effective_wid(), line)

    def err(self, msg: str) -> None:
        line = f"{console.red('[Error]')} {msg}"
        console.wlog(self.effective_wid(), line)

    def warn(self, msg: str) -> None:
        line = f"{console.yellow('[!]')} {msg}"
        console.wlog(self.effective_wid(), line)

    def remember_email_code(self, code: str) -> None:
        value = str(code or "").strip()
        if value:
            self.tried_email_codes.add(value)

    def email_otp_timeout(self, retry: bool = False) -> int:
        return self.otp_retry_wait_timeout_seconds if retry else self.otp_wait_timeout_seconds


def build_context(
    *,
    proxy: Optional[str],
    provider: dict[str, Any],
    worker_url: str,
    email_domain: str,
    api_secret: str = "",
    poller: Any = None,
    tag: str = "",
    wid: int = 0,
    otp_wait_timeout_seconds: int = 120,
    otp_retry_wait_timeout_seconds: int = 60,
) -> RegistrationContext:
    proxies: Any = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}
    return RegistrationContext(
        proxy=proxy,
        provider=dict(provider or {}),
        worker_url=worker_url,
        email_domain=email_domain,
        api_secret=api_secret,
        poller=poller,
        tag=tag,
        wid=wid,
        proxies=proxies,
        otp_wait_timeout_seconds=max(10, int(otp_wait_timeout_seconds or 120)),
        otp_retry_wait_timeout_seconds=max(10, int(otp_retry_wait_timeout_seconds or 60)),
    )

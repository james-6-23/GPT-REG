import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable

from flask import Response, g, has_request_context, jsonify, redirect, request, session, url_for

from reg_gpt.config import CONFIG_PATH, SCRIPT_DIR, load_or_create_config, normalize_config, save_config

LEGACY_WEBUI_CONFIG_PATH = os.path.join(SCRIPT_DIR, "webui_config.toml")
_security_lock = threading.Lock()
_login_attempts: dict[str, list[float]] = {}
_bootstrap_notice_lock = threading.Lock()
_bootstrap_notice_emitted = False


def _pbkdf2_hash(password: str, salt: bytes | None = None, iterations: int = 240000) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
    )


def _b64decode_nopad(value: str) -> bytes:
    pad = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode((value + pad).encode("ascii"))


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algo, iter_text, salt_text, digest_text = (password_hash or "").split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iter_text)
        salt = _b64decode_nopad(salt_text)
        expected = _b64decode_nopad(digest_text)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def secure_compare(left: str, right: str) -> bool:
    try:
        return hmac.compare_digest((left or "").encode("utf-8"), (right or "").encode("utf-8"))
    except Exception:
        return False


def _generate_defaults(existing_port: int = 5050) -> tuple[dict[str, Any], dict[str, str]]:
    username = "admin"
    password = secrets.token_urlsafe(18)
    api_token = secrets.token_urlsafe(32)
    session_secret = secrets.token_urlsafe(48)
    password_hash = _pbkdf2_hash(password)
    defaults = {
        "webui": {
            "host": "127.0.0.1",
            "port": existing_port,
        },
        "security": {
            "username": username,
            "password_hash": password_hash,
            "api_token": api_token,
            "session_secret": session_secret,
            "session_minutes": 480,
            "secure_cookie": False,
            "login_rate_limit": 8,
            "login_window_seconds": 900,
            "csrf_enabled": True,
            "trusted_origins": [
                f"http://127.0.0.1:{existing_port}",
                f"http://localhost:{existing_port}",
            ],
        },
    }
    bootstrap = {
        "username": username,
        "password": password,
        "api_token": api_token,
        "host": "127.0.0.1",
        "port": str(existing_port),
    }
    return defaults, bootstrap


def _emit_bootstrap_notice(
    *,
    username: str,
    password: str | None,
    api_token: str | None,
    host: str,
    port: int,
) -> None:
    global _bootstrap_notice_emitted
    with _bootstrap_notice_lock:
        if _bootstrap_notice_emitted:
            return
        _bootstrap_notice_emitted = True
    lines = [
        "",
        "============================================================",
        " Reg-GPT WebUI 首次安全凭据（仅终端显示，不再额外写文件）",
        f" 用户名: {username}",
    ]
    if password:
        lines.append(f" 密码: {password}")
    if api_token:
        lines.append(f" API Token: {api_token}")
    lines.extend(
        [
            f" 访问地址: http://{host}:{port}",
            f" 配置文件: {CONFIG_PATH}",
            " 请在首次登录后尽快进入“安全设置”修改凭据。",
            "============================================================",
            "",
        ]
    )
    print("\n".join(lines))


def _load_legacy_security_config() -> dict[str, Any]:
    if not os.path.exists(LEGACY_WEBUI_CONFIG_PATH):
        return {}
    try:
        import tomllib
        with open(LEGACY_WEBUI_CONFIG_PATH, "rb") as fh:
            legacy = tomllib.load(fh)
        webui = legacy.get("server") or {}
        security = legacy.get("security") or {}
        return {"webui": webui, "security": security}
    except Exception:
        return {}


def load_or_create_security_config() -> dict[str, Any]:
    with _security_lock:
        cfg = normalize_config(load_or_create_config())
        legacy = _load_legacy_security_config()
        changed = False
        generated_notice: dict[str, Any] = {}

        if legacy:
            if legacy.get("webui"):
                cfg["webui"].update({k: v for k, v in legacy["webui"].items() if v not in (None, "")})
                changed = True
            if legacy.get("security"):
                for key, value in legacy["security"].items():
                    if value not in (None, ""):
                        cfg["security"][key] = value
                        changed = True

        defaults, bootstrap = _generate_defaults(existing_port=cfg["webui"]["port"])
        for section in ("webui", "security"):
            for key, value in defaults[section].items():
                current = cfg[section].get(key)
                if current in ("", None, []):
                    cfg[section][key] = value
                    changed = True
                    if section == "security" and key == "password_hash":
                        generated_notice["password"] = bootstrap["password"]
                    elif section == "security" and key == "api_token":
                        generated_notice["api_token"] = value
                    elif section == "security" and key == "username":
                        generated_notice["username"] = value
                    elif section == "webui" and key == "host":
                        generated_notice["host"] = value
                    elif section == "webui" and key == "port":
                        generated_notice["port"] = value

        if changed:
            cfg = save_config(cfg)

        if generated_notice.get("password") or generated_notice.get("api_token"):
            _emit_bootstrap_notice(
                username=str(generated_notice.get("username") or cfg["security"]["username"]),
                password=str(generated_notice["password"]) if generated_notice.get("password") else None,
                api_token=str(generated_notice["api_token"]) if generated_notice.get("api_token") else None,
                host=str(generated_notice.get("host") or cfg["webui"]["host"]),
                port=int(generated_notice.get("port") or cfg["webui"]["port"]),
            )

        return cfg


@dataclass(frozen=True)
class WebUISecuritySettings:
    username: str
    password_hash: str
    api_token: str
    session_secret: str
    session_minutes: int
    secure_cookie: bool
    login_rate_limit: int
    login_window_seconds: int
    csrf_enabled: bool
    trusted_origins: list[str]
    host: str
    port: int


def get_settings() -> WebUISecuritySettings:
    cfg = load_or_create_security_config()
    sec = cfg["security"]
    webui = cfg["webui"]
    return WebUISecuritySettings(
        username=sec["username"],
        password_hash=sec["password_hash"],
        api_token=sec["api_token"],
        session_secret=sec["session_secret"],
        session_minutes=sec["session_minutes"],
        secure_cookie=sec["secure_cookie"],
        login_rate_limit=sec["login_rate_limit"],
        login_window_seconds=sec["login_window_seconds"],
        csrf_enabled=sec["csrf_enabled"],
        trusted_origins=list(sec["trusted_origins"]),
        host=webui["host"],
        port=webui["port"],
    )


def get_security_summary() -> dict[str, Any]:
    cfg = load_or_create_security_config()
    sec = cfg["security"]
    webui = cfg["webui"]
    return {
        "username": sec["username"],
        "has_api_token": bool(sec["api_token"]),
        "session_minutes": sec["session_minutes"],
        "secure_cookie": sec["secure_cookie"],
        "login_rate_limit": sec["login_rate_limit"],
        "login_window_seconds": sec["login_window_seconds"],
        "csrf_enabled": sec["csrf_enabled"],
        "trusted_origins": list(sec["trusted_origins"]),
        "host": webui["host"],
        "port": webui["port"],
        "config_path": CONFIG_PATH,
        "credential_delivery": "首次启动仅在当前终端显示一次，不额外写 bootstrap 文件",
        "legacy_config_path": LEGACY_WEBUI_CONFIG_PATH,
        "legacy_config_exists": os.path.exists(LEGACY_WEBUI_CONFIG_PATH),
    }


def update_security_settings(payload: dict[str, Any]) -> dict[str, Any]:
    current = load_or_create_security_config()
    sec = current["security"]
    webui = current["webui"]

    sec["username"] = str(payload.get("username") or sec["username"]).strip() or sec["username"]
    sec["session_minutes"] = max(5, int(payload.get("session_minutes") or sec["session_minutes"]))
    sec["secure_cookie"] = bool(payload.get("secure_cookie", sec["secure_cookie"]))
    sec["login_rate_limit"] = max(3, int(payload.get("login_rate_limit") or sec["login_rate_limit"]))
    sec["login_window_seconds"] = max(60, int(payload.get("login_window_seconds") or sec["login_window_seconds"]))
    sec["csrf_enabled"] = bool(payload.get("csrf_enabled", sec["csrf_enabled"]))

    origins = payload.get("trusted_origins")
    if isinstance(origins, list):
        sec["trusted_origins"] = [str(item).strip() for item in origins if str(item).strip()]
    elif isinstance(origins, str):
        sec["trusted_origins"] = [line.strip() for line in origins.splitlines() if line.strip()]

    new_password = str(payload.get("new_password") or "").strip()
    if new_password:
        sec["password_hash"] = _pbkdf2_hash(new_password)

    rotate_api_token = bool(payload.get("rotate_api_token", False))
    new_api_token = str(payload.get("api_token") or "").strip()
    if new_api_token:
        sec["api_token"] = new_api_token
    elif rotate_api_token:
        sec["api_token"] = secrets.token_urlsafe(32)

    webui["host"] = str(payload.get("host") or webui["host"]).strip() or webui["host"]
    webui["port"] = max(1, int(payload.get("port") or webui["port"]))

    saved = save_config(current)
    return {
        "config": saved,
        "summary": get_security_summary(),
        "new_api_token": sec["api_token"] if (new_api_token or rotate_api_token) else "",
    }


def issue_csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(24)
        session["csrf_token"] = token
    return token


def _request_uses_https() -> bool:
    if not has_request_context():
        return False
    if request.is_secure:
        return True
    forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
    if forwarded_proto == "https":
        return True
    forwarded = (request.headers.get("Forwarded") or "").lower()
    return "proto=https" in forwarded


def resolve_session_cookie_secure(settings: WebUISecuritySettings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(settings.secure_cookie and _request_uses_https())


def reset_session_auth() -> None:
    session.clear()
    session["csrf_token"] = secrets.token_urlsafe(24)


def _client_ip() -> str:
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or (request.remote_addr or "unknown")


def login_allowed() -> tuple[bool, str]:
    settings = get_settings()
    now = time.time()
    ip = _client_ip()
    window_start = now - settings.login_window_seconds
    attempts = [ts for ts in _login_attempts.get(ip, []) if ts >= window_start]
    _login_attempts[ip] = attempts
    if len(attempts) >= settings.login_rate_limit:
        return False, "登录尝试过于频繁，请稍后再试"
    return True, ""


def record_login_failure() -> None:
    ip = _client_ip()
    _login_attempts.setdefault(ip, []).append(time.time())


def clear_login_failures() -> None:
    ip = _client_ip()
    _login_attempts.pop(ip, None)


def authenticate_user(username: str, password: str) -> bool:
    settings = get_settings()
    if not secure_compare(username.strip(), settings.username):
        return False
    return verify_password(password, settings.password_hash)


def login_user() -> None:
    settings = get_settings()
    session.clear()
    session["authenticated"] = True
    session["username"] = settings.username
    session["csrf_token"] = secrets.token_urlsafe(24)
    session["login_at"] = int(time.time())
    session.permanent = True


def logout_user() -> None:
    reset_session_auth()


def is_api_token_authenticated() -> bool:
    auth = (request.headers.get("Authorization") or "").strip()
    if not auth.startswith("Bearer "):
        return False
    token = auth[7:].strip()
    expected = get_settings().api_token
    return bool(expected) and secure_compare(token, expected)


def is_session_authenticated() -> bool:
    return bool(session.get("authenticated"))


def is_authenticated() -> bool:
    if is_api_token_authenticated():
        g.auth_method = "token"
        return True
    if is_session_authenticated():
        g.auth_method = "session"
        return True
    g.auth_method = None
    return False


def origin_allowed() -> bool:
    settings = get_settings()
    if not settings.trusted_origins:
        return True
    origin = (request.headers.get("Origin") or request.headers.get("Referer") or "").strip()
    if not origin:
        return True
    return any(origin.startswith(item) for item in settings.trusted_origins)


def validate_csrf() -> tuple[bool, str]:
    settings = get_settings()
    if not settings.csrf_enabled:
        return True, ""
    if getattr(g, "auth_method", None) == "token":
        return True, ""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return True, ""
    if not origin_allowed():
        return False, "请求来源不受信任"
    header_token = (
        request.headers.get("X-CSRF-Token")
        or request.form.get("csrf_token")
        or request.headers.get("X-CSRFToken")
        or ""
    ).strip()
    session_token = (session.get("csrf_token") or "").strip()
    if not header_token or not session_token or not secure_compare(header_token, session_token):
        return False, "CSRF 校验失败"
    return True, ""


def unauthorized_response() -> Response:
    if request.path.startswith("/api/"):
        return jsonify(status="error", message="未登录或认证失效"), 401
    return redirect(url_for("login_page", next=request.path))


def require_auth(view: Callable):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not is_authenticated():
            return unauthorized_response()
        ok, message = validate_csrf()
        if not ok:
            return jsonify(status="error", message=message), 403
        return view(*args, **kwargs)

    return wrapper


def apply_security_headers(response: Response) -> Response:
    settings = get_settings()
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )
    if settings.secure_cookie:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

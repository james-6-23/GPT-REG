import base64
import hashlib
import json
import random
import secrets
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from typing import Any, Dict

from curl_cffi import requests

AUTH_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEFAULT_SCOPE = "openid email profile offline_access"


def get_default_redirect_uri() -> str:
    from reg_gpt.config import load_or_create_config
    cfg = load_or_create_config()
    oauth = cfg.get("oauth") or {}
    port = oauth.get("port", 1455)
    return f"http://localhost:{port}/auth/callback"


def make_trace_headers() -> Dict[str, str]:
    trace_id = random.randint(10**17, 10**18 - 1)
    parent_id = random.randint(10**17, 10**18 - 1)
    traceparent = f"00-{uuid.uuid4().hex}-{format(parent_id, '016x')}-01"
    return {
        "traceparent": traceparent,
        "tracestate": "dd=s:1;o:rum",
        "x-datadog-origin": "rum",
        "x-datadog-sampling-priority": "1",
        "x-datadog-trace-id": str(trace_id),
        "x-datadog-parent-id": str(parent_id),
    }


def b64url_no_pad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def sha256_b64url_no_pad(value: str) -> str:
    return b64url_no_pad(hashlib.sha256(value.encode("ascii")).digest())


def random_state(nbytes: int = 16) -> str:
    return secrets.token_urlsafe(nbytes)


def pkce_verifier() -> str:
    return secrets.token_urlsafe(64)


def parse_callback_url(callback_url: str) -> Dict[str, Any]:
    candidate = callback_url.strip()
    if not candidate:
        return {"code": "", "state": "", "error": "", "error_description": ""}

    if "://" not in candidate:
        if candidate.startswith("?"):
            candidate = f"http://localhost{candidate}"
        elif any(ch in candidate for ch in "/?#") or ":" in candidate:
            candidate = f"http://{candidate}"
        elif "=" in candidate:
            candidate = f"http://localhost/?{candidate}"

    parsed = urllib.parse.urlparse(candidate)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    fragment = urllib.parse.parse_qs(parsed.fragment, keep_blank_values=True)
    for key, values in fragment.items():
        if key not in query or not query[key] or not (query[key][0] or "").strip():
            query[key] = values

    def get1(key: str) -> str:
        values = query.get(key, [""])
        return (values[0] or "").strip()

    code = get1("code")
    state = get1("state")
    error = get1("error")
    error_description = get1("error_description")
    if code and not state and "#" in code:
        code, state = code.split("#", 1)
    if not error and error_description:
        error, error_description = error_description, ""
    return {
        "code": code,
        "state": state,
        "error": error,
        "error_description": error_description,
    }


def jwt_claims_no_verify(id_token: str) -> Dict[str, Any]:
    if not id_token or id_token.count(".") < 2:
        return {}
    payload_b64 = id_token.split(".")[1]
    pad = "=" * ((4 - (len(payload_b64) % 4)) % 4)
    try:
        payload = base64.urlsafe_b64decode((payload_b64 + pad).encode("ascii"))
        return json.loads(payload.decode("utf-8"))
    except Exception:
        return {}


def decode_jwt_segment(seg: str) -> Dict[str, Any]:
    raw = (seg or "").strip()
    if not raw:
        return {}
    pad = "=" * ((4 - (len(raw) % 4)) % 4)
    try:
        decoded = base64.urlsafe_b64decode((raw + pad).encode("ascii"))
        return json.loads(decoded.decode("utf-8"))
    except Exception:
        return {}


def extract_workspace_id_from_auth_cookie(auth_cookie: str) -> str:
    raw = (auth_cookie or "").strip()
    if not raw:
        return ""
    parts = [part for part in raw.split(".") if part]
    for seg in parts[:3]:
        data = decode_jwt_segment(seg)
        if not isinstance(data, dict):
            continue
        workspaces = data.get("workspaces") or []
        if isinstance(workspaces, list) and workspaces:
            wid = str((workspaces[0] or {}).get("id") or "").strip()
            if wid:
                return wid
        wid = str(data.get("workspace_id") or data.get("default_workspace_id") or "").strip()
        if wid:
            return wid
    return ""


def extract_code_from_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw or "code=" not in raw:
        return ""
    try:
        parsed = urllib.parse.urlparse(raw)
        return str(urllib.parse.parse_qs(parsed.query).get("code", [""])[0] or "").strip()
    except Exception:
        return ""


def capture_callback_from_redirects(session: Any, start_url: str, max_hops: int = 8) -> str:
    current_url = (start_url or "").strip()
    if not current_url:
        return ""
    for _ in range(max_hops):
        if "code=" in current_url and "state=" in current_url:
            return current_url
        resp = session.get(current_url, allow_redirects=False, timeout=15)
        if resp.status_code not in (301, 302, 303, 307, 308):
            break
        location = (resp.headers.get("Location") or "").strip()
        if not location:
            break
        next_url = urllib.parse.urljoin(current_url, location)
        if "code=" in next_url and "state=" in next_url:
            return next_url
        current_url = next_url
    return ""


def oauth_follow_for_code(session: Any, start_url: str, referer: str | None = None, max_hops: int = 8) -> tuple[str, str]:
    current_url = str(start_url or "").strip()
    last_url = current_url
    if not current_url:
        return "", ""
    for _ in range(max_hops):
        code = extract_code_from_url(current_url)
        if code:
            return code, current_url
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        }
        if referer:
            headers["Referer"] = referer
        resp = session.get(current_url, headers=headers, allow_redirects=False, timeout=30)
        last_url = str(getattr(resp, "url", current_url) or current_url)
        if resp.status_code not in (301, 302, 303, 307, 308):
            code = extract_code_from_url(last_url)
            return code, last_url
        location = (resp.headers.get("Location") or "").strip()
        if not location:
            return "", last_url
        next_url = urllib.parse.urljoin(current_url, location)
        referer = current_url
        current_url = next_url
    return "", last_url


def oauth_allow_redirect_extract_code(session: Any, url: str, referer: str | None = None) -> str:
    current_url = str(url or "").strip()
    if not current_url:
        return ""
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Upgrade-Insecure-Requests": "1",
    }
    if referer:
        headers["Referer"] = referer
    resp = session.get(current_url, headers=headers, allow_redirects=True, timeout=30)
    return extract_code_from_url(str(resp.url or ""))


class SentinelTokenGenerator:
    MAX_ATTEMPTS = 500000
    ERROR_PREFIX = "wQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D"

    def __init__(self, device_id: str | None = None, user_agent: str | None = None):
        self.device_id = device_id or str(uuid.uuid4())
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/145.0.0.0 Safari/537.36"
        )
        self.requirements_seed = str(random.random())
        self.sid = str(uuid.uuid4())

    @staticmethod
    def _fnv1a_32(text: str) -> str:
        h = 2166136261
        for ch in text:
            h ^= ord(ch)
            h = (h * 16777619) & 0xFFFFFFFF
        h ^= (h >> 16)
        h = (h * 2246822507) & 0xFFFFFFFF
        h ^= (h >> 13)
        h = (h * 3266489909) & 0xFFFFFFFF
        h ^= (h >> 16)
        h &= 0xFFFFFFFF
        return format(h, "08x")

    def _get_config(self) -> list[Any]:
        now_str = time.strftime("%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)", time.gmtime())
        perf_now = random.uniform(1000, 50000)
        time_origin = time.time() * 1000 - perf_now
        nav_prop = random.choice([
            "vendorSub", "productSub", "vendor", "maxTouchPoints",
            "scheduling", "userActivation", "doNotTrack", "geolocation",
            "connection", "plugins", "mimeTypes", "pdfViewerEnabled",
            "webkitTemporaryStorage", "webkitPersistentStorage",
            "hardwareConcurrency", "cookieEnabled", "credentials",
            "mediaDevices", "permissions", "locks", "ink",
        ])
        nav_val = f"{nav_prop}-undefined"
        return [
            "1920x1080", now_str, 4294705152, random.random(),
            self.user_agent,
            "https://sentinel.openai.com/sentinel/20260124ceb8/sdk.js",
            None, None, "en-US", "en-US,en", random.random(), nav_val,
            random.choice(["location", "implementation", "URL", "documentURI", "compatMode"]),
            random.choice(["Object", "Function", "Array", "Number", "parseFloat", "undefined"]),
            perf_now, self.sid, "", random.choice([4, 8, 12, 16]), time_origin,
        ]

    @staticmethod
    def _base64_encode(data: Any) -> str:
        raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return base64.b64encode(raw).decode("ascii")

    def _run_check(self, start_time: float, seed: str, difficulty: str, config: list[Any], nonce: int) -> str | None:
        config[3] = nonce
        config[9] = round((time.time() - start_time) * 1000)
        data = self._base64_encode(config)
        hash_hex = self._fnv1a_32(seed + data)
        diff_len = len(difficulty)
        if hash_hex[:diff_len] <= difficulty:
            return data + "~S"
        return None

    def generate_token(self, seed: str | None = None, difficulty: str | None = None) -> str:
        seed = seed if seed is not None else self.requirements_seed
        difficulty = str(difficulty or "0")
        start_time = time.time()
        config = self._get_config()
        for i in range(self.MAX_ATTEMPTS):
            result = self._run_check(start_time, seed, difficulty, config, i)
            if result:
                return "gAAAAAB" + result
        return "gAAAAAB" + self.ERROR_PREFIX + self._base64_encode(str(None))

    def generate_requirements_token(self) -> str:
        config = self._get_config()
        config[3] = 1
        config[9] = round(random.uniform(5, 50))
        data = self._base64_encode(config)
        return "gAAAAAC" + data


def fetch_sentinel_challenge(
    session: Any,
    device_id: str,
    flow: str = "authorize_continue",
    user_agent: str | None = None,
    sec_ch_ua: str | None = None,
    impersonate: str | None = None,
):
    generator = SentinelTokenGenerator(device_id=device_id, user_agent=user_agent)
    req_body = {"p": generator.generate_requirements_token(), "id": device_id, "flow": flow}
    headers = {
        "Content-Type": "text/plain;charset=UTF-8",
        "Referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html",
        "Origin": "https://sentinel.openai.com",
        "User-Agent": user_agent or "Mozilla/5.0",
        "sec-ch-ua": sec_ch_ua or '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }
    kwargs = {"data": json.dumps(req_body), "headers": headers, "timeout": 20}
    if impersonate:
        kwargs["impersonate"] = impersonate
    try:
        resp = session.post("https://sentinel.openai.com/backend-api/sentinel/req", **kwargs)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except Exception:
        return None


def build_sentinel_token(
    session: Any,
    device_id: str,
    flow: str = "authorize_continue",
    user_agent: str | None = None,
    sec_ch_ua: str | None = None,
    impersonate: str | None = None,
    ctx: Any = None,
) -> str | None:
    # 优先检查缓存中的 Token (如果是从 Playwright 助手预取的)
    if ctx and hasattr(ctx, "pop_sentinel_token"):
        cached = ctx.pop_sentinel_token(flow)
        if cached:
            return cached

    # 如果没有缓存，则降级到传统的模拟生成
    challenge = fetch_sentinel_challenge(
        session,
        device_id,
        flow=flow,
        user_agent=user_agent,
        sec_ch_ua=sec_ch_ua,
        impersonate=impersonate,
    )
    if not challenge:
        return None
    c_value = challenge.get("token", "")
    if not c_value:
        return None
    pow_data = challenge.get("proofofwork") or {}
    generator = SentinelTokenGenerator(device_id=device_id, user_agent=user_agent)
    if pow_data.get("required") and pow_data.get("seed"):
        p_value = generator.generate_token(seed=pow_data.get("seed"), difficulty=pow_data.get("difficulty", "0"))
    else:
        p_value = generator.generate_requirements_token()
    return json.dumps({"p": p_value, "t": "", "c": c_value, "id": device_id, "flow": flow}, separators=(",", ":"))


def raw_tls_request(fn, *args, max_retries: int = 4, base_delay: float = 1.5, **kwargs):
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            err = str(exc)
            is_tls = "(35)" in err or "TLS" in err or "OPENSSL" in err
            if is_tls and attempt < max_retries - 1:
                wait = base_delay * (1.5 ** attempt)
                time.sleep(wait)
                continue
            raise


def post_form(
    url: str,
    data: Dict[str, str],
    timeout: int = 30,
    proxies: Any = None,
    impersonate: str = "chrome",
) -> Dict[str, Any]:
    body = urllib.parse.urlencode(data)
    resp = raw_tls_request(
        requests.post,
        url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        proxies=proxies,
        impersonate=impersonate,
        timeout=timeout,
    )
    raw_text = resp.text or ""
    if resp.status_code != 200:
        raise RuntimeError(f"token exchange failed: {resp.status_code}: {raw_text}")
    try:
        return resp.json()
    except Exception as exc:
        raise RuntimeError(f"token exchange failed: invalid json: {raw_text[:300]}") from exc


@dataclass(frozen=True)
class OAuthStart:
    auth_url: str
    state: str
    code_verifier: str
    redirect_uri: str


def generate_oauth_url(*, redirect_uri: str | None = None, scope: str = DEFAULT_SCOPE) -> OAuthStart:
    if not redirect_uri:
        redirect_uri = get_default_redirect_uri()
    state = random_state()
    code_verifier = pkce_verifier()
    code_challenge = sha256_b64url_no_pad(code_verifier)
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "login",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    return OAuthStart(
        auth_url=auth_url,
        state=state,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
    )


def generate_oauth_url_dynamic(*, scope: str = DEFAULT_SCOPE) -> OAuthStart:
    return generate_oauth_url(redirect_uri=get_default_redirect_uri(), scope=scope)


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def submit_callback_url(
    *,
    callback_url: str,
    expected_state: str,
    code_verifier: str,
    redirect_uri: str | None = None,
    proxies: Any = None,
    impersonate: str = "chrome",
    mock: bool = False,
) -> str:
    if not redirect_uri:
        redirect_uri = get_default_redirect_uri()
    if mock:
        now = int(time.time())
        expired_rfc3339 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 3600))
        now_rfc3339 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        payload = {
            "type": "codex",
            "email": "mock@example.com",
            "password": "mock_password",
            "expired": expired_rfc3339,
            "id_token": "mock_id_token",
            "account_id": "mock_account_id",
            "access_token": "mock_access_token",
            "last_refresh": now_rfc3339,
            "refresh_token": "mock_refresh_token",
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    cb = parse_callback_url(callback_url)
    if cb["error"]:
        desc = cb["error_description"]
        raise RuntimeError(f"oauth error: {cb['error']}: {desc}".strip())
    if not cb["code"]:
        raise ValueError("callback url missing ?code=")
    if not cb["state"]:
        raise ValueError("callback url missing ?state=")
    if cb["state"] != expected_state:
        raise ValueError("state mismatch")

    token_resp = post_form(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": cb["code"],
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
        proxies=proxies,
        impersonate=impersonate,
    )

    access_token = (token_resp.get("access_token") or "").strip()
    refresh_token = (token_resp.get("refresh_token") or "").strip()
    id_token = (token_resp.get("id_token") or "").strip()
    expires_in = _to_int(token_resp.get("expires_in"))

    claims = jwt_claims_no_verify(id_token)
    email = str(claims.get("email") or "").strip()
    auth_claims = claims.get("https://api.openai.com/auth") or {}
    account_id = str(auth_claims.get("chatgpt_account_id") or "").strip()

    now = int(time.time())
    expired_rfc3339 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + max(expires_in, 0)))
    now_rfc3339 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))

    config = {
        "id_token": id_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "account_id": account_id,
        "last_refresh": now_rfc3339,
        "email": email,
        "type": "codex",
        "expired": expired_rfc3339,
    }
    return json.dumps(config, ensure_ascii=False, separators=(",", ":"))

import json
import urllib.parse
import time

from reg_gpt.email_providers import wait_for_email_code
from reg_gpt.oauth import (
    build_sentinel_token,
    capture_callback_from_redirects,
    extract_code_from_url,
    extract_workspace_id_from_auth_cookie,
    generate_oauth_url,
    jwt_claims_no_verify,
    make_trace_headers,
    post_form,
)
from reg_gpt.registration.context import RegistrationContext


def _oauth_json_headers(ctx: RegistrationContext, referer: str) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://auth.openai.com",
        "Referer": referer,
        "oai-device-id": ctx.device_id,
    }
    headers.update(make_trace_headers())
    return headers


def _oauth_html_headers(ctx: RegistrationContext, referer: str) -> dict[str, str]:
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": referer,
        "Upgrade-Insecure-Requests": "1",
    }
    return headers


def _chatgpt_session_headers(referer: str = "https://chatgpt.com/") -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Referer": referer,
        "Origin": "https://chatgpt.com",
    }


def _has_login_session(ctx: RegistrationContext) -> bool:
    try:
        jar = getattr(ctx.session.cookies, "jar", None)
        if jar is not None:
            return any(getattr(cookie, "name", "") == "login_session" for cookie in jar)
    except Exception:
        pass
    return bool(ctx.session.cookies.get("login_session"))


def _bootstrap_oauth_session(ctx: RegistrationContext) -> tuple[bool, str]:
    ctx.oauth = generate_oauth_url()
    try:
        resp = ctx.session.get(
            ctx.oauth.auth_url,
            headers=_oauth_html_headers(ctx, "https://chatgpt.com/"),
            allow_redirects=True,
            timeout=30,
        )
    except Exception as exc:
        ctx.err(f"{ctx.tag}OAuth /oauth/authorize 异常: {exc}")
        return False, ""

    final_url = str(resp.url or "")
    has_login = _has_login_session(ctx)
    if has_login:
        return True, final_url

    oauth2_url = "https://auth.openai.com/api/oauth/oauth2/auth"
    params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(ctx.oauth.auth_url).query, keep_blank_values=True))
    try:
        resp2 = ctx.session.get(
            oauth2_url,
            headers=_oauth_html_headers(ctx, ctx.oauth.auth_url),
            params=params,
            allow_redirects=True,
            timeout=30,
        )
        final_url = str(resp2.url or final_url)
    except Exception as exc:
        ctx.warn(f"{ctx.tag}OAuth /api/oauth/oauth2/auth 异常: {exc}")
    has_login = _has_login_session(ctx)
    return has_login, final_url


def _extract_account_id_from_claims(*claims_candidates: object) -> str:
    for claims in claims_candidates:
        if not isinstance(claims, dict):
            continue
        auth_claims = claims.get("https://api.openai.com/auth") or {}
        if isinstance(auth_claims, dict):
            for key in (
                "chatgpt_account_id",
                "account_id",
                "workspace_id",
                "chatgpt_organization_id",
                "organization_id",
                "org_id",
            ):
                value = str(auth_claims.get(key) or "").strip()
                if value:
                    return value
        for key in (
            "chatgpt_account_id",
            "account_id",
            "workspace_id",
            "chatgpt_organization_id",
            "organization_id",
            "org_id",
        ):
            value = str(claims.get(key) or "").strip()
            if value:
                return value
    return ""


def _build_session_token_json(ctx: RegistrationContext, session_data: dict) -> str:
    access_token = str(
        session_data.get("accessToken")
        or session_data.get("access_token")
        or session_data.get("accessJwt")
        or ""
    ).strip()
    if not access_token:
        return ""

    id_token = str(session_data.get("idToken") or session_data.get("id_token") or "").strip()
    refresh_token = str(session_data.get("refreshToken") or session_data.get("refresh_token") or "").strip()
    user_data = session_data.get("user") or {}
    access_claims = jwt_claims_no_verify(access_token)
    id_claims = jwt_claims_no_verify(id_token)
    email = str(
        (user_data.get("email") if isinstance(user_data, dict) else "")
        or id_claims.get("email")
        or access_claims.get("email")
        or ctx.email
        or ""
    ).strip()
    account_id = _extract_account_id_from_claims(session_data, user_data, id_claims, access_claims)

    expires_value = str(session_data.get("expires") or "").strip()
    if not expires_value:
        exp = int(access_claims.get("exp") or id_claims.get("exp") or 0)
        if exp > 0:
            expires_value = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(exp))

    now_rfc3339 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(time.time())))
    payload = {
        "type": "codex",
        "email": email,
        "password": ctx.reg_password,
        "expired": expires_value,
        "id_token": id_token,
        "account_id": account_id,
        "access_token": access_token,
        "last_refresh": now_rfc3339,
        "refresh_token": refresh_token,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def try_reuse_registration_session(ctx: RegistrationContext) -> str:
    session_url = "https://chatgpt.com/api/auth/session"
    referer = ctx.final_url if (ctx.final_url or "").startswith("https://chatgpt.com") else "https://chatgpt.com/"
    last_status = 0
    last_text = ""

    for attempt in range(2):
        try:
            if attempt > 0:
                ctx.session.get(
                    "https://chatgpt.com/",
                    headers=_oauth_html_headers(ctx, referer),
                    allow_redirects=True,
                    timeout=20,
                )
            resp = ctx.session.get(
                session_url,
                headers=_chatgpt_session_headers(referer),
                allow_redirects=True,
                timeout=20,
            )
        except Exception as exc:
            last_text = str(exc)
            ctx.warn(f"{ctx.tag}注册会话取 token 异常: {exc}")
            continue

        final_url = str(resp.url or "").strip()
        if final_url:
            ctx.info(f"{ctx.tag}Session 接口最终 URL: {final_url}")

        last_status = resp.status_code
        body_text = resp.text or ""
        last_text = body_text[:220]
        if resp.status_code != 200:
            continue

        try:
            session_data = resp.json()
        except Exception:
            if attempt == 0:
                ctx.warn(f"{ctx.tag}Session 接口返回非 JSON，准备再试一次")
                continue
            break

        if not isinstance(session_data, dict):
            if attempt == 0:
                ctx.warn(f"{ctx.tag}Session 接口返回结构异常，准备再试一次")
                continue
            break

        token_json = _build_session_token_json(ctx, session_data)
        if token_json:
            try:
                access_token = str(session_data.get("accessToken") or session_data.get("access_token") or "").strip()
                access_claims = jwt_claims_no_verify(access_token)
                account_id = _extract_account_id_from_claims(session_data, session_data.get("user") or {}, access_claims)
            except Exception:
                account_id = ""
            ctx.info(f"{ctx.tag}已复用注册会话直接获取 token，account_id={account_id or '-'}")
            return token_json

        if attempt == 0:
            ctx.warn(f"{ctx.tag}注册会话暂未产出 accessToken，准备再试一次")

    if last_status or last_text:
        ctx.warn(f"{ctx.tag}注册会话未直接拿到 token，准备回退 OAuth。status={last_status or '-'} detail={last_text}")
    else:
        ctx.warn(f"{ctx.tag}注册会话未直接拿到 token，准备回退 OAuth")
    return ""


def _post_authorize_continue(ctx: RegistrationContext, referer_url: str):
    sentinel = build_sentinel_token(
        ctx.session,
        ctx.device_id,
        flow="authorize_continue",
        impersonate=ctx.active_imp,
        ctx=ctx,
    )
    if not sentinel:
        ctx.err(f"{ctx.tag}OAuth sentinel(authorize_continue) 生成失败")
        return None
    headers = _oauth_json_headers(ctx, referer_url)
    headers["openai-sentinel-token"] = sentinel
    so_token = ctx.pop_sentinel_so_token("authorize_continue")
    if so_token:
        headers["openai-sentinel-so-token"] = so_token
    try:
        return ctx.session.post(
            "https://auth.openai.com/api/accounts/authorize/continue",
            json={"username": {"kind": "email", "value": ctx.email}},
            headers=headers,
            timeout=30,
            allow_redirects=False,
        )
    except Exception as exc:
        ctx.err(f"{ctx.tag}OAuth authorize/continue 异常: {exc}")
        return None


def _post_password_verify(ctx: RegistrationContext):
    sentinel = build_sentinel_token(
        ctx.session,
        ctx.device_id,
        flow="password_verify",
        impersonate=ctx.active_imp,
        ctx=ctx,
    )
    if not sentinel:
        ctx.err(f"{ctx.tag}OAuth sentinel(password_verify) 生成失败")
        return None
    headers = _oauth_json_headers(ctx, "https://auth.openai.com/log-in/password")
    headers["openai-sentinel-token"] = sentinel
    so_token = ctx.pop_sentinel_so_token("password_verify")
    if so_token:
        headers["openai-sentinel-so-token"] = so_token
    try:
        return ctx.session.post(
            "https://auth.openai.com/api/accounts/password/verify",
            json={"password": ctx.reg_password},
            headers=headers,
            timeout=30,
            allow_redirects=False,
        )
    except Exception as exc:
        ctx.err(f"{ctx.tag}OAuth password/verify 异常: {exc}")
        return None


def _validate_oauth_email_otp(ctx: RegistrationContext) -> tuple[bool, str, str]:
    """OTP 校验，返回 (是否成功, 新的 continue_url, 新的 page_type)。"""
    sentinel = build_sentinel_token(
        ctx.session,
        ctx.device_id,
        flow="password_verify",
        impersonate=ctx.active_imp,
        ctx=ctx,
    )
    headers = _oauth_json_headers(ctx, "https://auth.openai.com/email-verification")
    if sentinel:
        headers["openai-sentinel-token"] = sentinel

    so_token = ctx.pop_sentinel_so_token("password_verify")
    if so_token:
        headers["openai-sentinel-so-token"] = so_token

    if not ctx.otp_not_before_ms:
        ctx.otp_not_before_ms = int(time.time() * 1000)
    for attempt in range(2):
        code = wait_for_email_code(
            ctx.provider,
            email=ctx.email,
            mail_token=ctx.mail_token,
            proxy=ctx.proxy,
            tag=f"{ctx.tag}OAuth ",
            wid=ctx.wid,
            poller=ctx.poller,
            step_logger=ctx.step,
            wait_logger=lambda wid_value, line: None,
            dim=None,
            green=None,
            yellow=None,
            red=None,
            timeout=ctx.email_otp_timeout(retry=attempt > 0),
            impersonate=ctx.active_imp or "chrome",
            exclude_codes=ctx.tried_email_codes,
            seen_message_ids=ctx.mail_seen_ids,
            not_before_ms=ctx.otp_not_before_ms,
        )
        if not code:
            continue
        ctx.info(f"{ctx.tag}OAuth OTP 尝试校验")
        try:
            resp = ctx.session.post(
                "https://auth.openai.com/api/accounts/email-otp/validate",
                json={"code": code},
                headers=headers,
                timeout=30,
                allow_redirects=False,
            )
        except Exception as exc:
            ctx.remember_email_code(code)
            ctx.warn(f"{ctx.tag}OAuth email-otp/validate 异常: {exc}")
            continue
        if resp.status_code == 200:
            ctx.remember_email_code(code)
            otp_continue = ""
            otp_page = ""
            try:
                otp_data = resp.json()
                otp_continue = str((otp_data or {}).get("continue_url") or "").strip()
                otp_page = str(((otp_data or {}).get("page") or {}).get("type") or "").strip()
                ctx.info(f"{ctx.tag}OAuth OTP 验证成功 continue_url={otp_continue[:120]} page_type={otp_page}")
            except Exception:
                pass
            return True, otp_continue, otp_page
        ctx.remember_email_code(code)
        ctx.warn(f"{ctx.tag}OAuth OTP validate 返回 {resp.status_code}: {resp.text[:200]}")
    return False, "", ""


def _submit_workspace_and_org(ctx: RegistrationContext, consent_url: str) -> str:
    auth_cookie = ctx.session.cookies.get("oai-client-auth-session")
    workspace_id = extract_workspace_id_from_auth_cookie(auth_cookie or "")
    if not workspace_id:
        return ""

    headers = _oauth_json_headers(ctx, consent_url)
    resp = ctx.session.post(
        "https://auth.openai.com/api/accounts/workspace/select",
        json={"workspace_id": workspace_id},
        headers=headers,
        allow_redirects=False,
        timeout=30,
    )
    ctx.info(f"{ctx.tag}OAuth workspace/select -> {resp.status_code}")

    if resp.status_code in (301, 302, 303, 307, 308):
        location = (resp.headers.get("Location") or "").strip()
        if location.startswith("/"):
            location = f"https://auth.openai.com{location}"
        callback_url = capture_callback_from_redirects(ctx.session, location, max_hops=8)
        return callback_url or location

    if resp.status_code != 200:
        return ""

    try:
        ws_data = resp.json()
    except Exception:
        return ""

    continue_url = str(ws_data.get("continue_url") or "").strip()
    orgs = ((ws_data.get("data") or {}).get("orgs") or []) if isinstance(ws_data, dict) else []
    org_id = ""
    project_id = ""
    if orgs:
        org_id = str((orgs[0] or {}).get("id") or "").strip()
        projects = (orgs[0] or {}).get("projects") or []
        if projects:
            project_id = str((projects[0] or {}).get("id") or "").strip()

    if org_id:
        org_body = {"org_id": org_id}
        if project_id:
            org_body["project_id"] = project_id
        org_referer = continue_url if continue_url.startswith("http") else f"https://auth.openai.com{continue_url}" if continue_url else consent_url
        org_headers = _oauth_json_headers(ctx, org_referer)
        resp_org = ctx.session.post(
            "https://auth.openai.com/api/accounts/organization/select",
            json=org_body,
            headers=org_headers,
            allow_redirects=False,
            timeout=30,
        )
        ctx.info(f"{ctx.tag}OAuth organization/select -> {resp_org.status_code}")
        if resp_org.status_code in (301, 302, 303, 307, 308):
            location = (resp_org.headers.get("Location") or "").strip()
            if location.startswith("/"):
                location = f"https://auth.openai.com{location}"
            callback_url = capture_callback_from_redirects(ctx.session, location, max_hops=8)
            return callback_url or location
        if resp_org.status_code == 200:
            try:
                org_data = resp_org.json()
            except Exception:
                org_data = {}
            org_next = str((org_data or {}).get("continue_url") or "").strip()
            if org_next:
                if org_next.startswith("/"):
                    org_next = f"https://auth.openai.com{org_next}"
                callback_url = capture_callback_from_redirects(ctx.session, org_next, max_hops=8)
                if callback_url:
                    return callback_url

    if continue_url:
        if continue_url.startswith("/"):
            continue_url = f"https://auth.openai.com{continue_url}"
        callback_url = capture_callback_from_redirects(ctx.session, continue_url, max_hops=8)
        if callback_url:
            return callback_url
    return ""


def complete_oauth(ctx: RegistrationContext) -> str:
    ctx.info(f"{ctx.tag}开始执行 Codex OAuth 纯协议流程")
    ctx.session.cookies.set("oai-did", ctx.device_id, domain=".auth.openai.com")
    ctx.session.cookies.set("oai-did", ctx.device_id, domain="auth.openai.com")

    has_login_session, authorize_final_url = _bootstrap_oauth_session(ctx)
    if not authorize_final_url:
        return ""

    continue_referer = authorize_final_url if authorize_final_url.startswith("https://auth.openai.com") else "https://auth.openai.com/log-in"
    resp_continue = _post_authorize_continue(ctx, continue_referer)
    if resp_continue is None:
        return ""
    if resp_continue.status_code == 400 and "invalid_auth_step" in (resp_continue.text or ""):
        has_login_session, authorize_final_url = _bootstrap_oauth_session(ctx)
        if not authorize_final_url:
            return ""
        continue_referer = authorize_final_url if authorize_final_url.startswith("https://auth.openai.com") else "https://auth.openai.com/log-in"
        resp_continue = _post_authorize_continue(ctx, continue_referer)
        if resp_continue is None:
            return ""
    if resp_continue.status_code != 200:
        ctx.err(f"{ctx.tag}OAuth authorize/continue 非200: {resp_continue.status_code} {resp_continue.text[:220]}")
        return ""

    try:
        continue_data = resp_continue.json()
    except Exception:
        ctx.err(f"{ctx.tag}OAuth authorize/continue JSON 解析失败")
        return ""
    continue_url = str((continue_data or {}).get("continue_url") or "").strip()
    page_type = str(((continue_data or {}).get("page") or {}).get("type") or "")
    skip_password_verify = False
    if has_login_session:
        lower_continue = continue_url.lower()
        lower_page_type = page_type.lower()
        skip_password_verify = bool(
            extract_code_from_url(continue_url)
            or any(token in lower_continue for token in ("consent", "workspace", "organization", "callback", "sign-in-with-chatgpt"))
            or any(token in lower_page_type for token in ("consent", "workspace", "organization"))
        )
        if skip_password_verify:
            ctx.info(f"{ctx.tag}已检测到现成登录会话，跳过 password/verify")

    if not skip_password_verify:
        resp_verify = _post_password_verify(ctx)
        if resp_verify is None:
            return ""
        if resp_verify.status_code != 200:
            ctx.err(f"{ctx.tag}OAuth password/verify 非200: {resp_verify.status_code} {resp_verify.text[:220]}")
            return ""
        try:
            verify_data = resp_verify.json()
        except Exception:
            ctx.err(f"{ctx.tag}OAuth password/verify JSON 解析失败")
            return ""
        continue_url = str((verify_data or {}).get("continue_url") or continue_url or "").strip()
        page_type = str(((verify_data or {}).get("page") or {}).get("type") or page_type or "")

    need_oauth_otp = (
        page_type == "email_otp_verification"
        or "email-verification" in continue_url
        or "email-otp" in continue_url
    )
    if need_oauth_otp:
        ctx.info(f"{ctx.tag}OAuth 检测到邮箱 OTP 验证 (continue_url={continue_url[:120]}, page_type={page_type})")
        ctx.otp_not_before_ms = int(time.time() * 1000)
        otp_ok, otp_continue_url, otp_page_type = _validate_oauth_email_otp(ctx)
        if not otp_ok:
            ctx.err(f"{ctx.tag}OAuth 阶段 OTP 验证失败")
            return ""
        # 核心修复：使用 OTP 验证后返回的新 continue_url 和 page_type
        if otp_continue_url:
            continue_url = otp_continue_url
            ctx.info(f"{ctx.tag}OAuth OTP 后更新 continue_url={continue_url[:120]}")
        if otp_page_type:
            page_type = otp_page_type
            ctx.info(f"{ctx.tag}OAuth OTP 后更新 page_type={page_type}")

    callback_url = ""
    consent_url = continue_url
    if consent_url.startswith("/"):
        consent_url = f"https://auth.openai.com{consent_url}"
    ctx.info(f"{ctx.tag}OAuth OTP 后 consent_url={consent_url[:150]} page_type={page_type}")

    if consent_url and extract_code_from_url(consent_url):
        callback_url = consent_url
        ctx.info(f"{ctx.tag}OAuth 从 consent_url 直接提取到 code")
    if not callback_url and consent_url:
        callback_url = capture_callback_from_redirects(ctx.session, consent_url, max_hops=8)
        if callback_url:
            ctx.info(f"{ctx.tag}OAuth 从重定向链获取到 callback: {callback_url[:120]}")
        else:
            ctx.warn(f"{ctx.tag}OAuth 重定向链未捕获 callback，consent_url={consent_url[:150]}")

    consent_hint = (
        ("consent" in (consent_url or ""))
        or ("sign-in-with-chatgpt" in (consent_url or ""))
        or ("workspace" in (consent_url or ""))
        or ("organization" in (consent_url or ""))
        or ("consent" in page_type)
        or ("organization" in page_type)
    )
    ctx.info(f"{ctx.tag}OAuth consent_hint={consent_hint}")

    if not callback_url and consent_hint:
        if not consent_url:
            consent_url = "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"
        ctx.info(f"{ctx.tag}OAuth 尝试 workspace/org 流程 consent_url={consent_url[:150]}")
        callback_url = _submit_workspace_and_org(ctx, consent_url)

    if not callback_url:
        fallback_consent = "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"
        ctx.info(f"{ctx.tag}OAuth 尝试 fallback consent 流程")
        callback_url = _submit_workspace_and_org(ctx, fallback_consent)
        if not callback_url:
            callback_url = capture_callback_from_redirects(ctx.session, fallback_consent, max_hops=8)

    if not callback_url:
        from reg_gpt.oauth_server import get_callback_code
        from reg_gpt.config import load_or_create_config
        cfg = load_or_create_config()
        oauth_cfg = cfg.get("oauth") or {}
        if oauth_cfg.get("enabled", True):
            ctx.info(f"{ctx.tag}OAuth 自动化捕获失败，正在监听本地回调服务器 (state={ctx.oauth.state})...")
            code = get_callback_code(ctx.oauth.state, timeout=15)
            if code:
                 callback_url = f"http://localhost/callback?code={code}&state={ctx.oauth.state}"
                 ctx.info(f"{ctx.tag}从本地回调服务器捕获到 Code")

    if not callback_url:
        # 最后尝试：直接用 session reuse 作为兜底
        ctx.warn(f"{ctx.tag}OAuth callback 全部失败，尝试 session reuse 兜底")
        from reg_gpt.registration.oauth_finish import try_reuse_registration_session
        fallback_json = try_reuse_registration_session(ctx)
        if fallback_json:
            ctx.info(f"{ctx.tag}Session reuse 兜底成功")
            return fallback_json
        ctx.err(f"{ctx.tag}未获取到 OAuth callback/code (consent_url={consent_url[:100]}, page_type={page_type})")
        return ""

    try:
        token_resp = post_form(
            "https://auth.openai.com/oauth/token",
            {
                "grant_type": "authorization_code",
                "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
                "code": extract_code_from_url(callback_url),
                "redirect_uri": ctx.oauth.redirect_uri,
                "code_verifier": ctx.oauth.code_verifier,
            },
            proxies=ctx.proxies,
            impersonate=ctx.active_imp,
        )
    except Exception as exc:
        ctx.err(f"{ctx.tag}OAuth token 交换失败: {exc}")
        return ""

    access_token = str(token_resp.get("access_token") or "").strip()
    if not access_token:
        ctx.err(f"{ctx.tag}OAuth token 响应缺少 access_token")
        return ""

    try:
        id_token = str(token_resp.get("id_token") or "").strip()
        refresh_token = str(token_resp.get("refresh_token") or "").strip()
        expires_in = int(token_resp.get("expires_in") or 0)
        claims = jwt_claims_no_verify(id_token)
        email = str(claims.get("email") or ctx.email).strip()
        auth_claims = claims.get("https://api.openai.com/auth") or {}
        account_id = str(auth_claims.get("chatgpt_account_id") or "").strip()
        now = int(__import__("time").time())
        expired_rfc3339 = __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime(now + max(expires_in, 0)))
        now_rfc3339 = __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime(now))
        payload = {
            "type": "codex",
            "email": email,
            "password": ctx.reg_password,
            "expired": expired_rfc3339,
            "id_token": id_token,
            "account_id": account_id,
            "access_token": access_token,
            "last_refresh": now_rfc3339,
            "refresh_token": refresh_token,
        }
        ctx.info(f"{ctx.tag}Codex Token 获取成功")
        import json

        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except Exception as exc:
        ctx.err(f"{ctx.tag}OAuth token 数据组装失败: {exc}")
        return ""

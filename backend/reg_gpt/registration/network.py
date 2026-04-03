import random
import re
import time
from typing import Tuple

from curl_cffi import requests

import reg_gpt.console as console
from reg_gpt.email_providers import create_email_account
from reg_gpt.fingerprint import FP_IMPERSONATE_POOL, build_fingerprint, build_fp_headers, imp_engine, imp_is_mobile, imp_version_num
from reg_gpt.registration.context import RegistrationContext
from reg_gpt.tls import add_tls_retry


def _preferred_auth_pool() -> list[str]:
    chromium_desktop = [
        name for name in FP_IMPERSONATE_POOL
        if imp_engine(name) == "chromium" and not imp_is_mobile(name) and imp_version_num(name) >= 120
    ]
    if chromium_desktop:
        return chromium_desktop
    fallback = [
        name for name in FP_IMPERSONATE_POOL
        if imp_engine(name) == "chromium" and not imp_is_mobile(name)
    ]
    return fallback or list(FP_IMPERSONATE_POOL)


def _json_headers(referer: str, origin: str = "https://chatgpt.com") -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Referer": referer,
        "Origin": origin,
    }


def _html_headers(referer: str) -> dict[str, str]:
    return {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": referer,
        "Upgrade-Insecure-Requests": "1",
    }


def prepare_initial_session(ctx: RegistrationContext) -> None:
    auth_pool = _preferred_auth_pool()
    ctx.chosen_imp = random.choice(auth_pool)
    remaining = [name for name in auth_pool if name != ctx.chosen_imp]
    random.shuffle(remaining)
    ctx.impersonate_fallbacks = [ctx.chosen_imp] + remaining

    ctx.fp = build_fingerprint(
        imp_override=ctx.chosen_imp,
        platform_override='"Windows"',
        os_ver_override='"10.0.0"',
    )
    ctx.active_imp = ctx.chosen_imp
    ctx.session = requests.Session(proxies=ctx.proxies, impersonate=ctx.chosen_imp)
    ctx.session.headers.update(build_fp_headers(ctx.fp))
    add_tls_retry(ctx.session)
    ctx.session.cookies.set("oai-did", ctx.device_id, domain="chatgpt.com")
    ctx.session.cookies.set("oai-did", ctx.device_id, domain=".auth.openai.com")
    ctx.session.cookies.set("oai-did", ctx.device_id, domain="auth.openai.com")
    ctx.step(
        f"{ctx.tag}指纹",
        f"{ctx.chosen_imp} ({ctx.fp['engine']})  {ctx.fp['platform']}  {ctx.fp['viewport_w']}×{ctx.fp['viewport_h']}  {ctx.fp['timezone']}",
    )


def _check_trace(ctx: RegistrationContext) -> bool:
    trace = ctx.session.get("https://cloudflare.com/cdn-cgi/trace", timeout=10).text
    loc_match = re.search(r"^loc=(.+)$", trace, re.MULTILINE)
    loc = loc_match.group(1) if loc_match else None
    loc_display = console.green(str(loc)) if loc not in ("CN", "HK", None) else console.red(str(loc))
    ctx.step(f"{ctx.tag}出口IP", loc_display)
    if loc in {"CN", "HK"}:
        raise RuntimeError("检查代理—所在地不支持")
    return True


def _check_chatgpt_home(ctx: RegistrationContext) -> bool:
    resp = ctx.session.get("https://chatgpt.com/", headers=_html_headers("https://chatgpt.com/"), timeout=20, allow_redirects=True)
    ok = resp.status_code != 403
    ctx.step(f"{ctx.tag}ChatGPT首页", console.green(str(resp.status_code)) if ok else console.red(str(resp.status_code)))
    return ok


def _check_chatgpt_csrf(ctx: RegistrationContext) -> bool:
    resp = ctx.session.get(
        "https://chatgpt.com/api/auth/csrf",
        headers={"Accept": "application/json", "Referer": "https://chatgpt.com/"},
        timeout=20,
    )
    data = resp.json()
    token = data.get("csrfToken", "") if isinstance(data, dict) else ""
    ok = bool(token)
    ctx.step(f"{ctx.tag}CSRF预检", console.green("ok") if ok else console.red("missing"))
    return ok


def _check_auth_openai(ctx: RegistrationContext) -> bool:
    resp = ctx.session.get("https://auth.openai.com/", timeout=20, allow_redirects=True)
    ok = resp.status_code < 500
    ctx.step(f"{ctx.tag}Auth站点", console.green(str(resp.status_code)) if ok else console.red(str(resp.status_code)))
    return ok


def check_network(ctx: RegistrationContext) -> bool:
    try:
        _check_trace(ctx)
        checks = [
            _check_chatgpt_home(ctx),
            _check_chatgpt_csrf(ctx),
            _check_auth_openai(ctx),
        ]
        if not all(checks):
            raise RuntimeError("预检未通过")
        return True
    except Exception as exc:
        ctx.err(f"{ctx.tag}网络连接检查失败: {exc}")
        return False


def prepare_identity(ctx: RegistrationContext) -> bool:
    try:
        email, email_password, mail_token = create_email_account(
            ctx.provider,
            proxy=ctx.proxy,
            impersonate=ctx.active_imp or ctx.chosen_imp or "chrome",
        )
    except Exception as exc:
        ctx.err(f"{ctx.tag}创建邮箱失败: {exc}")
        return False
    ctx.email = email
    ctx.email_password = email_password
    ctx.mail_token = mail_token
    ctx.step(f"{ctx.tag}邮箱", ctx.email)
    return True


def visit_homepage(ctx: RegistrationContext) -> None:
    resp = ctx.session.get("https://chatgpt.com/", headers=_html_headers("https://chatgpt.com/"), timeout=20, allow_redirects=True)
    ctx.step(f"{ctx.tag}主页访问", console.green(str(resp.status_code)) if resp.status_code < 400 else console.red(str(resp.status_code)))


def get_csrf(ctx: RegistrationContext) -> bool:
    url = "https://chatgpt.com/api/auth/csrf"
    headers = {"Accept": "application/json", "Referer": "https://chatgpt.com/"}
    for attempt in range(2):
        resp = ctx.session.get(url, headers=headers, timeout=20)
        try:
            data = resp.json()
        except Exception:
            if attempt == 0:
                ctx.warn(f"{ctx.tag}CSRF 非 JSON，准备重试一次")
                time.sleep(random.uniform(0.4, 1.0))
                visit_homepage(ctx)
                continue
            ctx.err(f"{ctx.tag}获取 CSRF 失败: 非 JSON 响应 status={resp.status_code}")
            return False
        token = data.get("csrfToken", "") if isinstance(data, dict) else ""
        if token:
            ctx.csrf_token = token
            ctx.step(f"{ctx.tag}CSRF", console.green("ok"))
            return True
        if attempt == 0:
            ctx.warn(f"{ctx.tag}CSRF 缺失，准备重试一次")
            time.sleep(random.uniform(0.4, 1.0))
            visit_homepage(ctx)
            continue
    ctx.err(f"{ctx.tag}获取 CSRF 失败")
    return False


def signin(ctx: RegistrationContext) -> Tuple[bool, str]:
    url = "https://chatgpt.com/api/auth/signin/openai"
    params = {
        "prompt": "login",
        "ext-oai-did": ctx.device_id,
        "auth_session_logging_id": ctx.auth_session_logging_id,
        "screen_hint": "login_or_signup",
        "login_hint": ctx.email,
    }
    form_data = {"callbackUrl": "https://chatgpt.com/", "csrfToken": ctx.csrf_token, "json": "true"}
    resp = ctx.session.post(
        url,
        params=params,
        data=form_data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Referer": "https://chatgpt.com/",
            "Origin": "https://chatgpt.com",
        },
        timeout=20,
    )
    try:
        data = resp.json()
    except Exception:
        ctx.err(f"{ctx.tag}Signin 返回非 JSON status={resp.status_code}")
        return False, ""
    authorize_url = data.get("url", "") if isinstance(data, dict) else ""
    ctx.step(f"{ctx.tag}Signin", console.green("ok") if authorize_url else console.red(str(resp.status_code)))
    if not authorize_url:
        ctx.err(f"{ctx.tag}获取 authorize URL 失败: {str(data)[:200]}")
        return False, ""
    return True, authorize_url


def authorize(ctx: RegistrationContext, url: str) -> Tuple[bool, str]:
    resp = ctx.session.get(url, headers=_html_headers("https://chatgpt.com/"), allow_redirects=True, timeout=30)
    final_url = str(resp.url or "")
    ctx.set_final_url(final_url)
    ctx.step(f"{ctx.tag}Authorize", ctx.final_path or final_url or "-")
    return True, final_url


def establish_signup_session(ctx: RegistrationContext) -> bool:
    visit_homepage(ctx)
    time.sleep(random.uniform(0.3, 0.8))
    if not get_csrf(ctx):
        return False
    time.sleep(random.uniform(0.2, 0.5))
    ok, authorize_url = signin(ctx)
    if not ok:
        return False
    time.sleep(random.uniform(0.3, 0.8))
    ok, _ = authorize(ctx, authorize_url)
    if not ok:
        return False
    time.sleep(random.uniform(0.3, 0.8))
    ctx.info(f"{ctx.tag}Authorize → {ctx.final_path or ctx.final_url}")
    return True

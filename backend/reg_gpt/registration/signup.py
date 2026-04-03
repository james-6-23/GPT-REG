import json
import random
import re
import secrets
import string
import time
from typing import Tuple

import reg_gpt.console as console
from reg_gpt.email_providers import wait_for_email_code
from reg_gpt.mail_cf import random_birthdate, random_name
from reg_gpt.oauth import build_sentinel_token, make_trace_headers
from reg_gpt.registration.context import RegistrationContext


def _resolve_location(response) -> str:
    next_location = ""
    try:
        payload = response.json()
        next_location = str(
            payload.get("location")
            or payload.get("redirect_uri")
            or payload.get("url")
            or payload.get("continue_url")
            or payload.get("redirect_url")
            or ""
        ).strip()
    except Exception:
        next_location = ""
    if not next_location:
        next_location = (response.headers.get("Location") or "").strip()
    return next_location


def _json_headers(referer: str, origin: str = "https://auth.openai.com") -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Referer": referer,
        "Origin": origin,
    }
    headers.update(make_trace_headers())
    return headers


def register_account_password(ctx: RegistrationContext) -> bool:
    base_pwd = secrets.token_urlsafe(12)
    ctx.reg_password = base_pwd + random.choice(string.ascii_uppercase) + random.choice(string.digits) + random.choice("!@#$%^&*")

    # 获取 sentinel-token (用于应对注册接口的风控)
    sentinel = build_sentinel_token(
        ctx.session,
        ctx.device_id,
        flow="username_password_create",
        impersonate=ctx.active_imp or ctx.chosen_imp or "chrome",
        ctx=ctx,
    )

    headers = _json_headers("https://auth.openai.com/create-account/password")
    if sentinel:
        headers["openai-sentinel-token"] = sentinel

    resp = ctx.session.post(
        "https://auth.openai.com/api/accounts/user/register",
        json={"username": ctx.email, "password": ctx.reg_password},
        headers=headers,
        timeout=20,
    )
    ok = resp.status_code == 200
    ctx.step(f"{ctx.tag}账号注册", console.green("ok") if ok else console.red(str(resp.status_code)))
    if not ok:
        ctx.err(f"{ctx.tag}账号注册失败: {resp.text[:220]}")
    return ok


def send_otp(ctx: RegistrationContext) -> bool:
    ctx.otp_not_before_ms = int(time.time() * 1000)
    resp = ctx.session.get(
        "https://auth.openai.com/api/accounts/email-otp/send",
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://auth.openai.com/create-account/password",
            "Upgrade-Insecure-Requests": "1",
        },
        allow_redirects=True,
        timeout=20,
    )
    ok = resp.status_code < 400
    ctx.step(f"{ctx.tag}验证码发送", console.green("ok") if ok else console.red(str(resp.status_code)))
    if not ok:
        ctx.err(f"{ctx.tag}验证码发送失败: {resp.text[:220]}")
    return ok


def wait_for_verification_code(ctx: RegistrationContext, timeout: int = 120) -> str:
    return wait_for_email_code(
        ctx.provider,
        email=ctx.email,
        mail_token=ctx.mail_token,
        proxy=ctx.proxy,
        tag=ctx.tag,
        wid=ctx.wid,
        poller=ctx.poller,
        step_logger=ctx.step,
        wait_logger=lambda wid_value, line: console.wlog(wid_value, line),
        dim=console.dim,
        green=console.green,
        yellow=console.yellow,
        red=console.red,
        timeout=timeout,
        impersonate=ctx.active_imp or "chrome",
        exclude_codes=ctx.tried_email_codes,
        seen_message_ids=ctx.mail_seen_ids,
        not_before_ms=ctx.otp_not_before_ms,
    )


def validate_otp(ctx: RegistrationContext, code: str) -> Tuple[bool, dict]:
    # 校验阶段可能也需要 sentinel-token
    sentinel = build_sentinel_token(
        ctx.session,
        ctx.device_id,
        flow="password_verify",
        impersonate=ctx.active_imp or ctx.chosen_imp or "chrome",
        ctx=ctx,
    )
    headers = _json_headers("https://auth.openai.com/email-verification")
    if sentinel:
        headers["openai-sentinel-token"] = sentinel

    resp = ctx.session.post(
        "https://auth.openai.com/api/accounts/email-otp/validate",
        json={"code": code},
        headers=headers,
        timeout=20,
    )
    try:
        data = resp.json()
    except Exception:
        data = {"text": resp.text[:500]}
    ok = resp.status_code == 200
    ctx.step(f"{ctx.tag}验证码校验", console.green("ok") if ok else console.red(str(resp.status_code)))
    if not ok:
        ctx.warn(f"{ctx.tag}验证码校验失败: {str(data)[:220]}")
    return ok, data


def complete_email_verification(ctx: RegistrationContext) -> bool:
    if not ctx.otp_not_before_ms:
        ctx.otp_not_before_ms = int(time.time() * 1000)
    code = wait_for_verification_code(ctx, timeout=ctx.email_otp_timeout())
    if not code:
        ctx.err(f"{ctx.tag}未能获取验证码")
        return False

    time.sleep(random.uniform(0.3, 0.8))
    ok, _ = validate_otp(ctx, code)
    if ok:
        ctx.remember_email_code(code)
        return True

    ctx.remember_email_code(code)
    ctx.warn(f"{ctx.tag}验证码失败，尝试重发")
    if not send_otp(ctx):
        return False

    time.sleep(random.uniform(1.0, 2.0))
    code = wait_for_verification_code(ctx, timeout=ctx.email_otp_timeout(retry=True))
    if not code:
        ctx.err(f"{ctx.tag}重试后仍未获取验证码")
        return False

    time.sleep(random.uniform(0.3, 0.8))
    ok, _ = validate_otp(ctx, code)
    if not ok:
        ctx.remember_email_code(code)
        ctx.err(f"{ctx.tag}验证码重试后仍失败")
        return False
    ctx.remember_email_code(code)
    return True


def submit_profile(ctx: RegistrationContext) -> bool:
    rand_name = re.sub(r"[^A-Za-z ]", "", random_name()).strip()
    rand_birthdate = random_birthdate()
    ctx.step(f"{ctx.tag}身份信息", f"{rand_name}  {rand_birthdate}")

    # 使用新的 flow 名称
    flow_name = "oauth_create_account"
    sentinel = build_sentinel_token(
        ctx.session,
        ctx.device_id,
        flow=flow_name,
        impersonate=ctx.active_imp or ctx.chosen_imp or "chrome",
        ctx=ctx,
    )
    if not sentinel:
        ctx.err(f"{ctx.tag}{flow_name} sentinel 生成失败")
        return False

    headers = _json_headers("https://auth.openai.com/about-you")
    headers["oai-device-id"] = ctx.device_id
    headers["openai-sentinel-token"] = sentinel

    # 如果缓存中有 so-token，一并带上
    so_token = ctx.pop_sentinel_so_token(flow_name)
    if so_token:
        headers["openai-sentinel-so-token"] = so_token

    resp = ctx.session.post(
        "https://auth.openai.com/api/accounts/create_account",
        json={"name": rand_name, "birthdate": rand_birthdate},
        headers=headers,
        timeout=20,
    )
    try:
        data = resp.json()
    except Exception:
        data = {"text": resp.text[:500]}
    ok = resp.status_code == 200
    ctx.step(f"{ctx.tag}账户创建", console.green("ok") if ok else console.red(str(resp.status_code)))
    if not ok:
        ctx.err(f"{ctx.tag}账户创建失败: {str(data)[:220]}")
        return False
    ctx.callback_url = str(
        data.get("continue_url")
        or data.get("url")
        or data.get("redirect_url")
        or _resolve_location(resp)
        or ""
    ).strip()
    return True


def visit_callback(ctx: RegistrationContext) -> bool:
    if not ctx.callback_url:
        ctx.warn(f"{ctx.tag}未返回 callback URL，跳过回访")
        return False
    resp = ctx.session.get(
        ctx.callback_url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
        },
        allow_redirects=True,
        timeout=30,
    )
    ctx.set_final_url(str(resp.url or ctx.callback_url or ""))
    ok = resp.status_code < 500
    ctx.step(f"{ctx.tag}Callback", console.green(str(resp.status_code)) if ok else console.red(str(resp.status_code)))
    if ctx.final_url:
        ctx.info(f"{ctx.tag}注册回访最终 URL: {ctx.final_url}")
    return ok

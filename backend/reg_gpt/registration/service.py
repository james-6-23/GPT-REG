import random
import time
from typing import Any, Optional

from reg_gpt.registration.context import build_context
from reg_gpt.registration.network import check_network, establish_signup_session, prepare_identity, prepare_initial_session
from reg_gpt.registration.oauth_finish import complete_oauth, try_reuse_registration_session
from reg_gpt.registration.signup import (
    complete_email_verification,
    register_account_password,
    send_otp,
    submit_profile,
    visit_callback,
)
from reg_gpt.registration.sentinel_helper import preload_sentinel_tokens


def _complete_signup(ctx) -> bool:
    final_path = ctx.final_path or ""
    need_otp = False

    # 确保密码在所有分支都已生成（OAuth password/verify 需要用到）
    if not ctx.reg_password:
        import secrets as _secrets
        import string as _string
        base_pwd = _secrets.token_urlsafe(12)
        ctx.reg_password = base_pwd + random.choice(_string.ascii_uppercase) + random.choice(_string.digits) + random.choice("!@#$%^&*")

    if "create-account/password" in final_path:
        ctx.info(f"{ctx.tag}检测到全新注册流程")
        time.sleep(random.uniform(0.5, 1.0))
        if not register_account_password(ctx):
            return False
        time.sleep(random.uniform(0.3, 0.8))
        if not send_otp(ctx):
            return False
        need_otp = True
    elif "email-verification" in final_path or "email-otp" in final_path:
        ctx.info(f"{ctx.tag}检测到 OTP 验证阶段")
        need_otp = True
    elif "about-you" in final_path:
        ctx.info(f"{ctx.tag}检测到填写资料阶段")
    elif "callback" in final_path or "chatgpt.com" in (ctx.final_url or ""):
        ctx.info(f"{ctx.tag}账号已完成注册")
        return True
    else:
        ctx.warn(f"{ctx.tag}未知跳转，按完整注册流程兜底: {ctx.final_url}")
        if not register_account_password(ctx):
            return False
        if not send_otp(ctx):
            return False
        need_otp = True

    if need_otp:
        if not complete_email_verification(ctx):
            return False

    time.sleep(random.uniform(0.5, 1.5))
    if not submit_profile(ctx):
        return False
    time.sleep(random.uniform(0.2, 0.5))
    visit_callback(ctx)
    return True


def run_registration(
    *,
    proxy: Optional[str],
    provider: dict[str, Any],
    poller: Any = None,
    tag: str = "",
    wid: int = 0,
    otp_wait_timeout_seconds: int = 120,
    otp_retry_wait_timeout_seconds: int = 60,
) -> tuple[Optional[str], str, str]:
    provider_data = dict(provider or {})
    ctx = build_context(
        proxy=proxy,
        provider=provider_data,
        worker_url=str(provider_data.get("worker_url") or "").strip(),
        email_domain=str(provider_data.get("email_domain") or "").strip(),
        api_secret=str(provider_data.get("api_secret") or "").strip(),
        poller=poller,
        tag=tag,
        wid=wid,
        otp_wait_timeout_seconds=otp_wait_timeout_seconds,
        otp_retry_wait_timeout_seconds=otp_retry_wait_timeout_seconds,
    )
    prepare_initial_session(ctx)
    preload_sentinel_tokens(ctx)

    if not check_network(ctx):
        return None, "", ""

    if not prepare_identity(ctx):
        return None, "", ""

    try:
        from reg_gpt.config import load_or_create_config
        cfg = load_or_create_config()
        oauth_cfg = cfg.get("oauth") or {}
        if oauth_cfg.get("mock", False):
            ctx.info(f"{ctx.tag}检测到 OAuth Mock 模式，跳过真实注册流程")
            from reg_gpt.oauth import submit_callback_url
            token_json = submit_callback_url(callback_url="", expected_state="", code_verifier="", mock=True)
            return token_json, "mock@example.com", "mock_password"

        if not establish_signup_session(ctx):
            return None, ctx.email, ""

        if not _complete_signup(ctx):
            return None, ctx.email, ctx.reg_password

        # 强制走完整 OAuth 流程以产出 id_token / refresh_token
        # token_json = try_reuse_registration_session(ctx)
        # if not token_json:
        token_json = complete_oauth(ctx)

        # 质量控制：丢弃缺少 refresh_token 的半成品账号
        if token_json:
            import json as _json
            try:
                _parsed = _json.loads(token_json)
                if not _parsed.get("refresh_token"):
                    ctx.warn(f"{ctx.tag}Token 缺少 refresh_token，判定为死号，丢弃不保存")
                    return None, ctx.email, ctx.reg_password
            except Exception:
                pass

        return (token_json or None), ctx.email, ctx.reg_password
    except Exception as exc:
        err_str = str(exc)
        if "(35)" in err_str or "TLS" in err_str or "OPENSSL" in err_str:
            ctx.err(f"{ctx.tag}运行时 TLS 错误（已重试全部机会）: {exc}")
        else:
            ctx.err(f"{ctx.tag}运行时发生错误: {exc}")
        return None, ctx.email, ctx.reg_password

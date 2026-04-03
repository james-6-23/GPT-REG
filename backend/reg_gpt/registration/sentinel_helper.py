import json
import os
import time
from typing import List, Optional

try:
    from playwright.sync_api import sync_playwright
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False

from reg_gpt.registration.context import RegistrationContext

# 默认需要预取的 Sentinel Flow 列表 (包含冗余以应对流程中的多次验证与重试)
DEFAULT_FLOWS = [
    "authorize_continue",
    "authorize_continue",
    "username_password_create",
    "password_verify",
    "password_verify",
    "password_verify",
    "password_verify",
    "oauth_create_account",
]

# 核心配置：使用 OpenAI 最新的 Sentinel SDK 地址与 Frame URL
SDK_URL = os.environ.get("SDK_URL", "https://sentinel.openai.com/sentinel/20260219f9f6/sdk.js").strip()
FRAME_URL = os.environ.get("FRAME_URL", "https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=20260219f9f6").strip()
UA = os.environ.get("UA", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36").strip()


def preload_sentinel_tokens(ctx: RegistrationContext, flows: Optional[List[str]] = None) -> bool:
    """
    使用 Playwright 模拟浏览器运行 Sentinel SDK，一次性预取多个 Flow 的 Token。
    同步浏览器产生的 Cookies 到请求 Session 中，确保会话一致性。
    """
    if not _HAS_PLAYWRIGHT:
        ctx.info(f"{ctx.tag}Playwright 未安装，跳过 Sentinel 预取（将使用传统模式生成）")
        return False

    target_flows = flows or DEFAULT_FLOWS
    proxy_server = ctx.proxy or ""

    # 核心修复：确保 Playwright 的 UA 与 curl_cffi 的 impersonate 版本对齐
    browser_ua = UA
    if hasattr(ctx, "fp") and ctx.fp.get("impersonate"):
        imp = ctx.fp["impersonate"]
        ver = "".join(filter(str.isdigit, imp))
        if ver and imp.startswith("chrome"):
            browser_ua = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver}.0.0.0 Safari/537.36"

    ctx.info(f"{ctx.tag}启动 Sentinel 预取助手 (flows={target_flows})")

    try:
        with sync_playwright() as p:
            launch_args = {"headless": True}
            if proxy_server:
                launch_args["proxy"] = {"server": proxy_server}

            browser = p.chromium.launch(**launch_args)
            context = browser.new_context(
                user_agent=browser_ua,
                locale="en-US",
                viewport={"width": 1920, "height": 1080}
            )
            page = context.new_page()

            page.goto(FRAME_URL, wait_until="load", timeout=60000)
            ctx.info(f"{ctx.tag}等待 Sentinel SDK 环境初始化 (12s)...")
            page.wait_for_timeout(12000)
            page.wait_for_function("() => !!window.SentinelSDK", timeout=30000)

            result = page.evaluate(
                """async (flows) => {
                    const out = {
                        userAgent: navigator.userAgent,
                        flowResults: [],
                    };
                    if (!window.SentinelSDK) throw new Error('SentinelSDK missing');
                    for (const flow of flows) {
                        try {
                            await window.SentinelSDK.init(flow);
                            const tok = await window.SentinelSDK.token(flow);
                            let soTok = null;
                            try {
                                soTok = await window.SentinelSDK.sessionObserverToken(flow);
                            } catch (e) {}
                            out.flowResults.push({
                                flow: flow,
                                token: tok ? JSON.parse(tok) : null,
                                soToken: soTok ? JSON.parse(soTok) : null,
                            });
                        } catch (e) {}
                    }
                    return out;
                }""",
                target_flows
            )

            final_ua = result.get("userAgent") or browser_ua
            ctx.session.headers["User-Agent"] = final_ua

            try:
                if "Chrome/" in final_ua:
                    full_ver = final_ua.split("Chrome/")[1].split(" ")[0]
                    major_ver = full_ver.split(".")[0]
                    ctx.session.headers["Sec-CH-UA"] = f'"Chromium";v="{major_ver}", "Google Chrome";v="{major_ver}", "Not_A Brand";v="24"'
                    if hasattr(ctx, "fp"):
                        ctx.fp["browser_ver"] = major_ver
                        ctx.fp["chrome_ver"] = major_ver
            except:
                pass

            browser_cookies = context.cookies()
            for cookie in browser_cookies:
                c_name = cookie["name"]
                if c_name == "oai-did" or "sentinel" in cookie["domain"] or ".openai.com" in cookie["domain"]:
                     ctx.session.cookies.set(
                        c_name,
                        cookie["value"],
                        domain=cookie["domain"],
                        path=cookie["path"]
                    )

            flow_results = result.get("flowResults", [])
            updated_device_id = False

            for item in flow_results:
                flow = item.get("flow")
                token_obj = item.get("token")
                if token_obj:
                    token_id = token_obj.get("id")
                    if not updated_device_id and token_id:
                        if ctx.device_id != token_id:
                            ctx.info(f"{ctx.tag}同步 Device ID: {token_id}")
                            ctx.device_id = token_id
                            for domain in ("chatgpt.com", ".auth.openai.com", "auth.openai.com"):
                                ctx.session.cookies.set("oai-did", ctx.device_id, domain=domain)
                        updated_device_id = True

                    # 以列表形式存储以支持多次调用
                    if flow not in ctx.sentinel_tokens:
                        ctx.sentinel_tokens[flow] = []
                    ctx.sentinel_tokens[flow].append(json.dumps(token_obj, separators=(",", ":")))

                so_token_obj = item.get("soToken")
                if so_token_obj:
                    if flow not in ctx.sentinel_so_tokens:
                        ctx.sentinel_so_tokens[flow] = []
                    ctx.sentinel_so_tokens[flow].append(json.dumps(so_token_obj, separators=(",", ":")))

            total_tokens = sum(len(v) for v in ctx.sentinel_tokens.values())
            if total_tokens > 0:
                ctx.info(f"{ctx.tag}Sentinel 预取完成，获取 {total_tokens} 个令牌")
                return True
            else:
                ctx.warn(f"{ctx.tag}Sentinel 预取助手未获得任何令牌")
                return False

    except Exception as e:
        ctx.warn(f"{ctx.tag}Sentinel 预取助手运行出错: {str(e)}")
        import traceback
        ctx.warn(traceback.format_exc())
        return False
    finally:
        try:
            if 'browser' in locals():
                browser.close()
        except:
            pass

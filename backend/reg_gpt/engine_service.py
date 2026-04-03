import os
from dataclasses import dataclass
from typing import Any, Optional

import reg_gpt.console as console
from reg_gpt.config import RUNTIME_LOG_PATH, SCRIPT_DIR, ensure_runtime_layout, load_or_create_config, normalize_config
from reg_gpt.email_registry import choose_email_provider, get_enabled_email_providers
from reg_gpt.poller import CodePoller
from reg_gpt.register_flow import run_registration
from reg_gpt.runner import run_parallel, run_sequential
from reg_gpt.runtime_state import initialize_runtime, mark_runtime_stopped
from reg_gpt.storage import save_token_result

ENTRY_SCRIPT = os.path.join(SCRIPT_DIR, "openai_reg.py")
LOG_FILE = RUNTIME_LOG_PATH
ensure_runtime_layout()


@dataclass(frozen=True)
class RuntimeSettings:
    raw_config: dict[str, Any]
    proxy: Optional[str]
    sleep_min: int
    sleep_max: int
    max_success: int
    workers: int
    once: bool


class RegistrationEngine:
    def __init__(self, settings: RuntimeSettings) -> None:
        self.settings = settings
        self._poller: Optional[Any] = None

    def run(self, proxy: Optional[str], tag: str = "", wid: int = 0) -> tuple[Optional[str], str, str]:
        provider = choose_email_provider(self.settings.raw_config)
        if not provider:
            msg = f"{tag}未找到可用邮箱提供方，请检查“邮箱设置”"
            if wid > 0:
                console.wlog(wid, console.red(f"[Error] {msg}"))
            else:
                console.print_err(msg)
            return None, "", ""
        email_cfg = self.settings.raw_config.get("email") or {}
        otp_cfg = email_cfg.get("otp") or {}
        return run_registration(
            proxy=proxy,
            provider=provider,
            poller=self._poller,
            tag=tag,
            wid=wid,
            otp_wait_timeout_seconds=int(otp_cfg.get("wait_timeout_seconds") or 120),
            otp_retry_wait_timeout_seconds=int(otp_cfg.get("retry_wait_timeout_seconds") or 60),
        )

    def start_parallel_runtime(self, proxy: Optional[str], workers: int) -> dict:
        providers = get_enabled_email_providers(self.settings.raw_config)
        proxies: Any = None
        if proxy:
            proxies = {"http": proxy, "https": proxy}

        self._poller = None
        if len(providers) == 1 and str((providers[0] or {}).get("type") or "").strip().lower() == "cloudflare":
            provider = providers[0]
            self._poller = CodePoller(
                worker_url=str((provider or {}).get("worker_url") or "").strip(),
                api_secret=str((provider or {}).get("api_secret") or "").strip(),
                proxies=proxies,
                wait_logger=lambda wid, line: console.wlog(wid, line),
            )

        logger = console.DashboardLogger(workers=workers)
        console.set_logger(logger)
        logger.start()
        return {"logger": logger, "poller": self._poller}

    def stop_parallel_runtime(self, runtime_ctx: dict) -> None:
        poller = runtime_ctx.get("poller")
        logger = runtime_ctx.get("logger")
        if poller:
            poller.stop()
        if logger:
            logger.stop()
        self._poller = None
        console.set_logger(None)


def load_runtime_settings() -> RuntimeSettings:
    cfg = normalize_config(load_or_create_config())

    net_cfg = cfg.get("network") or {}
    run_cfg = cfg.get("run") or {}

    raw_proxy = str(net_cfg.get("proxy", "")).strip() if net_cfg.get("enabled", True) else ""
    proxy = (raw_proxy if "://" in raw_proxy else f"http://{raw_proxy}") if raw_proxy else None

    enabled_providers = get_enabled_email_providers(cfg)
    if not enabled_providers:
        console.print_warn("当前没有启用可用邮箱提供方，注册流程将无法成功开始")

    return RuntimeSettings(
        raw_config=cfg,
        proxy=proxy,
        sleep_min=max(1, int(run_cfg.get("sleep_min", 5))),
        sleep_max=max(max(1, int(run_cfg.get("sleep_min", 5))), int(run_cfg.get("sleep_max", 30))),
        max_success=max(0, int(run_cfg.get("max_success", 0))),
        workers=max(1, int(run_cfg.get("workers", 1))),
        once=bool(run_cfg.get("once", False)),
    )


def execute_runtime(settings: RuntimeSettings) -> None:
    engine = RegistrationEngine(settings)
    mode = f"parallel x{settings.workers}" if settings.workers > 1 else "sequential"

    initialize_runtime(
        pid=os.getpid(),
        mode=mode,
        workers_target=settings.workers,
        max_success=settings.max_success,
        once=settings.once,
        proxy=settings.proxy or "直连",
        sleep_min=settings.sleep_min,
        sleep_max=settings.sleep_max,
        entry_script=ENTRY_SCRIPT,
        log_file=LOG_FILE,
    )

    try:
        console.print_banner(settings.raw_config)

        if settings.workers > 1:
            run_parallel(
                proxy=settings.proxy,
                workers=settings.workers,
                sleep_min=settings.sleep_min,
                sleep_max=settings.sleep_max,
                max_success=settings.max_success,
                once=settings.once,
                run_func=lambda p, tag, wid: engine.run(p, tag=tag, wid=wid),
                save_func=save_token_result,
                on_parallel_start=engine.start_parallel_runtime,
                on_parallel_stop=engine.stop_parallel_runtime,
            )
        else:
            run_sequential(
                proxy=settings.proxy,
                sleep_min=settings.sleep_min,
                sleep_max=settings.sleep_max,
                max_success=settings.max_success,
                once=settings.once,
                run_func=lambda p: engine.run(p),
                save_func=save_token_result,
            )
        mark_runtime_stopped(0, "主程序执行完成")
    except KeyboardInterrupt:
        mark_runtime_stopped(130, "主程序被中断")
        raise
    except Exception as exc:
        mark_runtime_stopped(1, f"主程序异常退出: {exc}")
        raise

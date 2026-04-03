import queue
import threading
import time
from typing import Any, Dict, List, Optional

from .config import load_or_create_config, normalize_config
from .codex_proxy_client import CodexProxyClient, CodexProxyClientError

_sync_queue: queue.Queue[Dict[str, str]] = queue.Queue()
_sync_worker: Optional[threading.Thread] = None
_sync_worker_lock = threading.Lock()


class CodexProxyServiceError(RuntimeError):
    pass


def _load_config(force_reload: bool = False) -> Dict[str, Any]:
    return normalize_config(load_or_create_config(force_reload=force_reload))


def _build_client(force_reload: bool = False) -> CodexProxyClient:
    cfg = _load_config(force_reload=force_reload)
    cp_cfg = cfg.get("codex_proxy") or {}
    if not cp_cfg.get("enabled"):
        raise CodexProxyServiceError("CodexProxy 未启用")
    base_url = str(cp_cfg.get("base_url") or "").strip()
    admin_key = str(cp_cfg.get("admin_key") or "").strip()
    if not base_url or not admin_key:
        raise CodexProxyServiceError("请先在配置中心填写 CodexProxy 连接信息")
    net_cfg = cfg.get("network") or {}
    proxy = str(cp_cfg.get("upload_proxy_url") or "").strip()
    if not proxy and net_cfg.get("enabled"):
        proxy = str(net_cfg.get("proxy") or "").strip()
    return CodexProxyClient(
        base_url=base_url,
        admin_key=admin_key,
        timeout=int(cp_cfg.get("timeout") or 15),
        proxy=proxy or None,
    )


def test_codex_proxy_connection(force_reload: bool = False) -> Dict[str, Any]:
    client = _build_client(force_reload=force_reload)
    return client.test_connection()


def list_codex_proxy_accounts(force_reload: bool = False) -> List[Dict[str, Any]]:
    client = _build_client(force_reload=force_reload)
    return client.list_accounts()


def upload_single_account(
    *,
    name: str,
    refresh_token: str,
    proxy_url: str = "",
    force_reload: bool = False,
) -> Dict[str, Any]:
    client = _build_client(force_reload=force_reload)
    return client.upload_account(name=name, refresh_token=refresh_token, proxy_url=proxy_url)


def upload_batch_accounts(
    *,
    refresh_tokens: str,
    name_prefix: str = "reg",
    proxy_url: str = "",
    force_reload: bool = False,
) -> Dict[str, Any]:
    client = _build_client(force_reload=force_reload)
    return client.upload_accounts_batch(
        refresh_tokens=refresh_tokens,
        name_prefix=name_prefix,
        proxy_url=proxy_url,
    )


def delete_codex_proxy_account(name: str, force_reload: bool = False) -> Dict[str, Any]:
    client = _build_client(force_reload=force_reload)
    return client.delete_account(name)


# ─── 后台自动同步队列 ───


def enqueue_codex_proxy_sync(name: str, refresh_token: str) -> None:
    """注册成功后调用，将单个 RT 入队等待上传。"""
    if not name or not refresh_token:
        return
    cfg = _load_config(force_reload=False)
    cp_cfg = cfg.get("codex_proxy") or {}
    if not cp_cfg.get("enabled") or not cp_cfg.get("auto_sync_on_success"):
        return
    if not str(cp_cfg.get("base_url") or "").strip() or not str(cp_cfg.get("admin_key") or "").strip():
        return
    _sync_queue.put({"name": name, "refresh_token": refresh_token})
    _ensure_sync_worker()


def _ensure_sync_worker() -> None:
    global _sync_worker
    with _sync_worker_lock:
        if _sync_worker and _sync_worker.is_alive():
            return
        _sync_worker = threading.Thread(target=_sync_worker_loop, name="reg-gpt-codex-proxy-sync", daemon=True)
        _sync_worker.start()


def _sync_worker_loop() -> None:
    while True:
        item = _sync_queue.get()
        try:
            client = _build_client(force_reload=True)
            cfg = _load_config(force_reload=False)
            cp_cfg = cfg.get("codex_proxy") or {}
            proxy_url = str(cp_cfg.get("upload_proxy_url") or "").strip()
            client.upload_account(
                name=item["name"],
                refresh_token=item["refresh_token"],
                proxy_url=proxy_url,
            )
        except Exception:
            pass
        finally:
            _sync_queue.task_done()

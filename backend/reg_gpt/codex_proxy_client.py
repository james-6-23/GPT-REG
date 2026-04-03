import json
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

from curl_cffi import requests as curl_requests


class CodexProxyClientError(RuntimeError):
    pass


def normalize_codex_proxy_url(raw_url: str) -> str:
    """归一化 CodexProxy 地址，确保指向 /api/admin 路径。"""
    value = str(raw_url or "").strip().rstrip("/")
    if not value:
        return ""
    if "://" not in value:
        value = f"http://{value}"
    parsed = urlparse(value)
    path = (parsed.path or "").rstrip("/")
    # 自动补全路径
    if not path or path == "/":
        path = "/api/admin"
    elif path.endswith("/accounts"):
        path = path[: -len("/accounts")]
    if not path.endswith("/api/admin"):
        if "/api/admin" not in path:
            path = path.rstrip("/") + "/api/admin"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


class CodexProxyClient:
    def __init__(
        self,
        *,
        base_url: str,
        admin_key: str,
        timeout: int = 15,
        proxy: Optional[str] = None,
    ) -> None:
        self.base_url = normalize_codex_proxy_url(base_url)
        self.admin_key = str(admin_key or "").strip()
        self.timeout = max(1, int(timeout or 15))
        self.proxy = str(proxy or "").strip() or None

        if not self.base_url:
            raise CodexProxyClientError("CodexProxy base_url 不能为空")
        if not self.admin_key:
            raise CodexProxyClientError("CodexProxy admin_key 不能为空")

    @property
    def accounts_url(self) -> str:
        return f"{self.base_url}/accounts"

    def _session(self):
        session = curl_requests.Session()
        if self.proxy:
            session.proxies = {"http": self.proxy, "https": self.proxy}
        return session

    def _headers(self) -> Dict[str, str]:
        return {
            "X-Admin-Key": self.admin_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, url: str, **kwargs):
        session = self._session()
        try:
            return session.request(
                method=method.upper(),
                url=url,
                timeout=self.timeout,
                verify=False,
                **kwargs,
            )
        except Exception as exc:
            raise CodexProxyClientError(str(exc)) from exc
        finally:
            try:
                session.close()
            except Exception:
                pass

    def test_connection(self) -> Dict[str, Any]:
        """测试连接，获取账号列表。"""
        started = time.perf_counter()
        resp = self._request("GET", self.accounts_url, headers=self._headers())
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        if resp.status_code != 200:
            raise CodexProxyClientError(f"连接测试失败: HTTP {resp.status_code} - {(resp.text or '')[:240]}")

        try:
            data = resp.json()
        except Exception:
            data = {}

        accounts = []
        if isinstance(data, list):
            accounts = data
        elif isinstance(data, dict):
            accounts = data.get("accounts") or data.get("data") or data.get("items") or []

        return {
            "ok": True,
            "base_url": self.base_url,
            "remote_total": len(accounts) if isinstance(accounts, list) else 0,
            "response_time_ms": elapsed_ms,
            "message": "CodexProxy 连接正常",
        }

    def list_accounts(self) -> List[Dict[str, Any]]:
        resp = self._request("GET", self.accounts_url, headers=self._headers())
        if resp.status_code != 200:
            raise CodexProxyClientError(f"获取账号列表失败: HTTP {resp.status_code} - {(resp.text or '')[:240]}")
        try:
            data = resp.json()
        except Exception:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            items = data.get("accounts") or data.get("data") or data.get("items") or []
            return items if isinstance(items, list) else []
        return []

    def upload_account(
        self,
        *,
        name: str,
        refresh_token: str,
        proxy_url: str = "",
    ) -> Dict[str, Any]:
        """上传单个账号到 CodexProxy。"""
        payload = {
            "name": str(name or "").strip(),
            "refresh_token": str(refresh_token or "").strip(),
            "proxy_url": str(proxy_url or "").strip(),
        }
        if not payload["name"]:
            raise CodexProxyClientError("账号名不能为空")
        if not payload["refresh_token"]:
            raise CodexProxyClientError("refresh_token 不能为空")

        resp = self._request(
            "POST",
            self.accounts_url,
            headers=self._headers(),
            data=json.dumps(payload),
        )
        if resp.status_code not in {200, 201}:
            raise CodexProxyClientError(f"上传账号失败: HTTP {resp.status_code} - {(resp.text or '')[:240]}")

        return {
            "ok": True,
            "name": payload["name"],
            "status_code": resp.status_code,
        }

    def upload_accounts_batch(
        self,
        *,
        refresh_tokens: str,
        name_prefix: str = "reg",
        proxy_url: str = "",
    ) -> Dict[str, Any]:
        """批量上传：refresh_tokens 用换行分隔。"""
        lines = [line.strip() for line in refresh_tokens.strip().splitlines() if line.strip()]
        if not lines:
            raise CodexProxyClientError("refresh_tokens 不能为空")

        success = 0
        failed = 0
        results: List[Dict[str, Any]] = []

        for i, rt in enumerate(lines):
            name = f"{name_prefix}_{int(time.time())}_{i:03d}"
            try:
                result = self.upload_account(name=name, refresh_token=rt, proxy_url=proxy_url)
                success += 1
                results.append(result)
            except CodexProxyClientError as exc:
                failed += 1
                results.append({"ok": False, "name": name, "error": str(exc)})

        return {
            "total": len(lines),
            "success": success,
            "failed": failed,
            "results": results,
        }

    def delete_account(self, name: str) -> Dict[str, Any]:
        """删除单个账号。"""
        target = str(name or "").strip()
        if not target:
            raise CodexProxyClientError("账号名不能为空")
        resp = self._request(
            "DELETE",
            f"{self.accounts_url}/{target}",
            headers=self._headers(),
        )
        if resp.status_code not in {200, 204}:
            raise CodexProxyClientError(f"删除账号失败: HTTP {resp.status_code} - {(resp.text or '')[:240]}")
        return {"ok": True, "name": target}

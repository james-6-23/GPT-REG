import json
import os
import time
from typing import Any, Dict, Optional
from urllib.parse import quote, urlparse, urlunparse

from curl_cffi import requests as curl_requests


class CpaClientError(RuntimeError):
    pass


def normalize_management_url(raw_url: str) -> str:
    value = str(raw_url or "").strip()
    if not value:
        return ""

    parsed = urlparse(value)
    path = (parsed.path or "").rstrip("/")

    if path.endswith("/management.html"):
        path = path[: -len("/management.html")] + "/v0/management"
    elif path.endswith("/auth-files"):
        path = path[: -len("/auth-files")]
    elif path.endswith("/api-call"):
        path = path[: -len("/api-call")]

    normalized = urlunparse((parsed.scheme, parsed.netloc, path.rstrip("/"), "", "", ""))
    return normalized.rstrip("/")


class CpaClient:
    def __init__(
        self,
        *,
        management_url: str,
        management_token: str,
        timeout: int = 15,
        proxy: Optional[str] = None,
        verify: bool = False,
    ) -> None:
        self.management_url = normalize_management_url(management_url)
        self.management_token = str(management_token or "").strip()
        self.timeout = max(1, int(timeout or 15))
        self.proxy = str(proxy or "").strip() or None
        self.verify = bool(verify)

        if not self.management_url:
            raise CpaClientError("CPA management_url 不能为空")
        if not self.management_token:
            raise CpaClientError("CPA management_token 不能为空")

    @property
    def auth_files_url(self) -> str:
        return f"{self.management_url}/auth-files"

    @property
    def api_call_url(self) -> str:
        return f"{self.management_url}/api-call"

    def _session(self):
        session = curl_requests.Session()
        if self.proxy:
            session.proxies = {"http": self.proxy, "https": self.proxy}
        return session

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {"Authorization": f"Bearer {self.management_token}"}
        if extra:
            headers.update(extra)
        return headers

    def _request(self, method: str, url: str, **kwargs):
        session = self._session()
        try:
            resp = session.request(
                method=method.upper(),
                url=url,
                timeout=self.timeout,
                verify=self.verify,
                **kwargs,
            )
            return resp
        except Exception as exc:
            raise CpaClientError(str(exc)) from exc
        finally:
            try:
                session.close()
            except Exception:
                pass

    @staticmethod
    def _parse_json(resp) -> Dict[str, Any]:
        try:
            data = resp.json()
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def test_connection(self) -> Dict[str, Any]:
        started = time.perf_counter()
        resp = self._request("GET", self.auth_files_url, headers=self._headers())
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        if resp.status_code != 200:
            raise CpaClientError(f"测试失败: HTTP {resp.status_code} - {(resp.text or '')[:240]}")

        payload = self._parse_json(resp)
        files = payload.get("files", []) if isinstance(payload, dict) else []
        files = files if isinstance(files, list) else []

        return {
            "ok": True,
            "management_url": self.management_url,
            "auth_files_url": self.auth_files_url,
            "remote_total": len(files),
            "response_time_ms": elapsed_ms,
            "message": "CPA 站点连接正常",
        }

    def list_auth_files(self) -> list[Dict[str, Any]]:
        resp = self._request("GET", self.auth_files_url, headers=self._headers())
        if resp.status_code != 200:
            raise CpaClientError(f"获取 CPA 账号列表失败: HTTP {resp.status_code} - {(resp.text or '')[:240]}")
        payload = self._parse_json(resp)
        files = payload.get("files", []) if isinstance(payload, dict) else []
        return files if isinstance(files, list) else []

    def upload_auth_file(self, file_path: str, name: Optional[str] = None) -> Dict[str, Any]:
        path = os.path.abspath(file_path)
        if not os.path.exists(path):
            raise CpaClientError(f"待上传文件不存在: {path}")

        file_name = (name or os.path.basename(path)).strip()
        if not file_name.lower().endswith(".json"):
            file_name = f"{file_name}.json"

        with open(path, "rb") as fh:
            data = fh.read()

        target_url = f"{self.auth_files_url}?name={quote(file_name)}"
        resp = self._request(
            "POST",
            target_url,
            headers=self._headers({"Content-Type": "application/json"}),
            data=data,
        )
        if resp.status_code not in {200, 207}:
            raise CpaClientError(f"上传 CPA 失败: HTTP {resp.status_code} - {(resp.text or '')[:240]}")

        return {
            "ok": True,
            "name": file_name,
            "status_code": resp.status_code,
            "body": (resp.text or "")[:240],
        }

    def delete_auth_file(self, name: str) -> Dict[str, Any]:
        target_name = str(name or "").strip()
        if not target_name:
            raise CpaClientError("待删除账号名不能为空")

        target_url = f"{self.auth_files_url}?name={quote(target_name)}"
        resp = self._request("DELETE", target_url, headers=self._headers())
        if resp.status_code not in {200, 207}:
            raise CpaClientError(f"删除 CPA 账号失败: HTTP {resp.status_code} - {(resp.text or '')[:240]}")

        return {"ok": True, "name": target_name, "status_code": resp.status_code}

    def patch_auth_file_status(self, name: str, disabled: bool) -> Dict[str, Any]:
        resp = self._request(
            "PATCH",
            f"{self.auth_files_url}/status",
            headers=self._headers({"Content-Type": "application/json"}),
            json={"name": str(name or "").strip(), "disabled": bool(disabled)},
        )
        if resp.status_code != 200:
            raise CpaClientError(f"更新 CPA 账号启停失败: HTTP {resp.status_code} - {(resp.text or '')[:240]}")
        return {"ok": True, "name": name, "disabled": bool(disabled)}

    def patch_auth_file_fields(
        self,
        *,
        name: str,
        priority: Optional[int] = None,
        note: Optional[str] = None,
        prefix: Optional[str] = None,
        proxy_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"name": str(name or "").strip()}
        if priority is not None:
            payload["priority"] = int(priority)
        if note is not None:
            payload["note"] = str(note)
        if prefix is not None:
            payload["prefix"] = str(prefix)
        if proxy_url is not None:
            payload["proxy_url"] = str(proxy_url)

        resp = self._request(
            "PATCH",
            f"{self.auth_files_url}/fields",
            headers=self._headers({"Content-Type": "application/json"}),
            json=payload,
        )
        if resp.status_code != 200:
            raise CpaClientError(f"更新 CPA 账号字段失败: HTTP {resp.status_code} - {(resp.text or '')[:240]}")
        return {"ok": True, "name": name}

    def api_call(
        self,
        *,
        auth_index: str,
        method: str,
        url: str,
        header: Optional[Dict[str, str]] = None,
        data: str = "",
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload = {
            "auth_index": str(auth_index or "").strip(),
            "method": str(method or "GET").strip().upper(),
            "url": str(url or "").strip(),
            "header": dict(header or {}),
            "data": data or "",
        }
        if not payload["auth_index"]:
            raise CpaClientError("api_call 缺少 auth_index")
        if not payload["url"]:
            raise CpaClientError("api_call 缺少 url")

        session = self._session()
        try:
            resp = session.request(
                method="POST",
                url=self.api_call_url,
                headers=self._headers({"Content-Type": "application/json"}),
                json=payload,
                timeout=max(1, int(timeout or self.timeout)),
                verify=self.verify,
            )
        except Exception as exc:
            raise CpaClientError(str(exc)) from exc
        finally:
            try:
                session.close()
            except Exception:
                pass

        if resp.status_code != 200:
            raise CpaClientError(f"CPA api_call 失败: HTTP {resp.status_code} - {(resp.text or '')[:240]}")

        payload_resp = self._parse_json(resp)
        return {
            "status_code": int(payload_resp.get("status_code") or 0),
            "header": payload_resp.get("header") or {},
            "body": str(payload_resp.get("body") or ""),
        }

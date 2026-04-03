import threading
import time
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote

from curl_cffi import requests


class CodePoller:
    _POLL_INTERVAL = 2.0
    _MAX_ROUNDS = 70
    _INIT_WAIT = 5.0

    def __init__(
        self,
        *,
        worker_url: str,
        api_secret: str = "",
        proxies: Any = None,
        wait_logger: Optional[Callable[[int, str], None]] = None,
    ):
        self._worker_url = str(worker_url or "").strip()
        self._api_secret = str(api_secret or "").strip()
        self._proxies = proxies
        self._wait_logger = wait_logger
        self._lock = threading.Lock()
        self._pending: Dict[str, threading.Event] = {}
        self._results: Dict[str, str] = {}
        self._reg_time: Dict[str, float] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def register(self, email: str) -> None:
        ev = threading.Event()
        with self._lock:
            self._pending[email] = ev
            self._reg_time[email] = time.time()

    def wait(self, email: str, wid: int = 0, wait_message: str = "") -> str:
        with self._lock:
            ev = self._pending.get(email)
        if ev is None:
            return ""
        timeout = self._INIT_WAIT + self._MAX_ROUNDS * self._POLL_INTERVAL + 10
        if self._wait_logger and wait_message:
            self._wait_logger(wid, wait_message)
        ev.wait(timeout=timeout)
        with self._lock:
            code = self._results.pop(email, "")
            self._pending.pop(email, None)
        return code

    def stop(self) -> None:
        self._stop.set()

    def _poll_loop(self) -> None:
        headers: Dict[str, str] = {}
        if self._api_secret:
            headers["Authorization"] = f"Bearer {self._api_secret}"

        rounds: Dict[str, int] = {}
        err_count: Dict[str, int] = {}

        while not self._stop.is_set():
            with self._lock:
                now = time.time()
                emails = [
                    email for email, ev in self._pending.items()
                    if not ev.is_set() and now - self._reg_time.get(email, now) >= self._INIT_WAIT
                ]

            for email in emails:
                poll_url = f"{self._worker_url}?email={quote(email)}"
                delete_url = f"{self._worker_url}?email={quote(email)}&delete=1"
                current_round = rounds.get(email, 0)

                if current_round >= self._MAX_ROUNDS:
                    with self._lock:
                        self._results[email] = ""
                        ev = self._pending.get(email)
                    if ev:
                        ev.set()
                    rounds.pop(email, None)
                    err_count.pop(email, None)
                    continue

                try:
                    resp = requests.get(
                        poll_url,
                        headers=headers,
                        proxies=self._proxies,
                        impersonate="chrome",
                        timeout=12,
                    )
                    err_count[email] = 0
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("status") == "success":
                            code = str(data.get("code") or "").strip()
                            if code:
                                try:
                                    requests.get(
                                        delete_url,
                                        headers=headers,
                                        proxies=self._proxies,
                                        impersonate="chrome",
                                        timeout=8,
                                    )
                                except Exception:
                                    pass
                                with self._lock:
                                    self._results[email] = code
                                    ev = self._pending.get(email)
                                if ev:
                                    ev.set()
                                rounds.pop(email, None)
                                err_count.pop(email, None)
                                continue
                except Exception:
                    err_count[email] = err_count.get(email, 0) + 1

                rounds[email] = rounds.get(email, 0) + 1

            time.sleep(self._POLL_INTERVAL)

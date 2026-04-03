import queue
import re
import shutil
import sys
import threading
import time
from typing import Dict, List, Optional

from reg_gpt.email_registry import describe_email_provider, get_enabled_email_providers
from reg_gpt.runtime_state import append_event, update_worker_slot

USE_COLOR = sys.stdout.isatty()
print_lock = threading.Lock()
_logger = None


def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def green(value: str) -> str:
    return c(value, "92")


def red(value: str) -> str:
    return c(value, "91")


def yellow(value: str) -> str:
    return c(value, "93")


def cyan(value: str) -> str:
    return c(value, "96")


def gray(value: str) -> str:
    return c(value, "90")


def bold(value: str) -> str:
    return c(value, "1")


def dim(value: str) -> str:
    return c(value, "2")


def separator(char: str = "─", width: int = 60) -> str:
    return gray(char * width)


def tty_width() -> int:
    return max(60, shutil.get_terminal_size((100, 30)).columns)


def print_banner(cfg: dict) -> None:
    net_cfg = cfg.get("network") or {}
    proxy_val = net_cfg.get("proxy") or ""
    proxy_enabled = bool(net_cfg.get("enabled", True)) and bool(proxy_val)
    workers = (cfg.get("run") or {}).get("workers", 1)
    max_suc = (cfg.get("run") or {}).get("max_success", 0)
    providers = get_enabled_email_providers(cfg)
    domain = " / ".join(describe_email_provider(provider) for provider in providers) or "未启用"
    proxy_str = proxy_val if proxy_enabled else "直连"
    mode_str = f"并行 ×{workers}" if workers > 1 else "单线程"
    target_str = str(max_suc) if max_suc > 0 else "∞"

    print(separator())
    print(bold(cyan("  OpenAI 自动注册器")))
    print(separator())
    print(f"  {dim('邮箱通道')}  {domain}")
    print(f"  {dim('代    理')}  {proxy_str}")
    print(f"  {dim('运行模式')}  {mode_str}")
    print(f"  {dim('目标数量')}  {target_str}")
    print(separator())
    print()


def print_notice(msg: str) -> None:
    line = f"{yellow('[提示]')} {msg}"
    append_event(strip_ansi(line))
    print(line)


def print_ok(msg: str) -> None:
    line = f"{green('[✓]')} {msg}"
    append_event(strip_ansi(line))
    print(line)


def print_fail(msg: str) -> None:
    line = f"{red('[✗]')} {msg}"
    append_event(strip_ansi(line))
    print(line)


def print_info(msg: str) -> None:
    line = f"{cyan('[·]')} {msg}"
    append_event(strip_ansi(line))
    print(line)


def print_warn(msg: str) -> None:
    line = f"{yellow('[!]')} {msg}"
    append_event(strip_ansi(line))
    print(line)


def print_err(msg: str) -> None:
    line = f"{red('[Error]')} {msg}"
    append_event(strip_ansi(line))
    print(line)


def print_step(label: str, value: str) -> None:
    line = f"  {dim(label):20s}  {value}"
    update_worker_slot(1, line=strip_ansi(line))
    print(line)


ANSI_ESCAPE = re.compile(r"\033\[[0-9;]*m")


def strip_ansi(value: str) -> str:
    return ANSI_ESCAPE.sub("", value)


class DashboardLogger:
    _STEP_LINES = 3
    _TAIL_LINES = 10

    def __init__(self, workers: int):
        self._workers = workers
        self._parallel = workers > 1
        self._slots: Dict[int, List[str]] = {wid: [] for wid in range(1, workers + 1)}
        self._tail: List[str] = []
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._drawn = False
        self._fixed_lines = workers * (1 + self._STEP_LINES) + 1 + self._TAIL_LINES

    def start(self) -> None:
        if not self._parallel:
            return
        self._thread = threading.Thread(target=self._render_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._parallel:
            return
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def log(self, wid: int, line: str) -> None:
        update_worker_slot(wid, line=strip_ansi(line))
        if not self._parallel:
            with print_lock:
                print(line)
            return
        self._queue.put(("slot", wid, line))

    def event(self, line: str) -> None:
        append_event(strip_ansi(line))
        if not self._parallel:
            with print_lock:
                print(line)
            return
        self._queue.put(("tail", None, line))

    def notice(self, line: str) -> None:
        append_event(strip_ansi(line))
        if not self._parallel:
            with print_lock:
                print(line)
            return
        self._queue.put(("notice", None, line))

    def _render_loop(self) -> None:
        while not self._stop.is_set():
            changed = False
            try:
                while True:
                    kind, wid, line = self._queue.get_nowait()
                    self._apply(kind, wid, line)
                    changed = True
            except queue.Empty:
                pass
            if changed:
                self._redraw()
            time.sleep(0.12)

        try:
            while True:
                kind, wid, line = self._queue.get_nowait()
                self._apply(kind, wid, line)
        except queue.Empty:
            pass
        self._redraw()

    def _apply(self, kind: str, wid: Optional[int], line: str) -> None:
        if kind == "slot":
            if wid not in self._slots:
                return
            buf = self._slots[wid]
            buf.append(strip_ansi(line)[:tty_width() - 2])
            if len(buf) > self._STEP_LINES:
                buf.pop(0)
        elif kind in ("tail", "notice"):
            self._tail.append(strip_ansi(line)[:tty_width() - 2])
            if len(self._tail) > self._TAIL_LINES:
                self._tail.pop(0)

    def _redraw(self) -> None:
        width = tty_width()
        lines: List[str] = []
        for wid in sorted(self._slots.keys()):
            header = c(f"── W{wid} " + "─" * max(0, width - 6 - len(str(wid))), "90")
            lines.append(header)
            rows = self._slots[wid]
            for index in range(self._STEP_LINES):
                lines.append(" " + rows[index] if index < len(rows) else "")

        lines.append(c("─" * width, "90"))
        tail = self._tail[-self._TAIL_LINES:]
        for index in range(self._TAIL_LINES):
            lines.append(tail[index] if index < len(tail) else "")

        buf = []
        if self._drawn:
            buf.append(f"\033[{self._fixed_lines}A")
        for row in lines:
            buf.append(f"\033[2K{row}\n")

        sys.stdout.write("".join(buf))
        sys.stdout.flush()
        self._drawn = True


def set_logger(logger: Optional[DashboardLogger]) -> None:
    global _logger
    _logger = logger


def get_logger() -> Optional[DashboardLogger]:
    return _logger


def wlog(wid: int, line: str) -> None:
    logger = get_logger()
    if logger:
        logger.log(wid, line)
    else:
        update_worker_slot(wid, line=strip_ansi(line))
        with print_lock:
            print(line)


def wevent(line: str) -> None:
    logger = get_logger()
    if logger:
        logger.event(line)
    else:
        append_event(strip_ansi(line))
        with print_lock:
            print(line)

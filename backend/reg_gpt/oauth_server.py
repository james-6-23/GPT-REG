import http.server
import json
import socket
import threading
import time
import urllib.parse
from typing import Any, Dict, Optional

import reg_gpt.console as console

_CODE_STORE: Dict[str, str] = {}
_STORE_LOCK = threading.Lock()
_SERVER_INSTANCE: Optional['CallbackHTTPServer'] = None


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        # 统一使用 console.wlog 以保持 UI 优雅
        msg = format % args
        console.wlog(1, f"{console.dim('[OAuth Server]')} {msg}")

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/auth/callback":
            query = urllib.parse.parse_qs(parsed.query)
            code = query.get("code", [""])[0]
            state = query.get("state", [""])[0]

            if code and state:
                with _STORE_LOCK:
                    _CODE_STORE[state] = code
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("<h1>授权成功</h1><p>您可以关闭此窗口并回到程序。</p>".encode("utf-8"))
                return

        self.send_response(404)
        self.end_headers()


class CallbackHTTPServer(http.server.HTTPServer):
    def __init__(self, server_address, RequestHandlerClass):
        super().__init__(server_address, RequestHandlerClass)
        self.is_ready = False


def probe_port(host: str, port: int) -> bool:
    """探测端口是否可用。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def start_callback_server(host: str = "127.0.0.1", port: int = 1455) -> bool:
    """启动 OAuth 回调服务器。"""
    global _SERVER_INSTANCE

    if _SERVER_INSTANCE:
        return True

    if not probe_port(host, port):
        console.wlog(1, f"{console.red('[Error]')} OAuth 端口 {port} 已被占用，无法启动回调服务。")
        return False

    def run_server():
        global _SERVER_INSTANCE
        try:
            _SERVER_INSTANCE = CallbackHTTPServer((host, port), CallbackHandler)
            _SERVER_INSTANCE.is_ready = True
            console.wlog(1, f"{console.green('[OAuth Server]')} 监听已就绪: http://{host}:{port}/auth/callback")
            _SERVER_INSTANCE.serve_forever()
        except Exception as e:
            console.wlog(1, f"{console.red('[OAuth Server]')} 异常退出: {e}")
            _SERVER_INSTANCE = None

    thread = threading.Thread(target=run_server, daemon=True, name="OAuthServer")
    thread.start()

    # 显式等待监听成功
    for i in range(10):
        if _SERVER_INSTANCE and _SERVER_INSTANCE.is_ready:
            return True
        time.sleep(0.5)

    return False


def get_callback_code(state: str, timeout: int = 300) -> Optional[str]:
    """阻塞等待指定 state 的 callback code。"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        with _STORE_LOCK:
            if state in _CODE_STORE:
                return _CODE_STORE.pop(state)
        time.sleep(1)
    return None


def stop_callback_server():
    """停止回调服务器。"""
    global _SERVER_INSTANCE
    if _SERVER_INSTANCE:
        _SERVER_INSTANCE.shutdown()
        _SERVER_INSTANCE.server_close()
        _SERVER_INSTANCE = None
        console.wlog(1, f"{console.dim('[OAuth Server]')} 服务已停止。")

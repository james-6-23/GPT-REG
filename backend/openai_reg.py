"""
Reg-GPT 唯一对外主入口。

默认启动带登录鉴权的 WebUI；
WebUI 在内部拉起注册引擎时，也会回调本文件的内部参数模式，
不再额外暴露“另一个主程序”。
"""

import argparse
import sys


def _setup_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reg-GPT 主程序入口")
    parser.add_argument("--runtime-child", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> None:
    _setup_stdio()
    args = parse_args()
    if args.runtime_child:
        from reg_gpt.config import load_or_create_config
        from reg_gpt.oauth_server import start_callback_server

        cfg = load_or_create_config()
        oauth_cfg = cfg.get("oauth") or {}
        if oauth_cfg.get("enabled", True):
            start_callback_server(
                host=oauth_cfg.get("host", "127.0.0.1"),
                port=oauth_cfg.get("port", 1455)
            )

        from reg_gpt.engine import main as engine_main

        engine_main()
        return

    from reg_gpt.webgui.app import main as webui_main

    webui_main()


if __name__ == "__main__":
    main()

"""
Reg-GPT 注册执行引擎。

这是主程序内部使用的运行模块，由 `openai_reg.py --runtime-child`
触发；真正的配置解析、运行编排与状态收口在 `engine_service.py`。
"""

from reg_gpt.engine_service import execute_runtime, load_runtime_settings


def main() -> None:
    settings = load_runtime_settings()
    execute_runtime(settings)

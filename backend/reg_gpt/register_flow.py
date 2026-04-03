"""
兼容层：保留原 `reg_gpt.register_flow.run_registration` 导出，
实际实现已经拆分到 `reg_gpt.registration.*`。
"""

import os

os.environ.setdefault("SSLKEYLOGFILE", "")
os.environ.setdefault("CURL_SSL_BACKEND", "openssl")

from reg_gpt.registration.service import run_registration

__all__ = ["run_registration"]

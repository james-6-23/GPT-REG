import time


def add_tls_retry(session, max_retries: int = 4, base_delay: float = 1.5):
    """给 curl_cffi Session 实例注入 TLS 自动重试。"""
    original = session.request

    def patched(method, url, **kwargs):
        for attempt in range(max_retries):
            try:
                return original(method, url, **kwargs)
            except Exception as exc:
                err = str(exc)
                is_tls = "(35)" in err or "TLS" in err or "OPENSSL" in err
                if is_tls and attempt < max_retries - 1:
                    time.sleep(base_delay * (1.5 ** attempt))
                    continue
                raise

    session.request = patched
    return session


def raw_tls_request(fn, *args, max_retries: int = 4, base_delay: float = 1.5, **kwargs):
    """对不通过 Session 的独立请求函数加 TLS 重试。"""
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            err = str(exc)
            is_tls = "(35)" in err or "TLS" in err or "OPENSSL" in err
            if is_tls and attempt < max_retries - 1:
                time.sleep(base_delay * (1.5 ** attempt))
                continue
            raise

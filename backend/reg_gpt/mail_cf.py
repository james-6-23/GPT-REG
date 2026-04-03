import random
import string
import time
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote

from curl_cffi import requests


FIRST_NAMES = [
    "james", "john", "robert", "michael", "william", "david", "richard", "joseph",
    "thomas", "charles", "emma", "olivia", "ava", "isabella", "sophia", "mia",
    "charlotte", "amelia", "harper", "evelyn", "liam", "noah", "oliver", "elijah",
    "lucas", "mason", "logan", "ethan", "aiden", "jackson", "emily", "abigail",
    "ella", "scarlett", "grace", "chloe", "victoria", "riley", "aria", "lily",
]

LAST_NAMES = [
    "smith", "johnson", "williams", "brown", "jones", "garcia", "miller", "davis",
    "wilson", "taylor", "anderson", "thomas", "jackson", "white", "harris", "martin",
    "thompson", "young", "robinson", "lewis", "walker", "hall", "allen", "king",
    "wright", "scott", "green", "baker", "adams", "nelson", "carter", "mitchell",
]


def random_name() -> str:
    first = random.choice(FIRST_NAMES).capitalize()
    last = random.choice(LAST_NAMES).capitalize()
    return f"{first} {last}"


def random_birthdate() -> str:
    year = random.randint(1990, 2003)
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    return f"{year}-{month:02d}-{day:02d}"


def build_cf_email(email_domain: str) -> str:
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    suffix = random.randint(100, 99999)
    sep = random.choice(["", ".", "_"])
    extra = "".join(random.choices(string.ascii_lowercase, k=2)) if random.random() < 0.3 else ""
    local = f"{first}{sep}{last}{extra}{suffix}"
    return f"{local}@{email_domain}"


def wait_for_cf_code(
    *,
    email: str,
    worker_url: str,
    api_secret: str = "",
    proxies: Any = None,
    tag: str = "",
    wid: int = 0,
    poller: Any = None,
    step_logger: Optional[Callable[[str, str], None]] = None,
    wait_logger: Optional[Callable[[int, str], None]] = None,
    dim: Optional[Callable[[str], str]] = None,
    green: Optional[Callable[[str], str]] = None,
    yellow: Optional[Callable[[str], str]] = None,
    red: Optional[Callable[[str], str]] = None,
    poll_attempts: int = 60,
    initial_wait_seconds: int = 5,
    poll_interval_seconds: int = 2,
    delete_on_success: bool = True,
    exclude_codes: Optional[set[str]] = None,
) -> str:
    excluded = {str(item).strip() for item in (exclude_codes or set()) if str(item).strip()}
    if poller is not None:
        wait_message = f"  {dim('等待验证码') if dim else '等待验证码'}  {dim(email) if dim else email}"
        return poller.wait(email, wid=wid, wait_message=wait_message)

    headers: Dict[str, str] = {}
    if api_secret:
        headers["Authorization"] = f"Bearer {api_secret}"

    poll_url = f"{worker_url}?email={quote(email)}"
    delete_url = f"{worker_url}?email={quote(email)}&delete=1"

    if step_logger:
        step_logger(f"{tag}验证码", f"等待邮件投递 ({initial_wait_seconds}s)...")
    time.sleep(max(0, int(initial_wait_seconds)))

    print(f"  {dim(f'{tag}轮询中') if dim else f'{tag}轮询中'}  ", end="", flush=True)
    err_count = 0

    for _ in range(max(1, int(poll_attempts))):
        print(dim("·") if dim else "·", end="", flush=True)
        try:
            resp = requests.get(
                poll_url,
                headers=headers,
                proxies=proxies,
                impersonate="chrome",
                timeout=15,
            )
            err_count = 0
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    code = str(data.get("code") or "").strip()
                    if code:
                        if code in excluded:
                            print(f"  {(yellow('旧验证码，继续等待') if yellow else '旧验证码，继续等待')}", end="", flush=True)
                            time.sleep(max(1, int(poll_interval_seconds)))
                            continue
                        print(f"  {(green(code) if green else code)}", flush=True)
                        if delete_on_success:
                            try:
                                requests.get(
                                    delete_url,
                                    headers=headers,
                                    proxies=proxies,
                                    impersonate="chrome",
                                    timeout=10,
                                )
                            except Exception:
                                pass
                        return code
        except Exception:
            err_count += 1
            if err_count >= 5:
                warn_text = yellow("Worker 连续请求失败，检查网络/代理") if yellow else "Worker 连续请求失败，检查网络/代理"
                print(f"\n  {warn_text}", end="", flush=True)
        time.sleep(max(1, int(poll_interval_seconds)))

    print(f"  {(red('超时，未收到验证码') if red else '超时，未收到验证码')}", flush=True)
    return ""

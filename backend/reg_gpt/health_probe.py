import json
from typing import Tuple

OPENAI_HEALTH_API_URL = "https://api.openai.com/v1/models"
CODEX_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
CODEX_ACCOUNTS_CHECK_URL = "https://chatgpt.com/backend-api/wham/accounts/check"
CODEX_PROBE_MODEL = "gpt-5.1-codex"


def parse_api_error(resp_text: str) -> Tuple[str, str]:
    code = ""
    msg = ""
    try:
        obj = json.loads(resp_text or "")
        err = obj.get("error") if isinstance(obj, dict) else None
        if isinstance(err, dict):
            code = str(err.get("code") or "").strip()
            msg = str(err.get("message") or "").strip()
    except Exception:
        pass
    return code, msg


def parse_detail_error(resp_text: str) -> Tuple[str, str]:
    code = ""
    msg = ""
    try:
        obj = json.loads(resp_text or "")
        if not isinstance(obj, dict):
            return "", ""

        detail = obj.get("detail")
        if isinstance(detail, dict):
            code = str(detail.get("code") or "").strip()
            msg = str(detail.get("message") or "").strip()
        elif isinstance(detail, str):
            msg = detail.strip()

        if not code:
            code = str(obj.get("code") or "").strip()

        if not msg:
            err = obj.get("error")
            if isinstance(err, dict):
                msg = str(err.get("message") or "").strip()
            elif isinstance(err, str):
                msg = err.strip()

        if not msg:
            msg = str(obj.get("message") or "").strip()
    except Exception:
        pass

    return code, msg


def should_delete_on_error(status_code: int, err_code: str, err_msg: str) -> bool:
    if status_code in {401, 423}:
        return True
    if status_code == 403 and err_code in {
        "unsupported_country_region_territory",
        "account_deactivated",
        "account_suspended",
        "access_terminated",
        "invalid_api_key",
    }:
        return True

    text = (err_code + " " + err_msg).lower()
    if "unsupported country" in text or "not supported" in text:
        return True
    if "invalid_api_key" in text or "invalid api key" in text:
        return True
    if any(
        key in text
        for key in (
            "deactivated",
            "suspended",
            "terminated",
            "disabled",
            "banned",
            "policy_violation",
            "violated",
            "abuse",
            "unauthorized",
        )
    ):
        return True

    return False


def classify_openai_probe(status_code: int, body_text: str) -> Tuple[str, int, str]:
    code = int(status_code or 0)
    txt = body_text or ""

    if code == 200:
        return "healthy", code, "ok"

    err_code, err_msg = parse_api_error(txt)

    if code == 429:
        return "limited", code, (err_code or "rate_limited")

    if should_delete_on_error(code, err_code, err_msg):
        label = err_code or "forbidden"
        if err_msg:
            label = f"{label}:{err_msg}"
        return "unusable", code, label

    if code >= 500:
        return "unknown", code, "server_error"

    if code in (400, 403):
        reason = err_code or "request_forbidden"
        if err_msg:
            reason = f"{reason}:{err_msg}"
        return "unknown", code, f"openai_models:{reason}"

    return "unknown", code, f"openai_models:unexpected_status:{code}"


def classify_codex_probe(label: str, status_code: int, body_text: str) -> Tuple[str, int, str]:
    code = int(status_code or 0)
    txt = body_text or ""

    if code == 200:
        return "healthy", code, f"{label}:ok"

    err_code, err_msg = parse_detail_error(txt)

    if code == 429:
        return "limited", code, (f"{label}:{err_code}" if err_code else f"{label}:rate_limited")

    if code == 401:
        reason = err_code or "unauthorized"
        if err_msg:
            reason = f"{reason}:{err_msg}"
        return "unusable", code, f"{label}:{reason}"

    if should_delete_on_error(code, err_code, err_msg):
        reason = err_code or "forbidden"
        if err_msg:
            reason = f"{reason}:{err_msg}"
        return "unusable", code, f"{label}:{reason}"

    low = (err_code + " " + err_msg).lower()
    if code == 403 and any(item in low for item in ("quota", "limit", "rate")):
        return "limited", code, (f"{label}:{err_code}" if err_code else f"{label}:limited")

    if code >= 500:
        return "unknown", code, f"{label}:server_error"

    reason = err_code or "request_forbidden"
    if err_msg:
        reason = f"{reason}:{err_msg}"
    return "unknown", code, f"{label}:{reason}"


def merge_auto_probe_results(
    openai_res: Tuple[str, int, str],
    codex_res: Tuple[str, int, str],
    *,
    prefer_codex: bool = False,
) -> Tuple[str, int, str]:
    order = [("openai", openai_res), ("codex", codex_res)]
    if prefer_codex:
        order = [("codex", codex_res), ("openai", openai_res)]

    first_name, first = order[0]
    second_name, second = order[1]

    if first[0] in ("healthy", "limited"):
        return first
    if second[0] in ("healthy", "limited"):
        return second

    if first[0] == "unusable" and second[0] == "unusable":
        return (
            "unusable",
            first[1] or second[1],
            f"auto_both_unusable:{first_name}:{first[2]}|{second_name}:{second[2]}",
        )

    if first[0] == "unusable" or second[0] == "unusable":
        return (
            "unknown",
            first[1] or second[1],
            f"auto_conflict:{first_name}:{first[2]}|{second_name}:{second[2]}",
        )

    return (
        "unknown",
        first[1] or second[1],
        f"auto_unknown:{first_name}:{first[2]}|{second_name}:{second[2]}",
    )

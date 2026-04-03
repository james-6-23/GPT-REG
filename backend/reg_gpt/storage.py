import csv
import json
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple

from .config import LEGACY_TOKEN_DIR, TOKEN_DIR, _copy_legacy_tree_if_needed, ensure_runtime_layout

OUTPUT_DIR = TOKEN_DIR
ACCOUNTS_CSV = os.path.join(OUTPUT_DIR, "accounts.csv")
CSV_FIELDS = [
    "email",
    "password",
    "account_id",
    "access_token",
    "refresh_token",
    "expired",
    "registered_at",
    "token_file",
    "cpa_sync_status",
    "cpa_remote_name",
    "cpa_synced_at",
    "cpa_sync_message",
]

_csv_lock = threading.Lock()
ensure_runtime_layout()
_copy_legacy_tree_if_needed(LEGACY_TOKEN_DIR, OUTPUT_DIR)
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _norm_path(value: str) -> str:
    return os.path.normcase(os.path.abspath(value or ""))


def _read_csv_unlocked() -> Tuple[List[str], List[Dict[str, str]]]:
    if not os.path.exists(ACCOUNTS_CSV):
        return list(CSV_FIELDS), []
    try:
        with open(ACCOUNTS_CSV, "r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            fields = list(reader.fieldnames or [])
            rows = [dict(row) for row in reader]
    except Exception:
        return list(CSV_FIELDS), []
    if not fields:
        fields = list(CSV_FIELDS)
    return fields, rows


def _merge_fields(fields: List[str], required_fields: List[str]) -> List[str]:
    merged = list(fields or [])
    for field in required_fields:
        if field not in merged:
            merged.append(field)
    return merged


def _write_csv_unlocked(fields: List[str], rows: List[Dict[str, str]]) -> None:
    with open(ACCOUNTS_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _ensure_csv_schema_unlocked() -> List[str]:
    fields, rows = _read_csv_unlocked()
    merged = _merge_fields(fields, list(CSV_FIELDS))
    if merged != fields:
        _write_csv_unlocked(merged, rows)
    return merged


def read_accounts_table() -> Tuple[List[str], List[Dict[str, str]]]:
    with _csv_lock:
        fields, rows = _read_csv_unlocked()
        return _merge_fields(fields, list(CSV_FIELDS)), rows


def write_accounts_table(fields: List[str], rows: List[Dict[str, str]]) -> None:
    with _csv_lock:
        merged = _merge_fields(fields, list(CSV_FIELDS))
        _write_csv_unlocked(merged, rows)


def update_account_row(token_file: str, updates: Dict[str, Any], fallback: Dict[str, Any] | None = None) -> None:
    target = _norm_path(token_file)
    if not target:
        return

    with _csv_lock:
        fields, rows = _read_csv_unlocked()
        fields = _merge_fields(fields, list(CSV_FIELDS))

        target_row: Dict[str, str] | None = None
        for row in rows:
            row_path = str(row.get("token_file") or "").strip()
            if row_path and _norm_path(row_path) == target:
                target_row = row
                break

        if target_row is None and fallback is not None:
            target_row = {field: "" for field in fields}
            rows.append(target_row)
            for key, value in (fallback or {}).items():
                if key not in fields:
                    fields.append(key)
                target_row[key] = "" if value is None else str(value)

        if target_row is None:
            return

        for key, value in (updates or {}).items():
            if key not in fields:
                fields.append(key)
            target_row[key] = "" if value is None else str(value)

        _write_csv_unlocked(fields, rows)


def append_csv(row: Dict[str, str]) -> None:
    with _csv_lock:
        fields = _ensure_csv_schema_unlocked()
        write_header = not os.path.exists(ACCOUNTS_CSV) or os.path.getsize(ACCOUNTS_CSV) == 0
        with open(ACCOUNTS_CSV, "a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerow(row)


def save_token_result(token_json: str, reg_email: str, reg_password: str) -> str:
    try:
        token_data = json.loads(token_json)
        fname_email = str(token_data.get("email", reg_email)).replace("@", "_")
    except Exception:
        token_data = {}
        fname_email = reg_email.replace("@", "_") or "unknown"

    subdirs = []
    for d in os.listdir(OUTPUT_DIR):
        if d.startswith("batch_") and os.path.isdir(os.path.join(OUTPUT_DIR, d)):
            subdirs.append(d)
    
    if not subdirs:
        batch_num = 1
    else:
        subdirs.sort()
        latest = subdirs[-1]
        try:
            batch_num = int(latest.split("_")[1])
            count = sum(1 for f in os.listdir(os.path.join(OUTPUT_DIR, latest)) if f.lower().endswith(".json"))
            if count >= 100:
                batch_num += 1
        except Exception:
            batch_num = len(subdirs) + 1

    batch_dir = os.path.join(OUTPUT_DIR, f"batch_{batch_num:03d}")
    os.makedirs(batch_dir, exist_ok=True)

    file_name = os.path.join(batch_dir, f"token_{fname_email}_{int(time.time())}.json")
    with open(file_name, "w", encoding="utf-8") as fh:
        fh.write(token_json)

    append_csv({
        "email": str(token_data.get("email", reg_email)),
        "password": reg_password,
        "account_id": str(token_data.get("account_id", "")),
        "access_token": str(token_data.get("access_token", "")),
        "refresh_token": str(token_data.get("refresh_token", "")),
        "expired": str(token_data.get("expired", "")),
        "registered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "token_file": file_name,
    })

    try:
        from .cpa_service import enqueue_sync_token_file

        enqueue_sync_token_file(file_name)
    except Exception:
        pass
    return os.path.basename(file_name)


def count_accounts_csv() -> int:
    if not os.path.exists(ACCOUNTS_CSV):
        return 0
    try:
        with open(ACCOUNTS_CSV, "r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            return sum(1 for _ in reader)
    except Exception:
        return 0


def recent_token_files(limit: int = 20) -> List[Dict[str, Any]]:
    if not os.path.isdir(OUTPUT_DIR):
        return []
    items: List[Dict[str, Any]] = []
    for root, _, files in os.walk(OUTPUT_DIR):
        for name in files:
            if not name.lower().endswith(".json"):
                continue
            path = os.path.join(root, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            items.append({
                "name": name,
                "path": path,
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            })
    items.sort(key=lambda item: item["modified_at"], reverse=True)
    return items[:limit]

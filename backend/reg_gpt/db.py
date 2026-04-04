"""
统一的 SQLite 状态存储，替代散落的 JSON 文件。

表结构：
  kv_store  — 通用键值存储（runtime_state / cpa_state / email_weights 等）

线程安全：使用 check_same_thread=False + 模块级锁。
"""

import json
import os
import sqlite3
import threading
from typing import Any, Dict, Optional

from reg_gpt.config import DB_PATH, ensure_runtime_layout

_db_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        ensure_runtime_layout()
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS kv_store (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '{}'
            )
        """)
        _conn.commit()
    return _conn


def get_state(key: str) -> Dict[str, Any]:
    """读取一个 JSON 状态对象。"""
    with _db_lock:
        conn = _get_conn()
        row = conn.execute("SELECT value FROM kv_store WHERE key = ?", (key,)).fetchone()
    if not row:
        return {}
    try:
        data = json.loads(row[0])
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def set_state(key: str, data: Dict[str, Any]) -> None:
    """写入一个 JSON 状态对象（整体覆盖）。"""
    value = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    with _db_lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO kv_store (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()


def update_state(key: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """部分更新：读取 → 合并 → 写入，返回合并后的完整数据。"""
    with _db_lock:
        conn = _get_conn()
        row = conn.execute("SELECT value FROM kv_store WHERE key = ?", (key,)).fetchone()
        try:
            current = json.loads(row[0]) if row else {}
            if not isinstance(current, dict):
                current = {}
        except Exception:
            current = {}
        current.update(updates)
        value = json.dumps(current, ensure_ascii=False, separators=(",", ":"))
        conn.execute(
            "INSERT INTO kv_store (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
        return dict(current)


def delete_state(key: str) -> None:
    """删除一个状态键。"""
    with _db_lock:
        conn = _get_conn()
        conn.execute("DELETE FROM kv_store WHERE key = ?", (key,))
        conn.commit()


def mutate_state(key: str, mutator) -> Dict[str, Any]:
    """原子读-改-写：mutator(data) 就地修改 data dict。"""
    with _db_lock:
        conn = _get_conn()
        row = conn.execute("SELECT value FROM kv_store WHERE key = ?", (key,)).fetchone()
        try:
            data = json.loads(row[0]) if row else {}
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        mutator(data)
        value = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        conn.execute(
            "INSERT INTO kv_store (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
        return dict(data)

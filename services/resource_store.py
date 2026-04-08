"""
SQLite 持久化层：记录上传资源、权限校验和链接分发历史。

表设计
======

resources
---------
  记录每次成功上传的资源。

  resource_id  TEXT    PRIMARY KEY   QURL 返回的 resource_id（如 rkrdrn7o79c）
  discord_id   TEXT    NOT NULL     上传人的 Discord 用户 ID
  discord_name TEXT    NOT NULL     上传人的 Discord 用户名（含 #Discriminator 或全局名）
  platform     TEXT    NOT NULL     "discord"
  created_at   TEXT    NOT NULL     ISO 8601 UTC 时间

  -- 上传时可选字段
  md5_hash     TEXT                  上传文件的 MD5（仅文件上传时）
  file_type    TEXT                  "file" 或 "google-map"
  embed_url    TEXT                  Google Maps embed iframe src（仅 google-map 时）

  -- 来自 API 的过期时间
  expires_at   TEXT                  ISO 8601 UTC，NULL 表示不过期


mint_links
----------
  记录所有通过 resource_id 分发出去的 QURL 链接。

  link_id      INTEGER  PRIMARY KEY AUTOINCREMENT
  resource_id  TEXT     NOT NULL     REFERENCES resources(resource_id)
  discord_id   TEXT     NOT NULL     申请人的 Discord 用户 ID
  discord_name TEXT     NOT NULL     申请人的 Discord 用户名
  qurl_link    TEXT     NOT NULL     生成的 QURL 短链接
  expires_at   TEXT                  本次生成的链接过期时间（来自 mint API）
  minted_at    TEXT     NOT NULL     ISO 8601 UTC 时间
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------

_DB_PATH: str = getattr(settings, "db_path", None) or "data/resources.db"


def _ensure_db_dir() -> None:
    p = Path(_DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 连接管理（线程安全：每线程独立连接）
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    _ensure_db_dir()
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------

INIT_SQL = """
CREATE TABLE IF NOT EXISTS resources (
    resource_id  TEXT    PRIMARY KEY,
    discord_id   TEXT    NOT NULL,
    discord_name TEXT    NOT NULL,
    platform     TEXT    NOT NULL DEFAULT 'discord',
    created_at   TEXT    NOT NULL,

    md5_hash     TEXT,
    file_type    TEXT,
    embed_url    TEXT,

    expires_at   TEXT
);

CREATE TABLE IF NOT EXISTS mint_links (
    link_id      INTEGER  PRIMARY KEY AUTOINCREMENT,
    resource_id  TEXT     NOT NULL,
    discord_id   TEXT     NOT NULL,
    discord_name TEXT     NOT NULL,
    qurl_link    TEXT     NOT NULL,
    expires_at   TEXT,
    minted_at    TEXT     NOT NULL,

    FOREIGN KEY (resource_id) REFERENCES resources(resource_id)
);

CREATE INDEX IF NOT EXISTS idx_mint_links_resource_id ON mint_links(resource_id);
CREATE INDEX IF NOT EXISTS idx_mint_links_discord_id  ON mint_links(discord_id);
"""


def init_db() -> None:
    """创建表结构（幂等，多次调用安全）。"""
    conn = _get_conn()
    try:
        conn.executescript(INIT_SQL)
        conn.commit()
        logger.info(f"[resource_store] Database initialized at {_DB_PATH}")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# resources 表操作
# ---------------------------------------------------------------------------

def record_resource(
    resource_id: str,
    discord_id: str,
    discord_name: str,
    *,
    md5_hash: Optional[str] = None,
    file_type: Optional[str] = None,
    embed_url: Optional[str] = None,
    expires_at: Optional[str] = None,
) -> bool:
    """
    记录一次成功的上传。

    INSERT OR IGNORE 保证已有记录不被覆盖（QURL 对相同文件
    会返回相同的 resource_id，不能用 REPLACE 覆盖掉原上传人）。
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = _get_conn()
    try:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO resources
                (resource_id, discord_id, discord_name, platform, created_at,
                 md5_hash, file_type, embed_url, expires_at)
            VALUES (?, ?, ?, 'discord', ?, ?, ?, ?, ?)
            """,
            (resource_id, discord_id, discord_name, now,
             md5_hash, file_type, embed_url, expires_at),
        )
        conn.commit()
        if cur.rowcount == 0:
            logger.info(
                f"[resource_store] Resource {resource_id} already recorded for "
                f"{discord_name} ({discord_id}), skipping."
            )
        else:
            logger.info(
                f"[resource_store] Recorded resource {resource_id} "
                f"by {discord_name} ({discord_id}), type={file_type}"
            )
        return True
    except sqlite3.Error as e:
        logger.error(f"[resource_store] Failed to record resource: {e}")
        return False
    finally:
        conn.close()


def get_resource(resource_id: str) -> Optional[dict]:
    """查询资源元数据，返回 dict 或 None。"""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM resources WHERE resource_id = ?",
            (resource_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def is_owner(resource_id: str, discord_id: str, discord_name: str) -> bool:
    """
    检查给定 Discord 用户是否为该资源的拥有人。

    同时匹配 discord_id 或 discord_name（双向兼容）。
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM resources WHERE resource_id = ? AND (discord_id = ? OR discord_name = ?)",
            (resource_id, discord_id, discord_name),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def is_expired(resource_id: str) -> tuple[bool, Optional[str]]:
    """
    检查资源是否已过期。

    Returns:
        (is_expired, expires_at_str)
        - expires_at 为 NULL → 不过期，返回 (False, None)
        - expires_at 已过 → 已过期，返回 (True, expires_at)
        - 未过期 → (False, expires_at)
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT expires_at FROM resources WHERE resource_id = ?",
            (resource_id,),
        ).fetchone()
        if not row:
            return True, None  # 资源不存在，视为已过期
        raw = row["expires_at"]
        if raw is None:
            return False, None  # 不过期
        try:
            exp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return False, raw  # 无法解析，当作未过期
        now = datetime.now(timezone.utc)
        return exp <= now, raw
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# mint_links 表操作
# ---------------------------------------------------------------------------

def record_mint_link(
    resource_id: str,
    discord_id: str,
    discord_name: str,
    qurl_link: str,
    *,
    expires_at: Optional[str] = None,
) -> bool:
    """记录一次 mint_link 生成的链接。"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT INTO mint_links
                (resource_id, discord_id, discord_name, qurl_link, expires_at, minted_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (resource_id, discord_id, discord_name, qurl_link, expires_at, now),
        )
        conn.commit()
        logger.info(
            f"[resource_store] Recorded mint link {qurl_link} "
            f"for {discord_name} ({discord_id}), resource={resource_id}"
        )
        return True
    except sqlite3.Error as e:
        logger.error(f"[resource_store] Failed to record mint link: {e}")
        return False
    finally:
        conn.close()


def get_mint_links_for_resource(resource_id: str) -> list[dict]:
    """查询某资源的所有 mint 记录（供调试/统计用）。"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM mint_links WHERE resource_id = ? ORDER BY minted_at DESC",
            (resource_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_resources_by_owner(discord_id: str, discord_name: str) -> list[dict]:
    """查询指定用户上传的所有资源（按 discord_id 或 discord_name 匹配）。"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT * FROM resources
            WHERE discord_id = ? OR discord_name = ?
            ORDER BY created_at DESC
            """,
            (discord_id, discord_name),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_resource(resource_id: str) -> tuple[bool, int, int]:
    """
    删除指定资源及其所有关联的 mint_links。

    Returns:
        (success, mint_links_deleted, resources_deleted)
        - mint_links_deleted: 删除的 mint_links 行数
        - resources_deleted: 删除的 resources 行数（通常是 0 或 1）
    """
    conn = _get_conn()
    try:
        cur_m = conn.execute(
            "DELETE FROM mint_links WHERE resource_id = ?",
            (resource_id,),
        )
        cur_r = conn.execute(
            "DELETE FROM resources WHERE resource_id = ?",
            (resource_id,),
        )
        conn.commit()
        logger.info(
            f"[resource_store] Deleted resource {resource_id}: "
            f"mint_links={cur_m.rowcount}, resources={cur_r.rowcount}"
        )
        return True, cur_m.rowcount, cur_r.rowcount
    except sqlite3.Error as e:
        logger.error(f"[resource_store] Failed to delete resource {resource_id}: {e}")
        return False, 0, 0
    finally:
        conn.close()

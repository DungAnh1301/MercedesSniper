# -*- coding: utf-8 -*-
"""
Quản lý lịch sử tải SQLite an toàn đa luồng (WAL mode), lưu đầy đủ tổng thời gian A->Z
(từ lúc bấm nút Tải Ngay -> Load link -> Tải mạng -> Ghép MP4 -> Hoàn thành).
"""
from datetime import datetime
import os
import re
import shutil
import sqlite3
import sys
import threading

if getattr(sys, "frozen", False):
    EXE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    BASE_DIR = os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
        "MercedesSniper_MaxSpeed",
    )
    os.makedirs(BASE_DIR, exist_ok=True)
    _legacy_dir = r"D:\soitobu_ubunto\webGUI"
    for _fn in ("sniper_config.json", "sniper_history.db"):
        _src = os.path.join(_legacy_dir, _fn)
        _dst = os.path.join(BASE_DIR, _fn)
        if os.path.isfile(_src) and not os.path.exists(_dst):
            try:
                shutil.copy2(_src, _dst)
            except Exception:
                pass
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    EXE_DIR = BASE_DIR

DB_PATH = os.path.join(BASE_DIR, "sniper_history.db")


def extract_video_id(url_or_id: str) -> str:
    if not url_or_id:
        return ""
    s = str(url_or_id).strip()
    if s.startswith("yt:video:"):
        return s.split("yt:video:")[-1][:11]
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", s):
        return s
    m = re.search(r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/|/live/)([a-zA-Z0-9_-]{11})", s)
    return m.group(1) if m else ""


def sanitize_filename(name: str, max_len: int = 110) -> str:
    if not name:
        return "youtube_video"
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name)).strip(" ._")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned[:max_len].rstrip(" ._")) or "youtube_video"


class HistoryStore:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=20)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    video_id TEXT NOT NULL,
                    video_url TEXT,
                    channel_name TEXT,
                    note TEXT,
                    video_title TEXT,
                    resolution TEXT DEFAULT '',
                    file_path TEXT,
                    size_mb REAL DEFAULT 0,
                    elapsed_sec REAL DEFAULT 0,
                    load_sec REAL DEFAULT 0,
                    dl_sec REAL DEFAULT 0,
                    mux_sec REAL DEFAULT 0,
                    speed_mbs REAL DEFAULT 0,
                    status TEXT DEFAULT 'completed',
                    error_msg TEXT DEFAULT '',
                    created_at TEXT,
                    UNIQUE(username, video_id)
                )
                """
            )
            for col_sql in (
                "ALTER TABLE downloads ADD COLUMN resolution TEXT DEFAULT ''",
                "ALTER TABLE downloads ADD COLUMN load_sec REAL DEFAULT 0",
                "ALTER TABLE downloads ADD COLUMN dl_sec REAL DEFAULT 0",
                "ALTER TABLE downloads ADD COLUMN mux_sec REAL DEFAULT 0",
            ):
                try:
                    conn.execute(col_sql)
                except sqlite3.OperationalError:
                    pass
            conn.commit()

    def has_downloaded(self, username: str, video_id: str) -> bool:
        if not video_id:
            return False
        u_key = (username or "local").lower()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "SELECT status FROM downloads WHERE username=? AND video_id=?",
                (u_key, video_id),
            )
            row = cur.fetchone()
            if not row:
                return False
            return row[0] in ("downloading", "waiting_hd", "preparing", "completed")

    def has_seen_record(self, username: str, video_id: str) -> bool:
        """Kiểm tra video này đã từng được ghi nhận (đã tải / đang hiện ra mắt lúc tắt / đã ẩn) chưa."""
        if not video_id:
            return False
        u_key = (username or "local").lower()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "SELECT 1 FROM downloads WHERE username=? AND video_id=? LIMIT 1",
                (u_key, video_id),
            )
            return cur.fetchone() is not None

    def mark_dismissed(self, username: str, video_id: str, video_url: str = "", channel_name: str = "", video_title: str = ""):
        if not video_id:
            return
        self.upsert_record(
            username=username,
            video_id=video_id,
            video_url=video_url,
            channel_name=channel_name,
            video_title=video_title,
            status="dismissed",
        )

    def upsert_record(
        self,
        username: str,
        video_id: str,
        video_url: str = "",
        channel_name: str = "",
        note: str = "",
        video_title: str = "",
        resolution: str = "",
        file_path: str = "",
        size_mb: float = 0.0,
        elapsed_sec: float = 0.0,
        load_sec: float = 0.0,
        dl_sec: float = 0.0,
        mux_sec: float = 0.0,
        speed_mbs: float = 0.0,
        status: str = "downloading",
        error_msg: str = "",
    ):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        u_key = (username or "local").lower()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO downloads (
                    username, video_id, video_url, channel_name, note,
                    video_title, resolution, file_path, size_mb,
                    elapsed_sec, load_sec, dl_sec, mux_sec, speed_mbs,
                    status, error_msg, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(username, video_id) DO UPDATE SET
                    video_url=CASE WHEN excluded.video_url != '' THEN excluded.video_url ELSE downloads.video_url END,
                    channel_name=CASE WHEN excluded.channel_name != '' THEN excluded.channel_name ELSE downloads.channel_name END,
                    note=CASE WHEN excluded.note != '' THEN excluded.note ELSE downloads.note END,
                    video_title=CASE WHEN excluded.video_title != '' THEN excluded.video_title ELSE downloads.video_title END,
                    resolution=CASE WHEN excluded.resolution != '' THEN excluded.resolution ELSE downloads.resolution END,
                    file_path=CASE WHEN excluded.file_path != '' THEN excluded.file_path ELSE downloads.file_path END,
                    size_mb=excluded.size_mb,
                    elapsed_sec=excluded.elapsed_sec,
                    load_sec=excluded.load_sec,
                    dl_sec=excluded.dl_sec,
                    mux_sec=excluded.mux_sec,
                    speed_mbs=excluded.speed_mbs,
                    status=excluded.status,
                    error_msg=excluded.error_msg,
                    created_at=excluded.created_at
                """,
                (
                    u_key,
                    video_id,
                    video_url,
                    channel_name,
                    note,
                    video_title,
                    resolution,
                    file_path,
                    round(float(size_mb or 0), 2),
                    round(float(elapsed_sec or 0), 2),
                    round(float(load_sec or 0), 2),
                    round(float(dl_sec or 0), 2),
                    round(float(mux_sec or 0), 2),
                    round(float(speed_mbs or 0), 2),
                    status,
                    error_msg,
                    now_str,
                ),
            )
            conn.commit()

    def get_recent(self, username: str, limit: int = 60) -> list[dict]:
        u_key = (username or "local").lower()
        with self._lock, self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT * FROM downloads WHERE username=? AND status != 'dismissed' ORDER BY id DESC LIMIT ?",
                (u_key, limit),
            )
            return [dict(r) for r in cur.fetchall()]

    def clear_non_completed(self, username: str) -> int:
        u_key = (username or "local").lower()
        with self._lock, self._connect() as conn:
            cur1 = conn.execute(
                "DELETE FROM downloads WHERE username=? AND status IN ('failed', 'cancelled')",
                (u_key,),
            )
            cur2 = conn.execute(
                "UPDATE downloads SET status='dismissed' WHERE username=? AND status IN ('missed', 'skipped')",
                (u_key,),
            )
            conn.commit()
            return (cur1.rowcount or 0) + (cur2.rowcount or 0)

    def get_dismissed_ids(self, username: str) -> set[str]:
        u_key = (username or "local").lower()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "SELECT video_id FROM downloads WHERE username=? AND status='dismissed'",
                (u_key,),
            )
            return {str(r[0]) for r in cur.fetchall() if r[0]}

    def dismiss_all_old_videos(self, username: str, extra_items: list[dict] | None = None) -> int:
        """Đánh dấu ẩn toàn bộ video cũ (đã tải xong / trên Server / lỗi / bỏ qua) để không tự hiện lại."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        u_key = (username or "local").lower()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE downloads
                SET status='dismissed'
                WHERE username=? AND status NOT IN ('downloading', 'waiting_hd', 'preparing', 'queued', 'merging')
                """,
                (u_key,),
            )
            cnt = cur.rowcount or 0
            if extra_items:
                rows = []
                for it in extra_items:
                    vid = str(it.get("video_id") or "").strip()
                    if not vid:
                        continue
                    rows.append(
                        (
                            u_key,
                            vid,
                            str(it.get("url") or ""),
                            str(it.get("channel") or ""),
                            str(it.get("note") or ""),
                            str(it.get("title") or ""),
                            "dismissed",
                            now_str,
                        )
                    )
                if rows:
                    conn.executemany(
                        """
                        INSERT INTO downloads (
                            username, video_id, video_url, channel_name, note,
                            video_title, status, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(username, video_id) DO UPDATE SET status='dismissed'
                        """,
                        rows,
                    )
                    cnt += len(rows)
            conn.commit()
            return cnt

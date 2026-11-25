# -*- coding: utf-8 -*-
"""
Client kết nối trực tiếp Pure Push 0ms tới VPS Soitube (soitobe.duckdns.org / 192.46.229.231).
- Tuyệt đối KHÔNG dùng RSS, KHÔNG qua Telegram:
  YouTube -> Google Webhook -> VPS RAM -> Ống TCP /api/pc/stream (0ms) -> App Desktop!
- Ngay khoảnh khắc nhận `video_detected` (0ms), kích hoạt Pre-fetch bóc sẵn luồng tải trước cả khi phân loại xong.
- Quản lý kênh đồng bộ trực tiếp với VPS (Thêm / Xóa / Sửa Note / Gia hạn Webhook).
"""
from datetime import datetime, timedelta, timezone
import json
import re
import threading
import time
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import requests

from core.history_store import extract_video_id

ICT_TZ = timezone(timedelta(hours=7))


def now_ict_str() -> str:
    return datetime.now(ICT_TZ).strftime("%Y-%m-%d %H:%M:%S")

DEFAULT_SERVER_URL = "http://soitobe.duckdns.org"
FALLBACK_VPS_IP = "192.46.229.231"


def build_candidate_base_urls(raw_url: str) -> list[str]:
    raw = (raw_url or DEFAULT_SERVER_URL).strip().rstrip("/")
    if not raw.startswith(("http://", "https://")):
        raw = "http://" + raw

    parsed = urlparse(raw)
    host = parsed.hostname or "soitobe.duckdns.org"

    if parsed.port:
        return [f"{parsed.scheme}://{host}:{parsed.port}"]

    candidates = []
    probe_list = [
        f"{parsed.scheme}://{host}",
        f"http://{host}:5000",
        f"https://{host}",
        f"http://{host}",
    ]
    if host.lower() == "soitobe.duckdns.org" and FALLBACK_VPS_IP:
        probe_list.extend([f"http://{FALLBACK_VPS_IP}", f"http://{FALLBACK_VPS_IP}:5000"])

    for u in probe_list:
        if u not in candidates:
            candidates.append(u)
    return candidates


class SoitubeVPSClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "MercedesSniperStudio/4.0-PurePush (Windows PC)"})
        self.base_url = DEFAULT_SERVER_URL
        self.username = ""
        self.password = ""
        self.full_name = ""
        self.sse_supported = True
        self.last_ping_ms = 0

        self._seen_lock = threading.Lock()
        self._seen_video_ids = set()
        self._pending_unknown_ids = {}

        self._stop_event = threading.Event()
        self._worker_thread = None

        # Callbacks -> Qt Signals
        self.on_status_change = None      # (connected: bool, status_text: str)
        self.on_ping_updated = None       # (ping_ms: int)
        self.on_video_prefetch = None     # (video_dict: dict) -> 0ms instant pre-extract!
        self.on_new_video = None          # (video_dict: dict) -> trigger download!
        self.on_server_videos = None      # (videos_list: list[dict]) -> display Server DB feed!
        self.on_channels_updated = None   # (channels_list: list[dict])
        self.on_auth_expired = None       # (reason_msg: str)
        self.on_log = None                # (msg: str)
        self._catchup_lock = threading.Lock()

    def _log(self, msg: str):
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception:
                pass

    def resolve_working_url(self, raw_url: str) -> tuple[bool, str]:
        candidates = build_candidate_base_urls(raw_url)
        last_err = None
        for cand in candidates:
            for probe_ep in ("/api/system_health", "/login"):
                try:
                    t0 = time.perf_counter()
                    r = self.session.get(f"{cand}{probe_ep}", timeout=4.0)
                    if r.status_code < 500:
                        self.last_ping_ms = int((time.perf_counter() - t0) * 1000)
                        self.base_url = cand
                        if self.on_ping_updated:
                            self.on_ping_updated(self.last_ping_ms)
                        return True, cand
                except Exception as e:
                    last_err = e
        return False, f"Không kết nối được máy chủ ({raw_url}): {last_err}"

    def login(self, server_url: str, username: str, password: str) -> tuple[bool, str]:
        username = (username or "").strip()
        password = (password or "").strip()
        if not username or not password:
            return False, "Vui lòng nhập đầy đủ Tài khoản và Mật khẩu!"

        self.session.cookies.clear()
        ok_net, net_info = self.resolve_working_url(server_url)
        if not ok_net:
            return False, net_info

        try:
            r = self.session.post(
                f"{self.base_url}/api/pc/login",
                json={"username": username, "password": password},
                timeout=8,
            )
            if r.status_code == 200:
                data = r.json()
                self.username = data.get("username", username)
                self.password = password
                self.full_name = data.get("full_name") or self.username
                self.sse_supported = bool(data.get("sse_supported", True))
                return True, f"Kết nối thành công ({self.last_ping_ms}ms)"
            if r.status_code == 401:
                return False, "Sai tài khoản hoặc mật khẩu Web Soitube!"
        except Exception:
            pass

        try:
            r_check = self.session.post(
                f"{self.base_url}/api/login",
                json={"username": username, "password": password},
                timeout=8,
            )
            if r_check.status_code == 401:
                return False, "Sai tài khoản hoặc mật khẩu Web Soitube!"
            if r_check.status_code != 200:
                return False, f"Máy chủ trả mã lỗi {r_check.status_code}!"

            r_form = self.session.post(
                f"{self.base_url}/login",
                data={"username": username, "password": password},
                allow_redirects=True,
                timeout=8,
            )
            if "/login" in r_form.url:
                return False, "Không khởi tạo được phiên đăng nhập!"

            self.username = username
            self.password = password
            self.full_name = username
            self.sse_supported = False
            return True, "Đăng nhập thành công!"
        except Exception as e:
            return False, f"Lỗi kết nối tới máy chủ: {e}"

    # ==========================================================
    # 📺 ĐỒNG BỘ & QUẢN LÝ KÊNH TRỰC TIẾP VỚI VPS
    # ==========================================================
    def fetch_my_channels(self) -> list[dict]:
        try:
            t0 = time.perf_counter()
            r = self.session.get(f"{self.base_url}/api/pc/my_channels", timeout=8)
            self.last_ping_ms = int((time.perf_counter() - t0) * 1000)
            if self.on_ping_updated:
                self.on_ping_updated(self.last_ping_ms)

            if r.status_code == 401:
                if self._try_relogin():
                    r = self.session.get(f"{self.base_url}/api/pc/my_channels", timeout=8)
                else:
                    return []
            if r.status_code == 200:
                channels = r.json().get("channels", [])
                if self.on_channels_updated:
                    self.on_channels_updated(channels)
                return channels
        except Exception:
            pass

        try:
            r = self.session.get(f"{self.base_url}/", allow_redirects=False, timeout=8)
            if r.status_code in (301, 302, 401):
                self._trigger_auth_expired("Phiên đăng nhập đã hết hạn!")
                return []
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                channels = []
                for tr in soup.select("table tbody tr"):
                    a_tag = tr.find("a", href=re.compile(r"youtube\.com/channel/"))
                    if not a_tag:
                        continue
                    m_cid = re.search(r"channel/(UC[a-zA-Z0-9_-]+)", a_tag.get("href", ""))
                    cid = m_cid.group(1) if m_cid else ""
                    cname = a_tag.get_text(strip=True)
                    img_tag = tr.find("img")
                    avatar = img_tag.get("src", "") if img_tag else ""
                    note_input = tr.find("input", class_="note-input")
                    note_val = note_input.get("value", "") if note_input else ""
                    row_id = 0
                    if note_input and note_input.get("id", "").startswith("note-"):
                        try:
                            row_id = int(note_input["id"].split("-")[1])
                        except ValueError:
                            pass
                    if cid:
                        channels.append(
                            {
                                "id": row_id,
                                "channel_id": cid,
                                "channel_name": cname,
                                "note": note_val,
                                "avatar_url": avatar,
                            }
                        )
                if self.on_channels_updated:
                    self.on_channels_updated(channels)
                return channels
        except Exception:
            pass
        return []

    def add_channel(self, url_or_handle: str, note: str = "") -> tuple[bool, str]:
        note_clean = (note or "").strip() or "PC_Sniper"
        try:
            r = self.session.post(
                f"{self.base_url}/api/pc/add_channel",
                json={"url": url_or_handle, "note": note_clean},
                timeout=15,
            )
            if r.status_code in (200, 201):
                data = r.json()
                if data.get("status") in ("success", "exists"):
                    self.fetch_my_channels()
                    return True, data.get("message", "Đã thêm kênh!")
                return False, data.get("message", "Không thể thêm kênh!")
            if r.status_code == 400:
                return False, (r.json() or {}).get("message", "Link kênh không hợp lệ!")
        except Exception as e:
            return False, f"Lỗi kết nối khi thêm kênh: {e}"

        try:
            self.session.post(
                f"{self.base_url}/add",
                data={"url": url_or_handle, "note": note_clean},
                timeout=15,
            )
            self.fetch_my_channels()
            return True, "Đã thêm kênh lên hệ thống!"
        except Exception as e:
            return False, f"Lỗi thêm kênh: {e}"

    def delete_channel(self, row_id: int, channel_id: str = "") -> tuple[bool, str]:
        try:
            r = self.session.post(
                f"{self.base_url}/api/pc/delete_channel",
                json={"id": row_id, "channel_id": channel_id},
                timeout=10,
            )
            if r.status_code == 200:
                self.fetch_my_channels()
                return True, (r.json() or {}).get("message", "Đã xóa kênh!")
        except Exception:
            pass
        if row_id:
            try:
                self.session.get(f"{self.base_url}/delete/{row_id}", timeout=10)
                self.fetch_my_channels()
                return True, "Đã xóa kênh!"
            except Exception as e:
                return False, f"Lỗi xóa kênh: {e}"
        return False, "Không xóa được kênh!"

    def update_channel_note(self, row_id: int, channel_id: str, new_note: str) -> tuple[bool, str]:
        try:
            r = self.session.post(
                f"{self.base_url}/api/pc/update_note",
                json={"id": row_id, "channel_id": channel_id, "note": new_note},
                timeout=8,
            )
            if r.status_code == 200:
                return True, "Đã lưu Note!"
        except Exception:
            pass
        try:
            r2 = self.session.post(
                f"{self.base_url}/update_channel_note",
                json={"id": row_id, "note": new_note},
                timeout=8,
            )
            if r2.status_code == 200:
                return True, "Đã cập nhật Note!"
        except Exception as e:
            return False, str(e)
        return False, "Không cập nhật được Note!"

    def renew_webhooks_only(self) -> tuple[bool, str]:
        for ep in ("/api/pc/sync_now", "/api/sync_now"):
            try:
                r = self.session.post(f"{self.base_url}{ep}", timeout=35)
                if r.status_code == 200:
                    d = r.json()
                    if d.get("status") == "success":
                        self.fetch_my_channels()
                        return True, f"Đã gia hạn Webhook Google cho {d.get('renewed', 0)} kênh!"
            except Exception:
                pass
        return False, "Không thể gia hạn Webhook lúc này!"

    # ==========================================================
    # ⚡ ỐNG ĐẨY TRỰC TIẾP PURE PUSH 0MS (/api/pc/stream)
    # ==========================================================
    def fetch_server_videos(self, limit: int = 50) -> list[dict]:
        """
        Tải danh sách các video gần nhất từ DB Server (`video_log`) của các kênh đang canh
        để hiển thị đầy đủ thông tin lên Tool PC (người dùng thích bài nào thì bấm nút Tải hoặc để đấy).
        """
        with self._catchup_lock:
            items: list[dict] = []
            got_ok = False
            try:
                t0 = time.perf_counter()
                r = requests.get(
                    f"{self.base_url}/api/pc/server_videos",
                    params={"limit": limit},
                    cookies=self.session.cookies,
                    headers=self.session.headers,
                    timeout=10,
                )
                self.last_ping_ms = int((time.perf_counter() - t0) * 1000)
                if self.on_ping_updated:
                    self.on_ping_updated(self.last_ping_ms)
                if r.status_code == 200:
                    data = r.json() or {}
                    if data.get("status") == "ok":
                        items = list(data.get("videos") or [])
                        got_ok = True
            except Exception:
                pass

            if not got_ok:
                try:
                    r_lat = requests.get(
                        f"{self.base_url}/api/latest_videos",
                        cookies=self.session.cookies,
                        headers=self.session.headers,
                        allow_redirects=False,
                        timeout=8,
                    )
                    if r_lat.status_code == 200:
                        lat_list = r_lat.json()
                        if isinstance(lat_list, list):
                            items = [
                                it
                                for it in reversed(lat_list)
                                if (it.get("v_type") or "").upper() in ("LONG", "SHORT")
                            ]
                except Exception:
                    pass

            with self._seen_lock:
                for it in items:
                    vid = it.get("video_id") or extract_video_id(it.get("url", ""))
                    if vid:
                        self._seen_video_ids.add(vid)

            if items and self.on_server_videos:
                self.on_server_videos(items)
            return items

    def start_watching(self):
        self.stop_watching()
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._watch_loop, daemon=True, name="PurePushStream")
        self._worker_thread.start()

    def stop_watching(self):
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.5)
        self._worker_thread = None

    def _trigger_auth_expired(self, msg: str):
        self._stop_event.set()
        if self.on_auth_expired:
            self.on_auth_expired(msg)

    def _emit_status(self, connected: bool, text: str):
        if self.on_status_change:
            self.on_status_change(connected, text)

    def _dispatch_video_ready(self, payload: dict):
        url = payload.get("url") or ""
        vid = extract_video_id(url)
        if not vid:
            return

        with self._seen_lock:
            if vid in self._seen_video_ids:
                return
            self._seen_video_ids.add(vid)

        self._log(
            f"⚡ [PUSH 0ms] Nhận video mới: [{payload.get('v_type', 'VIDEO')}] {payload.get('title', vid)}"
        )
        if self.on_new_video:
            self.on_new_video(dict(payload))

    def _try_relogin(self) -> bool:
        if not self.username or not self.password:
            return False
        ok, msg = self.login(self.base_url, self.username, self.password)
        if not ok and ("Sai tài khoản" in msg):
            self._trigger_auth_expired("Mật khẩu tài khoản đã thay đổi, vui lòng đăng nhập lại!")
            return False
        return ok

    def _on_connected_sync(self):
        self.fetch_my_channels()
        self.fetch_server_videos()

    def _watch_loop(self):
        while not self._stop_event.is_set():
            self._run_pure_push_stream()

    def _run_pure_push_stream(self):
        try:
            self._emit_status(True, f"Trực chiến Real-time ({self.last_ping_ms}ms)")
            with self.session.get(
                f"{self.base_url}/api/pc/stream",
                stream=True,
                timeout=(6, 35),
            ) as resp:
                if resp.status_code == 401:
                    self._try_relogin()
                    return

                event_name = "message"
                data_lines = []

                for raw_line in resp.iter_lines(chunk_size=256, decode_unicode=True):
                    if self._stop_event.is_set():
                        return
                    if raw_line is None:
                        continue
                    line = raw_line.strip("\r")

                    if line == "":
                        if data_lines:
                            raw_json = "\n".join(data_lines)
                            data_lines.clear()
                            try:
                                payload = json.loads(raw_json)
                                if event_name == "connected":
                                    threading.Thread(target=self._on_connected_sync, daemon=True).start()
                                elif event_name == "channels_updated":
                                    ch_list = payload.get("channels")
                                    if isinstance(ch_list, list):
                                        self._log(
                                            f"🔄 [PUSH 0ms] Đã đồng bộ danh sách kênh từ Web ({len(ch_list)} kênh)"
                                        )
                                        if self.on_channels_updated:
                                            self.on_channels_updated(ch_list)
                                    else:
                                        threading.Thread(target=self.fetch_my_channels, daemon=True).start()
                                elif event_name == "video_detected":
                                    # 0.00ms: Bóc sẵn link video ngay lập tức!
                                    if self.on_video_prefetch:
                                        self.on_video_prefetch(payload)
                                elif event_name == "video_ready":
                                    self._dispatch_video_ready(payload)
                            except Exception:
                                pass
                        event_name = "message"
                    elif line.startswith("event:"):
                        event_name = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line.split(":", 1)[1].strip())
                    elif line.startswith(": keepalive"):
                        pass

        except Exception as e:
            if not self._stop_event.is_set():
                self._log(f"⚠️ Mất ống Push ({e}), đang tự kết nối lại sau 2s...")
                self._emit_status(False, "Đang nối lại đường truyền...")
                self._stop_event.wait(2.0)
                self._try_relogin()

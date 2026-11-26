# -*- coding: utf-8 -*-
"""
TURBO MAX-SPEED DOWNLOADER ENGINE (Mercedes Sniper v3.0)
Giải quyết triệt để 5 nút thắt tốc độ tải YouTube:
1. Pre-Fetch 0ms + Single-Pass Extraction: Bóc tách `info` đúng 1 lần duy nhất, giữ cache giải mã chữ ký NodeJS.
2. Dual-Stream Parallel Pipeline: Kéo Video (16-32 luồng) & Audio (8 luồng) CÙNG MỘT LÚC thay vì tuần tự.
3. Multi-Range HTTP Chunk Engine + Parallel HLS Segment Engine: Bẻ khóa giới hạn băng thông cho cả HTTPS thường lẫn m3u8!
4. Tùy chọn IDM Bridge Mode (bắn qua StreamBridge nội bộ sang IDMan.exe không bao giờ dính lỗi 403).
5. Hỗ trợ Hủy tức thì (Cancel < 0.1s), Tải lại (Retry), Cookies YouTube, và tải Thumbnail hiển thị trực quan.
"""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urljoin
import urllib.request
import requests
from requests.adapters import HTTPAdapter
import yt_dlp

from core.history_store import BASE_DIR, EXE_DIR, HistoryStore, extract_video_id, sanitize_filename

YT_CACHE_DIR = os.path.join(BASE_DIR, ".yt_cache")
os.makedirs(YT_CACHE_DIR, exist_ok=True)

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)


class DownloadCancelledError(Exception):
    """Ném ra khi người dùng bấm nút Hủy (Cancel) trên giao diện."""


def find_ffmpeg_dir() -> str | None:
    meipass = getattr(sys, "_MEIPASS", None)
    candidates = []
    if meipass:
        candidates.extend(
            [
                os.path.join(meipass, "ffmpeg.exe"),
                os.path.join(meipass, "bin", "ffmpeg.exe"),
                os.path.join(meipass, "ffmpeg", "bin", "ffmpeg.exe"),
            ]
        )
    candidates.extend(
        [
            os.path.join(EXE_DIR, "ffmpeg", "bin", "ffmpeg.exe"),
            os.path.join(EXE_DIR, "bin", "ffmpeg.exe"),
            os.path.join(EXE_DIR, "ffmpeg.exe"),
            os.path.join(BASE_DIR, "ffmpeg", "bin", "ffmpeg.exe"),
            os.path.join(BASE_DIR, "bin", "ffmpeg.exe"),
            os.path.join(BASE_DIR, "ffmpeg.exe"),
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        ]
    )
    for c in candidates:
        if os.path.isfile(c):
            return os.path.dirname(c)
    in_path = shutil.which("ffmpeg")
    return os.path.dirname(in_path) if in_path else None


def find_js_runtime() -> tuple[str | None, str | None]:
    """Dò tự động `deno.exe` hoặc `node.exe` (ưu tiên bản đóng gói chìm / đặt cạnh .exe / hệ thống)."""
    meipass = getattr(sys, "_MEIPASS", None)
    search_roots = [r for r in (meipass, EXE_DIR, BASE_DIR) if r]
    for rt_name, exe_name in (("deno", "deno.exe"), ("node", "node.exe")):
        for root in search_roots:
            for rel in (exe_name, os.path.join("bin", exe_name)):
                p = os.path.join(root, rel)
                if os.path.isfile(p):
                    return rt_name, p
        in_path = shutil.which(rt_name)
        if in_path:
            return rt_name, in_path
    for c in (r"C:\Program Files\nodejs\node.exe", r"C:\Program Files (x86)\nodejs\node.exe"):
        if os.path.isfile(c):
            return "node", c
    return None, None


def find_nodejs_path() -> str | None:
    _, js_exe = find_js_runtime()
    return js_exe


def find_idm_exe() -> str | None:
    for c in (
        r"C:\Program Files (x86)\Internet Download Manager\IDMan.exe",
        r"C:\Program Files\Internet Download Manager\IDMan.exe",
    ):
        if os.path.isfile(c):
            return c
    return shutil.which("IDMan.exe")


_CACHED_SYSTEM_CAPS: dict | None = None


def _detect_impersonate_clients() -> set[str]:
    """Kiểm tra các profile giả lập chữ ký TLS trình duyệt thật (curl_cffi) sẵn có trong yt-dlp."""
    clients: set[str] = set()
    try:
        if not importlib.util.find_spec("curl_cffi"):
            return clients
        from yt_dlp.networking.impersonate import ImpersonateTarget  # noqa: F401
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            for tgt, _prov in ydl._get_available_impersonate_targets():
                c_name = getattr(tgt, "client", None)
                if c_name:
                    clients.add(c_name.lower())
    except Exception:
        pass
    return clients


def detect_system_capabilities(force_refresh: bool = False) -> dict:
    global _CACHED_SYSTEM_CAPS
    if _CACHED_SYSTEM_CAPS is not None and not force_refresh:
        return _CACHED_SYSTEM_CAPS
    ff_dir = find_ffmpeg_dir()
    js_kind, node_exe = find_js_runtime()
    idm_exe = find_idm_exe()
    imp_clients = _detect_impersonate_clients()
    meipass = getattr(sys, "_MEIPASS", None)
    ffmpeg_embedded = bool(ff_dir and meipass and os.path.normcase(ff_dir).startswith(os.path.normcase(meipass)))
    has_nvenc = False
    if ff_dir:
        try:
            ff_exe = os.path.join(ff_dir, "ffmpeg.exe")
            cp = subprocess.run(
                [ff_exe, "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                timeout=4,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            has_nvenc = "h264_nvenc" in (cp.stdout or "")
        except Exception:
            has_nvenc = False
    _CACHED_SYSTEM_CAPS = {
        "ffmpeg_dir": ff_dir,
        "ffmpeg_ok": bool(ff_dir),
        "ffmpeg_embedded": ffmpeg_embedded,
        "js_runtime_kind": js_kind,
        "node_exe": node_exe,
        "node_ok": bool(node_exe),
        "idm_exe": idm_exe,
        "idm_ok": bool(idm_exe),
        "nvenc_ok": has_nvenc,
        "impersonate_clients": imp_clients,
        "tls_impersonate_ok": bool(imp_clients),
    }
    return _CACHED_SYSTEM_CAPS


class StreamBridgeServer:
    """Cầu nối HTTP nội bộ giúp IDM tải luồng googlevideo.com đa kết nối không bao giờ dính 403."""

    def __init__(self, routes: dict):
        self.routes = routes
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()

        routes_ref = self.routes
        # Đi thẳng IP dân cư (box_proxy = 0 kiểu Hitomi), bỏ qua mọi System Proxy rác
        direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def do_HEAD(self):
                self._proxy(send_body=False)

            def do_GET(self):
                self._proxy(send_body=True)

            def _proxy(self, send_body=True):
                item = routes_ref.get(self.path)
                if not item:
                    self.send_error(404)
                    return
                target_url, base_headers = item
                req_headers = dict(base_headers or {})
                req_headers.setdefault("User-Agent", CHROME_UA)
                if "Range" in self.headers:
                    req_headers["Range"] = self.headers["Range"]

                req = urllib.request.Request(target_url, headers=req_headers, method="GET")
                try:
                    with direct_opener.open(req, timeout=25) as resp:
                        self.send_response(resp.status)
                        has_accept = False
                        for k in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
                            val = resp.headers.get(k)
                            if val:
                                if k.lower() == "accept-ranges":
                                    has_accept = True
                                self.send_header(k, val)
                        if not has_accept:
                            self.send_header("Accept-Ranges", "bytes")
                        self.end_headers()
                        if send_body:
                            while True:
                                chunk = resp.read(262144)
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                except Exception:
                    pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self) -> str:
        self.thread.start()
        return f"http://127.0.0.1:{self.port}"

    def stop(self):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass


class TurboDownloaderEngine:
    """
    Engine Tải Max Speed đa luồng có Pre-fetch 0ms, Hủy tức thì, Tải lại & Thumbnail Cache.
    """

    def __init__(self, history_store: HistoryStore, cfg: dict):
        self.history = history_store
        self.cfg = cfg
        self.caps = detect_system_capabilities()

        max_conc = max(1, min(5, int(cfg.get("max_concurrent_videos", 3))))
        self._max_conc = max_conc
        self.executor = ThreadPoolExecutor(max_workers=max_conc, thread_name_prefix="TurboVideo")
        self.prefetch_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="Prefetch0ms")
        self.thumb_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ThumbFetch")

        self._lock = threading.Lock()
        self._active_tasks = {}      # {video_id: task_dict}
        self._cancel_events = {}     # {video_id: threading.Event}
        self._prefetch_cache = {}    # {video_id: (timestamp, Future)}
        self._thumb_cache = {}       # {video_id: bytes}

        # Cơ chế 'lock = True' học từ Hitomi cho khâu giải mã link:
        # 1 video lẻ -> qua ngay ở 0.00ms; nhiều video dồn dập -> xếp hàng giải mã từng bài một!
        self._extract_gate = threading.Lock()
        self._last_extract_done_ts = 0.0
        self._cookie_required_vids: set[str] = set()
        self._bot_gate_until = 0.0

        self._http_session = requests.Session()
        # Đi thẳng IP dân cư VNPT sạch (box_proxy = 0 kiểu Hitomi), không dính System Proxy/Env Proxy rác
        self._http_session.trust_env = False
        self._http_session.headers.update(
            {
                "User-Agent": CHROME_UA,
                "Accept": "*/*",
                "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                "Origin": "https://www.youtube.com",
                "Referer": "https://www.youtube.com/",
            }
        )
        adapter = HTTPAdapter(pool_connections=64, pool_maxsize=64, max_retries=2)
        self._http_session.mount("https://", adapter)
        self._http_session.mount("http://", adapter)

        self._stop_warm = threading.Event()
        threading.Thread(target=self._stopwatch_ticker_loop, daemon=True, name="LiveStopwatch").start()

        # Callbacks -> IPC / Signals
        self.on_task_update = None      # (task_dict)
        self.on_task_finished = None    # (task_dict)
        self.on_task_failed = None      # (task_dict)
        self.on_thumb_ready = None      # (video_id: str, img_bytes: bytes)
        self.on_total_speed = None      # (total_mbs: float, active_count: int)
        self.on_log = None              # (msg: str)

    def _log(self, msg: str):
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception:
                pass

    def update_runtime_config(self, cfg: dict):
        self.cfg = cfg

    def _stopwatch_ticker_loop(self):
        """Đếm giây nhẹ nhàng (0.5s/nhịp) chỉ khi có video đang ở pha chuẩn bị/ghép file."""
        while not self._stop_warm.is_set():
            time.sleep(0.5)
            if not self._active_tasks:
                continue
            now = time.perf_counter()
            snapshots = []
            with self._lock:
                for t in self._active_tasks.values():
                    st = t.get("state")
                    c_t0 = t.get("click_t0")
                    if not c_t0 or st not in ("preparing", "waiting_hd", "muxing"):
                        continue
                    el = now - c_t0
                    base_msg = t.get("phase_label") or "🔍 Đang load & bóc link YouTube..."
                    t["status_text"] = f"{base_msg} • ⏱ Đã chạy: {el:.1f}s"
                    snapshots.append(dict(t))
            for snap in snapshots:
                if self.on_task_update:
                    try:
                        self.on_task_update(snap)
                    except Exception:
                        pass

    def _emit_update(self, task: dict):
        if self.on_task_update:
            try:
                self.on_task_update(dict(task))
            except Exception:
                pass
        self._broadcast_aggregate_speed()

    def _broadcast_aggregate_speed(self):
        if not self.on_total_speed:
            return
        with self._lock:
            active_list = [
                t for t in self._active_tasks.values()
                if t.get("state") in ("preparing", "waiting_hd", "downloading", "muxing")
            ]
            total_spd = sum(float(t.get("live_speed_mbs") or 0.0) for t in active_list)
            cnt = len(active_list)
        try:
            self.on_total_speed(round(total_spd, 1), cnt)
        except Exception:
            pass

    # ==========================================================
    # 🖼️ TẢI NHANH THUMBNAIL TRONG NỀN (~12KB / 40ms)
    # ==========================================================
    def get_cached_thumbnail(self, video_id: str) -> bytes | None:
        return self._thumb_cache.get(video_id)

    def request_thumbnail(self, video_id: str):
        if not video_id or video_id in self._thumb_cache:
            if video_id in self._thumb_cache and self.on_thumb_ready:
                self.on_thumb_ready(video_id, self._thumb_cache[video_id])
            return

        def _job():
            for q in ("mqdefault.jpg", "hqdefault.jpg"):
                try:
                    r = self._http_session.get(
                        f"https://i.ytimg.com/vi/{video_id}/{q}", timeout=4
                    )
                    if r.status_code == 200 and len(r.content) > 800:
                        self._thumb_cache[video_id] = r.content
                        if self.on_thumb_ready:
                            self.on_thumb_ready(video_id, r.content)
                        return
                except Exception:
                    pass

        self.thumb_pool.submit(_job)

    # ==========================================================
    # 🛡️ TẦNG BÓC LINK STEALTH HỌC TỪ HITOMI (TLS IMPERSONATION + MOBILE API + EXTRACT LOCK)
    # ==========================================================
    @contextlib.contextmanager
    def _guarded_extract_slot(self, cancel_ev: threading.Event | None = None):
        """
        Khóa tuần tự khâu giải mã link trên www.youtube.com (học từ `lock = True` của Hitomi):
        - Khi rảnh (video mới nổ lẻ từ Webhook): đi qua ngay ở 0.00ms, không trễ dù chỉ 1ms!
        - Khi có bão nhiều video cùng lúc: tự xếp hàng MAX_EXTRACT=1 kèm nhịp nghỉ tự nhiên
          (0.85s - 1.30s) để tuyệt đối không kích hoạt tường lửa chống spam IP của YouTube.
        """
        while True:
            if cancel_ev is not None:
                self._check_cancel(cancel_ev)
            if self._extract_gate.acquire(timeout=0.1):
                break
        try:
            if self._last_extract_done_ts > 0:
                elapsed = time.perf_counter() - self._last_extract_done_ts
                min_gap = 0.85 + random.uniform(0.0, 0.45)
                if elapsed < min_gap:
                    wait_s = min_gap - elapsed
                    if cancel_ev is not None:
                        self._sleep_cancellable(wait_s, cancel_ev)
                    else:
                        time.sleep(wait_s)
            yield
        finally:
            self._last_extract_done_ts = time.perf_counter()
            self._extract_gate.release()

    def _has_cookie_configured(self) -> bool:
        c_mode = self.cfg.get("cookie_mode", "none")
        if c_mode == "file":
            c_file = (self.cfg.get("cookie_file") or "").strip()
            return bool(c_file and os.path.isfile(c_file))
        return c_mode in ("chrome", "edge", "brave", "firefox")

    @staticmethod
    def _has_playable_video(info: dict | None) -> bool:
        if not isinstance(info, dict):
            return False
        if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
            return True
        for f in info.get("formats") or []:
            if (f.get("vcodec") or "none") != "none" and f.get("url"):
                return True
        return False

    def _build_ydl_extract_opts(
        self,
        use_cookies: bool = True,
        player_clients: list[str] | None = None,
        impersonate_browser: str | None = None,
    ) -> dict:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "cachedir": YT_CACHE_DIR,
            "socket_timeout": 12,
            # Đi thẳng IP dân cư VNPT sạch (tương đương box_proxy = 0 của Hitomi)
            "proxy": "",
        }
        if self.caps["ffmpeg_dir"]:
            opts["ffmpeg_location"] = self.caps["ffmpeg_dir"]

        # Chỉ gắn JS solver (deno/node) khi dùng client mặc định/web (các client Apple/Safari không cần giải n-sig JS)
        if self.caps["node_ok"] and not player_clients:
            js_kind = self.caps.get("js_runtime_kind") or "node"
            js_exe = self.caps.get("node_exe")
            opts["js_runtimes"] = {js_kind: {"path": js_exe} if js_exe else {}}

        if player_clients:
            opts["extractor_args"] = {"youtube": {"player_client": list(player_clients)}}

        # Giả lập chữ ký mã hóa TLS trình duyệt thật qua curl_cffi (học từ Hitomi patch)
        imp_avail = self.caps.get("impersonate_clients") or set()
        chosen_imp = None
        if impersonate_browser and impersonate_browser in imp_avail:
            chosen_imp = impersonate_browser
        elif "chrome" in imp_avail:
            chosen_imp = "chrome"
        elif "safari" in imp_avail:
            chosen_imp = "safari"

        if chosen_imp:
            try:
                from yt_dlp.networking.impersonate import ImpersonateTarget
                opts["impersonate"] = ImpersonateTarget.from_str(chosen_imp)
            except Exception:
                pass

        if use_cookies:
            c_mode = self.cfg.get("cookie_mode", "none")
            if c_mode == "file":
                c_file = (self.cfg.get("cookie_file") or "").strip()
                if c_file and os.path.isfile(c_file):
                    opts["cookiefile"] = c_file
            elif c_mode in ("chrome", "edge", "brave", "firefox"):
                opts["cookiesfrombrowser"] = (c_mode,)
        return opts

    def _extract_video_info_once(
        self,
        url: str,
        vid: str = "",
        cancel_ev: threading.Event | None = None,
    ) -> dict:
        """
        Cơ chế bóc link siêu tốc chuẩn MP4 gốc (itag 137 + 140 y hệt IDM):
        - Tầng 1 (`visionos` 1-API-call + Safari TLS): Chỉ tốn 1 vòng gọi JSON lấy thẳng luồng HTTPS MP4 gốc
          1080p H.264 & M4A (nhanh gấp đôi so với tải m3u8 thừa, không tốn Cookie).
        - Tầng 2 (Kho Cookie xác thực + Chrome TLS): Kích hoạt tức thì (0ms delay nội bộ) nếu gặp kênh
          giới hạn tuổi / hội viên hoặc mạng đang bị hỏi xác thực Bot.
        """
        v_id = vid or extract_video_id(url)
        now_ts = time.time()
        with self._lock:
            prefer_cookie = bool(
                (v_id and v_id in self._cookie_required_vids)
                or (now_ts < self._bot_gate_until)
            )
        has_cookie = self._has_cookie_configured()

        last_err: Exception | None = None

        with self._guarded_extract_slot(cancel_ev):
            # TẦNG 1: 1-Call `visionos` lấy thẳng luồng HTTPS MP4 1080p gốc (không tải m3u8 thừa, không phơi Cookie)
            if not prefer_cookie:
                try:
                    opts_stealth = self._build_ydl_extract_opts(
                        use_cookies=False,
                        player_clients=["visionos"],
                        impersonate_browser="safari",
                    )
                    with yt_dlp.YoutubeDL(opts_stealth) as ydl:
                        info = ydl.extract_info(url, download=False)
                    if self._has_playable_video(info):
                        return info
                except DownloadCancelledError:
                    raise
                except Exception as e1:
                    last_err = e1
                    err_low = str(e1).lower()
                    if "not a bot" in err_low or "sign in" in err_low:
                        with self._lock:
                            self._bot_gate_until = time.time() + 300.0
                    if has_cookie:
                        self._log(f"ℹ️ [{v_id}] Chuyển thẳng sang Tầng 2 (Kho Cookie xác thực)...")

            # TẦNG 2: Bóc kèm Kho Cookie sống + chữ ký TLS Chrome thật
            if has_cookie:
                try:
                    opts_cookie = self._build_ydl_extract_opts(
                        use_cookies=True,
                        player_clients=None,
                        impersonate_browser="chrome",
                    )
                    with yt_dlp.YoutubeDL(opts_cookie) as ydl:
                        info = ydl.extract_info(url, download=False)
                    if self._has_playable_video(info):
                        if v_id:
                            with self._lock:
                                if len(self._cookie_required_vids) > 500:
                                    self._cookie_required_vids.clear()
                                self._cookie_required_vids.add(v_id)
                        return info
                except DownloadCancelledError:
                    raise
                except Exception as e2:
                    last_err = e2
                    e2_low = str(e2).lower()
                    if "not a bot" in e2_low:
                        raise RuntimeError(
                            "YouTube đang chặn IP mạng hiện tại (hãy kiểm tra tắt HMA/VPN toàn máy) "
                            "hoặc file Cookies đã hết hạn đăng nhập!"
                        ) from e2
                    self._log(f"⚠️ [{v_id}] Lỗi đọc Cookie ({e2}), thử phương án dự phòng...")

            # TẦNG 3: Dự phòng cuối bằng bộ client mặc định + Chrome TLS không Cookie
            try:
                opts_plain = self._build_ydl_extract_opts(
                    use_cookies=False,
                    player_clients=None,
                    impersonate_browser="chrome",
                )
                with yt_dlp.YoutubeDL(opts_plain) as ydl:
                    return ydl.extract_info(url, download=False)
            except DownloadCancelledError:
                raise
            except Exception as e3:
                err_final = last_err or e3
                if "not a bot" in str(err_final).lower():
                    raise RuntimeError(
                        "YouTube đang chặn IP mạng hiện tại (hãy kiểm tra tắt HMA/VPN toàn máy) "
                        "hoặc cập nhật lại Cookies YouTube!"
                    ) from err_final
                raise err_final

    def prefetch_url(self, video_url: str):
        vid = extract_video_id(video_url)
        if not vid:
            return
        norm_url = f"https://www.youtube.com/watch?v={vid}"
        now = time.time()

        with self._lock:
            # Dọn cache hết hạn > 90s
            expired = [k for k, (ts, _) in self._prefetch_cache.items() if now - ts > 90]
            for k in expired:
                self._prefetch_cache.pop(k, None)

            if vid in self._prefetch_cache or vid in self._active_tasks:
                return
            # Cơ chế LazyUrl học từ Hitomi (lazyLoading = 1.0):
            # Chỉ Pre-fetch 0ms khi đường ống đang rảnh; nếu đang tải dồn dập nhiều bài thì để tới lượt mới bóc link!
            if len(self._active_tasks) >= self._max_conc or self._extract_gate.locked():
                return
            fut = self.prefetch_pool.submit(self._extract_video_info_once, norm_url, vid, None)
            self._prefetch_cache[vid] = (now, fut)

        self.request_thumbnail(vid)

    def _consume_or_extract_info(
        self,
        vid: str,
        url: str,
        cancel_ev: threading.Event | None = None,
    ) -> tuple[dict, bool]:
        """Nếu đã có bản Pre-fetch 0ms đang chạy hoặc xong trong 60s gần nhất -> lấy luôn không bóc lại!"""
        fut = None
        with self._lock:
            cached = self._prefetch_cache.pop(vid, None)
            if cached and (time.time() - cached[0] < 65):
                fut = cached[1]

        if fut is not None:
            try:
                info = fut.result(timeout=18)
                if self._has_playable_video(info):
                    return info, True
            except Exception:
                pass

        return self._extract_video_info_once(url, vid=vid, cancel_ev=cancel_ev), False

    @staticmethod
    def _find_existing_file_on_disk(
        vid: str,
        save_dir: str,
        channel_name: str,
        subfolder_by_channel: bool,
    ) -> str | None:
        """
        Kiểm tra nhanh xem file `*[vid].mp4` đã nằm sẵn trên ổ đĩa chưa (học từ Hitomi patch):
        Nếu đã tải đầy đủ (> 100KB) thì bỏ qua ngay lập tức, không tốn dù chỉ 1 request lên YouTube!
        """
        if not vid:
            return None
        base_dir = save_dir or os.path.join(os.path.expanduser("~"), "Downloads", "Soitube_1080p")
        if not os.path.isdir(base_dir):
            return None

        suffix = f"[{vid}].mp4"
        search_dirs = []
        if subfolder_by_channel and channel_name and channel_name not in ("Manual", "YouTube", "Tải Thủ Công", "Tải Nhanh"):
            ch_dir = os.path.join(base_dir, sanitize_filename(channel_name, 60))
            if os.path.isdir(ch_dir):
                search_dirs.append(ch_dir)
        search_dirs.append(base_dir)

        try:
            for entry in os.scandir(base_dir):
                if entry.is_dir() and entry.path not in search_dirs:
                    search_dirs.append(entry.path)
        except OSError:
            pass

        for d in search_dirs:
            try:
                for entry in os.scandir(d):
                    if (
                        entry.is_file()
                        and not entry.name.startswith("._tmp_")
                        and entry.name.endswith(suffix)
                    ):
                        if entry.stat().st_size >= 102400:
                            return entry.path
            except OSError:
                continue
        return None

    @staticmethod
    def _compute_hd_poll_delay(attempt: int, waited_sec: float) -> float:
        """
        Giãn nhịp quét 1080p thông minh kèm Jitter tự nhiên (giảm ~75-80% request thừa so với quét 2.5s cố định):
        - 3 nhịp đầu (~12s đầu): quét 3.5s - 5.5s để bắt tức thì các clip ngắn vừa lên HD.
        - Dưới 90s: 8.0s - 9.5s.
        - Từ 90s - 240s: 12.0s - 14.0s.
        - Trên 240s (video dài đang render trên YouTube): 17.5s - 20.0s.
        """
        jitter = random.uniform(0.0, 1.5)
        if attempt <= 1:
            return 3.5 + random.uniform(0.0, 0.6)
        if attempt == 2:
            return 4.5 + random.uniform(0.0, 0.8)
        if attempt == 3:
            return 5.8 + random.uniform(0.0, 1.0)
        if waited_sec < 90:
            return 8.0 + jitter
        if waited_sec < 240:
            return 12.0 + jitter
        return 17.5 + random.uniform(0.0, 2.5)

    # ==========================================================
    # 🎯 QUẢN LÝ HÀNG ĐỢI, HỦY (CANCEL) & TẢI LẠI (RETRY)
    # ==========================================================
    def cancel_task(self, video_id: str) -> bool:
        with self._lock:
            ev = self._cancel_events.get(video_id)
            if ev:
                ev.set()
                return True
        return False

    def enqueue(
        self,
        username: str,
        video_url: str,
        channel_name: str = "Manual",
        video_title: str = "",
        note: str = "",
        save_dir: str = "",
        subfolder_by_channel: bool = True,
        res_profile: str | None = None,
        hd_mode: str | None = None,
        force_redownload: bool = False,
        skip_existing_on_disk: bool | None = None,
        channel_id: str = "",
    ) -> tuple[bool, str]:
        click_t0 = time.perf_counter()
        vid = extract_video_id(video_url)
        if not vid:
            return False, "Link YouTube không hợp lệ!"

        norm_url = f"https://www.youtube.com/watch?v={vid}"
        resolved_save_dir = save_dir or self.cfg.get("save_dir", "")
        if skip_existing_on_disk is None:
            skip_existing_on_disk = not force_redownload

        with self._lock:
            if vid in self._active_tasks:
                return False, "Video này đang nằm trong tiến trình tải!"
            if not force_redownload and self.history.has_downloaded(username, vid):
                return False, "Video này đã được tải trước đó!"

            # Học từ Hitomi patch: Nếu file [vid].mp4 đã nằm sẵn nguyên vẹn trên ổ đĩa -> bỏ qua ngay, tốn 0 request!
            existing_fp = (
                self._find_existing_file_on_disk(vid, resolved_save_dir, channel_name, subfolder_by_channel)
                if skip_existing_on_disk
                else None
            )

        if existing_fp:
            sz_mb = round(os.path.getsize(existing_fp) / (1024 * 1024), 2)
            fname = os.path.basename(existing_fp)
            suffix = f" [{vid}].mp4"
            inferred_title = video_title or (fname[: -len(suffix)] if fname.endswith(suffix) else f"Video {vid}")
            parent_dir_name = os.path.basename(os.path.dirname(existing_fp))
            inferred_ch = (
                channel_name
                if channel_name not in ("Manual", "YouTube", "Tải Thủ Công", "Tải Nhanh")
                else (parent_dir_name or "YouTube")
            )
            done_task = {
                "username": username,
                "video_id": vid,
                "url": norm_url,
                "channel_id": channel_id or "",
                "channel": inferred_ch,
                "title": inferred_title,
                "note": note or "",
                "save_dir": resolved_save_dir,
                "subfolder_by_channel": subfolder_by_channel,
                "res_profile": res_profile or self.cfg.get("res_profile", "1080p_h264"),
                "hd_mode": hd_mode or self.cfg.get("hd_mode", "wait_hd"),
                "resolution_badge": "Sẵn trên ổ",
                "duration_sec": 0,
                "click_t0": click_t0,
                "load_sec": 0.0,
                "dl_sec": 0.0,
                "mux_sec": 0.0,
                "phase_label": "✅ Đã có sẵn trên ổ đĩa",
                "percent": 100.0,
                "live_speed_mbs": 0.0,
                "speed_str": "0ms Disk Hit",
                "status_text": f"⚡ Đã có sẵn trên ổ đĩa ({sz_mb:.1f} MB) • Bỏ qua tải lại (0 request YouTube)",
                "state": "completed",
                "file_path": existing_fp,
                "size_mb": sz_mb,
                "elapsed_sec": 0.01,
                "speed_mbs": 0.0,
            }
            self.request_thumbnail(vid)
            self.history.upsert_record(
                username=username,
                video_id=vid,
                video_url=norm_url,
                channel_name=inferred_ch,
                note=done_task["note"],
                video_title=inferred_title,
                resolution="Disk Hit",
                file_path=existing_fp,
                size_mb=sz_mb,
                elapsed_sec=0.01,
                status="completed",
            )
            self._log(f"⚡ [DISK HIT 0ms] Bỏ qua tải lại vì file đã có sẵn: {fname} ({sz_mb:.1f} MB)")
            self._emit_update(done_task)
            if self.on_task_finished:
                self.on_task_finished(dict(done_task))
            return True, "File đã có sẵn trên ổ đĩa!"

        with self._lock:
            if vid in self._active_tasks:
                return False, "Video này đang nằm trong tiến trình tải!"
            cancel_ev = threading.Event()
            self._cancel_events[vid] = cancel_ev

            chosen_res = res_profile or self.cfg.get("res_profile", "1080p_h264")
            chosen_hd = hd_mode or self.cfg.get("hd_mode", "wait_hd")

            task = {
                "username": username,
                "video_id": vid,
                "url": norm_url,
                "channel_id": channel_id or "",
                "channel": channel_name or "YouTube",
                "title": video_title or f"Video {vid}",
                "note": note or "",
                "save_dir": resolved_save_dir,
                "subfolder_by_channel": subfolder_by_channel,
                "res_profile": chosen_res,
                "hd_mode": chosen_hd,
                "resolution_badge": "",
                "duration_sec": 0,
                "click_t0": click_t0,
                "load_sec": 0.0,
                "dl_sec": 0.0,
                "mux_sec": 0.0,
                "phase_label": "🔍 Đang load & bóc link YouTube...",
                "percent": 5.0,
                "live_speed_mbs": 0.0,
                "speed_str": "Đang load link...",
                "status_text": "🔍 Đang load & bóc link YouTube... • ⏱ Đã chạy: 0.0s",
                "state": "preparing",
                "file_path": "",
                "size_mb": 0.0,
                "elapsed_sec": 0.0,
                "speed_mbs": 0.0,
            }
            self._active_tasks[vid] = task

        self.request_thumbnail(vid)
        self.history.upsert_record(
            username=username,
            video_id=vid,
            video_url=norm_url,
            channel_name=task["channel"],
            note=task["note"],
            video_title=task["title"],
            status="downloading",
        )
        self._emit_update(task)
        self.executor.submit(self._execute_download_pipeline, vid, task, cancel_ev)
        return True, "Đã nạp vào đường ống tải Max Speed!"

    # ==========================================================
    # 🧠 CHỌN LUỒNG TỐI ƯU NHẤT TỪ BẢNG FORMAT (KHÔNG BÓC LẠI LINK)
    # ==========================================================
    @staticmethod
    def _select_optimal_pair(info: dict, res_profile: str, allow_lower_fallback: bool) -> dict:
        """
        Chọn cặp (video_format, audio_format, need_h264_transcode, resolution_label, max_available_height).
        Ưu tiên luồng HLS m3u8 CDN (không bóp băng thông) hoặc HTTPS trực tiếp chuẩn H.264 + AAC!
        """
        formats = info.get("formats") or []
        v_formats = [
            f for f in formats
            if (f.get("vcodec") or "none") != "none" and f.get("url")
        ]
        a_formats = [
            f for f in formats
            if (f.get("acodec") or "none") != "none"
            and (f.get("vcodec") or "none") == "none"
            and f.get("url")
        ]

        max_h = max((int(f.get("height") or 0) for f in v_formats), default=0)

        # Chọn Audio AAC (mp4a) bản NGÔN NGỮ GỐC (original) chất lượng cao nhất chuẩn IDM
        def _audio_score(af):
            acodec = (af.get("acodec") or "").lower()
            proto = (af.get("protocol") or "").lower()
            fid = str(af.get("format_id") or "")
            note = (af.get("format_note") or "").lower()
            is_aac = 1 if ("mp4a" in acodec or af.get("ext") == "m4a") else 0
            is_https = 1 if proto in ("https", "http") and not af.get("fragments") else 0
            lang_pref = int(af.get("language_preference") if af.get("language_preference") is not None else -1)
            is_orig = 1 if ("original" in note or lang_pref >= 10 or fid == "140") else 0
            not_drc = 0 if ("drc" in fid.lower() or "drc" in note) else 1
            abr = float(af.get("abr") or af.get("tbr") or 0)
            return (is_aac, is_https, is_orig, lang_pref, not_drc, abr)

        best_audio = max(a_formats, key=_audio_score) if a_formats else None

        def _is_h264(vf):
            vc = (vf.get("vcodec") or "").lower()
            return vc.startswith("avc1") or "h264" in vc

        def _video_speed_score(vf):
            proto = (vf.get("protocol") or "").lower()
            # ƯU TIÊN SỐ 1 LÀ HTTPS MP4 NGUYÊN BẢN CỦA GOOGLE (itag 137 - y hệt IDM!):
            # Giúp kéo `&range=` tốc độ tối đa VÀ giữ nguyên `time_base = 1/15360` chuẩn ISO MP4
            # để khi đưa vào CapCut / Premiere thì GPU Hardware Decode + Render mượt gấp nhiều lần .ts!
            is_https_native = 1 if (proto in ("https", "http") and not vf.get("fragments")) else 0
            fps = float(vf.get("fps") or 30)
            tbr = float(vf.get("tbr") or vf.get("vbr") or 0)
            return (is_https_native, fps, tbr)

        chosen_v = None
        need_transcode = False

        if res_profile == "720p_fast":
            cands = [f for f in v_formats if int(f.get("height") or 0) <= 720 and _is_h264(f)]
            if not cands:
                cands = [f for f in v_formats if int(f.get("height") or 0) <= 720]
            if cands:
                top_h = max(int(f.get("height") or 0) for f in cands)
                chosen_v = max([f for f in cands if int(f.get("height") or 0) == top_h], key=_video_speed_score)

        elif res_profile == "best_max":
            if v_formats:
                chosen_v = max(
                    v_formats,
                    key=lambda f: (
                        int(f.get("height") or 0),
                        1 if _is_h264(f) else 0,
                        *_video_speed_score(f),
                    ),
                )

        else:
            # Mặc định: 1080p_h264 chuẩn dựng phim Premiere / CapCut
            h1080_avc = [f for f in v_formats if int(f.get("height") or 0) == 1080 and _is_h264(f)]
            if h1080_avc:
                chosen_v = max(h1080_avc, key=_video_speed_score)
            elif allow_lower_fallback:
                h1080_any = [f for f in v_formats if int(f.get("height") or 0) == 1080]
                if h1080_any:
                    chosen_v = max(h1080_any, key=_video_speed_score)
                    need_transcode = True
                else:
                    avc_any = [f for f in v_formats if _is_h264(f)]
                    pool = avc_any if avc_any else v_formats
                    if pool:
                        top_h = max(int(f.get("height") or 0) for f in pool)
                        chosen_v = max([f for f in pool if int(f.get("height") or 0) == top_h], key=_video_speed_score)
                        need_transcode = not _is_h264(chosen_v)

        res_label = ""
        if chosen_v:
            vh = int(chosen_v.get("height") or 0)
            vfps = int(chosen_v.get("fps") or 0)
            vc_short = "H.264" if _is_h264(chosen_v) else (chosen_v.get("vcodec") or "").split(".")[0].upper()
            res_label = f"{vh}p{vfps if vfps > 30 else ''} {vc_short}".strip()

        return {
            "video": chosen_v,
            "audio": best_audio,
            "need_transcode": need_transcode,
            "res_label": res_label,
            "max_height": max_h,
        }

    # ==========================================================
    # 🚀 ENGINE KÉO ĐA LUỒNG (HTTP MULTI-RANGE + PARALLEL HLS + FALLBACK)
    # ==========================================================
    def _check_cancel(self, cancel_ev: threading.Event):
        if cancel_ev.is_set():
            raise DownloadCancelledError("Đã hủy tải theo yêu cầu!")

    def _download_https_multirange(
        self,
        fmt: dict,
        out_path: str,
        num_threads: int,
        cancel_ev: threading.Event,
        on_delta_bytes,
    ) -> bool:
        """
        Tải luồng HTTPS MP4 gốc (itag 137 / 140) tốc độ cao chuẩn IDM:
        - Truyền trực tiếp tham số `&range=start-end` trên URL googlevideo.com để né hoàn toàn
          bộ giới hạn băng thông HTTP Range Header (~6-10 MB/s) của YouTube!
        - Giữ đúng 1 File Handle mở duy nhất suốt phiên tải (tránh mở/đóng file 40-60 lần gây nghẽn Antivirus).
        """
        url = fmt["url"]
        base_headers = dict(fmt.get("http_headers") or {})
        total_size = int(fmt.get("filesize") or 0)

        # Chỉ probe bytes=0-0 khi metadata chưa có sẵn chính xác filesize (tiết kiệm ~300ms RTT!)
        if total_size <= 0:
            probe_headers = dict(base_headers)
            probe_headers["Range"] = "bytes=0-0"
            r0 = self._http_session.get(url, headers=probe_headers, stream=True, timeout=10)
            try:
                if r0.status_code != 206:
                    return False
                cr = r0.headers.get("Content-Range", "")
                m_tot = re.search(r"/(\d+)$", cr)
                if m_tot:
                    total_size = int(m_tot.group(1))
            finally:
                r0.close()

        if total_size <= 0:
            return False

        # Chia mảnh 6MB tối ưu cho tốc độ cao mà không tốn overhead kết nối thừa
        chunk_size = 6 * 1024 * 1024
        ranges = []
        pos = 0
        while pos < total_size:
            end = min(pos + chunk_size - 1, total_size - 1)
            ranges.append((pos, end))
            pos = end + 1

        workers = min(max(2, num_threads), 32, len(ranges))
        can_use_url_range = ("googlevideo.com" in url) and ("&range=" not in url) and ("?range=" not in url)
        url_sep = "&" if "?" in url else "?"
        write_lock = threading.Lock()

        with open(out_path, "wb") as fp:
            fp.truncate(total_size)

        with open(out_path, "r+b") as shared_fp:
            def _fetch_range(rng):
                start_b, end_b = rng
                expected_len = end_b - start_b + 1
                use_q_param = can_use_url_range

                for attempt in range(4):
                    self._check_cancel(cancel_ev)
                    reported_this_try = 0
                    write_offset = start_b
                    try:
                        hdrs = dict(base_headers)
                        if use_q_param:
                            req_url = f"{url}{url_sep}range={start_b}-{end_b}"
                            hdrs.pop("Range", None)
                        else:
                            req_url = url
                            hdrs["Range"] = f"bytes={start_b}-{end_b}"

                        with self._http_session.get(req_url, headers=hdrs, stream=True, timeout=15) as resp:
                            if resp.status_code not in (200, 206):
                                if use_q_param:
                                    use_q_param = False
                                    continue
                                raise RuntimeError(f"HTTP {resp.status_code}")

                            cl_hdr = resp.headers.get("Content-Length")
                            if use_q_param and resp.status_code == 200 and cl_hdr and int(cl_hdr) > expected_len + 4096:
                                # Server phớt lờ query range -> chuyển tức thì sang Header Range
                                use_q_param = False
                                continue

                            mem_buf = bytearray()
                            for net_chunk in resp.iter_content(chunk_size=262144):
                                self._check_cancel(cancel_ev)
                                if not net_chunk:
                                    continue
                                n = len(net_chunk)
                                mem_buf.extend(net_chunk)
                                reported_this_try += n
                                on_delta_bytes(n)

                                # Xả xuống đĩa theo cụm >= 1MB để tối ưu tốc độ NVMe/SSD & không khóa luồng
                                if len(mem_buf) >= 1048576:
                                    with write_lock:
                                        shared_fp.seek(write_offset)
                                        shared_fp.write(mem_buf)
                                    write_offset += len(mem_buf)
                                    mem_buf.clear()

                            if mem_buf:
                                with write_lock:
                                    shared_fp.seek(write_offset)
                                    shared_fp.write(mem_buf)
                                write_offset += len(mem_buf)
                                mem_buf.clear()

                        if reported_this_try == expected_len:
                            return
                        on_delta_bytes(-reported_this_try)
                        if use_q_param:
                            use_q_param = False
                    except DownloadCancelledError:
                        raise
                    except Exception:
                        if reported_this_try > 0:
                            on_delta_bytes(-reported_this_try)
                        if use_q_param and attempt == 0:
                            use_q_param = False
                            continue
                        if attempt == 3:
                            raise
                        time.sleep(0.2 * (attempt + 1))

            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = [pool.submit(_fetch_range, r) for r in ranges]
                for f in futs:
                    f.result()

            shared_fp.flush()

        return os.path.exists(out_path) and os.path.getsize(out_path) == total_size

    def _download_hls_parallel_ts(
        self,
        fmt: dict,
        out_path: str,
        num_threads: int,
        cancel_ev: threading.Event,
        on_delta_bytes,
        on_seg_progress=None,
    ) -> bool:
        """
        Tải siêu tốc playlist HLS (.m3u8) bằng 24-32 luồng Keep-Alive trực tiếp trong RAM
        và ghi tuần tự ra file .ts (nhanh hơn yt-dlp mặc định vì không tốn overhead quản lý file lẻ).
        Nếu phát hiện mã hóa AES (#EXT-X-KEY) hoặc fMP4 (#EXT-X-MAP) sẽ trả về False để chuyển sang yt-dlp.
        """
        m3u8_url = fmt["url"]
        hdrs = dict(fmt.get("http_headers") or {})
        r = self._http_session.get(m3u8_url, headers=hdrs, timeout=10)
        if r.status_code != 200:
            return False

        text = r.text
        if "#EXT-X-KEY" in text or "#EXT-X-MAP" in text or "#EXT-X-STREAM-INF" in text:
            return False

        seg_urls = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            seg_urls.append(urljoin(m3u8_url, line))

        if not seg_urls:
            return False

        total_segs = len(seg_urls)
        workers = min(max(4, num_threads), 32, total_segs)

        def _fetch_seg(idx_and_url):
            idx, s_url = idx_and_url
            for attempt in range(4):
                self._check_cancel(cancel_ev)
                try:
                    with self._http_session.get(s_url, headers=hdrs, timeout=14) as sr:
                        if sr.status_code != 200:
                            raise RuntimeError(f"Seg HTTP {sr.status_code}")
                        data = sr.content
                        on_delta_bytes(len(data))
                        return idx, data
                except DownloadCancelledError:
                    raise
                except Exception:
                    if attempt == 3:
                        raise
                    time.sleep(0.2 * (attempt + 1))

        # Chạy theo cửa sổ trượt (window = workers * 2) để không tốn RAM với video dài mà vẫn kịch trần tốc độ!
        done_segs = 0
        window_size = workers * 2
        with open(out_path, "wb") as f_out, ThreadPoolExecutor(max_workers=workers) as pool:
            next_to_submit = 0
            next_to_write = 0
            pending_futs = set()
            ready_buffers = {}

            while next_to_submit < min(total_segs, window_size):
                pending_futs.add(pool.submit(_fetch_seg, (next_to_submit, seg_urls[next_to_submit])))
                next_to_submit += 1

            while pending_futs:
                self._check_cancel(cancel_ev)
                done, pending_futs = wait(pending_futs, return_when=FIRST_COMPLETED)
                for fut in done:
                    idx, buf = fut.result()
                    ready_buffers[idx] = buf
                    done_segs += 1
                    if on_seg_progress:
                        on_seg_progress(done_segs, total_segs)

                    if next_to_submit < total_segs:
                        pending_futs.add(
                            pool.submit(_fetch_seg, (next_to_submit, seg_urls[next_to_submit]))
                        )
                        next_to_submit += 1

                while next_to_write in ready_buffers:
                    f_out.write(ready_buffers.pop(next_to_write))
                    next_to_write += 1

        return os.path.exists(out_path) and os.path.getsize(out_path) > 0

    def _download_single_stream_ytdlp_fallback(
        self,
        base_info: dict,
        fmt: dict,
        out_path: str,
        num_threads: int,
        cancel_ev: threading.Event,
        on_delta_bytes,
    ):
        """Fallback an toàn tuyệt đối qua process_info (KHÔNG bóc lại URL từ YouTube!)."""
        last_bytes = [0]

        def _hook(d):
            self._check_cancel(cancel_ev)
            if d.get("status") == "downloading":
                cur = int(d.get("downloaded_bytes") or 0)
                delta = cur - last_bytes[0]
                if delta > 0:
                    last_bytes[0] = cur
                    on_delta_bytes(delta)

        with self._lock:
            need_ck = bool(base_info.get("id") in self._cookie_required_vids)
        opts = self._build_ydl_extract_opts(use_cookies=need_ck)
        opts.update(
            {
                "outtmpl": out_path,
                "concurrent_fragment_downloads": num_threads,
                "http_chunk_size": 10485760,
                "retries": 5,
                "fragment_retries": 5,
                "progress_hooks": [_hook],
                "overwrites": True,
            }
        )
        single_info = {
            "id": base_info.get("id", "vid"),
            "title": base_info.get("title", "video"),
            "ext": fmt.get("ext", "mp4"),
            "url": fmt["url"],
            "format_id": fmt.get("format_id", "0"),
            "protocol": fmt.get("protocol", "https"),
            "http_headers": fmt.get("http_headers") or {},
            "vcodec": fmt.get("vcodec"),
            "acodec": fmt.get("acodec"),
        }
        if fmt.get("fragments"):
            single_info["fragments"] = fmt["fragments"]
        if fmt.get("fragment_base_url"):
            single_info["fragment_base_url"] = fmt["fragment_base_url"]

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.process_info(single_info)

    def _download_one_track(
        self,
        base_info: dict,
        fmt: dict,
        out_path: str,
        num_threads: int,
        cancel_ev: threading.Event,
        on_delta_bytes,
        on_seg_progress=None,
    ):
        proto = (fmt.get("protocol") or "").lower()
        try:
            if "m3u8" in proto:
                ok = self._download_hls_parallel_ts(
                    fmt, out_path, num_threads, cancel_ev, on_delta_bytes, on_seg_progress
                )
                if ok:
                    return
            elif proto in ("https", "http") and not fmt.get("fragments"):
                ok = self._download_https_multirange(
                    fmt, out_path, num_threads, cancel_ev, on_delta_bytes
                )
                if ok:
                    return
        except DownloadCancelledError:
            raise
        except Exception as e:
            self._log(f"ℹ️ Chuyển luồng tải dự phòng cho format {fmt.get('format_id')}: {e}")

        self._download_single_stream_ytdlp_fallback(
            base_info, fmt, out_path, num_threads, cancel_ev, on_delta_bytes
        )

    # ==========================================================
    # ⚡ CHẾ ĐỘ IDM BRIDGE (TÙY CHỌN CHO MÁY CÓ IDMAN.EXE)
    # ==========================================================
    def _run_idm_bridge_download(
        self,
        vf: dict,
        af: dict | None,
        tmp_dir: str,
        vid: str,
        cancel_ev: threading.Event,
        on_progress_cb,
    ) -> tuple[str, str | None]:
        idm_exe = self.caps["idm_exe"]
        if not idm_exe:
            raise RuntimeError("Không tìm thấy IDMan.exe, hãy chuyển sang chế độ Turbo Hybrid!")

        v_name = f"_tmp_{vid}_v.mp4"
        a_name = f"_tmp_{vid}_a.m4a"
        v_path = os.path.join(tmp_dir, v_name)
        a_path = os.path.join(tmp_dir, a_name)
        for p in (v_path, a_path):
            if os.path.exists(p):
                os.remove(p)

        routes = {"/video.mp4": (vf["url"], vf.get("http_headers", {}))}
        if af:
            routes["/audio.m4a"] = (af["url"], af.get("http_headers", {}))

        bridge = StreamBridgeServer(routes)
        base_b = bridge.start()
        no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.run(
                [idm_exe, "/d", f"{base_b}/video.mp4", "/p", tmp_dir, "/f", v_name, "/n"],
                creationflags=no_win,
                check=False,
            )
            if af:
                subprocess.run(
                    [idm_exe, "/d", f"{base_b}/audio.m4a", "/p", tmp_dir, "/f", a_name, "/n"],
                    creationflags=no_win,
                    check=False,
                )

            expected_targets = [v_path] + ([a_path] if af else [])
            est_total = int(vf.get("filesize") or vf.get("filesize_approx") or 0) + int(
                (af.get("filesize") or af.get("filesize_approx") or 0) if af else 0
            )
            t_start = time.perf_counter()

            while time.perf_counter() - t_start < 300:
                self._check_cancel(cancel_ev)
                ready_all = True
                cur_bytes = 0
                for fp in expected_targets:
                    if os.path.exists(fp):
                        sz = os.path.getsize(fp)
                        cur_bytes += sz
                        if sz < 65536:
                            ready_all = False
                        else:
                            try:
                                with open(fp, "rb+"):
                                    pass
                            except OSError:
                                ready_all = False
                    else:
                        ready_all = False

                el = max(0.15, time.perf_counter() - t_start)
                spd_mbs = (cur_bytes / (1024 * 1024)) / el
                pct = min(98.5, (cur_bytes * 100.0 / est_total)) if est_total > 0 else 50.0
                on_progress_cb(pct, spd_mbs)

                if ready_all:
                    return v_path, (a_path if af else None)
                time.sleep(0.15)

            raise RuntimeError("IDM tải quá thời gian chờ!")
        finally:
            bridge.stop()

    # ==========================================================
    # 🏁 ĐƯỜNG ỐNG THỰC THI CHÍNH CHO TỪNG VIDEO
    # ==========================================================
    def _sleep_cancellable(self, seconds: float, cancel_ev: threading.Event):
        end_t = time.time() + seconds
        while time.time() < end_t:
            self._check_cancel(cancel_ev)
            time.sleep(min(0.2, max(0.05, end_t - time.time())))

    def _execute_download_pipeline(self, vid: str, task: dict, cancel_ev: threading.Event):
        t0 = task.get("click_t0") or time.perf_counter()
        temp_files = []
        try:
            self.caps = detect_system_capabilities()
            if not self.caps["ffmpeg_dir"]:
                raise RuntimeError("Chưa tìm thấy FFmpeg (C:\\ffmpeg\\bin\\ffmpeg.exe) trên máy!")

            res_profile = task["res_profile"]
            hd_mode = task["hd_mode"]
            hd_wait_min = max(1, int(self.cfg.get("hd_wait_minutes", 12)))
            wait_deadline = time.time() + (hd_wait_min * 60)

            # BƯỚC 1: BÓC LINK 1 LẦN DUY NHẤT (TẬN DỤNG BẢN PRE-FETCH 0MS & KHÓA CHỐNG SPAM KIỂU HITOMI)
            attempt = 0
            selected = None
            info = None
            hd_wait_started_ts = time.perf_counter()

            while True:
                self._check_cancel(cancel_ev)
                attempt += 1
                t_ext = time.perf_counter()
                if attempt == 1:
                    info, was_prefetched = self._consume_or_extract_info(vid, task["url"], cancel_ev=cancel_ev)
                    ext_ms = int((time.perf_counter() - t_ext) * 1000)
                    tag_pf = "⚡ Pre-fetch Hit" if was_prefetched else "🔍 Stealth Extract"
                    self._log(f"[{vid}] {tag_pf} xong trong {ext_ms}ms")
                else:
                    info = self._extract_video_info_once(task["url"], vid=vid, cancel_ev=cancel_ev)

                if info.get("title"):
                    task["title"] = info["title"]
                if info.get("channel_id") and not task.get("channel_id"):
                    task["channel_id"] = info["channel_id"]
                if info.get("uploader") and task["channel"] in ("Manual", "YouTube", "Tải Thủ Công", "Tải Nhanh"):
                    task["channel"] = info["uploader"]
                task["duration_sec"] = int(info.get("duration") or 0)

                if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
                    raise RuntimeError("Video đang phát trực tiếp / Công chiếu chờ (LIVE), bỏ qua!")

                ts_pub = info.get("release_timestamp") or info.get("timestamp")
                age_sec = (time.time() - ts_pub) if ts_pub else None
                is_fresh = (age_sec is None) or (age_sec < 2700)

                must_wait_1080 = (
                    res_profile == "1080p_h264"
                    and hd_mode == "wait_hd"
                    and is_fresh
                    and time.time() < wait_deadline
                )

                selected = self._select_optimal_pair(
                    info, res_profile=res_profile, allow_lower_fallback=(not must_wait_1080)
                )

                if selected["video"] is not None:
                    break

                if must_wait_1080:
                    rem = int(wait_deadline - time.time())
                    waited_so_far = time.perf_counter() - hd_wait_started_ts
                    poll_delay = self._compute_hd_poll_delay(attempt, waited_so_far)
                    task["state"] = "waiting_hd"
                    task["live_speed_mbs"] = 0.0
                    task["speed_str"] = "Canh 1080p..."
                    task["phase_label"] = (
                        f"⏳ Chờ YouTube lên 1080p (hiện có {selected['max_height']}p) • "
                        f"lần {attempt} (nhịp {poll_delay:.1f}s • còn {rem}s)"
                    )
                    task["status_text"] = f"{task['phase_label']} • ⏱ Đã chạy: {time.perf_counter() - t0:.1f}s"
                    self._emit_update(task)
                    self._sleep_cancellable(poll_delay, cancel_ev)
                    continue

                # Hết thời gian chờ hoặc video cũ không có 1080p -> lấy bản tốt nhất hiện có
                selected = self._select_optimal_pair(info, res_profile=res_profile, allow_lower_fallback=True)
                if selected["video"] is not None:
                    break
                raise RuntimeError("Không tìm thấy luồng video hợp lệ từ YouTube!")

            vf = selected["video"]
            af = selected["audio"]
            need_transcode = selected["need_transcode"]
            task["resolution_badge"] = selected["res_label"]

            # BƯỚC 2: CHUẨN BỊ THƯ MỤC ĐÍCH
            target_dir = task["save_dir"] or os.path.join(os.path.expanduser("~"), "Downloads", "Soitube_1080p")
            if task["subfolder_by_channel"] and task["channel"]:
                target_dir = os.path.join(target_dir, sanitize_filename(task["channel"], 60))
            os.makedirs(target_dir, exist_ok=True)

            safe_title = sanitize_filename(task["title"], 100)
            base_name = f"{safe_title} [{vid}]"
            final_mp4 = os.path.join(target_dir, f"{base_name}.mp4")

            # BƯỚC 3: KÉO SONG SONG VIDEO + AUDIO TỐC ĐỘ KỊCH TRẦN
            num_threads = max(8, min(32, int(self.cfg.get("threads_per_video", 24))))
            engine_mode = self.cfg.get("engine_mode", "turbo_hybrid")
            if engine_mode == "idm_bridge" and not self.caps["idm_ok"]:
                engine_mode = "turbo_hybrid"

            t_dl_start = time.perf_counter()
            load_sec = max(0.01, t_dl_start - t0)
            task["load_sec"] = round(load_sec, 2)
            task["state"] = "downloading"

            if engine_mode == "idm_bridge" and ("https" in (vf.get("protocol") or "")):
                def _idm_prog(pct, spd):
                    tot_now = time.perf_counter() - t0
                    task["percent"] = round(pct, 1)
                    task["live_speed_mbs"] = round(spd, 1)
                    task["speed_str"] = f"{spd:.1f} MB/s"
                    task["status_text"] = (
                        f"⚡ IDM {task['resolution_badge']}: {pct:.1f}% • {spd:.1f} MB/s • "
                        f"⏱ Tổng đã chạy: {tot_now:.1f}s (Load link: {load_sec:.2f}s)"
                    )
                    self._emit_update(task)

                v_part, a_part = self._run_idm_bridge_download(vf, af, target_dir, vid, cancel_ev, _idm_prog)
                temp_files.extend([p for p in (v_part, a_part) if p])
            else:
                v_ext = "ts" if "m3u8" in (vf.get("protocol") or "") else (vf.get("ext") or "mp4")
                v_part = os.path.join(target_dir, f"._tmp_{vid}_video.{v_ext}")
                a_part = None
                temp_files.append(v_part)

                if af and (vf.get("acodec") in (None, "none")):
                    a_ext = "ts" if "m3u8" in (af.get("protocol") or "") else (af.get("ext") or "m4a")
                    a_part = os.path.join(target_dir, f"._tmp_{vid}_audio.{a_ext}")
                    temp_files.append(a_part)

                est_v = int(vf.get("filesize") or vf.get("filesize_approx") or 0)
                est_a = int((af.get("filesize") or af.get("filesize_approx") or 0) if a_part else 0)
                est_total = est_v + est_a

                dl_lock = threading.Lock()
                shared_prog = {"bytes": 0, "seg_pct": 0.0, "last_ui": 0.0}

                def _on_bytes(delta: int):
                    now = time.perf_counter()
                    with dl_lock:
                        shared_prog["bytes"] = max(0, shared_prog["bytes"] + delta)
                        if now - shared_prog["last_ui"] < 0.28:
                            return
                        shared_prog["last_ui"] = now
                        cur_b = shared_prog["bytes"]
                        seg_p = shared_prog["seg_pct"]

                    el = max(0.08, now - t_dl_start)
                    tot_now = now - t0
                    spd = (cur_b / (1024 * 1024)) / el
                    if est_total > 0:
                        pct = min(98.5, cur_b * 100.0 / est_total)
                    else:
                        pct = min(98.5, seg_p)

                    task["percent"] = round(pct, 1)
                    task["live_speed_mbs"] = round(spd, 1)
                    task["speed_str"] = f"{spd:.1f} MB/s"
                    task["status_text"] = (
                        f"🚀 Đang kéo {task['resolution_badge']}: {task['percent']}% • {spd:.1f} MB/s • "
                        f"⏱ Tổng đã chạy: {tot_now:.1f}s (Load link: {load_sec:.2f}s)"
                    )
                    self._emit_update(task)

                def _on_v_segs(done_s: int, tot_s: int):
                    with dl_lock:
                        shared_prog["seg_pct"] = (done_s * 98.0 / max(1, tot_s))

                # CHẠY SONG SONG CẢ LUỒNG VIDEO (24 LUỒNG) VÀ LUỒNG AUDIO (8 LUỒNG) CÙNG LÚC!
                with ThreadPoolExecutor(max_workers=2) as pair_pool:
                    fut_v = pair_pool.submit(
                        self._download_one_track,
                        info,
                        vf,
                        v_part,
                        num_threads,
                        cancel_ev,
                        _on_bytes,
                        _on_v_segs,
                    )
                    fut_a = (
                        pair_pool.submit(
                            self._download_one_track,
                            info,
                            af,
                            a_part,
                            min(8, num_threads),
                            cancel_ev,
                            _on_bytes,
                            None,
                        )
                        if a_part
                        else None
                    )
                    fut_v.result()
                    if fut_a:
                        fut_a.result()

            t_mux_start = time.perf_counter()
            dl_only_sec = max(0.05, t_mux_start - t_dl_start)

            # BƯỚC 4: GHÉP SIÊU TỐC BẰNG FFMPEG STREAM COPY (< 0.3s)
            self._check_cancel(cancel_ev)
            task["state"] = "muxing"
            task["percent"] = 99.0
            task["phase_label"] = "🔧 Đang đóng gói MP4 siêu tốc..."
            task["status_text"] = f"🔧 Đang đóng gói MP4 siêu tốc... • ⏱ Đã chạy: {t_mux_start - t0:.1f}s"
            self._emit_update(task)

            ffmpeg_exe = os.path.join(self.caps["ffmpeg_dir"], "ffmpeg.exe")
            no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            is_ts_source = v_part.endswith(".ts") or bool(a_part and a_part.endswith(".ts"))
            cmd = [ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error"]
            if is_ts_source:
                cmd.extend(["-fflags", "+genpts"])
            cmd.extend(["-i", v_part])
            if a_part and os.path.exists(a_part):
                cmd.extend(["-i", a_part])

            if need_transcode and res_profile == "1080p_h264":
                task["phase_label"] = "🔄 Chuẩn hóa H.264 bằng phần cứng..."
                task["status_text"] = f"{task['phase_label']} • ⏱ Đã chạy: {time.perf_counter() - t0:.1f}s"
                self._emit_update(task)
                if self.caps["nvenc_ok"]:
                    cmd.extend(["-c:v", "h264_nvenc", "-preset", "p1", "-cq", "21"])
                else:
                    cmd.extend(["-c:v", "libx264", "-preset", "ultrafast", "-crf", "21"])
                cmd.extend(["-c:a", "aac", "-b:a", "192k"])
            else:
                cmd.extend(["-c", "copy"])
                if is_ts_source:
                    cmd.extend(["-bsf:a", "aac_adtstoasc"])

            # Ghi 1-pass trực tiếp ra ổ đĩa (không bật +faststart ghi đè lần 2 vô ích cho CapCut/Premiere)
            cmd.append(final_mp4)
            subprocess.run(cmd, check=True, creationflags=no_win)

            if not os.path.exists(final_mp4) or os.path.getsize(final_mp4) < 10240:
                raise RuntimeError("Đóng gói file MP4 thất bại!")

            t_done = time.perf_counter()
            mux_sec = max(0.01, t_done - t_mux_start)
            total_elapsed = max(0.05, t_done - t0)
            size_mb = os.path.getsize(final_mp4) / (1024 * 1024)
            net_speed_mbs = size_mb / dl_only_sec

            task.update(
                {
                    "state": "completed",
                    "percent": 100.0,
                    "live_speed_mbs": 0.0,
                    "file_path": final_mp4,
                    "size_mb": round(size_mb, 2),
                    "elapsed_sec": round(total_elapsed, 2),
                    "load_sec": round(load_sec, 2),
                    "dl_sec": round(dl_only_sec, 2),
                    "mux_sec": round(mux_sec, 2),
                    "speed_mbs": round(net_speed_mbs, 2),
                    "speed_str": f"{net_speed_mbs:.1f} MB/s",
                    "status_text": (
                        f"✅ {size_mb:.1f} MB • Tổng từ lúc bấm: {total_elapsed:.2f}s "
                        f"(Load link: {load_sec:.2f}s + Tải: {dl_only_sec:.2f}s + Ghép: {mux_sec:.2f}s) • {net_speed_mbs:.1f} MB/s"
                    ),
                }
            )
            self.history.upsert_record(
                username=task["username"],
                video_id=vid,
                video_url=task["url"],
                channel_name=task["channel"],
                note=task["note"],
                video_title=task["title"],
                resolution=task["resolution_badge"],
                file_path=final_mp4,
                size_mb=size_mb,
                elapsed_sec=total_elapsed,
                load_sec=load_sec,
                dl_sec=dl_only_sec,
                mux_sec=mux_sec,
                speed_mbs=net_speed_mbs,
                status="completed",
            )
            self._log(
                f"🏁 [XONG A->Z: {total_elapsed:.2f}s = Load {load_sec:.2f}s + Tải {dl_only_sec:.2f}s + Ghép {mux_sec:.2f}s] "
                f"{task['title']} ({size_mb:.1f} MB • {net_speed_mbs:.1f} MB/s)"
            )
            self._emit_update(task)
            if self.on_task_finished:
                self.on_task_finished(dict(task))

        except DownloadCancelledError:
            elapsed = time.perf_counter() - t0
            task.update(
                {
                    "state": "cancelled",
                    "live_speed_mbs": 0.0,
                    "speed_str": "Đã dừng",
                    "status_text": "⏹ Đã hủy tải bởi người dùng",
                    "elapsed_sec": round(elapsed, 2),
                }
            )
            self.history.upsert_record(
                username=task["username"],
                video_id=vid,
                video_url=task["url"],
                channel_name=task["channel"],
                note=task["note"],
                video_title=task["title"],
                elapsed_sec=elapsed,
                status="cancelled",
                error_msg="Đã hủy",
            )
            self._log(f"⏹ [ĐÃ HỦY] {task['title']}")
            self._emit_update(task)

        except Exception as err:
            elapsed = time.perf_counter() - t0
            err_str = str(err)
            task.update(
                {
                    "state": "failed",
                    "live_speed_mbs": 0.0,
                    "speed_str": "Lỗi",
                    "status_text": f"❌ {err_str}",
                    "elapsed_sec": round(elapsed, 2),
                }
            )
            self.history.upsert_record(
                username=task["username"],
                video_id=vid,
                video_url=task["url"],
                channel_name=task["channel"],
                note=task["note"],
                video_title=task["title"],
                elapsed_sec=elapsed,
                status="failed",
                error_msg=err_str,
            )
            self._log(f"❌ [LỖI TẢI] {task['title']}: {err_str}")
            self._emit_update(task)
            if self.on_task_failed:
                self.on_task_failed(dict(task))

        finally:
            for tf in temp_files:
                try:
                    if tf and os.path.exists(tf):
                        os.remove(tf)
                except Exception:
                    pass
            with self._lock:
                self._active_tasks.pop(vid, None)
                self._cancel_events.pop(vid, None)
            self._broadcast_aggregate_speed()

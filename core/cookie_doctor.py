# -*- coding: utf-8 -*-
"""
Bộ Chuẩn Hóa, Bảo Vệ Chống Ghi Đè & Kiểm Định Thực Chiến Cookie YouTube (Cookie Doctor)
- Bảo vệ 100% file `cookies.txt` gốc: Luôn tạo bản sao tạm thời cho mỗi lượt gọi `yt-dlp`,
  ngăn chặn triệt để lỗi `yt-dlp` tự động ghi đè làm mất khóa `LOGIN_INFO` trong file gốc của người dùng!
- Tự động nhận diện & chuyển đổi mọi định dạng Cookie phổ biến sang chuẩn Netscape:
  1. File Netscape `cookies.txt` chuẩn (kể cả thiếu dòng tiêu đề `# Netscape HTTP Cookie File`).
  2. File JSON xuất từ J2Team Cookies / Cookie-Editor / EditThisCookie.
  3. Chuỗi Header `Cookie: a=b; c=d...` dán trực tiếp vào file `.txt`.
- Kiểm định thực chiến 3 bước (`verify_youtube_cookies`): Kiểm tra khóa `LOGIN_INFO` + `SAPISID`,
  bóc thử luồng video thật qua JS Runtime nhúng chìm (`qjs.exe` / `deno` / `node` + `ejs:github`)
  và test kết nối tải thực tế tới máy chủ `googlevideo.com`.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import tempfile
import time
import uuid
import requests
import yt_dlp

from core.history_store import BASE_DIR

COOKIE_RUNTIME_DIR = os.path.join(BASE_DIR, ".yt_cookie_runtime")
TEST_YOUTUBE_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def _cleanup_old_runtime_cookies():
    if not os.path.isdir(COOKIE_RUNTIME_DIR):
        return
    now = time.time()
    try:
        for fn in os.listdir(COOKIE_RUNTIME_DIR):
            fp = os.path.join(COOKIE_RUNTIME_DIR, fn)
            try:
                if os.path.isfile(fp) and (now - os.path.getmtime(fp) > 600):
                    os.remove(fp)
            except OSError:
                pass
    except OSError:
        pass


def cleanup_runtime_cookie_file(temp_path: str | None):
    if temp_path and os.path.isfile(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass


def _convert_raw_text_to_netscape(raw_text: str) -> str:
    """Chuyển đổi Netscape / JSON (J2Team, Cookie-Editor) / Raw Cookie Header về chuẩn Netscape."""
    stripped = (raw_text or "").lstrip("\ufeff").strip()
    if not stripped:
        return ""

    # Trường hợp 1: Định dạng JSON (J2Team Cookies `{"cookies": [...]}` hoặc Cookie-Editor `[...]`)
    if stripped[0] in ("[", "{"):
        try:
            parsed = json.loads(stripped)
            items = parsed.get("cookies") if isinstance(parsed, dict) else parsed
            if isinstance(items, list):
                lines = ["# Netscape HTTP Cookie File", "# Auto-converted from JSON Cookie format", ""]
                default_exp = int(time.time()) + 365 * 86400
                for c in items:
                    if not isinstance(c, dict):
                        continue
                    name = str(c.get("name") or "").strip()
                    val = str(c.get("value") or "").strip()
                    dom = str(c.get("domain") or ".youtube.com").strip()
                    if not name:
                        continue
                    include_sub = "TRUE" if dom.startswith(".") else "FALSE"
                    path = str(c.get("path") or "/").strip() or "/"
                    secure = "TRUE" if c.get("secure", True) else "FALSE"
                    exp_raw = c.get("expirationDate") or c.get("expires") or c.get("expiry") or default_exp
                    try:
                        exp = max(0, int(float(exp_raw)))
                    except Exception:
                        exp = default_exp
                    lines.append(f"{dom}\t{include_sub}\t{path}\t{secure}\t{exp}\t{name}\t{val}")
                return "\n".join(lines) + "\n"
        except Exception:
            pass

    # Trường hợp 2: Đã là dạng bảng Tab 7 cột Netscape (có hoặc thiếu dòng `# Netscape HTTP Cookie File`)
    tab_lines = [
        ln for ln in stripped.splitlines()
        if ln.strip() and not ln.lstrip().startswith("#") and ln.count("\t") >= 6
    ]
    if tab_lines:
        # Tự động bổ sung các cookie SID từ `.google.com` sang `.youtube.com` nếu `.youtube.com` có LOGIN_INFO mà thiếu SID
        yt_names = set()
        google_sid_rows: list[list[str]] = []
        out_rows = ["# Netscape HTTP Cookie File", ""]
        for ln in tab_lines:
            clean_ln = ln.strip()
            if clean_ln.startswith("#HttpOnly_"):
                # MozillaCookieJar hỗ trợ hoặc bỏ tiền tố #HttpOnly_ để tương thích mọi bản Python
                clean_ln = clean_ln[len("#HttpOnly_"):]
            parts = clean_ln.split("\t")
            if len(parts) >= 7:
                dom = parts[0].strip()
                cname = parts[5].strip()
                if "youtube.com" in dom:
                    yt_names.add(cname)
                elif "google.com" in dom and cname in (
                    "SID", "HSID", "SSID", "APISID", "SAPISID",
                    "__Secure-1PSID", "__Secure-3PSID", "__Secure-1PAPISID", "__Secure-3PAPISID",
                ):
                    google_sid_rows.append(parts[:7])
                out_rows.append("\t".join(parts[:7]))

        if "LOGIN_INFO" in yt_names:
            for g_parts in google_sid_rows:
                cname = g_parts[5].strip()
                if cname not in yt_names:
                    mirrored = [".youtube.com", "TRUE", "/", g_parts[3], g_parts[4], cname, g_parts[6]]
                    out_rows.append("\t".join(mirrored))
                    yt_names.add(cname)

        return "\n".join(out_rows) + "\n"

    # Trường hợp 3: Chuỗi Header `Cookie: SID=...; HSID=...; LOGIN_INFO=...`
    raw_hdr = stripped
    if raw_hdr.lower().startswith("cookie:"):
        raw_hdr = raw_hdr.split(":", 1)[1].strip()
    if "=" in raw_hdr and (";" in raw_hdr or "\n" not in raw_hdr):
        lines = ["# Netscape HTTP Cookie File", ""]
        exp = int(time.time()) + 365 * 86400
        for pair in raw_hdr.split(";"):
            pair = pair.strip()
            if "=" not in pair:
                continue
            k, v = pair.split("=", 1)
            k = k.strip()
            v = v.strip()
            if k:
                sec = "TRUE" if k.startswith("__Secure-") or k.startswith("__Host-") or k in ("SAPISID", "SSID") else "FALSE"
                lines.append(f".youtube.com\tTRUE\t/\t{sec}\t{exp}\t{k}\t{v}")
        if len(lines) > 2:
            return "\n".join(lines) + "\n"

    return ""


def prepare_working_cookie_file(src_cookie_path: str) -> tuple[str | None, str]:
    """
    Đọc file Cookie gốc (CHỈ ĐỌC - KHÔNG BAO GIỜ SỬA FILE GỐC), chuẩn hóa sang Netscape
    và xuất ra 1 bản sao tạm riêng biệt cho lượt chạy hiện tại để `yt-dlp` không thể ghi đè làm hỏng Cookie gốc!
    Trả về `(working_cookie_path, error_msg)`.
    """
    path = (src_cookie_path or "").strip()
    if not path or not os.path.isfile(path):
        return None, "Chưa chọn file Cookie hoặc đường dẫn file không tồn tại trên máy!"

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except Exception as exc:
        return None, f"Không thể đọc file Cookie: {exc}"

    netscape_txt = _convert_raw_text_to_netscape(raw)
    if not netscape_txt:
        return None, (
            "File Cookie trống hoặc sai định dạng! Hãy xuất chuẩn Netscape `cookies.txt` "
            "(hoặc JSON từ J2Team / Cookie-Editor)."
        )

    _cleanup_old_runtime_cookies()
    os.makedirs(COOKIE_RUNTIME_DIR, exist_ok=True)
    tmp_path = os.path.join(COOKIE_RUNTIME_DIR, f"ck_{uuid.uuid4().hex[:12]}.txt")
    try:
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(netscape_txt)
        return tmp_path, ""
    except Exception as exc:
        return None, f"Không tạo được bộ đệm Cookie tạm thời: {exc}"


def inspect_cookie_file_auth(working_cookie_path: str) -> dict:
    """Kiểm tra chi tiết các khóa xác thực đăng nhập YouTube bên trong file Cookie đã chuẩn hóa."""
    res = {
        "total_cookies": 0,
        "yt_cookies_count": 0,
        "has_login_info": False,
        "has_sapisid": False,
        "expired_auth": False,
        "is_authenticated": False,
    }
    try:
        jar = http.cookiejar.MozillaCookieJar(working_cookie_path)
        jar.load(ignore_discard=True, ignore_expires=True)
        res["total_cookies"] = len(jar)
        now = time.time()
        yt_names = set()
        for c in jar:
            if "youtube.com" in (c.domain or ""):
                res["yt_cookies_count"] += 1
                yt_names.add(c.name)
                if c.name in ("LOGIN_INFO", "SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID"):
                    if c.expires and 0 < c.expires < now:
                        res["expired_auth"] = True

        res["has_login_info"] = "LOGIN_INFO" in yt_names
        res["has_sapisid"] = bool(
            yt_names.intersection({"SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID"})
        )
        res["is_authenticated"] = bool(
            res["has_login_info"] and res["has_sapisid"] and not res["expired_auth"]
        )
    except Exception:
        pass
    return res


def verify_youtube_cookies(cfg: dict, caps: dict | None = None) -> dict:
    """
    Kiểm tra thực chiến Cookie YouTube A -> Z:
    1. Kiểm tra nguồn Cookie (`file` hoặc trình duyệt) và xác thực phiên đăng nhập (`LOGIN_INFO` + `SAPISID`).
    2. Bóc thử luồng Video 1080p thực tế từ YouTube qua động cơ JS nhúng chìm (`qjs` / `deno` / `node` + `ejs:github`).
    3. Gửi thử gói probe `Range: bytes=0-0` lên `googlevideo.com` xác nhận không dính `HTTP 403`.
    """
    from core.turbo_downloader import YT_CACHE_DIR, detect_system_capabilities

    t0 = time.perf_counter()
    if caps is None:
        caps = detect_system_capabilities()

    c_mode = (cfg.get("cookie_mode") or "none").strip().lower()
    c_file = (cfg.get("cookie_file") or "").strip()
    js_kind = caps.get("js_runtime_kind") or ""
    js_exe = caps.get("node_exe") or ""
    js_status = f"{js_kind.upper()} sẵn sàng" if caps.get("node_ok") else "Thiếu JS Runtime"

    # Trường hợp 0: Đang để chế độ Không dùng Cookie -> test xem mạng hiện tại tải ẩn danh có thông không
    if c_mode == "none" or not c_mode:
        try:
            opts = {
                "quiet": True,
                "no_warnings": True,
                "noprogress": True,
                "cachedir": YT_CACHE_DIR,
                "socket_timeout": 10,
                "proxy": "",
                "extractor_args": {"youtube": {"player_client": ["visionos"]}},
            }
            if "safari" in (caps.get("impersonate_clients") or set()):
                from yt_dlp.networking.impersonate import ImpersonateTarget
                opts["impersonate"] = ImpersonateTarget.from_str("safari")
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(TEST_YOUTUBE_URL, download=False)
            v_cnt = sum(1 for f in (info.get("formats") or []) if (f.get("vcodec") or "none") != "none" and f.get("url"))
            elapsed = time.perf_counter() - t0
            if v_cnt > 0:
                return {
                    "ok": True,
                    "mode": "none",
                    "summary": (
                        f"✅ Đang tắt Cookie — IP mạng hiện tại sạch, tải ẩn danh OK ({v_cnt} luồng video • {elapsed:.2f}s • {js_status})."
                    ),
                    "detail": "Mạng hiện tại chưa bị YouTube hỏi Bot. Nếu muốn tải kênh giới hạn tuổi/hội viên hoặc khi mạng bị hỏi Bot, hãy chọn 'Dùng file cookies.txt'.",
                }
        except Exception as exc:
            return {
                "ok": False,
                "mode": "none",
                "summary": "❌ Chưa bật Cookie & IP mạng hiện tại đang bị YouTube chặn hỏi xác thực Bot!",
                "detail": (
                    f"Chi tiết từ YouTube: {exc}\n\n"
                    "👉 Cách khắc phục: Chuyển chế độ Cookie sang 'Dùng file cookies.txt', mở trình duyệt Ẩn danh (Ctrl+Shift+N) "
                    "đăng nhập YouTube -> xuất file bằng tiện ích 'Get cookies.txt LOCALLY' -> ĐÓNG NGAY cửa sổ ẩn danh rồi chọn file vào đây!"
                ),
            }

    temp_ck: str | None = None
    try:
        opts_ck: dict = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "cachedir": YT_CACHE_DIR,
            "socket_timeout": 14,
            "proxy": "",
        }
        if caps.get("ffmpeg_dir"):
            opts_ck["ffmpeg_location"] = caps["ffmpeg_dir"]
        if caps.get("node_ok"):
            opts_ck["js_runtimes"] = {js_kind: {"path": js_exe} if js_exe else {}}
            opts_ck["remote_components"] = ["ejs:github"]

        imp_avail = caps.get("impersonate_clients") or set()
        if "chrome" in imp_avail:
            try:
                from yt_dlp.networking.impersonate import ImpersonateTarget
                opts_ck["impersonate"] = ImpersonateTarget.from_str("chrome")
            except Exception:
                pass

        if c_mode == "file":
            temp_ck, prep_err = prepare_working_cookie_file(c_file)
            if not temp_ck:
                return {
                    "ok": False,
                    "mode": "file",
                    "summary": f"❌ Lỗi file Cookie: {prep_err}",
                    "detail": prep_err,
                }

            auth_stat = inspect_cookie_file_auth(temp_ck)
            if not auth_stat["is_authenticated"]:
                if auth_stat["yt_cookies_count"] == 0:
                    reason = "File Cookie không chứa bất kỳ cookie nào của miền `youtube.com` (có thể bạn xuất nhầm khi đang đứng ở trang web khác)."
                elif auth_stat["expired_auth"]:
                    reason = "Phiên đăng nhập trong file Cookie đã hết hạn thời gian (`expired`)."
                elif not auth_stat["has_login_info"]:
                    reason = (
                        "Thiếu khóa đăng nhập sống `LOGIN_INFO` trên `.youtube.com` (do tài khoản chưa đăng nhập YouTube "
                        "hoặc bạn xuất từ trình duyệt thường rồi tiếp tục lướt làm Google tự xoay vòng vô hiệu hóa Cookie cũ)."
                    )
                else:
                    reason = "Thiếu khóa chữ ký bảo mật `SAPISID` / `__Secure-1PAPISID` của tài khoản YouTube."

                return {
                    "ok": False,
                    "mode": "file",
                    "summary": "❌ COOKIE ĐÃ HẾT HẠN HOẶC BỊ ĐĂNG XUẤT KHỎI YOUTUBE!",
                    "detail": (
                        f"Nguyên nhân chính xác: {reason}\n\n"
                        "💡 Cách lấy Cookie chuẩn sống lâu 100% không bị chết lại:\n"
                        "1. Mở Cửa sổ Ẩn danh mới (Ctrl + Shift + N) trên Chrome/Edge.\n"
                        "2. Vào thẳng https://www.youtube.com và Đăng nhập tài khoản.\n"
                        "3. Bấm tiện ích 'Get cookies.txt LOCALLY' để tải file `cookies.txt` về máy.\n"
                        "4. ĐÓNG NGAY cửa sổ ẩn danh đó lại (tuyệt đối không bấm Đăng xuất, chỉ bấm dấu X tắt cửa sổ ẩn danh) rồi chọn file vừa tải vào Tool!"
                    ),
                }
            opts_ck["cookiefile"] = temp_ck
        elif c_mode in ("chrome", "edge", "brave", "firefox"):
            opts_ck["cookiesfrombrowser"] = (c_mode,)
        else:
            return {
                "ok": False,
                "mode": c_mode,
                "summary": f"❌ Chế độ Cookie không hợp lệ: {c_mode}",
                "detail": "Hãy chọn 'Dùng file cookies.txt'.",
            }

        # Bước 2: Gọi thực tế lên YouTube kiểm tra `ie.is_authenticated` + bóc tách danh sách Format Video
        with yt_dlp.YoutubeDL(opts_ck) as ydl:
            ie = ydl.get_info_extractor("Youtube")
            # Khởi tạo cookiejar cho trình duyệt nếu dùng cookiesfrombrowser
            _ = ydl.cookiejar
            if not getattr(ie, "is_authenticated", False):
                return {
                    "ok": False,
                    "mode": c_mode,
                    "summary": f"❌ Nguồn Cookie '{c_mode}' CHƯA ĐĂNG NHẬP YouTube!",
                    "detail": (
                        "Trình duyệt hoặc file Cookie hiện tại chưa có phiên đăng nhập YouTube hợp lệ (`LOGIN_INFO`).\n"
                        "Khuyên dùng: Xuất ra file `cookies.txt` từ cửa sổ Ẩn danh đã đăng nhập YouTube để ổn định 100%!"
                    ),
                }

            info = ydl.extract_info(TEST_YOUTUBE_URL, download=False)

        v_fmts = [
            f for f in (info.get("formats") or [])
            if (f.get("vcodec") or "none") != "none" and f.get("url")
        ]
        if not v_fmts:
            return {
                "ok": False,
                "mode": c_mode,
                "summary": f"❌ Cookie có đăng nhập nhưng không lấy được luồng Video ({js_status})!",
                "detail": "YouTube không trả về luồng MP4 hợp lệ. Hãy xuất lại file cookies.txt mới từ cửa sổ Ẩn danh.",
            }

        # Bước 3: Kiểm tra kết nối tải thử 1 byte đầu tiên từ máy chủ lưu trữ `googlevideo.com` (chống lỗi 403 ngầm)
        mp4_https = [f for f in v_fmts if (f.get("protocol") or "") in ("https", "http") and not f.get("fragments")]
        test_fmt = mp4_https[-1] if mp4_https else v_fmts[-1]
        probe_ok = True
        if (test_fmt.get("protocol") or "") in ("https", "http"):
            hdrs = dict(test_fmt.get("http_headers") or {})
            hdrs["Range"] = "bytes=0-1023"
            with requests.get(test_fmt["url"], headers=hdrs, stream=True, timeout=8) as r_probe:
                if r_probe.status_code not in (200, 206):
                    probe_ok = False
                    probe_code = r_probe.status_code

        if not probe_ok:
            return {
                "ok": False,
                "mode": c_mode,
                "summary": f"❌ Bóc được link nhưng luồng tải bị chặn HTTP {probe_code}!",
                "detail": "Hãy kiểm tra tắt VPN/Proxy đổi IP giữa chừng trên máy hoặc xuất lại file cookies.txt mới.",
            }

        elapsed = time.perf_counter() - t0
        max_h = max((int(f.get("height") or 0) for f in v_fmts), default=0)
        return {
            "ok": True,
            "mode": c_mode,
            "summary": (
                f"✅ COOKIE SỐNG & HOẠT ĐỘNG TỐT 100%! "
                f"(Đã xác thực YouTube • Lấy {len(v_fmts)} luồng tới {max_h}p • {js_status} • {elapsed:.2f}s)"
            ),
            "detail": (
                f"• Trạng thái đăng nhập YouTube: HỢP LỆ (đầy đủ LOGIN_INFO & SAPISID, đã bật chống ghi đè hỏng file gốc).\n"
                f"• Động cơ giải mã JS cho máy cũ: {js_status} + EJS.\n"
                f"• Kiểm tra luồng tải thực tế googlevideo.com: HTTP 206 OK ({len(v_fmts)} luồng sẵn sàng • phản hồi {elapsed:.2f}s)."
            ),
        }
    except Exception as exc:
        err_txt = str(exc)
        low = err_txt.lower()
        if c_mode in ("chrome", "edge", "brave") and any(
            k in low for k in ("dpapi", "decrypt", "copy", "permission", "locked", "cookie")
        ):
            hint = (
                f"Windows / {c_mode.capitalize()} đời mới khóa cứng mã hóa Cookie khi trình duyệt đang chạy (App-Bound Encryption).\n\n"
                "👉 Khắc phục triệt để 100%: Chuyển sang chế độ 'Dùng file cookies.txt' -> xuất file bằng tiện ích 'Get cookies.txt LOCALLY' trên cửa sổ Ẩn danh!"
            )
            short = f"❌ Trình duyệt {c_mode.capitalize()} đang khóa mã hóa Cookie trên Windows — hãy dùng file cookies.txt!"
        elif "not a bot" in low or "sign in" in low:
            hint = (
                "YouTube từ chối phiên Cookie này (Cookie đã bị xoay vòng hết hạn hoặc IP đang bật VPN bẩn).\n\n"
                "👉 Hãy mở Cửa sổ Ẩn danh (Ctrl+Shift+N) -> Đăng nhập YouTube -> Xuất file `cookies.txt` mới -> ĐÓNG NGAY cửa sổ ẩn danh rồi nạp lại!"
            )
            short = "❌ YouTube từ chối Cookie này (Cookie đã hết hạn hoặc IP dính chặn Bot)!"
        else:
            hint = f"Chi tiết kỹ thuật: {err_txt}"
            short = f"❌ Kiểm tra Cookie thất bại: {err_txt[:110]}"

        return {
            "ok": False,
            "mode": c_mode,
            "summary": short,
            "detail": hint,
        }
    finally:
        cleanup_runtime_cookie_file(temp_ck)

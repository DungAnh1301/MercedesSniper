# -*- coding: utf-8 -*-
"""
Bài test đua tốc độ thực tế chuẩn 1080p (không hơn không kém):
1. YT-DLP chuẩn (RAM + NodeJS solver + FFmpeg)
2. IDM (IDMan.exe đa luồng qua Local Header-Bridge chống lỗi 403 YouTube + FFmpeg)
3. YT-DLP + Turbo 16-Luồng Python (Bóc link + kéo 16 luồng Range song song trực tiếp + FFmpeg)
"""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import yt_dlp

IDM_EXE = r"C:\Program Files (x86)\Internet Download Manager\IDMan.exe"
FFMPEG_EXE = r"C:\ffmpeg\bin\ffmpeg.exe"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_outputs")

# Khóa cứng đúng chuẩn 1080p MP4 (H.264 + AAC) - không hơn không kém, công bằng 100% dung lượng
STRICT_1080P_FORMAT = (
    "bestvideo[height=1080][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/"
    "bestvideo[height=1080][ext=mp4]+bestaudio[ext=m4a]/"
    "best[height=1080]"
)


def ensure_clean_dir(path):
    if os.path.exists(path):
        shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)


def verify_resolution(filepath):
    """Dùng ffprobe kiểm tra chính xác độ phân giải file đầu ra."""
    ffprobe = os.path.join(os.path.dirname(FFMPEG_EXE), "ffprobe.exe")
    if not os.path.exists(ffprobe) or not os.path.exists(filepath):
        return "Unknown"
    try:
        res = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,codec_name",
                "-of",
                "csv=p=0",
                filepath,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return res.stdout.strip()
    except Exception:
        return "Unknown"


def is_file_ready(filepath, min_bytes=102400):
    if not os.path.exists(filepath):
        return False
    try:
        if os.path.getsize(filepath) < min_bytes:
            return False
        with open(filepath, "rb+"):
            pass
        return True
    except OSError:
        return False


def wait_for_files(filepaths, timeout=240):
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        if all(is_file_ready(fp) for fp in filepaths):
            return True, time.perf_counter() - start
        time.sleep(0.1)
    return False, time.perf_counter() - start


class StreamBridgeServer:
    """
    Cầu nối HTTP nội bộ siêu nhẹ giúp IDM tải link googlevideo.com đa luồng (Range)
    mà không bị YouTube chặn lỗi 403 Forbidden do lệch User-Agent.
    """

    def __init__(self, routes):
        self.routes = routes  # {'/video.mp4': (url, headers), ...}
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()

        routes_ref = self.routes

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
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
                req_headers = dict(base_headers)
                if "Range" in self.headers:
                    req_headers["Range"] = self.headers["Range"]

                req = urllib.request.Request(target_url, headers=req_headers, method="GET")
                try:
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        self.send_response(resp.status)
                        has_accept_ranges = False
                        for k in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
                            val = resp.headers.get(k)
                            if val:
                                if k.lower() == "accept-ranges":
                                    has_accept_ranges = True
                                self.send_header(k, val)
                        if not has_accept_ranges:
                            self.send_header("Accept-Ranges", "bytes")
                        self.end_headers()
                        if send_body:
                            while True:
                                chunk = resp.read(262144)  # 256KB buffer
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
                except Exception as e:
                    try:
                        self.send_error(502, str(e))
                    except Exception:
                        pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return f"http://127.0.0.1:{self.port}"

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_ytdlp(video_url):
    print("\n" + "=" * 70)
    print("🚀 [1] YT-DLP GỐC (Chuẩn 1080p + NodeJS Solver + FFmpeg)")
    print("=" * 70)
    sub_dir = os.path.join(OUT_DIR, "ytdlp")
    ensure_clean_dir(sub_dir)
    out_template = os.path.join(sub_dir, "ytdlp_1080p.%(ext)s")

    ydl_opts = {
        "format": STRICT_1080P_FORMAT,
        "outtmpl": out_template,
        "merge_output_format": "mp4",
        "js_runtimes": {"node": {}},
        "concurrent_fragment_downloads": 16,
        "http_chunk_size": 10485760,
        "ffmpeg_location": os.path.dirname(FFMPEG_EXE),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }

    t0 = time.perf_counter()
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])
    total_time = time.perf_counter() - t0

    final_file = os.path.join(sub_dir, "ytdlp_1080p.mp4")
    size_mb = os.path.getsize(final_file) / (1024 * 1024) if os.path.exists(final_file) else 0
    speed_mbs = size_mb / total_time if total_time > 0 else 0
    res_info = verify_resolution(final_file)

    print(
        f"✅ [YT-DLP XONG] Tổng: {total_time:.2f}s | File: {size_mb:.2f} MB | "
        f"Tốc độ TB: {speed_mbs:.2f} MB/s | Stream: {res_info}"
    )
    return {
        "name": "yt-dlp (Chuẩn)",
        "ok": size_mb > 0,
        "total_s": total_time,
        "size_mb": size_mb,
        "speed_mbs": speed_mbs,
        "res": res_info,
    }


def test_idm(video_url, timeout=240):
    print("\n" + "=" * 70)
    print("⚡ [2] IDM (Bóc link 1080p + Bắn IDMan.exe Đa Luồng + FFmpeg)")
    print("=" * 70)
    sub_dir = os.path.join(OUT_DIR, "idm")
    ensure_clean_dir(sub_dir)

    t0 = time.perf_counter()
    ydl_opts = {
        "format": STRICT_1080P_FORMAT,
        "js_runtimes": {"node": {}},
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=False)
    extract_time = time.perf_counter() - t0
    print(f"⏱️ Bóc link 1080p xong sau: {extract_time:.2f}s")

    req_formats = info.get("requested_formats")
    vf, af = req_formats[0], req_formats[1]

    bridge = StreamBridgeServer(
        {
            "/video.mp4": (vf["url"], vf.get("http_headers", {})),
            "/audio.m4a": (af["url"], af.get("http_headers", {})),
        }
    )
    base_url = bridge.start()

    v_file = os.path.join(sub_dir, "idm_video.mp4")
    a_file = os.path.join(sub_dir, "idm_audio.m4a")

    try:
        t_dl0 = time.perf_counter()
        subprocess.run([IDM_EXE, "/d", f"{base_url}/video.mp4", "/p", sub_dir, "/f", "idm_video.mp4", "/n"], check=False)
        subprocess.run([IDM_EXE, "/d", f"{base_url}/audio.m4a", "/p", sub_dir, "/f", "idm_audio.m4a", "/n"], check=False)

        ok, dl_time = wait_for_files([v_file, a_file], timeout=timeout)
    finally:
        bridge.stop()

    if not ok:
        print("❌ IDM tải quá thời gian chờ!")
        return {"name": "IDM (IDMan.exe)", "ok": False, "total_s": time.perf_counter() - t0, "size_mb": 0, "speed_mbs": 0, "res": "Failed"}

    t_m0 = time.perf_counter()
    final_file = os.path.join(sub_dir, "idm_1080p.mp4")
    subprocess.run(
        [FFMPEG_EXE, "-y", "-i", v_file, "-i", a_file, "-c", "copy", final_file],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    merge_time = time.perf_counter() - t_m0
    total_time = time.perf_counter() - t0

    size_mb = os.path.getsize(final_file) / (1024 * 1024)
    speed_mbs = size_mb / total_time if total_time > 0 else 0
    res_info = verify_resolution(final_file)

    print(
        f"✅ [IDM XONG] Tổng: {total_time:.2f}s (Bóc: {extract_time:.2f}s + IDM kéo: {dl_time:.2f}s + Ghép: {merge_time:.2f}s) | "
        f"File: {size_mb:.2f} MB | Tốc độ TB: {speed_mbs:.2f} MB/s | Stream: {res_info}"
    )
    return {
        "name": "IDM (IDMan.exe)",
        "ok": True,
        "extract_s": extract_time,
        "dl_s": dl_time,
        "merge_s": merge_time,
        "total_s": total_time,
        "size_mb": size_mb,
        "speed_mbs": speed_mbs,
        "res": res_info,
    }


if __name__ == "__main__":
    target_url = sys.argv[1] if len(sys.argv) >= 2 else "https://www.youtube.com/watch?v=zEZaiazazWI"
    r1 = test_ytdlp(target_url)
    r2 = test_idm(target_url)

    print("\n" + "=" * 70)
    print("🏁 KẾT QUẢ CHUNG CUỘC (CHUẨN 1080p MP4)")
    print("=" * 70)
    for r in (r1, r2):
        status = "OK" if r["ok"] else "FAIL"
        print(f"- {r['name']:<16}: [{status}] Tổng {r['total_s']:6.2f}s | {r['size_mb']:6.2f} MB | {r['speed_mbs']:6.2f} MB/s | {r['res']}")
    print("=" * 70)

# -*- coding: utf-8 -*-
"""
MERCEDES SNIPER STUDIO (Pure Push 0ms • 120FPS Isolated GUI + Separate Download Worker Process)
- Tiến trình GUI hoàn toàn độc lập, tuyệt đối không gánh luồng tải hay khóa GIL -> mượt tuyệt đối!
"""
import json
import multiprocessing
import os
import subprocess
import sys

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

if os.name == "nt" and getattr(sys, "frozen", False):
    _orig_popen = subprocess.Popen

    class _SilentPopen(_orig_popen):
        def __init__(self, args, *pargs, **kwargs):
            cmd0 = ""
            if isinstance(args, (list, tuple)) and args:
                cmd0 = str(args[0]).lower()
            elif isinstance(args, str):
                cmd0 = args.lower()
            # Chỉ ẩn cửa sổ CMD cho ffmpeg / ffprobe / tasklist / taskkill, KHÔNG ẩn Explorer hay CapCut!
            if (
                "explorer" not in cmd0
                and "capcut" not in cmd0
                and kwargs.get("creationflags", 0) == 0
            ):
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            super().__init__(args, *pargs, **kwargs)

    subprocess.Popen = _SilentPopen

from core.history_store import BASE_DIR

CONFIG_FILE = os.path.join(BASE_DIR, "sniper_config.json")


def load_config() -> dict:
    from core.vps_client import DEFAULT_SERVER_URL

    default_dl = os.path.join(os.path.expanduser("~"), "Downloads", "Soitube_1080p")
    cfg = {
        "server_url": DEFAULT_SERVER_URL,
        "username": "",
        "password": "",
        "remember": True,
        "save_dir": default_dl,
        "subfolder_by_channel": True,
        "auto_download": True,
        "sound_alert": True,
        "toast_popup": True,
        "auto_capcut": False,
        "capcut_template": "__blank__",
        "capcut_draft_root": "",
        "channel_templates": {},
        "selected_capcut_templates": [],
        "res_profile": "1080p_h264",
        "hd_mode": "wait_hd",
        "hd_wait_minutes": 12,
        "engine_mode": "turbo_hybrid",
        "threads_per_video": 24,
        "max_concurrent_videos": 3,
        "cookie_mode": "none",
        "cookie_file": "",
        "allow_long": True,
        "allow_short": False,
        "min_duration_sec": 0,
        "max_duration_sec": 0,
        "note_filter": "",
        "exclude_keywords": "",
        "disabled_channels": {},
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                cfg.update(saved)
        except Exception:
            pass
    return cfg


def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _acquire_single_instance_or_wakeup() -> tuple[object, object, object]:
    """
    Chặn mở chồng nhiều bản Tool ngầm bằng cơ chế chiếm quyền sở hữu Mutex thực sự (`WaitForSingleObject`):
    - Đánh dấu `HANDLE_FLAG_INHERIT = 0` để CapCut / FFmpeg không bao giờ kế thừa nhầm Handle.
    - Nếu bản trước bị tắt ngang (`Stop-Process` / crash), Windows trả `WAIT_ABANDONED (0x80)` -> tự tiếp quản mở bình thường 100%, không bao giờ bị kẹt Mutex ma!
    - Chỉ khi có 1 tiến trình GUI đang sống thực sự giữ Mutex (`WAIT_TIMEOUT = 0x102`) mới kích hoạt Wakeup gọi cửa sổ cũ lên.
    """
    if os.name != "nt":
        return None, None, None
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        k32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        k32.CreateEventW.restype = wintypes.HANDLE

        k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        k32.CreateMutexW.restype = wintypes.HANDLE

        k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k32.WaitForSingleObject.restype = wintypes.DWORD

        k32.SetEvent.argtypes = [wintypes.HANDLE]
        k32.SetEvent.restype = wintypes.BOOL

        k32.ReleaseMutex.argtypes = [wintypes.HANDLE]
        k32.ReleaseMutex.restype = wintypes.BOOL

        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.CloseHandle.restype = wintypes.BOOL

        k32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
        k32.SetHandleInformation.restype = wintypes.BOOL

        HANDLE_FLAG_INHERIT = 0x00000001
        WAIT_OBJECT_0 = 0x00000000
        WAIT_ABANDONED = 0x00000080
        WAIT_TIMEOUT = 0x00000102

        ev_handle = k32.CreateEventW(None, False, False, "Local\\MercedesSniper_LiveOwner_Wakeup_v6")
        if ev_handle:
            k32.SetHandleInformation(ev_handle, HANDLE_FLAG_INHERIT, 0)

        mx_handle = k32.CreateMutexW(None, False, "Local\\MercedesSniper_LiveOwner_Mutex_v6")
        if not mx_handle:
            return k32, None, ev_handle
        k32.SetHandleInformation(mx_handle, HANDLE_FLAG_INHERIT, 0)

        wait_res = k32.WaitForSingleObject(mx_handle, 0)
        if wait_res in (WAIT_OBJECT_0, WAIT_ABANDONED):
            return k32, mx_handle, ev_handle

        if wait_res == WAIT_TIMEOUT:
            if ev_handle:
                k32.SetEvent(ev_handle)
                k32.CloseHandle(ev_handle)
            k32.CloseHandle(mx_handle)
            sys.exit(0)

        return k32, mx_handle, ev_handle
    except SystemExit:
        raise
    except Exception:
        return None, None, None


def _release_single_instance(k32, mx_handle, ev_handle):
    if not k32:
        return
    try:
        if mx_handle:
            k32.ReleaseMutex(mx_handle)
            k32.CloseHandle(mx_handle)
        if ev_handle:
            k32.CloseHandle(ev_handle)
    except Exception:
        pass


def main():
    # Chỉ nạp PyQt6 bên trong tiến trình GUI chính (tiến trình Worker con sẽ nhẹ bẫng, không nạp PyQt6!)
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QDialog

    if "--self-test" in sys.argv:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _app = QApplication(sys.argv)
        from core.turbo_downloader import detect_system_capabilities
        from core.worker_bridge import IsolatedDownloaderProxy
        import yt_dlp  # noqa: F401

        caps = detect_system_capabilities()
        if not caps.get("ffmpeg_ok"):
            sys.exit(2)
        proxy = IsolatedDownloaderProxy(load_config())
        proxy.shutdown()
        sys.exit(0)

    k32_dll, mx_handle, ev_handle = _acquire_single_instance_or_wakeup()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app._single_instance_refs = (k32_dll, mx_handle, ev_handle)
    app.aboutToQuit.connect(lambda: _release_single_instance(k32_dll, mx_handle, ev_handle))

    from core.vps_client import DEFAULT_SERVER_URL, SoitubeVPSClient
    from ui.login_dialog import LoginDialog
    from ui.main_window import SniperMainWindow
    from ui.theme import STUDIO_STYLESHEET

    app.setStyleSheet(STUDIO_STYLESHEET)

    cfg = load_config()
    vps = SoitubeVPSClient()

    logged_in = False
    if cfg.get("remember") and cfg.get("username") and cfg.get("password"):
        ok, _ = vps.login(
            cfg.get("server_url") or DEFAULT_SERVER_URL,
            cfg["username"],
            cfg["password"],
        )
        logged_in = ok

    if not logged_in:
        dlg = LoginDialog(vps, cfg, save_config)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            _release_single_instance(k32_dll, mx_handle, ev_handle)
            sys.exit(0)

    win = SniperMainWindow(vps, cfg, save_config)
    app._main_win_ref = win
    if ev_handle and k32_dll and os.name == "nt":
        import threading

        def _watch_wakeup():
            while True:
                res = k32_dll.WaitForSingleObject(ev_handle, 0xFFFFFFFF)
                if res == 0:
                    QTimer.singleShot(0, win._restore_from_tray)
                else:
                    break

        threading.Thread(target=_watch_wakeup, daemon=True, name="SingleInstanceWakeup").start()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()

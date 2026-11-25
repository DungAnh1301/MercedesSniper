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


def _acquire_single_instance_or_wakeup() -> tuple[object, object]:
    """Chặn mở chồng nhiều bản Tool ngầm dưới khay hệ thống (bấm đúp icon Desktop sẽ gọi cửa sổ cũ hiện lên ngay!)."""
    if os.name != "nt":
        return None, None
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        ERROR_ALREADY_EXISTS = 183
        ev_handle = k32.CreateEventW(None, False, False, "Local\\MercedesSniper_MaxSpeed_Wakeup_v5")
        mx_handle = k32.CreateMutexW(None, False, "Local\\MercedesSniper_MaxSpeed_Mutex_v5")
        if k32.GetLastError() == ERROR_ALREADY_EXISTS:
            if ev_handle:
                k32.SetEvent(ev_handle)
                k32.CloseHandle(ev_handle)
            if mx_handle:
                k32.CloseHandle(mx_handle)
            sys.exit(0)
        return mx_handle, ev_handle
    except Exception:
        return None, None


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

    mx_handle, ev_handle = _acquire_single_instance_or_wakeup()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app._single_instance_refs = (mx_handle, ev_handle)

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
            sys.exit(0)

    win = SniperMainWindow(vps, cfg, save_config)
    app._main_win_ref = win
    if ev_handle and os.name == "nt":
        import ctypes
        import threading

        def _watch_wakeup():
            k32 = ctypes.windll.kernel32
            while True:
                res = k32.WaitForSingleObject(ev_handle, 0xFFFFFFFF)
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

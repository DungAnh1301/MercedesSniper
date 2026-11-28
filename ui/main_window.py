# -*- coding: utf-8 -*-
"""
Cửa sổ chính MERCEDES SNIPER STUDIO (Pure Push 0ms & Max Speed Card UI)
- Bố cục khoa học: Thanh Sidebar Điều Hướng Trái (215px) + 4 Màn Hình Chuyên Biệt rộng thoáng.
- Nhận tín hiệu trực tiếp 0ms từ VPS (/api/pc/stream), tuyệt đối không dùng RSS, không qua Telegram.
"""
from datetime import datetime
import os
import re
import shutil
import sys
import threading
import time
import webbrowser

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from core.capcut_injector import (
    BLANK_TEMPLATE_KEY,
    get_capcut_draft_root,
    has_visible_capcut_window,
    list_capcut_templates,
    scan_all_capcut_projects,
    set_custom_draft_root,
    set_extra_selected_templates,
)
from core.history_store import HistoryStore, extract_video_id
from core.updater import (
    APP_VERSION,
    check_github_update,
    download_update_asset,
    launch_self_updater,
)
from core.vps_client import SoitubeVPSClient
from core.worker_bridge import IsolatedDownloaderProxy
from ui.login_dialog import LoginDialog
from ui.pages import (
    CapCutTemplatesPage,
    ChannelsPage,
    LiveQueuePage,
    RulesPage,
    SettingsPage,
)
from ui.theme import (
    STUDIO_STYLESHEET,
    SidebarNavButton,
    ToggleSwitch,
    create_mercedes_icon,
    play_alert_beep,
)
from ui.toast_popup import DesktopToastPopup


class UIBridgeSignals(QObject):
    sig_vps_status = pyqtSignal(bool, str)
    sig_ping = pyqtSignal(int)
    sig_channels = pyqtSignal(list)
    sig_new_video = pyqtSignal(dict)
    sig_server_videos = pyqtSignal(list)
    sig_auth_expired = pyqtSignal(str)

    sig_dl_update = pyqtSignal(dict)
    sig_dl_finished = pyqtSignal(dict)
    sig_dl_failed = pyqtSignal(dict)
    sig_thumb_ready = pyqtSignal(str, bytes)
    sig_total_speed = pyqtSignal(float, int)

    sig_log = pyqtSignal(str)
    sig_async_done = pyqtSignal(bool, str)
    sig_capcut_done = pyqtSignal(str, bool, str, str)
    sig_capcut_scan_ready = pyqtSignal(list, list, str, bool)
    sig_update_check_done = pyqtSignal(dict, bool)
    sig_update_dl_progress = pyqtSignal(int, float, float)
    sig_update_dl_done = pyqtSignal(bool, str)


class SniperMainWindow(QMainWindow):
    def __init__(self, vps_client: SoitubeVPSClient, cfg: dict, save_cfg_fn):
        super().__init__()
        self.vps = vps_client
        self.cfg = cfg
        self._save_cfg = save_cfg_fn

        self.icon = create_mercedes_icon()
        self.setWindowIcon(self.icon)
        self.setWindowTitle(f"Mercedes Sniper v{APP_VERSION} — {self.vps.username}")
        self.resize(1120, 660)
        self.setMinimumSize(880, 500)
        QApplication.instance().setStyleSheet(STUDIO_STYLESHEET)

        self.signals = UIBridgeSignals()
        self.history = HistoryStore()
        self.downloader = IsolatedDownloaderProxy(self.cfg)

        self._channels_cache: list[dict] = []
        self._channels_sig: list[tuple] = []
        self._task_cache: dict[str, dict] = {}
        set_custom_draft_root(self.cfg.get("capcut_draft_root") or "")
        set_extra_selected_templates(
            self.cfg.get("selected_capcut_templates") or [],
            explicit_mode=bool(self.cfg.get("capcut_tpl_explicit_v2")),
        )
        self._available_templates: list[str] = list_capcut_templates()
        self._force_quit = False
        self._tray_notified_once = False
        self._scan_in_progress = False
        self._channels_dirty = False
        self._scanned_projs_cache: list[dict] = []
        self._scanned_root_cache: str = ""
        self._templates_dirty = False
        self._update_checking = False
        self._update_downloading = False
        self._update_silent_mode = False
        self._staged_ready_exe: str = ""
        self._pending_update_info: dict | None = None
        self._update_notified_tag: str = ""
        self._update_popup_dlg: QDialog | None = None

        if not self.cfg.get("per_channel_tpl_v1"):
            self.cfg["per_channel_tpl_v1"] = True
            self.cfg["capcut_template"] = BLANK_TEMPLATE_KEY
            self.cfg.setdefault("channel_templates", {})
            self._save_cfg(self.cfg)

        self._build_layout()
        self._setup_tray()
        self._connect_signals()
        self.page_queue.update_tpl_button_count(len(self._available_templates))
        self.nav_templates.set_badge(len(self._available_templates), highlight=False)
        self._load_past_history()
        self._refresh_disk_space()
        # Quét ngầm danh sách Project CapCut sau khi cửa sổ đã mở mượt mà (0.00ms khựng GUI!)
        QTimer.singleShot(250, lambda: self._handle_reload_capcut_templates(show_feedback=False))
        # Kiểm tra phiên bản mới trên GitHub Releases ngầm mỗi 90 giây (0.00ms khựng GUI!) -> có bản mới là hiện ngay để bấm tải!
        QTimer.singleShot(1500, lambda: self._start_update_check(manual=False))
        self._upd_timer = QTimer(self)
        self._upd_timer.timeout.connect(lambda: self._start_update_check(manual=False))
        self._upd_timer.start(90 * 1000)

        # Timer nhẹ nhàng (220ms = ~4.5Hz) chỉ đọc hàng đợi kết quả từ Tiến trình Worker Độc lập
        self._ipc_timer = QTimer(self)
        self._ipc_timer.timeout.connect(self.downloader.drain_events)
        self._ipc_timer.start(220)

        # Bắt đầu nghe luồng Push 0ms trực tiếp từ VPS
        self.vps.start_watching()
        self._append_log("⚡ GUI Độc lập 120FPS • Tiến trình Tải Tách Rời & Đường truyền Push 0ms sẵn sàng!")

    # ==========================================================
    # 🏛️ BỐ CỤC SIDEBAR TRÁI + STACKED PAGES THOÁNG SẠCH
    # ==========================================================
    def _build_layout(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1. THANH SIDEBAR TRÁI NHỎ GỌN (204px)
        sidebar = QFrame()
        sidebar.setFixedWidth(204)
        sidebar.setObjectName("LeftSidebar")
        sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sb_lay = QVBoxLayout(sidebar)
        sb_lay.setContentsMargins(10, 14, 10, 12)
        sb_lay.setSpacing(4)

        # Thương hiệu gọn gàng
        lbl_logo = QLabel("MERCEDES SNIPER")
        lbl_logo.setStyleSheet(
            "color: #FFFFFF; font-size: 13.5px; font-weight: 900; letter-spacing: 1.2px; "
            "background: transparent; padding-left: 4px;"
        )
        lbl_tag = QLabel(f"v{APP_VERSION} • Pure Push 0ms")
        lbl_tag.setStyleSheet(
            "color: #CBD5E1; font-size: 10.5px; font-weight: 600; "
            "background: transparent; padding-left: 4px; margin-bottom: 8px;"
        )
        sb_lay.addWidget(lbl_logo)
        sb_lay.addWidget(lbl_tag)

        # 5 Nút chuyển màn hình gọn 34px
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        self.nav_queue = SidebarNavButton("⚡", "Trung Tâm Tải")
        self.nav_channels = SidebarNavButton("📺", "Kênh Đang Canh")
        self.nav_templates = SidebarNavButton("✂️", "Kho Mẫu CapCut")
        self.nav_rules = SidebarNavButton("🎯", "Quy Tắc Tự Tải")
        self.nav_settings = SidebarNavButton("⚙️", "Cài Đặt Hệ Thống")

        for idx, btn in enumerate(
            (self.nav_queue, self.nav_channels, self.nav_templates, self.nav_rules, self.nav_settings)
        ):
            self.nav_group.addButton(btn, idx)
            sb_lay.addWidget(btn)

        self.nav_queue.setChecked(True)
        sb_lay.addStretch(1)

        # Khối trạng thái & Công tắc Tự Động Tải nhỏ gọn góc dưới Sidebar
        bot_card = QFrame()
        bot_card.setObjectName("SidebarBotCard")
        bot_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bc_lay = QVBoxLayout(bot_card)
        bc_lay.setContentsMargins(9, 8, 9, 8)
        bc_lay.setSpacing(5)

        auto_row = QHBoxLayout()
        lbl_auto = QLabel("Tự Động Tải")
        lbl_auto.setStyleSheet("color: #FFFFFF; font-size: 12px; font-weight: 800;")
        self.sw_auto = ToggleSwitch(checked=bool(self.cfg.get("auto_download", True)), active_color="#10B981")
        self.sw_auto.toggled.connect(self._save_all_prefs)
        auto_row.addWidget(lbl_auto)
        auto_row.addStretch()
        auto_row.addWidget(self.sw_auto)
        bc_lay.addLayout(auto_row)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #334155; border: none;")
        bc_lay.addWidget(sep)

        self.lbl_disk = QLabel("💾 Ổ lưu trống: -- GB")
        self.lbl_disk.setStyleSheet("color: #E2E8F0; font-size: 11px; font-weight: 600;")
        bc_lay.addWidget(self.lbl_disk)

        usr_row = QHBoxLayout()
        lbl_u = QLabel(f"👤 {self.vps.username}")
        lbl_u.setStyleSheet("color: #FFFFFF; font-size: 11.5px; font-weight: 700;")
        btn_out = QPushButton("Đổi nick")
        btn_out.setFixedHeight(23)
        btn_out.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_out.clicked.connect(self._handle_logout)
        usr_row.addWidget(lbl_u, 1)
        usr_row.addWidget(btn_out)
        bc_lay.addLayout(usr_row)

        self.btn_update = QPushButton(f"🔄 Cập nhật (v{APP_VERSION})")
        self.btn_update.setFixedHeight(25)
        self.btn_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_update.setToolTip("Kiểm tra & tự động cập nhật phiên bản mới nhất từ GitHub Releases")
        self.btn_update.setStyleSheet(
            "QPushButton { background-color: #1E293B; color: #CBD5E1; border: 1px solid #334155; "
            "border-radius: 5px; font-size: 11px; font-weight: 700; padding: 2px 6px; }"
            "QPushButton:hover { background-color: #334155; color: #FFFFFF; border-color: #475569; }"
        )
        self.btn_update.clicked.connect(self._on_update_button_clicked)
        bc_lay.addWidget(self.btn_update)

        sb_lay.addWidget(bot_card)
        root.addWidget(sidebar)

        # 2. VÙNG TRANG CHÍNH (STACKED PAGES)
        self.stack = QStackedWidget()

        self.page_queue = LiveQueuePage(
            on_manual_submit=self._handle_manual_urls,
            on_open_folder=self._open_save_root,
            on_clear_finished=self._clear_non_completed_cards,
            on_open_templates_tab=lambda: self._switch_to_tab(2),
            on_refresh_server_feed=self._handle_refresh_server_feed,
            on_clear_all_old=self._clear_all_old_videos,
        )
        self.page_channels = ChannelsPage(
            on_add_channel=self._handle_add_channel,
            on_renew_all=self._handle_renew_webhooks,
            on_bulk_toggle=self._handle_bulk_channel_toggle,
            on_refresh_channels=self._handle_refresh_channels,
            on_reload_templates=self._handle_reload_capcut_templates,
        )
        self.page_templates = CapCutTemplatesPage(
            on_scan_capcut=lambda: self._handle_reload_capcut_templates(show_feedback=True),
            on_pick_draft_root=self._on_pick_custom_capcut_root,
            on_open_capcut_draft_dir=self._open_capcut_draft_dir,
            on_save_templates=self._on_save_selected_capcut_templates,
        )
        self.page_rules = RulesPage(
            cfg=self.cfg,
            on_prefs_changed=self._save_all_prefs,
        )
        self.page_settings = SettingsPage(
            cfg=self.cfg,
            on_prefs_changed=self._save_all_prefs,
            on_pick_dir=self._choose_save_dir,
            on_pick_cookie=self._choose_cookie_file,
        )

        self.stack.addWidget(self.page_queue)
        self.stack.addWidget(self.page_channels)
        self.stack.addWidget(self.page_templates)
        self.stack.addWidget(self.page_rules)
        self.stack.addWidget(self.page_settings)

        self.nav_group.idClicked.connect(self._on_nav_tab_switched)

        # Thanh thông báo Cập nhật 1-Click nổi bật ngay trên đầu giao diện
        self.update_banner = QFrame()
        self.update_banner.setVisible(False)
        self.update_banner.setStyleSheet(
            "QFrame { background-color: #064E3B; border-bottom: 1px solid #10B981; }"
        )
        ub_lay = QHBoxLayout(self.update_banner)
        ub_lay.setContentsMargins(16, 9, 14, 9)
        ub_lay.setSpacing(12)

        ub_txt_col = QVBoxLayout()
        ub_txt_col.setContentsMargins(0, 0, 0, 0)
        ub_txt_col.setSpacing(2)
        self.lbl_upd_title = QLabel("🚀 Đã có phiên bản mới!")
        self.lbl_upd_title.setStyleSheet(
            "color: #ECFDF5; font-size: 13px; font-weight: 800; background: transparent; border: none;"
        )
        self.lbl_upd_notes = QLabel("")
        self.lbl_upd_notes.setStyleSheet(
            "color: #A7F3D0; font-size: 11.5px; background: transparent; border: none;"
        )
        ub_txt_col.addWidget(self.lbl_upd_title)
        ub_txt_col.addWidget(self.lbl_upd_notes)
        ub_lay.addLayout(ub_txt_col, 1)

        self.bar_upd_progress = QProgressBar()
        self.bar_upd_progress.setVisible(False)
        self.bar_upd_progress.setRange(0, 100)
        self.bar_upd_progress.setFixedSize(170, 18)
        self.bar_upd_progress.setTextVisible(True)
        self.bar_upd_progress.setStyleSheet(
            "QProgressBar { background-color: #022C22; color: #FFFFFF; border: 1px solid #10B981; "
            "border-radius: 6px; text-align: center; font-size: 10.5px; font-weight: 700; }"
            "QProgressBar::chunk { background-color: #10B981; border-radius: 5px; }"
        )
        ub_lay.addWidget(self.bar_upd_progress)

        self.btn_upd_banner_dl = QPushButton("⬇ Tải & Cập nhật ngay")
        self.btn_upd_banner_dl.setFixedHeight(32)
        self.btn_upd_banner_dl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_upd_banner_dl.setStyleSheet(
            "QPushButton { background-color: #10B981; color: #022C22; border: none; "
            "border-radius: 6px; font-size: 12px; font-weight: 800; padding: 0 14px; }"
            "QPushButton:hover { background-color: #34D399; color: #022C22; }"
            "QPushButton:disabled { background-color: #047857; color: #D1FAE5; }"
        )
        self.btn_upd_banner_dl.clicked.connect(self._on_one_click_update_triggered)
        ub_lay.addWidget(self.btn_upd_banner_dl)

        self.btn_upd_banner_hide = QPushButton("✕")
        self.btn_upd_banner_hide.setFixedSize(26, 26)
        self.btn_upd_banner_hide.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_upd_banner_hide.setToolTip("Ẩn thanh thông báo (vẫn có thể bấm nút Cập nhật ở góc dưới trái)")
        self.btn_upd_banner_hide.setStyleSheet(
            "QPushButton { background: transparent; color: #A7F3D0; border: none; font-size: 13px; font-weight: 700; }"
            "QPushButton:hover { color: #FFFFFF; background-color: rgba(255,255,255,0.12); border-radius: 4px; }"
        )
        self.btn_upd_banner_hide.clicked.connect(lambda: self.update_banner.setVisible(False))
        ub_lay.addWidget(self.btn_upd_banner_hide)

        right_panel = QWidget()
        rp_lay = QVBoxLayout(right_panel)
        rp_lay.setContentsMargins(0, 0, 0, 0)
        rp_lay.setSpacing(0)
        rp_lay.addWidget(self.update_banner)
        rp_lay.addWidget(self.stack, 1)

        root.addWidget(right_panel, 1)

    def _switch_to_tab(self, idx: int):
        btn = self.nav_group.button(idx)
        if btn:
            btn.setChecked(True)
        self._on_nav_tab_switched(idx)

    def _on_nav_tab_switched(self, idx: int):
        # Chuyển trang tức thì, chỉ dựng danh sách của Tab phụ đúng lúc người dùng bấm mở Tab đó!
        self.stack.setCurrentIndex(idx)
        if idx == 1:
            if self._channels_dirty:
                self._render_channels_page_now()
            if not self._channels_cache:
                threading.Thread(target=self.vps.fetch_my_channels, daemon=True).start()
        elif idx == 2:
            if self._templates_dirty:
                self._render_templates_page_now()
            elif not self._scanned_projs_cache:
                self._handle_reload_capcut_templates(show_feedback=False)

    # ==========================================================
    # 🔗 KẾT NỐI LUỒNG NGẦM & TÍN HIỆU 0MS
    # ==========================================================
    def _connect_signals(self):
        self.vps.on_status_change = self.signals.sig_vps_status.emit
        self.vps.on_ping_updated = self.signals.sig_ping.emit
        self.vps.on_channels_updated = self.signals.sig_channels.emit
        self.vps.on_video_prefetch = self._on_bg_video_prefetch
        self.vps.on_new_video = self.signals.sig_new_video.emit
        self.vps.on_server_videos = self.signals.sig_server_videos.emit
        self.vps.on_auth_expired = self.signals.sig_auth_expired.emit
        self.vps.on_log = self.signals.sig_log.emit

        self.downloader.on_task_update = self._ui_upsert_card
        self.downloader.on_task_finished = self._ui_on_download_finished
        self.downloader.on_task_failed = self._ui_on_download_failed
        self.downloader.on_thumb_ready = self._ui_on_thumb_ready
        self.downloader.on_total_speed = self._ui_on_total_speed
        self.downloader.on_log = self._append_log
        self.downloader.on_enqueue_rejected = lambda msg: QMessageBox.warning(self, "Thông báo", msg)
        self.downloader.on_capcut_done = self._ui_on_capcut_done

        self.signals.sig_vps_status.connect(self.page_queue.set_connection_badge)
        self.signals.sig_ping.connect(self._on_ping_updated)
        self.signals.sig_channels.connect(self._ui_on_channels)
        self.signals.sig_new_video.connect(self._ui_on_new_video)
        self.signals.sig_server_videos.connect(self._ui_on_server_videos)
        self.signals.sig_auth_expired.connect(self._ui_on_auth_expired)

        self.signals.sig_dl_update.connect(self._ui_upsert_card)
        self.signals.sig_dl_finished.connect(self._ui_on_download_finished)
        self.signals.sig_dl_failed.connect(self._ui_on_download_failed)
        self.signals.sig_thumb_ready.connect(self._ui_on_thumb_ready)
        self.signals.sig_total_speed.connect(self._ui_on_total_speed)

        self.signals.sig_log.connect(self._append_log)
        self.signals.sig_async_done.connect(self._ui_on_async_done)
        self.signals.sig_capcut_done.connect(self._ui_on_capcut_done)
        self.signals.sig_capcut_scan_ready.connect(self._ui_on_capcut_scan_ready)
        self.signals.sig_update_check_done.connect(self._ui_on_update_check_done)
        self.signals.sig_update_dl_progress.connect(self._ui_on_update_dl_progress)
        self.signals.sig_update_dl_done.connect(self._ui_on_update_dl_done)

    def _on_bg_video_prefetch(self, payload: dict):
        """Chạy ngay ở 0.00ms khi nhận `video_detected` (nếu kênh không bị tắt canh thì bóc link luôn!)."""
        url = payload.get("url") or ""
        if not url:
            return
        disabled = self._get_disabled_set()
        cid = payload.get("channel_id") or ""
        cname = payload.get("channel") or ""
        if (cid and cid in disabled) or (cname and cname in disabled):
            return
        note_flt = (self.cfg.get("note_filter") or "").strip().lower()
        v_note = (payload.get("note") or "").strip().lower()
        if note_flt and note_flt not in v_note:
            return
        self.downloader.prefetch_url(url)

    def _on_ping_updated(self, ms: int):
        if "Trực chiến" in self.page_queue.lbl_conn_pill.text():
            self.page_queue.set_connection_badge(True, f"Trực chiến Real-time ({ms}ms)")

    def _append_log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.page_settings.txt_logs.appendPlainText(f"[{ts}] {msg}")

    # ==========================================================
    # 💾 LƯU CẤU HÌNH ĐỒNG BỘ TỪ CÁC TRANG
    # ==========================================================
    def _save_all_prefs(self, *_args):
        self.cfg["auto_download"] = self.sw_auto.isChecked()
        self.cfg["allow_long"] = self.page_rules.sw_long.isChecked()
        self.cfg["allow_short"] = self.page_rules.sw_short.isChecked()
        self.cfg["min_duration_sec"] = self.page_rules.spn_min.value()
        self.cfg["max_duration_sec"] = self.page_rules.spn_max.value()
        self.cfg["exclude_keywords"] = self.page_rules.inp_exclude.text().strip()
        self.cfg["note_filter"] = self.page_rules.inp_note_flt.text().strip()

        self.cfg["subfolder_by_channel"] = self.page_settings.sw_subfolder.isChecked()
        self.cfg["res_profile"] = self.page_settings.cmb_res.currentData()
        self.cfg["hd_mode"] = self.page_settings.cmb_hd_mode.currentData()
        self.cfg["engine_mode"] = self.page_settings.cmb_engine.currentData()
        self.cfg["threads_per_video"] = self.page_settings.spn_threads.value()
        self.cfg["max_concurrent_videos"] = self.page_settings.spn_conc.value()
        self.cfg["sound_alert"] = self.page_settings.sw_sound.isChecked()
        self.cfg["toast_popup"] = self.page_settings.sw_popup.isChecked()
        self.cfg["auto_capcut"] = self.page_settings.sw_auto_capcut.isChecked()
        self.cfg["cookie_mode"] = self.page_settings.cmb_cookie.currentData()
        self.cfg["cookie_file"] = self.page_settings.inp_cookie_file.text().strip()

        self._save_cfg(self.cfg)
        self.downloader.update_runtime_config(self.cfg)
        self._refresh_all_cards_capcut_labels()
        self._refresh_disk_space()

    def _refresh_disk_space(self):
        save_p = self.cfg.get("save_dir") or os.path.expanduser("~")
        probe = save_p if os.path.exists(save_p) else os.path.splitdrive(save_p)[0] + "\\"
        try:
            free_gb = shutil.disk_usage(probe).free / (1024**3)
            self.lbl_disk.setText(f"💾 Ổ lưu trống: {free_gb:.1f} GB")
        except Exception:
            pass

    def _choose_save_dir(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "Chọn thư mục lưu Video", self.page_settings.inp_save_dir.text()
        )
        if chosen:
            self.page_settings.inp_save_dir.setText(chosen)
            self.cfg["save_dir"] = chosen
            self._save_cfg(self.cfg)
            self._refresh_disk_space()

    def _choose_cookie_file(self):
        fp, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file Cookies YouTube (cookies.txt hoặc JSON)",
            "",
            "Cookie Files (*.txt *.json);;All Files (*)",
        )
        if fp:
            self.page_settings.inp_cookie_file.setText(fp)
            self.page_settings.cmb_cookie.setCurrentIndex(
                self.page_settings.cmb_cookie.findData("file")
            )
            self._save_all_prefs()
            self.page_settings.run_cookie_test()

    def _open_save_root(self):
        d = self.cfg.get("save_dir") or os.path.join(os.path.expanduser("~"), "Downloads", "Soitube_1080p")
        os.makedirs(d, exist_ok=True)
        os.startfile(d)

    # ==========================================================
    # 📺 QUẢN LÝ KÊNH & MẪU CAPCUT RIÊNG TỪNG KÊNH (MÀN HÌNH 2)
    # ==========================================================
    def _get_disabled_set(self) -> set:
        return set(self.cfg.get("disabled_channels", {}).get(self.vps.username, []))

    def _get_channel_tpl_map(self) -> dict:
        all_maps = self.cfg.setdefault("channel_templates", {})
        if not isinstance(all_maps, dict):
            all_maps = {}
            self.cfg["channel_templates"] = all_maps
        u_map = all_maps.setdefault(self.vps.username, {})
        if not isinstance(u_map, dict):
            u_map = {}
            all_maps[self.vps.username] = u_map
        return u_map

    def _resolve_task_template(self, task: dict) -> str:
        """
        Quy tắc chuẩn theo từng kênh:
        - Kênh A gắn `mau_1` -> dùng `mau_1`
        - Kênh B gắn `mau_2` -> dùng `mau_2`
        - Kênh đang canh nhưng KHÔNG gắn mẫu -> luôn trả về `BLANK_TEMPLATE_KEY` (Project trắng để tự edit!)
        - Link dán lẻ của kênh ngoài danh sách canh -> theo ô `✂️ Tải lẻ` (mặc định cũng là Project trắng).
        """
        cid = (task.get("channel_id") or "").strip()
        cname = (task.get("channel") or "").strip()
        tpl_map = self._get_channel_tpl_map()

        matched_ch = None
        if cid:
            for c in self._channels_cache:
                if c.get("channel_id") == cid:
                    matched_ch = c
                    break
        if matched_ch is None and cname and cname not in ("YouTube", "Tải Nhanh"):
            for c in self._channels_cache:
                if c.get("channel_name") == cname:
                    matched_ch = c
                    if not cid:
                        cid = (c.get("channel_id") or "").strip()
                    break

        assigned = (tpl_map.get(cid) if cid else None) or (
            tpl_map.get(cname) if (not cid and cname) else None
        )
        if assigned and assigned != BLANK_TEMPLATE_KEY:
            return assigned if assigned in self._available_templates else BLANK_TEMPLATE_KEY

        return BLANK_TEMPLATE_KEY

    def _decorate_task_capcut_badge(self, task: dict):
        tpl = self._resolve_task_template(task)
        task["selected_tpl"] = tpl
        task["templates_list"] = list(self._available_templates)

    def _refresh_all_cards_capcut_labels(self):
        for vid, t in list(self._task_cache.items()):
            self._decorate_task_capcut_badge(t)
            card = self.page_queue.cards_map.get(vid)
            if card is not None:
                card.refresh_card_templates(self._available_templates, t["selected_tpl"])

    def _on_channel_template_changed(self, cid: str, cname: str, tpl_key: str):
        tpl_map = self._get_channel_tpl_map()
        val = (tpl_key or "").strip() or BLANK_TEMPLATE_KEY
        key = cid or cname
        if val == BLANK_TEMPLATE_KEY:
            if cid:
                tpl_map.pop(cid, None)
            if cname:
                tpl_map.pop(cname, None)
            self._append_log(f"✂️ Kênh '{cname}': Đặt về Project trắng (Tự edit)")
        else:
            if key:
                tpl_map[key] = val
            self._append_log(f"✂️ Kênh '{cname}': Đã gắn Mẫu CapCut '{val}'")
        self._save_cfg(self.cfg)
        self.page_channels.update_summary_label()
        self._refresh_all_cards_capcut_labels()

    def _handle_reload_capcut_templates(self, show_feedback: bool = True):
        if self._scan_in_progress:
            return
        self._scan_in_progress = True
        custom_root = str(self.cfg.get("capcut_draft_root") or "")
        extra_sel = list(self.cfg.get("selected_capcut_templates") or [])
        explicit_v2 = bool(self.cfg.get("capcut_tpl_explicit_v2"))

        def _bg_scan():
            try:
                set_custom_draft_root(custom_root)
                set_extra_selected_templates(extra_sel, explicit_mode=explicit_v2)
                det_root = get_capcut_draft_root()
                projs = scan_all_capcut_projects()
                tpls = list_capcut_templates(extra_sel, explicit_mode=explicit_v2, scanned_projects=projs)
                self.signals.sig_capcut_scan_ready.emit(tpls, projs, det_root, show_feedback)
            except Exception:
                self._scan_in_progress = False

        threading.Thread(target=_bg_scan, daemon=True, name="CapCutBgScan").start()

    def _migrate_and_normalize_capcut_selection(self, all_projs: list):
        """Chuyển đổi mượt từ cơ chế cũ sang chọn trực tiếp 100% (không khóa mau_1, tự ánh xạ tên hiển thị)."""
        changed_cfg = False
        if not self.cfg.get("capcut_tpl_explicit_v2"):
            seeded = [str(x).strip() for x in (self.cfg.get("selected_capcut_templates") or []) if str(x or "").strip()]
            for p in all_projs:
                if p.get("is_named_template"):
                    fn = str(p.get("folder_name") or "").strip()
                    if fn and fn not in seeded:
                        seeded.append(fn)
            self.cfg["selected_capcut_templates"] = seeded
            self.cfg["capcut_tpl_explicit_v2"] = True
            set_extra_selected_templates(seeded, explicit_mode=True)
            changed_cfg = True

        # Chuẩn hóa tên mẫu gắn trên các kênh nếu trước đó lưu theo folder_name khác với template_key
        folder_to_key = {
            str(p.get("folder_name") or ""): str(p.get("template_key") or p.get("display_name") or "")
            for p in all_projs
            if p.get("folder_name")
        }
        all_maps = self.cfg.get("channel_templates")
        if isinstance(all_maps, dict):
            for _u, cmap in all_maps.items():
                if isinstance(cmap, dict):
                    for k, v in list(cmap.items()):
                        if v in folder_to_key and folder_to_key[v] and folder_to_key[v] != v:
                            cmap[k] = folder_to_key[v]
                            changed_cfg = True

        if changed_cfg:
            self._save_cfg(self.cfg)
            self.downloader.update_runtime_config(self.cfg)

    def _ui_on_capcut_scan_ready(
        self,
        new_tpls: list,
        all_projs: list,
        detected_root: str,
        show_feedback: bool,
    ):
        self._scan_in_progress = False
        self._scanned_projs_cache = list(all_projs)
        self._scanned_root_cache = detected_root
        self._migrate_and_normalize_capcut_selection(self._scanned_projs_cache)
        new_tpls = list_capcut_templates(
            self.cfg.get("selected_capcut_templates") or [],
            explicit_mode=bool(self.cfg.get("capcut_tpl_explicit_v2")),
            scanned_projects=self._scanned_projs_cache,
        )

        tpls_changed = new_tpls != self._available_templates
        self._available_templates = list(new_tpls)

        if self.stack.currentIndex() == 2:
            self._render_templates_page_now()
        else:
            self._templates_dirty = True

        self.page_queue.update_tpl_button_count(len(self._available_templates))
        self.nav_templates.set_badge(len(self._available_templates), highlight=False)
        if tpls_changed:
            if self.page_channels.row_widgets:
                self.page_channels.refresh_template_dropdowns(
                    self._available_templates,
                    self._get_channel_tpl_map(),
                )
            self._refresh_all_cards_capcut_labels()

        if show_feedback:
            cnt = len(self._available_templates)
            names = ", ".join(self._available_templates) if cnt else "Chưa chọn mẫu (dùng Project trắng)"
            self._append_log(
                f"✂️ Đã quét CapCut tại [{detected_root}] ({len(all_projs)} project • đang chọn {cnt} mẫu): {names}"
            )
            self.page_channels.btn_reload_tpl.setText(f"✓ Đã nạp ({cnt} mẫu)")
            self.page_templates.btn_scan.setText(f"✓ Đã quét ({len(all_projs)} project)")
            QTimer.singleShot(
                1300,
                lambda: (
                    self.page_channels.btn_reload_tpl.setText("✂️ Nạp DS Mẫu"),
                    self.page_templates.btn_scan.setText("🔄 Quét CapCut"),
                ),
            )

    def _sync_selected_templates_state(self, selected_folders: list[str]):
        self.cfg["selected_capcut_templates"] = list(selected_folders)
        self.cfg["capcut_tpl_explicit_v2"] = True
        set_extra_selected_templates(selected_folders, explicit_mode=True)
        self._save_cfg(self.cfg)
        self.downloader.update_runtime_config(self.cfg)

        new_tpls = list_capcut_templates(
            selected_folders,
            explicit_mode=True,
            scanned_projects=self._scanned_projs_cache,
        )
        tpls_changed = new_tpls != self._available_templates
        self._available_templates = list(new_tpls)
        cnt = len(self._available_templates)
        self.page_templates.update_selection_counts(cnt)
        self.page_queue.update_tpl_button_count(cnt)
        self.nav_templates.set_badge(cnt, highlight=False)
        if tpls_changed:
            if self.page_channels.row_widgets:
                self.page_channels.refresh_template_dropdowns(
                    self._available_templates,
                    self._get_channel_tpl_map(),
                )
            self._refresh_all_cards_capcut_labels()

    def _on_toggle_extra_capcut_tpl(self, folder_name: str, checked: bool):
        aliases = {folder_name}
        for p in self._scanned_projs_cache:
            if p.get("folder_name") == folder_name:
                if p.get("display_name"):
                    aliases.add(str(p["display_name"]))
                if p.get("template_key"):
                    aliases.add(str(p["template_key"]))
                break

        cur = [str(x) for x in (self.cfg.get("selected_capcut_templates") or []) if x]
        if checked:
            if folder_name not in cur:
                cur.append(folder_name)
        else:
            cur = [x for x in cur if x not in aliases]
        self._sync_selected_templates_state(cur)

    def _on_save_selected_capcut_templates(self):
        if self.page_templates.proj_rows:
            cur = [r.folder_name for r in self.page_templates.proj_rows if r.sw_use.isChecked() and r.folder_name]
        else:
            cur = [str(x) for x in (self.cfg.get("selected_capcut_templates") or []) if x]
        self._sync_selected_templates_state(cur)
        cnt = len(self._available_templates)
        names = ", ".join(self._available_templates) if cnt else "Project trắng"
        self._append_log(f"✅ Đã lưu {cnt} mẫu CapCut (dùng trực tiếp Project gốc, không tạo bản sao): {names}")
        self.page_templates.btn_save_tpl.setText(f"✓ Đã lưu ({cnt} mẫu)!")
        QTimer.singleShot(
            1400,
            lambda: self.page_templates.update_selection_counts(len(self._available_templates)),
        )

    def _on_pick_custom_capcut_root(self):
        cur_ov = (self.cfg.get("capcut_draft_root") or "").strip()
        if cur_ov:
            ans = QMessageBox.question(
                self,
                "Khôi phục tự động dò theo globalSetting?",
                f"Hiện đang trỏ thủ công vào:\n{cur_ov}\n\n"
                "• Chọn Yes: Quay về chế độ TỰ ĐỘNG đọc theo globalSetting của CapCut.\n"
                "• Chọn No: Chọn một thư mục nháp khác trên ổ cứng.",
            )
            if ans == QMessageBox.StandardButton.Yes:
                self.cfg["capcut_draft_root"] = ""
                set_custom_draft_root("")
                self._save_cfg(self.cfg)
                self.downloader.update_runtime_config(self.cfg)
                self._handle_reload_capcut_templates(show_feedback=True)
                return

        chosen_dir = QFileDialog.getExistingDirectory(
            self,
            "Chọn thư mục chứa nháp CapCut (ví dụ com.lveditor.draft hoặc CapCut Drafts)",
            get_capcut_draft_root(),
        )
        if not chosen_dir:
            return
        self.cfg["capcut_draft_root"] = chosen_dir
        set_custom_draft_root(chosen_dir)
        self._save_cfg(self.cfg)
        self.downloader.update_runtime_config(self.cfg)
        self._handle_reload_capcut_templates(show_feedback=True)

    def _open_capcut_draft_dir(self):
        root = get_capcut_draft_root()
        os.makedirs(root, exist_ok=True)
        os.startfile(root)

    def _handle_refresh_server_feed(self):
        self.page_queue.btn_sync_feed.setEnabled(False)
        self.page_queue.btn_sync_feed.setText("⏳ Đang tải...")

        def _work():
            self.vps.fetch_server_videos(limit=50)
            self.signals.sig_async_done.emit(True, "Đã làm mới danh sách video từ DB Server!")

        threading.Thread(target=_work, daemon=True).start()

    def _ui_on_channels(self, channels: list):
        pending_tpl = getattr(self, "_pending_add_tpl", BLANK_TEMPLATE_KEY)
        before_cids = getattr(self, "_pending_add_cids_before", None)
        if pending_tpl != BLANK_TEMPLATE_KEY and isinstance(before_cids, set):
            tpl_map = self._get_channel_tpl_map()
            changed = False
            for ch in channels:
                ncid = ch.get("channel_id") or ""
                if ncid and ncid not in before_cids:
                    tpl_map[ncid] = pending_tpl
                    changed = True
            if changed:
                self._pending_add_tpl = BLANK_TEMPLATE_KEY
                self._pending_add_cids_before = None
                self._save_cfg(self.cfg)

        new_sig = [
            (
                ch.get("id"),
                ch.get("channel_id"),
                ch.get("channel_name"),
                ch.get("note"),
                ch.get("avatar_url"),
            )
            for ch in channels
        ]
        self._channels_cache = channels
        disabled = self._get_disabled_set()
        enabled_cnt = sum(
            1
            for ch in channels
            if (ch.get("channel_id") not in disabled) and (ch.get("channel_name") not in disabled)
        )
        self.nav_channels.set_badge(enabled_cnt, highlight=False)
        if new_sig == self._channels_sig and len(self.page_channels.row_widgets) == len(channels):
            self.page_channels.update_summary_label()
            self._refresh_all_cards_capcut_labels()
            return

        self._channels_sig = new_sig
        self._refresh_all_cards_capcut_labels()
        if self.stack.currentIndex() == 1:
            self._render_channels_page_now()
        else:
            self._channels_dirty = True

    def _render_channels_page_now(self):
        self._channels_dirty = False
        self.page_channels.populate_channels(
            channels=self._channels_cache,
            disabled_set=self._get_disabled_set(),
            on_toggle_fn=self._on_single_channel_toggled,
            on_note_fn=self._on_channel_note_edited,
            on_open_yt_fn=lambda cid: webbrowser.open(f"https://www.youtube.com/channel/{cid}/videos") if cid else None,
            on_delete_fn=self._on_channel_delete_clicked,
            templates_list=self._available_templates,
            channel_tpl_map=self._get_channel_tpl_map(),
            on_tpl_fn=self._on_channel_template_changed,
        )

    def _render_templates_page_now(self):
        self._templates_dirty = False
        extra_sel = set(self.cfg.get("selected_capcut_templates") or [])
        self.page_templates.populate_projects(
            projects=self._scanned_projs_cache,
            selected_extra_set=extra_sel,
            on_toggle_tpl_fn=self._on_toggle_extra_capcut_tpl,
            detected_root=self._scanned_root_cache,
            explicit_mode=bool(self.cfg.get("capcut_tpl_explicit_v2")),
        )

    def _on_single_channel_toggled(self, cid: str, cname: str, checked: bool):
        disabled = self._get_disabled_set()
        if checked:
            disabled.discard(cid)
            disabled.discard(cname)
        else:
            if cid:
                disabled.add(cid)
            if cname:
                disabled.add(cname)
        self.cfg.setdefault("disabled_channels", {})[self.vps.username] = list(disabled)
        self._save_cfg(self.cfg)

        en_cnt = sum(1 for r in self.page_channels.row_widgets if r.sw_enable.isChecked())
        self.nav_channels.set_badge(en_cnt, highlight=False)
        self.page_channels.update_summary_label()

    def _handle_bulk_channel_toggle(self, enable_all: bool):
        disabled = self._get_disabled_set()
        for r in self.page_channels.row_widgets:
            if not r.isVisible():
                continue
            r.sw_enable.blockSignals(True)
            r.sw_enable.setChecked(enable_all)
            r.sw_enable._animate_to_state(enable_all)
            r.sw_enable.blockSignals(False)
            if enable_all:
                disabled.discard(r.cid)
                disabled.discard(r.cname)
            else:
                if r.cid:
                    disabled.add(r.cid)
                if r.cname:
                    disabled.add(r.cname)

        self.cfg.setdefault("disabled_channels", {})[self.vps.username] = list(disabled)
        self._save_cfg(self.cfg)
        en_cnt = sum(1 for r in self.page_channels.row_widgets if r.sw_enable.isChecked())
        self.nav_channels.set_badge(en_cnt, highlight=False)
        self.page_channels.update_summary_label()

    def _on_channel_note_edited(self, row_id: int, cid: str, new_note: str):
        for ch in self._channels_cache:
            if ch.get("channel_id") == cid:
                ch["note"] = new_note
        threading.Thread(
            target=lambda: self.vps.update_channel_note(row_id, cid, new_note),
            daemon=True,
        ).start()

    def _on_channel_delete_clicked(self, row_id: int, cid: str, cname: str):
        ans = QMessageBox.question(
            self,
            "Xóa kênh theo dõi",
            f"Bạn muốn xóa kênh '{cname}' khỏi danh sách canh?",
        )
        if ans == QMessageBox.StandardButton.Yes:
            tpl_map = self._get_channel_tpl_map()
            if cid:
                tpl_map.pop(cid, None)
            if cname:
                tpl_map.pop(cname, None)
            self._save_cfg(self.cfg)
            self._channels_cache = [c for c in self._channels_cache if c.get("channel_id") != cid]
            self._ui_on_channels(self._channels_cache)
            threading.Thread(
                target=lambda: self.vps.delete_channel(row_id, cid),
                daemon=True,
            ).start()

    def _handle_add_channel(self):
        raw_url = self.page_channels.inp_url.text().strip()
        note_txt = self.page_channels.inp_note.text().strip()
        if not raw_url:
            return
        self._pending_add_tpl = self.page_channels.get_add_bar_template()
        self._pending_add_cids_before = {
            c.get("channel_id") for c in self._channels_cache if c.get("channel_id")
        }
        self.page_channels.btn_add.setEnabled(False)
        self.page_channels.btn_add.setText("Đang thêm...")

        def _work():
            ok, msg = self.vps.add_channel(raw_url, note_txt)
            self.signals.sig_async_done.emit(ok, msg)

        threading.Thread(target=_work, daemon=True).start()

    def _handle_refresh_channels(self):
        self.page_channels.btn_refresh.setEnabled(False)
        self.page_channels.btn_refresh.setText("⏳ Đang đồng bộ...")

        def _work():
            self._channels_sig = []
            chs = self.vps.fetch_my_channels()
            self.signals.sig_async_done.emit(
                True, f"Đã đồng bộ danh sách kênh từ Web ({len(chs)} kênh)!"
            )

        threading.Thread(target=_work, daemon=True).start()

    def _handle_renew_webhooks(self):
        self.page_channels.btn_renew.setEnabled(False)
        self.page_channels.btn_renew.setText("⏳ Đang gia hạn...")

        def _work():
            ok, msg = self.vps.renew_webhooks_only()
            self.signals.sig_async_done.emit(ok, msg)

        threading.Thread(target=_work, daemon=True).start()

    def _ui_on_async_done(self, ok: bool, msg: str):
        self.page_queue.btn_sync_feed.setEnabled(True)
        self.page_queue.btn_sync_feed.setText("🔄 Tải DS Server")
        self.page_channels.btn_add.setEnabled(True)
        self.page_channels.btn_add.setText("Thêm Kênh")
        self.page_channels.btn_refresh.setEnabled(True)
        self.page_channels.btn_refresh.setText("⚡ Đồng Bộ Web")
        self.page_channels.btn_renew.setEnabled(True)
        self.page_channels.btn_renew.setText("🔄 Gia Hạn Webhook")
        if ok:
            self.page_channels.inp_url.clear()
            self.page_channels.reset_add_bar_template()
            self._append_log(f"✅ {msg}")
        else:
            self._pending_add_tpl = BLANK_TEMPLATE_KEY
            self._pending_add_cids_before = None
            self._append_log(f"⚠️ {msg}")
            QMessageBox.warning(self, "Thông báo", msg)

    # ==========================================================
    # ⚡ XỬ LÝ TÍN HIỆU VIDEO MỚI & QUẢN LÝ THẺ CARD TẢI
    # ==========================================================
    def _handle_manual_urls(self):
        raw = self.page_queue.inp_url.text().strip()
        if not raw:
            return
        tokens = [t.strip() for t in re.split(r"[\s,;]+", raw) if t.strip()]
        is_bulk = len(tokens) > 1
        added = 0
        last_err = ""
        for u in tokens:
            ok, msg = self.downloader.enqueue(
                username=self.vps.username,
                video_url=u,
                channel_name="Tải Nhanh",
                save_dir=self.cfg.get("save_dir", ""),
                subfolder_by_channel=bool(self.cfg.get("subfolder_by_channel", True)),
                res_profile=self.cfg.get("res_profile", "1080p_h264"),
                hd_mode=self.cfg.get("hd_mode", "wait_hd"),
                force_redownload=(not is_bulk),
                notify_reject=(not is_bulk),
            )
            if ok:
                added += 1
            else:
                last_err = msg
        if added > 0:
            self.page_queue.inp_url.clear()
        elif last_err:
            QMessageBox.warning(self, "Thông báo", last_err)

    def _check_auto_rules(self, v: dict) -> tuple[bool, str]:
        if not self.sw_auto.isChecked():
            return False, "Đang tắt Tự Động Tải"

        disabled = self._get_disabled_set()
        cid = v.get("channel_id") or ""
        cname = v.get("channel") or ""
        if (cid and cid in disabled) or (cname and cname in disabled):
            return False, "Kênh đang tắt canh"

        note_flt = (self.cfg.get("note_filter") or "").strip().lower()
        v_note = (v.get("note") or "").strip().lower()
        if note_flt and note_flt not in v_note:
            return False, f"Khác nhãn Note ({note_flt})"

        v_type = (v.get("v_type") or "Unknown").upper()
        if "LIVE" in v_type or "PREMIERE" in v_type or v_type == "POST":
            return False, f"Định dạng {v_type}"
        if v_type == "SHORT" and not self.cfg.get("allow_short", False):
            return False, "Đang tắt tự kéo Shorts"
        if v_type == "LONG" and not self.cfg.get("allow_long", True):
            return False, "Đang tắt tự kéo Video Dài"

        dur_sec = int(v.get("duration_sec") or 0)
        min_d = int(self.cfg.get("min_duration_sec") or 0)
        max_d = int(self.cfg.get("max_duration_sec") or 0)
        if dur_sec > 0:
            if min_d > 0 and dur_sec < min_d:
                return False, f"Ngắn hơn {min_d}s"
            if max_d > 0 and dur_sec > max_d:
                return False, f"Dài hơn {max_d}s"

        ex_raw = (self.cfg.get("exclude_keywords") or "").strip()
        if ex_raw:
            t_low = (v.get("title") or "").lower()
            for kw in [k.strip().lower() for k in ex_raw.split(",") if k.strip()]:
                if kw in t_low:
                    return False, f"Chứa từ khóa '{kw}'"

        return True, "OK"

    @staticmethod
    def _resolve_video_delay_sec(v: dict) -> int | None:
        srv_delay = v.get("delay_sec")
        pub_ts = v.get("published_ts")
        if pub_ts is not None:
            try:
                pc_delay = max(0, int(time.time() - float(pub_ts)))
                if srv_delay is None or abs(pc_delay - int(srv_delay)) <= 120:
                    return pc_delay
            except Exception:
                pass
        if srv_delay is not None:
            try:
                return max(0, int(srv_delay))
            except Exception:
                pass
        return None

    def _ui_on_new_video(self, v: dict):
        cname = v.get("channel") or "YouTube"
        title = v.get("title") or "Video Mới"
        note = v.get("note") or ""
        v_type = v.get("v_type") or "VIDEO"
        url = v.get("url") or ""
        vid = extract_video_id(url)
        delay_s = self._resolve_video_delay_sec(v)
        delay_txt = f"delay : {delay_s} (s)" if delay_s is not None else ""

        disabled = self._get_disabled_set()
        if (v.get("channel_id") in disabled) or (cname in disabled):
            return

        if delay_txt:
            self._append_log(f"⚡ [{cname}] {title} • {delay_txt}")

        should_dl, reason = self._check_auto_rules(v)

        if should_dl:
            if self.cfg.get("sound_alert", True):
                play_alert_beep(is_complete=False)
            if self.cfg.get("toast_popup", True):
                ch_disp = f"{cname} • {note}" if note else cname
                if delay_txt:
                    ch_disp = f"{ch_disp} • {delay_txt}"
                pop = DesktopToastPopup(
                    f"⚡ VIDEO MỚI [{v_type}] • ĐANG KÉO MAX SPEED",
                    ch_disp,
                    title,
                    accent="#E11D48",
                    thumb_bytes=self.downloader.get_cached_thumbnail(vid),
                    duration_ms=7500,
                    video_url=url,
                )
                pop.show()

            self.downloader.enqueue(
                username=self.vps.username,
                video_url=url,
                channel_name=cname,
                channel_id=v.get("channel_id") or "",
                video_title=title,
                note=note,
                save_dir=self.cfg.get("save_dir", ""),
                subfolder_by_channel=bool(self.cfg.get("subfolder_by_channel", True)),
                res_profile=self.cfg.get("res_profile", "1080p_h264"),
                hd_mode=self.cfg.get("hd_mode", "wait_hd"),
                force_redownload=False,
            )
        else:
            # Đưa vào mục "Bỏ qua / Lỗi" để người dùng có thể bấm "⬇ Tải" thủ công bất cứ lúc nào!
            if vid:
                self.downloader.request_thumbnail(vid)
                v_type_up = str(v_type).upper()
                is_live_watch = ("LIVE" in v_type_up) or ("PREMIERE" in v_type_up)
                if is_live_watch:
                    if self.cfg.get("sound_alert", True):
                        play_alert_beep(is_complete=False)
                    if self.cfg.get("toast_popup", True):
                        ch_disp = f"{cname} • {note}" if note else cname
                        if delay_txt:
                            ch_disp = f"{ch_disp} • {delay_txt}"
                        pop = DesktopToastPopup(
                            f"🔴 CANH VIDEO {v_type_up} • BẤM TẢI THỦ CÔNG",
                            ch_disp,
                            title,
                            accent="#F59E0B",
                            thumb_bytes=self.downloader.get_cached_thumbnail(vid),
                            duration_ms=9000,
                            video_url=url,
                        )
                        pop.show()
                    st_parts = [f"🔴 Canh video {v_type_up} (Không tự tải — bấm ⬇ Tải khi xong Live)"]
                else:
                    st_parts = [f"⏭ Bỏ qua tự tải ({reason})"]
                if delay_txt:
                    st_parts.append(delay_txt)
                if v.get("v_dur"):
                    st_parts.append(str(v.get("v_dur")))
                skipped_task = {
                    "video_id": vid,
                    "url": url,
                    "channel": cname,
                    "channel_id": v.get("channel_id") or "",
                    "note": note,
                    "title": title,
                    "resolution_badge": v_type,
                    "percent": 0.0,
                    "state": "skipped",
                    "status_text": " • ".join(st_parts),
                    "file_path": "",
                }
                self._ui_upsert_card(skipped_task)

    def _ui_on_server_videos(self, videos: list):
        """
        Hiển thị lại danh sách thông tin video đang lưu trong DB Server (`video_log`)
        lên Trung Tâm Tải: người dùng thích tải bài nào thì bấm nút `⬇ Tải`, không tải thì cứ để nguyên đó.
        """
        if not videos:
            return

        disabled = self._get_disabled_set()
        dismissed_ids = self.history.get_dismissed_ids(self.vps.username)
        note_flt = (self.cfg.get("note_filter") or "").strip().lower()
        new_thumb_vids: list[str] = []

        # Gom nhóm cập nhật hàng loạt (setUpdatesEnabled(False) + chỉ lọc 1 lần duy nhất ở cuối -> tốn <8ms!)
        self.page_queue.cards_container.setUpdatesEnabled(False)
        try:
            for v in videos[-30:]:
                url = v.get("url") or ""
                vid = v.get("video_id") or extract_video_id(url)
                if not vid or vid in dismissed_ids:
                    continue

                cid = v.get("channel_id") or ""
                cname = v.get("channel") or "YouTube"
                if (cid and cid in disabled) or (cname in disabled):
                    continue

                v_note = (v.get("note") or "").strip()
                if note_flt and note_flt not in v_note.lower():
                    continue

                v_type = (v.get("v_type") or "LONG").upper()
                if v_type == "SHORT" and not self.cfg.get("allow_short", False):
                    continue

                if vid in self._task_cache:
                    existing = self._task_cache[vid]
                    if cid and not existing.get("channel_id"):
                        existing["channel_id"] = cid
                        self._decorate_task_capcut_badge(existing)
                        c_existing = self.page_queue.cards_map.get(vid)
                        if c_existing is not None:
                            c_existing.refresh_card_templates(self._available_templates, existing["selected_tpl"])
                    c_widget = self.page_queue.cards_map.get(vid)
                    if c_widget is not None:
                        self.page_queue.cards_lay.removeWidget(c_widget)
                        self.page_queue.cards_lay.insertWidget(0, c_widget)
                    continue

                title = v.get("title") or vid
                v_dur = v.get("v_dur") or ""
                posted = v.get("posted_at_str") or ""
                ago = v.get("time_ago") or ""
                time_part = f"{posted} ({ago})" if (posted and ago) else (posted or ago)
                dur_part = f"{v_type} {v_dur}".strip()
                d_sec = v.get("delay_sec")
                delay_part = f"⚡ delay : {int(d_sec)} (s)" if d_sec is not None else ""
                st_txt = " • ".join(p for p in ("🌐 Trên Server", delay_part, time_part, dur_part) if p)

                self._ui_upsert_card(
                    {
                        "video_id": vid,
                        "url": url,
                        "channel": cname,
                        "channel_id": cid,
                        "note": v_note,
                        "title": title,
                        "resolution_badge": v_type,
                        "percent": 0.0,
                        "state": "server_feed",
                        "status_text": st_txt,
                        "file_path": "",
                    },
                    defer_filter=True,
                )
                new_thumb_vids.append(vid)

            self.page_queue.apply_card_filter()
        finally:
            self.page_queue.cards_container.setUpdatesEnabled(True)

        for vid in reversed(new_thumb_vids[-12:]):
            self.downloader.request_thumbnail(vid)

    def _load_past_history(self):
        rows = self.history.get_recent(self.vps.username, limit=25)
        if not rows:
            return
        self.page_queue.cards_container.setUpdatesEnabled(False)
        try:
            for r in reversed(rows):
                st = r["status"]
                if st == "missed":
                    continue
                res_b = r.get("resolution") or ""
                vid = r["video_id"]
                if st == "completed":
                    ld = float(r.get("load_sec") or 0)
                    dl = float(r.get("dl_sec") or 0)
                    mx = float(r.get("mux_sec") or 0)
                    tot = float(r.get("elapsed_sec") or 0)
                    if ld > 0 or dl > 0:
                        st_txt = (
                            f"✅ {r['size_mb']} MB • Tổng từ lúc bấm: {tot:.2f}s "
                            f"(Load link: {ld:.2f}s + Tải: {dl:.2f}s + Ghép: {mx:.2f}s) • {r['speed_mbs']} MB/s"
                        )
                    else:
                        st_txt = f"✅ {r['size_mb']} MB • Tổng thời gian: {tot:.2f}s ({r['speed_mbs']} MB/s)"
                elif st == "cancelled":
                    st_txt = "⏹ Đã hủy tải"
                elif st in ("downloading", "preparing", "waiting_hd", "muxing", "queued", "merging"):
                    st = "cancelled"
                    st_txt = "⏹ Đã dừng giữa chừng (lần mở trước)"
                    try:
                        self.history.upsert_task(
                            self.vps.username,
                            {
                                "video_id": vid,
                                "url": r.get("video_url") or f"https://www.youtube.com/watch?v={vid}",
                                "channel": r["channel_name"],
                                "note": r["note"],
                                "title": r["video_title"],
                                "resolution_badge": res_b,
                                "status": "cancelled",
                            },
                        )
                    except Exception:
                        pass
                else:
                    st_txt = f"❌ {r['error_msg'] or st}"

                self._ui_upsert_card(
                    {
                        "video_id": vid,
                        "url": r.get("video_url") or f"https://www.youtube.com/watch?v={vid}",
                        "channel": r["channel_name"],
                        "note": r["note"],
                        "title": r["video_title"],
                        "resolution_badge": res_b,
                        "percent": 100.0 if st == "completed" else 0.0,
                        "status_text": st_txt,
                        "state": st,
                        "file_path": r["file_path"],
                    },
                    defer_filter=True,
                )
            self.page_queue.apply_card_filter()
        finally:
            self.page_queue.cards_container.setUpdatesEnabled(True)

    def _ui_upsert_card(self, task: dict, defer_filter: bool = False):
        vid = task.get("video_id") or extract_video_id(task.get("url", ""))
        if not vid:
            return
        prev = self._task_cache.get(vid)
        merged = dict(task)
        if prev:
            if not merged.get("channel_id") and prev.get("channel_id"):
                merged["channel_id"] = prev["channel_id"]
            if "_last_used_tpl" in prev and "_last_used_tpl" not in merged:
                merged["_last_used_tpl"] = prev["_last_used_tpl"]
        self._decorate_task_capcut_badge(merged)
        self._task_cache[vid] = merged
        self.page_queue.upsert_card(
            vid=vid,
            task=merged,
            on_cancel=self.downloader.cancel_task,
            on_retry=self._retry_or_manual_card,
            on_capcut=self._handle_apply_capcut,
            on_dismiss=self._dismiss_single_card,
            templates_list=self._available_templates,
            thumb_bytes=self.downloader.get_cached_thumbnail(vid),
            defer_filter=defer_filter,
        )

    def _handle_apply_capcut(
        self,
        vid: str,
        chosen_tpl: str | None = None,
        auto_mode: bool = False,
    ):
        t = self._task_cache.get(vid) or {}
        file_path = t.get("file_path") or ""
        if not file_path or not os.path.isfile(file_path):
            if not auto_mode:
                QMessageBox.warning(self, "CapCut 1-Click", "Không tìm thấy file video .mp4 trên ổ cứng!")
            return

        if chosen_tpl is not None:
            tpl_name = chosen_tpl or BLANK_TEMPLATE_KEY
        else:
            tpl_name = self._resolve_task_template(t)

        t["_last_used_tpl"] = tpl_name
        title = t.get("title") or ""
        # Chỉ tự bật CapCut nếu CapCut đang tắt (không tự tắt mở lại, không click ẩn làm phiền!)
        should_launch = not has_visible_capcut_window()

        self.downloader.apply_capcut_async(
            vid=vid,
            video_path=file_path,
            video_title=title,
            template_name=tpl_name,
            auto_launch_capcut=should_launch,
            force_restart_if_open=False,
        )

    def _ui_on_capcut_done(self, vid: str, ok: bool, msg: str, draft_name: str):
        if ok:
            self._append_log(f"✂️ [CAPCUT 1-CLICK] {msg}")
            t = self._task_cache.get(vid)
            used_tpl = (t.get("_last_used_tpl") if t else None) or BLANK_TEMPLATE_KEY
            if t:
                base_st = re.sub(r"\s*•\s*✂️ Đã tạo:.*$", "", t.get("status_text") or "")
                t["status_text"] = f"{base_st} • ✂️ Đã tạo: {draft_name}"
                self._ui_upsert_card(t)
            if self.cfg.get("toast_popup", True):
                tpl_disp = (
                    "Project trắng (Tự edit)"
                    if used_tpl == BLANK_TEMPLATE_KEY
                    else f"Mẫu kênh: {used_tpl}"
                )
                pop = DesktopToastPopup(
                    "✂️ ĐÃ ĐẨY VÀO CAPCUT THÀNH CÔNG!",
                    tpl_disp,
                    draft_name,
                    accent="#38BDF8",
                    thumb_bytes=self.downloader.get_cached_thumbnail(vid),
                    duration_ms=6500,
                )
                pop.show()
        else:
            self._append_log(f"⚠️ [CAPCUT LỖI] {msg}")
            QMessageBox.warning(self, "Lỗi tạo Project CapCut", msg)

    def _retry_or_manual_card(self, vid: str):
        t = self._task_cache.get(vid) or {}
        url = t.get("url") or f"https://www.youtube.com/watch?v={vid}"
        self.downloader.enqueue(
            username=self.vps.username,
            video_url=url,
            channel_name=t.get("channel") or "YouTube",
            channel_id=t.get("channel_id") or "",
            video_title=t.get("title") or "",
            note=t.get("note") or "",
            save_dir=self.cfg.get("save_dir", ""),
            subfolder_by_channel=bool(self.cfg.get("subfolder_by_channel", True)),
            res_profile=self.cfg.get("res_profile", "1080p_h264"),
            hd_mode=self.cfg.get("hd_mode", "wait_hd"),
            force_redownload=True,
        )

    def _dismiss_single_card(self, vid: str):
        t = self._task_cache.pop(vid, None) or {}
        self.history.mark_dismissed(
            username=self.vps.username,
            video_id=vid,
            video_url=t.get("url") or "",
            channel_name=t.get("channel") or "",
            video_title=t.get("title") or "",
        )
        card = self.page_queue.cards_map.pop(vid, None)
        if card:
            self.page_queue.cards_lay.removeWidget(card)
            card.deleteLater()
        self.page_queue.apply_card_filter()

    def _clear_non_completed_cards(self):
        self.history.clear_non_completed(self.vps.username)
        to_remove = [
            vid
            for vid, card in self.page_queue.cards_map.items()
            if card.current_state in ("failed", "cancelled", "skipped", "missed")
        ]
        for vid in to_remove:
            card = self.page_queue.cards_map.pop(vid, None)
            self._task_cache.pop(vid, None)
            if card:
                self.page_queue.cards_lay.removeWidget(card)
                card.deleteLater()
        self.page_queue.apply_card_filter()

    def _clear_all_old_videos(self):
        active_states = ("downloading", "queued", "waiting_hd", "merging", "preparing")
        old_vids = [
            vid
            for vid, card in self.page_queue.cards_map.items()
            if card.current_state not in active_states
        ]
        if not old_vids:
            QMessageBox.information(self, "Xóa video cũ", "Danh sách hiện đã sạch sẽ, không có video cũ nào cần xóa!")
            return

        mp4_files = []
        for vid in old_vids:
            fp = (self._task_cache.get(vid) or {}).get("file_path") or ""
            if fp and os.path.isfile(fp):
                mp4_files.append(fp)

        delete_disk_files = False
        if mp4_files:
            box = QMessageBox(self)
            box.setWindowTitle("Xóa toàn bộ video cũ")
            box.setIcon(QMessageBox.Icon.Question)
            box.setText(
                f"Bạn muốn xóa toàn bộ {len(old_vids)} video cũ đang hiện trên Tool như thế nào?\n\n"
                f"• [🧹 Chỉ dọn danh sách]: Xóa sạch thẻ cũ trên Tool (giữ nguyên {len(mp4_files)} file .mp4 trong ổ cứng).\n"
                f"• [🗑 Xóa cả file .mp4]: Dọn sạch danh sách VÀ xóa luôn {len(mp4_files)} file .mp4 cũ khỏi ổ cứng."
            )
            btn_list_only = box.addButton("🧹 Chỉ dọn danh sách", QMessageBox.ButtonRole.AcceptRole)
            btn_with_mp4 = box.addButton(f"🗑 Xóa cả file .mp4 ({len(mp4_files)})", QMessageBox.ButtonRole.DestructiveRole)
            btn_cancel = box.addButton("Hủy", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(btn_list_only)
            box.exec()
            clicked = box.clickedButton()
            if clicked is btn_cancel or clicked is None:
                return
            delete_disk_files = clicked is btn_with_mp4
        else:
            ans = QMessageBox.question(
                self,
                "Xóa toàn bộ video cũ",
                f"Bạn có chắc muốn xóa sạch toàn bộ {len(old_vids)} video cũ khỏi danh sách Tool không?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return

        extra_items = []
        self.page_queue.cards_container.setUpdatesEnabled(False)
        try:
            for vid in old_vids:
                t = self._task_cache.pop(vid, None) or {}
                extra_items.append(
                    {
                        "video_id": vid,
                        "url": t.get("url") or "",
                        "channel": t.get("channel") or "",
                        "note": t.get("note") or "",
                        "title": t.get("title") or "",
                    }
                )
                card = self.page_queue.cards_map.pop(vid, None)
                if card:
                    self.page_queue.cards_lay.removeWidget(card)
                    card.deleteLater()
            self.page_queue.apply_card_filter()
        finally:
            self.page_queue.cards_container.setUpdatesEnabled(True)

        self.history.dismiss_all_old_videos(self.vps.username, extra_items=extra_items)

        deleted_files_cnt = 0
        if delete_disk_files:
            for fp in mp4_files:
                try:
                    os.remove(fp)
                    deleted_files_cnt += 1
                except OSError:
                    pass
            self._refresh_disk_space()

        if delete_disk_files:
            self._append_log(f"🗑 Đã xóa sạch {len(old_vids)} video cũ trên Tool & xóa {deleted_files_cnt} file .mp4 trên ổ cứng!")
        else:
            self._append_log(f"🧹 Đã dọn sạch {len(old_vids)} video cũ khỏi danh sách Tool!")

    def _ui_on_thumb_ready(self, vid: str, img_bytes: bytes):
        card = self.page_queue.cards_map.get(vid)
        if card:
            card.set_thumbnail_bytes(img_bytes)

    def _ui_on_total_speed(self, speed_mbs: float, active_cnt: int):
        self.page_queue.set_speed_badge(speed_mbs, active_cnt)
        self.nav_queue.set_badge(active_cnt, highlight=True)

    def _ui_on_download_finished(self, task: dict):
        if self.cfg.get("sound_alert", True):
            play_alert_beep(is_complete=True)
        if self.cfg.get("toast_popup", True):
            vid = task.get("video_id") or ""
            tot = task.get("elapsed_sec", 0)
            ld = task.get("load_sec", 0)
            dl = task.get("dl_sec", 0)
            head = (
                f"✅ XONG TRONG {tot:.2f}s (Load {ld:.1f}s + Tải {dl:.1f}s) • "
                f"{task.get('size_mb', 0):.1f} MB ({task.get('speed_mbs', 0):.1f} MB/s)"
            )
            pop = DesktopToastPopup(
                head,
                task.get("channel") or "YouTube",
                task.get("title") or "",
                accent="#4ADE80",
                file_path=task.get("file_path") or "",
                thumb_bytes=self.downloader.get_cached_thumbnail(vid),
                duration_ms=11000,
                video_url=task.get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else ""),
            )
            pop.show()
        self._refresh_disk_space()
        if self.cfg.get("auto_capcut", False):
            vid = task.get("video_id") or ""
            if vid:
                self._handle_apply_capcut(vid, auto_mode=True)

    def _ui_on_download_failed(self, task: dict):
        if self.cfg.get("toast_popup", True):
            vid = task.get("video_id") or ""
            pop = DesktopToastPopup(
                "⚠️ CHƯA TẢI ĐƯỢC VIDEO",
                task.get("channel") or "YouTube",
                task.get("status_text") or "Lỗi tải video",
                accent="#F59E0B",
                thumb_bytes=self.downloader.get_cached_thumbnail(vid),
                duration_ms=8500,
                video_url=task.get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else ""),
            )
            pop.show()

    # ==========================================================
    # 🚀 TỰ ĐỘNG CẬP NHẬT QUA GITHUB RELEASES (100% TỰ ĐỘNG NGẦM 0 CHẠM)
    # ==========================================================
    def _count_active_downloads(self) -> int:
        return sum(
            1
            for t in self._task_cache.values()
            if t.get("state") in ("downloading", "queued", "waiting_hd", "merging")
        )

    def _on_update_button_clicked(self):
        self._restore_from_tray(check_upd=False)
        if self._update_downloading:
            return
        if self._staged_ready_exe and os.path.isfile(self._staged_ready_exe):
            self._apply_update_and_restart(self._staged_ready_exe, silent=False)
            return
        if self._pending_update_info and self._pending_update_info.get("has_update"):
            self._refresh_update_banner(self._pending_update_info)
            self._show_update_popup_card(self._pending_update_info)
            return
        self._start_update_check(manual=True)

    def _on_one_click_update_triggered(self):
        if self._update_popup_dlg is not None:
            try:
                self._update_popup_dlg.close()
            except Exception:
                pass
            self._update_popup_dlg = None
        if self._update_downloading:
            return
        if self._staged_ready_exe and os.path.isfile(self._staged_ready_exe):
            self._apply_update_and_restart(self._staged_ready_exe, silent=False)
            return
        if self._pending_update_info and self._pending_update_info.get("has_update"):
            self._begin_update_download(self._pending_update_info, silent=False)

    def _refresh_update_banner(self, info: dict):
        new_ver = info.get("latest_version") or ""
        size_mb = (int(info.get("size_bytes") or 0)) / (1024 * 1024)
        size_txt = f" (~{size_mb:.1f} MB)" if size_mb > 1 else ""
        notes_one = re.sub(r"\s+", " ", (info.get("notes") or "Bản cập nhật mới đã sẵn sàng để tải về!").strip())
        if len(notes_one) > 115:
            notes_one = notes_one[:112] + "..."
        self.lbl_upd_title.setText(f"🚀 Đã có phiên bản mới Mercedes Sniper v{new_ver}{size_txt}!")
        self.lbl_upd_notes.setText(f"📝 {notes_one}")
        if not self._update_downloading:
            self.bar_upd_progress.setVisible(False)
            self.btn_upd_banner_dl.setEnabled(True)
            if self._staged_ready_exe and os.path.isfile(self._staged_ready_exe):
                self.btn_upd_banner_dl.setText(f"⚡ Khởi động lên v{new_ver} ngay")
            else:
                self.btn_upd_banner_dl.setText("⬇ Tải & Cập nhật ngay")
        self.update_banner.setVisible(True)

    def _show_update_popup_card(self, info: dict):
        if self._update_downloading:
            return
        if self._update_popup_dlg is not None:
            try:
                if self._update_popup_dlg.isVisible():
                    self._update_popup_dlg.raise_()
                    return
            except Exception:
                pass

        new_ver = info.get("latest_version") or ""
        size_mb = (int(info.get("size_bytes") or 0)) / (1024 * 1024)
        size_txt = f"~{size_mb:.1f} MB" if size_mb > 1 else "Bản mới nhất"
        notes = (info.get("notes") or "Tối ưu hiệu năng & khắc phục lỗi.").strip()
        if len(notes) > 500:
            notes = notes[:500] + "..."

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Phiên bản mới v{new_ver} đã sẵn sàng!")
        dlg.setWindowModality(Qt.WindowModality.NonModal)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dlg.setFixedWidth(460)
        dlg.setStyleSheet(
            "QDialog { background-color: #0F172A; border: 1px solid #10B981; border-radius: 10px; }"
            "QLabel { background: transparent; }"
        )

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)

        lbl_head = QLabel(f"🚀 CÓ PHIÊN BẢN MỚI: v{new_ver}")
        lbl_head.setStyleSheet("color: #34D399; font-size: 16px; font-weight: 900;")
        lay.addWidget(lbl_head)

        lbl_meta = QLabel(f"Đang dùng: v{APP_VERSION}   •   Bản mới: v{new_ver} ({size_txt})")
        lbl_meta.setStyleSheet("color: #94A3B8; font-size: 12px; font-weight: 600;")
        lay.addWidget(lbl_meta)

        notes_box = QFrame()
        notes_box.setStyleSheet(
            "QFrame { background-color: #1E293B; border: 1px solid #334155; border-radius: 8px; }"
        )
        nb_lay = QVBoxLayout(notes_box)
        nb_lay.setContentsMargins(12, 10, 12, 10)
        lbl_notes = QLabel(notes)
        lbl_notes.setWordWrap(True)
        lbl_notes.setStyleSheet("color: #E2E8F0; font-size: 12.5px; border: none;")
        nb_lay.addWidget(lbl_notes)
        lay.addWidget(notes_box)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_later = QPushButton("Để sau")
        btn_later.setFixedHeight(36)
        btn_later.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_later.setStyleSheet(
            "QPushButton { background-color: #1E293B; color: #CBD5E1; border: 1px solid #475569; "
            "border-radius: 7px; font-size: 12px; font-weight: 700; padding: 0 16px; }"
            "QPushButton:hover { background-color: #334155; color: #FFFFFF; }"
        )
        btn_later.clicked.connect(dlg.close)

        btn_go = QPushButton(f"⬇ Tải về & Cập nhật lên v{new_ver} ngay")
        btn_go.setFixedHeight(36)
        btn_go.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_go.setStyleSheet(
            "QPushButton { background-color: #10B981; color: #022C22; border: none; "
            "border-radius: 7px; font-size: 12.5px; font-weight: 800; padding: 0 18px; }"
            "QPushButton:hover { background-color: #34D399; color: #022C22; }"
        )
        btn_go.clicked.connect(self._on_one_click_update_triggered)

        btn_row.addWidget(btn_later)
        btn_row.addWidget(btn_go, 1)
        lay.addLayout(btn_row)

        self._update_popup_dlg = dlg
        dlg.destroyed.connect(lambda *_: setattr(self, "_update_popup_dlg", None))
        dlg.show()
        dlg.raise_()

    def _start_update_check(self, manual: bool = False):
        if self._update_checking or self._update_downloading:
            return
        if (not manual) and self._staged_ready_exe and os.path.isfile(self._staged_ready_exe):
            self._try_auto_apply_staged()
            return
        self._update_checking = True
        if manual:
            self.btn_update.setText("⏳ Đang kiểm tra...")

        def _worker():
            info = check_github_update(timeout=8.0)
            self.signals.sig_update_check_done.emit(info, manual)

        threading.Thread(target=_worker, daemon=True, name="GitHubUpdateCheck").start()

    def _ui_on_update_check_done(self, info: dict, manual: bool):
        self._update_checking = False
        if not info.get("ok"):
            if not (self._pending_update_info and self._pending_update_info.get("has_update")):
                self.btn_update.setText(f"🔄 Cập nhật (v{APP_VERSION})")
            if manual:
                QMessageBox.warning(
                    self,
                    "Không thể kiểm tra cập nhật",
                    f"Không kết nối được tới GitHub Releases:\n{info.get('error') or 'Lỗi mạng'}",
                )
            return

        if info.get("has_update"):
            self._pending_update_info = info
            new_ver = info.get("latest_version") or ""
            tag = info.get("tag_name") or f"v{new_ver}"
            self.btn_update.setText(f"🚀 Nâng cấp v{new_ver}!")
            self.btn_update.setToolTip(f"Đã có phiên bản mới {tag}! Bấm để tải & cập nhật ngay.")
            self.btn_update.setStyleSheet(
                "QPushButton { background-color: #059669; color: #FFFFFF; border: 1px solid #10B981; "
                "border-radius: 5px; font-size: 11px; font-weight: 800; padding: 2px 6px; }"
                "QPushButton:hover { background-color: #10B981; color: #FFFFFF; }"
            )
            self._refresh_update_banner(info)

            if manual:
                self._show_update_popup_card(info)
            elif self._update_notified_tag != tag:
                self._update_notified_tag = tag
                self._append_log(
                    f"🚀 Đã có bản cập nhật mới {tag}! Bấm nút [⬇ Tải & Cập nhật ngay] trên thanh thông báo để nâng cấp."
                )
                try:
                    self.tray.showMessage(
                        f"🚀 Đã có Mercedes Sniper {tag} mới!",
                        "Mở ứng dụng và bấm [⬇ Tải & Cập nhật ngay] để nâng cấp phiên bản mới nhất.",
                        QSystemTrayIcon.MessageIcon.Information,
                        6000,
                    )
                except Exception:
                    pass
                if self.isVisible():
                    self._show_update_popup_card(info)
        else:
            self._pending_update_info = None
            self.update_banner.setVisible(False)
            self.btn_update.setText(f"🔄 Cập nhật (v{APP_VERSION})")
            if manual:
                QMessageBox.information(
                    self,
                    "Đã là bản mới nhất",
                    f"✅ Bạn đang sử dụng phiên bản mới nhất (v{APP_VERSION}) trên GitHub!",
                )

    def _begin_update_download(self, info: dict, silent: bool = False):
        if self._update_downloading:
            return
        new_ver = info.get("latest_version") or ""
        self._update_downloading = True
        self._update_silent_mode = silent
        self.btn_update.setEnabled(False)
        self.btn_update.setText("⬇ Đang tải 0%...")
        self.update_banner.setVisible(True)
        self.bar_upd_progress.setValue(0)
        self.bar_upd_progress.setFormat("0%")
        self.bar_upd_progress.setVisible(True)
        self.btn_upd_banner_dl.setEnabled(False)
        self.btn_upd_banner_dl.setText("⬇ Đang tải 0%...")
        self._append_log(f"⬇ Đang tải bản cập nhật v{new_ver} từ GitHub Releases...")

        def _dl_worker():
            try:
                staged_path = download_update_asset(
                    info,
                    progress_cb=lambda pct, cur_mb, tot_mb: self.signals.sig_update_dl_progress.emit(
                        pct, cur_mb, tot_mb
                    ),
                )
                self.signals.sig_update_dl_done.emit(True, staged_path)
            except Exception as exc:
                self.signals.sig_update_dl_done.emit(False, str(exc))

        threading.Thread(target=_dl_worker, daemon=True, name="GitHubUpdateDownload").start()

    def _ui_on_update_dl_progress(self, pct: int, cur_mb: float, tot_mb: float):
        self.btn_update.setText(f"⬇ Đang tải {pct}%...")
        self.bar_upd_progress.setValue(max(0, min(100, pct)))
        if tot_mb > 0:
            self.bar_upd_progress.setFormat(f"{pct}% ({cur_mb:.0f}/{tot_mb:.0f} MB)")
        else:
            self.bar_upd_progress.setFormat(f"{pct}%")
        self.btn_upd_banner_dl.setText(f"⬇ Đang tải {pct}%...")

    def _ui_on_update_dl_done(self, ok: bool, path_or_err: str):
        self._update_downloading = False
        self.btn_update.setEnabled(True)
        self.btn_upd_banner_dl.setEnabled(True)
        if not ok:
            ver = (self._pending_update_info or {}).get("latest_version") or APP_VERSION
            self.btn_update.setText(f"🚀 Nâng cấp v{ver}!")
            self.bar_upd_progress.setVisible(False)
            self.btn_upd_banner_dl.setText("⬇ Thử tải lại")
            self._append_log(f"❌ Lỗi tải bản cập nhật: {path_or_err}")
            if not self._update_silent_mode:
                QMessageBox.warning(self, "Lỗi cập nhật", f"Không thể tải bản cập nhật:\n{path_or_err}")
            return

        self.bar_upd_progress.setValue(100)
        self.bar_upd_progress.setFormat("100% • Đang cài đặt...")
        self._staged_ready_exe = path_or_err
        if self._count_active_downloads() > 0:
            ver = (self._pending_update_info or {}).get("latest_version") or APP_VERSION
            self.btn_update.setText(f"⚡ Xong tải sẽ lên v{ver}")
            self.btn_upd_banner_dl.setText(f"⚡ Áp dụng ngay v{ver}")
            self._append_log(
                f"✅ Đã tải xong bản v{ver}! Đang chờ video hiện tại tải xong sẽ tự động khởi động lại nâng cấp..."
            )
            if not hasattr(self, "_staged_wait_timer"):
                self._staged_wait_timer = QTimer(self)
                self._staged_wait_timer.timeout.connect(self._try_auto_apply_staged)
            self._staged_wait_timer.start(3000)
            return

        self._apply_update_and_restart(path_or_err, silent=self._update_silent_mode)

    def _try_auto_apply_staged(self):
        if not self._staged_ready_exe or not os.path.isfile(self._staged_ready_exe):
            if hasattr(self, "_staged_wait_timer"):
                self._staged_wait_timer.stop()
            return
        if self._count_active_downloads() == 0:
            if hasattr(self, "_staged_wait_timer"):
                self._staged_wait_timer.stop()
            self._apply_update_and_restart(self._staged_ready_exe, silent=True)

    def _apply_update_and_restart(self, exe_path: str, silent: bool = False):
        applied, msg = launch_self_updater(exe_path)
        if not applied:
            self.btn_update.setText(f"🔄 Cập nhật (v{APP_VERSION})")
            if not silent:
                QMessageBox.information(self, "Đã tải gói cập nhật", msg)
            return

        self._append_log(f"✅ {msg}")
        self._release_single_instance_handles()
        self._quit_completely()

    def _release_single_instance_handles(self):
        if os.name != "nt":
            return
        try:
            app = QApplication.instance()
            refs = getattr(app, "_single_instance_refs", None)
            if refs and len(refs) == 3:
                k32, mx_h, ev_h = refs
                if k32:
                    if mx_h:
                        k32.ReleaseMutex(mx_h)
                        k32.CloseHandle(mx_h)
                    if ev_h:
                        k32.CloseHandle(ev_h)
                app._single_instance_refs = (None, None, None)
        except Exception:
            pass

    # ==========================================================
    # 🔐 SYSTEM TRAY & VÒNG ĐỜI CỬA SỔ
    # ==========================================================
    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setToolTip(f"Mercedes Sniper — {self.vps.username}")

        menu = QMenu()
        act_show = QAction("🖥 Mở Mercedes Sniper", self)
        act_show.triggered.connect(self._restore_from_tray)
        act_folder = QAction("📂 Mở thư mục lưu Video", self)
        act_folder.triggered.connect(self._open_save_root)
        act_upd = QAction(f"🔄 Kiểm tra cập nhật (v{APP_VERSION})", self)
        act_upd.triggered.connect(self._on_update_button_clicked)
        act_quit = QAction("❌ Thoát hẳn", self)
        act_quit.triggered.connect(self._quit_completely)

        menu.addAction(act_show)
        menu.addAction(act_folder)
        menu.addAction(act_upd)
        menu.addSeparator()
        menu.addAction(act_quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._restore_from_tray()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick
            else None
        )
        self.tray.show()

    def _ui_on_auth_expired(self, msg: str):
        self.vps.stop_watching()
        self._restore_from_tray()
        QMessageBox.warning(self, "Phiên đăng nhập hết hạn", msg)
        self._reopen_login()

    def _handle_logout(self):
        self.vps.stop_watching()
        self.cfg["password"] = ""
        self._save_cfg(self.cfg)
        self._reopen_login()

    def _reopen_login(self):
        self._ipc_timer.stop()
        self.downloader.shutdown()
        self.tray.hide()
        self._force_quit = True
        self.close()
        dlg = LoginDialog(self.vps, self.cfg, self._save_cfg)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            win = SniperMainWindow(self.vps, self.cfg, self._save_cfg)
            win.show()
            QApplication.instance()._main_win_ref = win

    def _restore_from_tray(self, check_upd: bool = True):
        self.showNormal()
        self.activateWindow()
        self.raise_()
        if check_upd:
            self._start_update_check(manual=False)

    def _quit_completely(self):
        self._force_quit = True
        self._ipc_timer.stop()
        self.vps.stop_watching()
        self.downloader.shutdown()
        self.tray.hide()
        QApplication.quit()

    def closeEvent(self, event):
        if self._force_quit:
            event.accept()
            return
        event.ignore()
        self.hide()
        if not self._tray_notified_once:
            self._tray_notified_once = True
            self.tray.showMessage(
                "Mercedes Sniper đang trực chiến ngầm",
                "Đường truyền Push 0ms vẫn đang hoạt động dưới khay hệ thống!",
                QSystemTrayIcon.MessageIcon.Information,
                3200,
            )

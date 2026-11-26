# -*- coding: utf-8 -*-
"""
4 Màn hình chức năng tách biệt, thoáng đãng (1 Màn hình = 1 Nhiệm vụ rõ ràng):
1. LiveQueuePage: Trung tâm tải bằng Thẻ Card hiện đại (95% thời gian sử dụng).
2. ChannelsPage: Quản lý kênh theo dõi rộng rãi trên toàn trang.
3. RulesPage: Các quy tắc tự động tải (Loại video, Độ dài, Từ khóa, Note).
4. SettingsPage: Thư mục lưu, Chất lượng, Động cơ tải 32 luồng, Cookies & Chẩn đoán.
"""
import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.capcut_injector import (
    BLANK_TEMPLATE_KEY,
    list_capcut_templates,
    scan_all_capcut_projects,
)
from core.turbo_downloader import detect_system_capabilities
from ui.cards import (
    CapCutProjectRowCard,
    ChannelRowCard,
    DownloadCardWidget,
    NoWheelComboBox,
    SettingSectionCard,
    TemplatePickerButton,
)
from ui.theme import PillFilterButton, ToggleSwitch


class LiveQueuePage(QWidget):
    """Màn hình 1: Trung tâm Tải Max Speed (Hiện danh sách video từ DB Server + nút Tải + chọn Mẫu CapCut ngay trên thẻ)."""

    def __init__(
        self,
        on_manual_submit,
        on_open_folder,
        on_clear_finished,
        on_open_templates_tab=None,
        on_refresh_server_feed=None,
        on_clear_all_old=None,
        parent=None,
    ):
        super().__init__(parent)
        self._on_open_templates_tab = on_open_templates_tab
        self._on_refresh_server_feed = on_refresh_server_feed
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 8)
        lay.setSpacing(7)

        # 1. TOP BAR NHỎ GỌN (30px): Trạng thái Push | Spotlight Link | Đồng hồ Tốc độ
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self.lbl_conn_pill = QLabel("● Đang nối ống Push...")
        self.lbl_conn_pill.setFixedHeight(30)
        self.lbl_conn_pill.setStyleSheet(
            "background-color: #263244; color: #F8FAFC; border: 1px solid #64748B; "
            "border-radius: 15px; padding: 0 11px; font-size: 11.5px; font-weight: 700;"
        )
        top_bar.addWidget(self.lbl_conn_pill)

        # Spotlight Paste Box gọn 30px
        spot_box = QFrame()
        spot_box.setObjectName("SpotlightBox")
        spot_box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        spot_box.setFixedHeight(30)
        sp_lay = QHBoxLayout(spot_box)
        sp_lay.setContentsMargins(9, 2, 3, 2)
        sp_lay.setSpacing(6)

        self.inp_url = QLineEdit()
        self.inp_url.setObjectName("SpotlightInput")
        self.inp_url.setPlaceholderText("🔗 Dán 1 hoặc nhiều link YouTube vào đây để kéo Max Speed ngay...")
        self.inp_url.returnPressed.connect(on_manual_submit)

        btn_go = QPushButton("⚡ Tải Ngay")
        btn_go.setObjectName("RubyBtn")
        btn_go.setFixedHeight(24)
        btn_go.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_go.clicked.connect(on_manual_submit)

        sp_lay.addWidget(self.inp_url, 1)
        sp_lay.addWidget(btn_go)
        top_bar.addWidget(spot_box, 1)

        self.lbl_speed_pill = QLabel("🚀 0.0 MB/s")
        self.lbl_speed_pill.setFixedHeight(30)
        self.lbl_speed_pill.setMinimumWidth(104)
        self.lbl_speed_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_speed_pill.setStyleSheet(
            "background-color: #263244; color: #E2E8F0; border: 1px solid #64748B; "
            "border-radius: 15px; padding: 0 10px; font-size: 11.5px; font-weight: 800;"
        )
        top_bar.addWidget(self.lbl_speed_pill)
        lay.addLayout(top_bar)

        # 2. SUB-BAR GỌN (25px): PILL FILTERS + MỞ THƯ MỤC
        sub_bar = QHBoxLayout()
        sub_bar.setSpacing(6)

        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)

        self.pill_all = PillFilterButton("Tất cả")
        self.pill_unfetched = PillFilterButton("Chưa tải")
        self.pill_unfetched.setToolTip("Các video đang lưu trong DB Server chưa tải về máy này")
        self.pill_active = PillFilterButton("Đang tải")
        self.pill_done = PillFilterButton("Hoàn tất")
        self.pill_other = PillFilterButton("Bỏ qua / Lỗi")
        self.pill_all.setChecked(True)

        self.filter_group.addButton(self.pill_all, 0)
        self.filter_group.addButton(self.pill_unfetched, 4)
        self.filter_group.addButton(self.pill_active, 1)
        self.filter_group.addButton(self.pill_done, 2)
        self.filter_group.addButton(self.pill_other, 3)
        for b in (self.pill_all, self.pill_unfetched, self.pill_active, self.pill_done, self.pill_other):
            sub_bar.addWidget(b)

        sub_bar.addStretch()

        self.btn_open_tpl = QPushButton("✂️ Kho Mẫu CapCut")
        self.btn_open_tpl.setObjectName("CapCutBtn")
        self.btn_open_tpl.setFixedHeight(25)
        self.btn_open_tpl.setToolTip("Mở Kho Mẫu để quét toàn bộ Project trên CapCut PC hoặc nhập mẫu mới")
        self.btn_open_tpl.setCursor(Qt.CursorShape.PointingHandCursor)
        if self._on_open_templates_tab:
            self.btn_open_tpl.clicked.connect(self._on_open_templates_tab)
        sub_bar.addWidget(self.btn_open_tpl)

        self.btn_sync_feed = QPushButton("🔄 Tải DS Server")
        self.btn_sync_feed.setFixedHeight(25)
        self.btn_sync_feed.setToolTip("Làm mới danh sách các video đã lưu trên DB Server")
        self.btn_sync_feed.setCursor(Qt.CursorShape.PointingHandCursor)
        if self._on_refresh_server_feed:
            self.btn_sync_feed.clicked.connect(self._on_refresh_server_feed)
        sub_bar.addWidget(self.btn_sync_feed)

        btn_folder = QPushButton("📂 Thư mục")
        btn_folder.setFixedHeight(25)
        btn_folder.setToolTip("Mở thư mục lưu video đã tải")
        btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_folder.clicked.connect(on_open_folder)

        btn_clean = QPushButton("🧹 Dọn lỗi")
        btn_clean.setFixedHeight(25)
        btn_clean.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_clean.clicked.connect(on_clear_finished)

        self.btn_clear_all = QPushButton("🗑 Xóa video cũ")
        self.btn_clear_all.setObjectName("GhostDangerBtn")
        self.btn_clear_all.setFixedHeight(25)
        self.btn_clear_all.setToolTip("Xóa sạch toàn bộ danh sách video cũ trên Tool (tùy chọn giữ hoặc xóa cả file .mp4)")
        self.btn_clear_all.setCursor(Qt.CursorShape.PointingHandCursor)
        if on_clear_all_old:
            self.btn_clear_all.clicked.connect(on_clear_all_old)

        sub_bar.addWidget(btn_folder)
        sub_bar.addWidget(btn_clean)
        sub_bar.addWidget(self.btn_clear_all)
        lay.addLayout(sub_bar)

        # 3. DANH SÁCH THẺ VIDEO MẢNH GỌN (62px/thanh, cách nhau 5px)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cards_container = QWidget()
        self.cards_container.setObjectName("ScrollHost")
        self.cards_lay = QVBoxLayout(self.cards_container)
        self.cards_lay.setContentsMargins(0, 1, 3, 6)
        self.cards_lay.setSpacing(5)

        # Empty State gọn nhẹ
        self.empty_box = QFrame()
        self.empty_box.setObjectName("TransparentBox")
        em_lay = QVBoxLayout(self.empty_box)
        em_lay.setContentsMargins(0, 70, 0, 70)
        em_lay.setSpacing(6)
        lbl_em_ic = QLabel("⚡")
        lbl_em_ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_em_ic.setStyleSheet("font-size: 34px; color: #38BDF8;")
        lbl_em_t = QLabel("Đang trực chiến nhận tín hiệu Real-time 0ms")
        lbl_em_t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_em_t.setStyleSheet("font-size: 14.5px; font-weight: 800; color: #FFFFFF;")
        lbl_em_s = QLabel(
            "Ngay khi kênh đăng video mới, hệ thống tự động bắt & kéo 1080p Max Speed tại đây.\n"
            "Hoặc dán link YouTube bất kỳ vào thanh phía trên để tải ngay."
        )
        lbl_em_s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_em_s.setStyleSheet("font-size: 12px; color: #CBD5E1;")
        em_lay.addWidget(lbl_em_ic)
        em_lay.addWidget(lbl_em_t)
        em_lay.addWidget(lbl_em_s)

        self.cards_lay.addWidget(self.empty_box)
        self.cards_lay.addStretch(1)
        self.scroll.setWidget(self.cards_container)
        lay.addWidget(self.scroll, 1)

        self.filter_group.idClicked.connect(lambda _: self.apply_card_filter())
        self.cards_map: dict[str, DownloadCardWidget] = {}
        self._speed_active_look: bool | None = None
        self._conn_active_look: bool | None = None

    def set_connection_badge(self, connected: bool, text: str):
        self.lbl_conn_pill.setText(f"● {text}")
        if connected != self._conn_active_look:
            self._conn_active_look = connected
            if connected:
                self.lbl_conn_pill.setStyleSheet(
                    "background-color: #0D281E; color: #34D399; border: 1px solid #10B981; "
                    "border-radius: 15px; padding: 0 11px; font-size: 11.5px; font-weight: 700;"
                )
            else:
                self.lbl_conn_pill.setStyleSheet(
                    "background-color: #2B1C14; color: #FBBF24; border: 1px solid #D97706; "
                    "border-radius: 15px; padding: 0 11px; font-size: 11.5px; font-weight: 700;"
                )

    def set_speed_badge(self, speed_mbs: float, active_cnt: int):
        is_act = active_cnt > 0 and speed_mbs > 0
        self.lbl_speed_pill.setText(f"🚀 {speed_mbs:.1f} MB/s" if is_act else "🚀 0.0 MB/s")
        if is_act != self._speed_active_look:
            self._speed_active_look = is_act
            if is_act:
                self.lbl_speed_pill.setStyleSheet(
                    "background-color: #064E3B; color: #4ADE80; border: 1px solid #10B981; "
                    "border-radius: 15px; padding: 0 10px; font-size: 12px; font-weight: 800;"
                )
            else:
                self.lbl_speed_pill.setStyleSheet(
                    "background-color: #263244; color: #E2E8F0; border: 1px solid #64748B; "
                    "border-radius: 15px; padding: 0 10px; font-size: 11.5px; font-weight: 800;"
                )

    def update_tpl_button_count(self, count: int):
        self.btn_open_tpl.setText(f"✂️ Kho Mẫu ({count})" if count > 0 else "✂️ Kho Mẫu CapCut")

    def upsert_card(
        self,
        vid: str,
        task: dict,
        on_cancel,
        on_retry,
        on_capcut=None,
        on_dismiss=None,
        templates_list: list[str] | None = None,
        thumb_bytes: bytes | None = None,
        defer_filter: bool = False,
    ):
        card = self.cards_map.get(vid)
        is_new = card is None
        prev_state = None if is_new else card.current_state
        if is_new:
            card = DownloadCardWidget(
                vid,
                on_cancel,
                on_retry,
                on_capcut_fn=on_capcut,
                on_dismiss_fn=on_dismiss,
                templates_list=templates_list,
            )
            if thumb_bytes:
                card.set_thumbnail_bytes(thumb_bytes)
            self.cards_map[vid] = card
            self.cards_lay.insertWidget(0, card)
        card.update_from_task(task)
        if not defer_filter and (is_new or card.current_state != prev_state):
            self.apply_card_filter()

    def apply_card_filter(self):
        fid = self.filter_group.checkedId()
        active_set = ("preparing", "waiting_hd", "downloading", "muxing")
        feed_set = ("server_feed", "missed")

        c_all = len(self.cards_map)
        c_act = sum(1 for c in self.cards_map.values() if c.current_state in active_set)
        c_done = sum(1 for c in self.cards_map.values() if c.current_state == "completed")
        c_feed = sum(1 for c in self.cards_map.values() if c.current_state in feed_set)
        c_oth = c_all - c_act - c_done - c_feed

        self.pill_all.setText(f"Tất cả ({c_all})" if c_all else "Tất cả")
        self.pill_unfetched.setText(f"Chưa tải ({c_feed})" if c_feed else "Chưa tải")
        self.pill_active.setText(f"Đang tải ({c_act})" if c_act else "Đang tải")
        self.pill_done.setText(f"Hoàn tất ({c_done})" if c_done else "Hoàn tất")
        self.pill_other.setText(f"Bỏ qua / Lỗi ({c_oth})" if c_oth else "Bỏ qua / Lỗi")

        visible_any = False
        for card in self.cards_map.values():
            st = card.current_state
            if fid == 1:
                vis = st in active_set
            elif fid == 2:
                vis = st == "completed"
            elif fid == 3:
                vis = st not in active_set and st != "completed" and st not in feed_set
            elif fid == 4:
                vis = st in feed_set
            else:
                vis = True
            card.setVisible(vis)
            if vis:
                visible_any = True

        self.empty_box.setVisible(not visible_any and c_all == 0)


class ChannelsPage(QWidget):
    """Màn hình 2: Quản lý Kênh Đang Canh dạng thanh mảnh gọn + gắn Mẫu CapCut riêng từng kênh."""

    def __init__(
        self,
        on_add_channel,
        on_renew_all,
        on_bulk_toggle,
        on_refresh_channels=None,
        on_reload_templates=None,
        parent=None,
    ):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 8)
        lay.setSpacing(6)

        # Header 1 dòng gọn gàng
        head = QHBoxLayout()
        head.setSpacing(7)
        lbl_h = QLabel("Kênh Đang Canh")
        lbl_h.setStyleSheet("font-size: 14.5px; font-weight: 800; color: #FFFFFF;")
        self.lbl_sub = QLabel("Đồng bộ 0ms với Web Soitube")
        self.lbl_sub.setStyleSheet("font-size: 11.5px; color: #34D399; font-weight: 700;")
        head.addWidget(lbl_h)
        head.addWidget(QLabel("•"))
        head.addWidget(self.lbl_sub)
        head.addStretch(1)

        self.btn_reload_tpl = QPushButton("✂️ Nạp DS Mẫu")
        self.btn_reload_tpl.setFixedHeight(27)
        self.btn_reload_tpl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reload_tpl.setToolTip(
            "Quét lại thư mục nháp CapCut PC để cập nhật danh sách mẫu (mau_1, mau_2... mau_10)"
        )
        if on_reload_templates:
            self.btn_reload_tpl.clicked.connect(on_reload_templates)
        head.addWidget(self.btn_reload_tpl)

        self.btn_refresh = QPushButton("⚡ Đồng Bộ Web")
        self.btn_refresh.setFixedHeight(27)
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        if on_refresh_channels:
            self.btn_refresh.clicked.connect(on_refresh_channels)
        head.addWidget(self.btn_refresh)

        self.btn_renew = QPushButton("🔄 Gia Hạn Webhook")
        self.btn_renew.setFixedHeight(27)
        self.btn_renew.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_renew.clicked.connect(on_renew_all)
        head.addWidget(self.btn_renew)
        lay.addLayout(head)

        # Thanh Thêm kênh mới gọn nhẹ (kèm chọn sẵn Mẫu CapCut hoặc để Project trắng)
        add_card = QFrame()
        add_card.setObjectName("StudioCard")
        add_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        add_lay = QHBoxLayout(add_card)
        add_lay.setContentsMargins(8, 5, 8, 5)
        add_lay.setSpacing(6)

        self.inp_url = QLineEdit()
        self.inp_url.setFixedHeight(27)
        self.inp_url.setPlaceholderText("➕ Dán link kênh YouTube hoặc @handle cần canh...")
        self.inp_url.returnPressed.connect(on_add_channel)

        self.inp_note = QLineEdit()
        self.inp_note.setFixedHeight(27)
        self.inp_note.setFixedWidth(130)
        self.inp_note.setPlaceholderText("Nhãn Note (Máy 1)")
        self.inp_note.returnPressed.connect(on_add_channel)

        lbl_add_cc = QLabel("✂️")
        lbl_add_cc.setStyleSheet("color: #38BDF8; font-size: 11.5px;")
        lbl_add_cc.setToolTip("Gắn sẵn Mẫu CapCut cho kênh sắp thêm (Không chọn = Project trắng)")

        self.cmb_add_tpl = TemplatePickerButton(blank_label="Project trắng", width=136, height=27)
        self.cmb_add_tpl.setToolTip("Gắn sẵn Mẫu CapCut cho kênh mới (Mặc định: Project trắng)")

        self.btn_add = QPushButton("Thêm Kênh")
        self.btn_add.setObjectName("RubyBtn")
        self.btn_add.setFixedHeight(27)
        self.btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add.clicked.connect(on_add_channel)

        add_lay.addWidget(self.inp_url, 1)
        add_lay.addWidget(self.inp_note)
        add_lay.addWidget(lbl_add_cc)
        add_lay.addWidget(self.cmb_add_tpl)
        add_lay.addWidget(self.btn_add)
        lay.addWidget(add_card)

        # Thanh Tìm kiếm & Bật/Tắt hàng loạt gọn 27px
        flt_row = QHBoxLayout()
        flt_row.setSpacing(6)
        self.inp_search = QLineEdit()
        self.inp_search.setFixedHeight(27)
        self.inp_search.setPlaceholderText("🔍 Tìm nhanh theo tên kênh, nhãn Note hoặc tên Mẫu CapCut (VD: mau_1)...")
        self.inp_search.textChanged.connect(self._apply_search)

        btn_on_all = QPushButton("Bật tất cả")
        btn_on_all.setFixedHeight(27)
        btn_on_all.clicked.connect(lambda: on_bulk_toggle(True))
        btn_off_all = QPushButton("Tắt tất cả")
        btn_off_all.setFixedHeight(27)
        btn_off_all.clicked.connect(lambda: on_bulk_toggle(False))

        flt_row.addWidget(self.inp_search, 1)
        flt_row.addWidget(btn_on_all)
        flt_row.addWidget(btn_off_all)
        lay.addLayout(flt_row)

        # Danh sách Thanh Kênh mảnh gọn (38px/thanh, cách nhau 4px)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_host = QWidget()
        self.list_host.setObjectName("ScrollHost")
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(0, 1, 3, 6)
        self.list_lay.setSpacing(4)
        self.list_lay.addStretch(1)
        self.scroll.setWidget(self.list_host)
        lay.addWidget(self.scroll, 1)

        self.row_widgets: list[ChannelRowCard] = []

    def reload_add_bar_templates(self, templates_list: list[str]):
        cur = str(self.cmb_add_tpl.currentData() or BLANK_TEMPLATE_KEY)
        if cur != BLANK_TEMPLATE_KEY and cur not in templates_list:
            cur = BLANK_TEMPLATE_KEY
        self.cmb_add_tpl.set_state(templates_list, cur)

    def reset_add_bar_template(self):
        self.cmb_add_tpl.set_state(self.cmb_add_tpl._templates, BLANK_TEMPLATE_KEY)

    def get_add_bar_template(self) -> str:
        val = self.cmb_add_tpl.currentData()
        return str(val) if val else BLANK_TEMPLATE_KEY

    def update_summary_label(self):
        total = len(self.row_widgets)
        en_cnt = sum(1 for r in self.row_widgets if r.sw_enable.isChecked())
        tpl_cnt = sum(
            1
            for r in self.row_widgets
            if (r.cmb_tpl.currentData() or BLANK_TEMPLATE_KEY) != BLANK_TEMPLATE_KEY
        )
        self.lbl_sub.setText(f"Đang canh {en_cnt}/{total} kênh • {tpl_cnt} kênh gắn mẫu")

    def refresh_template_dropdowns(self, templates_list: list[str], channel_tpl_map: dict[str, str]):
        self.reload_add_bar_templates(templates_list)
        for r in self.row_widgets:
            sel = (
                channel_tpl_map.get(r.cid)
                or channel_tpl_map.get(r.cname)
                or BLANK_TEMPLATE_KEY
            )
            r.set_templates_list(templates_list, sel)
        self.update_summary_label()

    def populate_channels(
        self,
        channels: list[dict],
        disabled_set: set,
        on_toggle_fn,
        on_note_fn,
        on_open_yt_fn,
        on_delete_fn,
        templates_list: list[str] | None = None,
        channel_tpl_map: dict[str, str] | None = None,
        on_tpl_fn=None,
    ):
        self.list_host.setUpdatesEnabled(False)
        try:
            for w in self.row_widgets:
                self.list_lay.removeWidget(w)
                w.deleteLater()
            self.row_widgets.clear()

            tpls = list_capcut_templates() if templates_list is None else list(templates_list)
            tpl_map = channel_tpl_map or {}
            self.reload_add_bar_templates(tpls)

            for ch in channels:
                cid = ch.get("channel_id") or ""
                cname = ch.get("channel_name") or cid
                is_en = (cid not in disabled_set) and (cname not in disabled_set)
                sel_tpl = tpl_map.get(cid) or tpl_map.get(cname) or BLANK_TEMPLATE_KEY
                row = ChannelRowCard(
                    ch,
                    is_en,
                    on_toggle_fn,
                    on_note_fn,
                    on_open_yt_fn,
                    on_delete_fn,
                    templates_list=tpls,
                    selected_tpl=sel_tpl,
                    on_tpl_change_fn=on_tpl_fn,
                )
                self.row_widgets.append(row)
                self.list_lay.insertWidget(self.list_lay.count() - 1, row)

            self.update_summary_label()
            self._apply_search()
        finally:
            self.list_host.setUpdatesEnabled(True)

    def _apply_search(self):
        q = self.inp_search.text().strip().lower()
        for r in self.row_widgets:
            hay = f"{r.cname} {r.cid} {r.inp_note.text()} {r.cmb_tpl.currentText()}".lower()
            r.setVisible((not q) or (q in hay))


class CapCutTemplatesPage(QWidget):
    """Màn hình 3: Tự đọc globalSetting & quét toàn bộ Project trên CapCut PC để tích chọn trực tiếp làm Mẫu."""

    def __init__(
        self,
        on_scan_capcut,
        on_pick_draft_root,
        on_open_capcut_draft_dir,
        on_save_templates=None,
        parent=None,
    ):
        super().__init__(parent)
        self._total_projs_cnt = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 8)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(7)
        lbl_h = QLabel("Kho Mẫu CapCut")
        lbl_h.setStyleSheet("font-size: 14.5px; font-weight: 800; color: #FFFFFF;")
        self.lbl_sub = QLabel("Tự động quét qua globalSetting")
        self.lbl_sub.setStyleSheet("font-size: 11.5px; color: #38BDF8; font-weight: 700;")
        head.addWidget(lbl_h)
        head.addWidget(QLabel("•"))
        head.addWidget(self.lbl_sub)
        head.addStretch(1)

        self.btn_save_tpl = QPushButton("💾 Lưu mẫu")
        self.btn_save_tpl.setObjectName("DragActionBtn")
        self.btn_save_tpl.setFixedHeight(27)
        self.btn_save_tpl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save_tpl.setToolTip(
            "Lưu danh sách các Project đã tích chọn làm Mẫu (dùng trực tiếp Project gốc, không nhân bản thêm Project mới)"
        )
        if on_save_templates:
            self.btn_save_tpl.clicked.connect(on_save_templates)
        head.addWidget(self.btn_save_tpl)

        self.btn_scan = QPushButton("🔄 Quét CapCut")
        self.btn_scan.setObjectName("CapCutBtn")
        self.btn_scan.setFixedHeight(27)
        self.btn_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_scan.clicked.connect(on_scan_capcut)
        head.addWidget(self.btn_scan)

        self.btn_pick_root = QPushButton("📍 Đổi Ổ Nháp")
        self.btn_pick_root.setFixedHeight(27)
        self.btn_pick_root.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pick_root.setToolTip(
            "Mặc định Tool tự đọc globalSetting của CapCut (tự nhận cả ổ C:, D:, E:).\n"
            "Chỉ cần bấm nút này nếu máy dùng bản CapCut Portable đặc biệt."
        )
        self.btn_pick_root.clicked.connect(on_pick_draft_root)
        head.addWidget(self.btn_pick_root)

        btn_open_dir = QPushButton("📂 Thư Mục CapCut")
        btn_open_dir.setFixedHeight(27)
        btn_open_dir.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_open_dir.clicked.connect(on_open_capcut_draft_dir)
        head.addWidget(btn_open_dir)
        lay.addLayout(head)

        guide = QFrame()
        guide.setObjectName("StudioCard")
        guide.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        g_lay = QVBoxLayout(guide)
        g_lay.setContentsMargins(10, 6, 10, 6)
        g_lay.setSpacing(2)
        self.lbl_detected_root = QLabel("📍 Kho nháp CapCut (globalSetting): ...")
        self.lbl_detected_root.setStyleSheet("color: #7DD3FC; font-size: 11px; font-weight: 700;")
        lbl_g = QLabel(
            "💡 Tích chọn trực tiếp vào các Project CapCut bên dưới rồi bấm '💾 Lưu mẫu' — "
            "Tool dùng thẳng Project gốc (giữ nguyên tên gốc, không bắt đặt tên lại và không copy tạo Project thừa)!"
        )
        lbl_g.setWordWrap(True)
        lbl_g.setStyleSheet("color: #E2E8F0; font-size: 11.5px; font-weight: 600;")
        g_lay.addWidget(self.lbl_detected_root)
        g_lay.addWidget(lbl_g)
        lay.addWidget(guide)

        self.inp_search = QLineEdit()
        self.inp_search.setFixedHeight(27)
        self.inp_search.setPlaceholderText("🔍 Tìm nhanh theo tên Project trên CapCut...")
        self.inp_search.textChanged.connect(self._apply_search)
        lay.addWidget(self.inp_search)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_host = QWidget()
        self.list_host.setObjectName("ScrollHost")
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(0, 1, 3, 6)
        self.list_lay.setSpacing(5)
        self.list_lay.addStretch(1)
        self.scroll.setWidget(self.list_host)
        lay.addWidget(self.scroll, 1)

        self.proj_rows: list[CapCutProjectRowCard] = []
        self._last_proj_sig: list[tuple] | None = None

    def update_selection_counts(self, active_cnt: int | None = None):
        if active_cnt is None:
            active_cnt = sum(1 for r in self.proj_rows if r.sw_use.isChecked())
        self.lbl_sub.setText(
            f"Đang chọn {active_cnt} Mẫu sẵn sàng  •  Quét thấy {self._total_projs_cnt} Project trong CapCut PC"
        )
        self.btn_save_tpl.setText(f"💾 Lưu mẫu ({active_cnt})" if active_cnt else "💾 Lưu mẫu")

    def populate_projects(
        self,
        projects: list[dict],
        selected_extra_set: set[str],
        on_toggle_tpl_fn,
        detected_root: str = "",
        explicit_mode: bool = False,
    ):
        if detected_root:
            self.lbl_detected_root.setText(f"📍 Kho nháp CapCut đang quét: {detected_root}")

        self._total_projs_cnt = len(projects)
        new_sig = [
            (
                p.get("folder_name") or "",
                p.get("template_key") or p.get("display_name") or "",
                p.get("modified_str") or "",
                (
                    (p.get("folder_name") or "") in selected_extra_set
                    or (p.get("display_name") or "") in selected_extra_set
                    or (p.get("template_key") or "") in selected_extra_set
                    or ((not explicit_mode) and bool(p.get("is_named_template")))
                ),
            )
            for p in projects
        ]
        if new_sig == self._last_proj_sig and len(self.proj_rows) == len(projects):
            return
        self._last_proj_sig = new_sig

        self.list_host.setUpdatesEnabled(False)
        try:
            for w in self.proj_rows:
                self.list_lay.removeWidget(w)
                w.deleteLater()
            self.proj_rows.clear()

            active_cnt = 0
            for p in projects:
                fname = p.get("folder_name") or ""
                dname = p.get("display_name") or fname
                tkey = p.get("template_key") or dname
                is_sel = (
                    (fname in selected_extra_set)
                    or (dname in selected_extra_set)
                    or (tkey in selected_extra_set)
                    or ((not explicit_mode) and bool(p.get("is_named_template")))
                )
                if is_sel:
                    active_cnt += 1
                row = CapCutProjectRowCard(p, is_sel, on_toggle_tpl_fn)
                self.proj_rows.append(row)
                self.list_lay.insertWidget(self.list_lay.count() - 1, row)

            self.update_selection_counts(active_cnt)
            self._apply_search()
        finally:
            self.list_host.setUpdatesEnabled(True)

    def _apply_search(self):
        q = self.inp_search.text().strip().lower()
        for r in self.proj_rows:
            hay = f"{r.template_key} {r.display_name} {r.folder_name}".lower()
            r.setVisible((not q) or (q in hay))


class RulesPage(QWidget):
    """Màn hình 3: Quy tắc Lọc Tự Động trình bày dạng Card sạch sẽ."""

    def __init__(self, cfg: dict, on_prefs_changed, parent=None):
        super().__init__(parent)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("ScrollHost")
        lay = QVBoxLayout(host)
        lay.setContentsMargins(14, 10, 14, 14)
        lay.setSpacing(10)

        lbl_h = QLabel("Quy Tắc Tự Động Bắt Video")
        lbl_h.setStyleSheet("font-size: 14.5px; font-weight: 800; color: #F8FAFC;")
        lay.addWidget(lbl_h)

        # Card 1: Định dạng video
        c1 = SettingSectionCard(
            "Định dạng Video cần tự động kéo",
            "Livestream đang phát và Bài viết cộng đồng luôn tự động bị chặn để tránh rác ổ cứng.",
        )
        self.sw_long = ToggleSwitch(checked=bool(cfg.get("allow_long", True)), active_color="#10B981")
        self.sw_short = ToggleSwitch(checked=bool(cfg.get("allow_short", False)), active_color="#10B981")
        self.sw_long.toggled.connect(on_prefs_changed)
        self.sw_short.toggled.connect(on_prefs_changed)

        c1.add_setting_row(
            "🎬 Video Dài (LONG)",
            "Tự động tải các video khung ngang thông thường lớn hơn 60 giây.",
            self.sw_long,
        )
        c1.add_setting_row(
            "📱 Video Ngắn (YouTube Shorts)",
            "Tự động tải các clip khung dọc hoặc thời lượng dưới 60 giây.",
            self.sw_short,
        )
        lay.addWidget(c1)

        # Card 2: Thời lượng & Từ khóa
        c2 = SettingSectionCard(
            "Giới hạn Thời lượng & Từ khóa loại trừ",
            "Tránh tự tải nhầm các video tổng hợp quá dài (3–4 tiếng) hoặc các từ khóa không mong muốn.",
        )
        self.spn_min = QSpinBox()
        self.spn_min.setRange(0, 36000)
        self.spn_min.setSuffix(" giây")
        self.spn_min.setFixedWidth(130)
        self.spn_min.setValue(int(cfg.get("min_duration_sec", 0)))
        self.spn_min.valueChanged.connect(on_prefs_changed)

        self.spn_max = QSpinBox()
        self.spn_max.setRange(0, 86400)
        self.spn_max.setSuffix(" giây")
        self.spn_max.setFixedWidth(130)
        self.spn_max.setValue(int(cfg.get("max_duration_sec", 0)))
        self.spn_max.valueChanged.connect(on_prefs_changed)

        c2.add_setting_row(
            "Thời lượng tối thiểu",
            "Đặt 0 giây nếu không giới hạn tối thiểu.",
            self.spn_min,
        )
        c2.add_setting_row(
            "Thời lượng tối đa",
            "Đặt 0 giây nếu không giới hạn (Gợi ý: 2400 giây = 40 phút).",
            self.spn_max,
        )

        self.inp_exclude = QLineEdit(cfg.get("exclude_keywords", ""))
        self.inp_exclude.setPlaceholderText("VD: compilation, highlight, rerun (phân cách bằng dấu phẩy)...")
        self.inp_exclude.textChanged.connect(on_prefs_changed)
        c2.add_setting_row(
            "Từ khóa loại trừ trong tiêu đề",
            "Nếu tiêu đề chứa bất kỳ từ nào trong ô này, tool chỉ báo tin chứ không tự tải.",
            self.inp_exclude,
        )
        self.inp_exclude.setFixedWidth(340)
        lay.addWidget(c2)

        # Card 3: Phân luồng theo Note máy
        c3 = SettingSectionCard(
            "Phân luồng theo Nhãn Máy (Note Filter)",
            "Hữu ích khi 1 tài khoản dùng trên nhiều máy tính khác nhau.",
        )
        self.inp_note_flt = QLineEdit(cfg.get("note_filter", ""))
        self.inp_note_flt.setFixedWidth(260)
        self.inp_note_flt.setPlaceholderText("Để trống = Nhận tất cả kênh")
        self.inp_note_flt.textChanged.connect(on_prefs_changed)
        c3.add_setting_row(
            "Chỉ tự tải kênh khớp nhãn Note",
            "Nếu nhập 'Máy 1', tool chỉ tự động tải các kênh có nhãn Note chứa chữ 'Máy 1'.",
            self.inp_note_flt,
        )
        lay.addWidget(c3)

        lay.addStretch(1)
        scroll.setWidget(host)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)


class SettingsPage(QWidget):
    """Màn hình 4: Cài đặt Thư mục, Chất lượng, Động cơ Max Speed & Cookies."""

    _sig_hw_ready = pyqtSignal(str)
    _sig_cookie_test_done = pyqtSignal(dict)

    def __init__(self, cfg: dict, on_prefs_changed, on_pick_dir, on_pick_cookie, parent=None):
        super().__init__(parent)
        self._cfg_ref = cfg
        self._testing_cookie = False
        self._sig_cookie_test_done.connect(self._on_cookie_test_finished)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("ScrollHost")
        lay = QVBoxLayout(host)
        lay.setContentsMargins(14, 10, 14, 14)
        lay.setSpacing(10)

        lbl_h = QLabel("Cài Đặt Hệ Thống & Động Cơ Max Speed")
        lbl_h.setStyleSheet("font-size: 14.5px; font-weight: 800; color: #F8FAFC;")
        lay.addWidget(lbl_h)

        # Card 1: Lưu trữ & Chất lượng
        c1 = SettingSectionCard(
            "Lưu trữ & Chất lượng Video",
            "Cấu hình nơi xuất file và chuẩn định dạng phục vụ dựng/đăng nhanh nhất.",
        )

        dir_wrap = QWidget()
        dir_wrap.setObjectName("TransparentBox")
        d_lay = QHBoxLayout(dir_wrap)
        d_lay.setContentsMargins(0, 0, 0, 0)
        d_lay.setSpacing(8)
        self.inp_save_dir = QLineEdit(cfg.get("save_dir", ""))
        self.inp_save_dir.setReadOnly(True)
        self.inp_save_dir.setFixedWidth(290)
        btn_dir = QPushButton("📁 Đổi thư mục")
        btn_dir.clicked.connect(on_pick_dir)
        d_lay.addWidget(self.inp_save_dir)
        d_lay.addWidget(btn_dir)
        c1.add_setting_row("Thư mục lưu Video", "Nơi lưu các file .mp4 sau khi tải xong.", dir_wrap)

        self.sw_subfolder = ToggleSwitch(checked=bool(cfg.get("subfolder_by_channel", True)), active_color="#10B981")
        self.sw_subfolder.toggled.connect(on_prefs_changed)
        c1.add_setting_row(
            "Tự chia thư mục con theo Tên Kênh",
            "Giúp quản lý file gọn gàng, không bị lẫn video giữa các kênh.",
            self.sw_subfolder,
        )

        self.cmb_res = QComboBox()
        self.cmb_res.setFixedWidth(345)
        self.cmb_res.addItem("1080p MP4 (H.264 + AAC Chuẩn Dựng)", "1080p_h264")
        self.cmb_res.addItem("2K / 4K Chất Lượng Cao Nhất", "best_max")
        self.cmb_res.addItem("720p Siêu Tốc Nhẹ Máy", "720p_fast")
        i_r = self.cmb_res.findData(cfg.get("res_profile", "1080p_h264"))
        if i_r >= 0:
            self.cmb_res.setCurrentIndex(i_r)
        self.cmb_res.currentIndexChanged.connect(on_prefs_changed)
        c1.add_setting_row(
            "Độ phân giải tải mặc định",
            "1080p H.264 tương thích ngay 100% với CapCut, Premiere & Trình duyệt.",
            self.cmb_res,
        )

        self.cmb_hd_mode = QComboBox()
        self.cmb_hd_mode.setFixedWidth(345)
        self.cmb_hd_mode.addItem("Đợi đúng giây lên 1080p (Quét 2.5s)", "wait_hd")
        self.cmb_hd_mode.addItem("Kéo ngay bản cao nhất hiện có", "grab_now")
        i_h = self.cmb_hd_mode.findData(cfg.get("hd_mode", "wait_hd"))
        if i_h >= 0:
            self.cmb_hd_mode.setCurrentIndex(i_h)
        self.cmb_hd_mode.currentIndexChanged.connect(on_prefs_changed)
        c1.add_setting_row(
            "Chế độ bắt video vừa mới đăng (0 giây tuổi)",
            "Chờ YouTube xử lý xong 1080p hay kéo luôn bản 720p có sẵn ngay giây đầu.",
            self.cmb_hd_mode,
        )
        lay.addWidget(c1)

        # Card 2: Động cơ tốc độ cao & Thông báo
        c2 = SettingSectionCard(
            "Động cơ Kéo Đa Luồng & Cookies",
            "Tận dụng tối đa đường truyền cáp quang bằng cách kéo song song luồng Hình và Tiếng.",
        )

        self.cmb_engine = QComboBox()
        self.cmb_engine.setFixedWidth(345)
        self.cmb_engine.addItem("Turbo Multi-Stream (24-32 luồng - Khuyên dùng)", "turbo_hybrid")
        self.cmb_engine.addItem("IDM Bridge (Bắn qua IDMan.exe trên máy)", "idm_bridge")
        i_e = self.cmb_engine.findData(cfg.get("engine_mode", "turbo_hybrid"))
        if i_e >= 0:
            self.cmb_engine.setCurrentIndex(i_e)
        self.cmb_engine.currentIndexChanged.connect(on_prefs_changed)
        c2.add_setting_row("Động cơ tải (Download Engine)", "Turbo Multi-Stream chạy ngầm 100% không hiện cửa sổ phụ.", self.cmb_engine)

        self.spn_threads = QSpinBox()
        self.spn_threads.setRange(8, 32)
        self.spn_threads.setSuffix(" luồng")
        self.spn_threads.setFixedWidth(130)
        self.spn_threads.setValue(int(cfg.get("threads_per_video", 24)))
        self.spn_threads.valueChanged.connect(on_prefs_changed)
        c2.add_setting_row("Số luồng chia mảnh mỗi video", "Khuyên dùng 24 - 32 luồng cho mạng tốc độ cao.", self.spn_threads)

        self.spn_conc = QSpinBox()
        self.spn_conc.setRange(1, 5)
        self.spn_conc.setSuffix(" video")
        self.spn_conc.setFixedWidth(130)
        self.spn_conc.setValue(int(cfg.get("max_concurrent_videos", 3)))
        self.spn_conc.valueChanged.connect(on_prefs_changed)
        c2.add_setting_row("Số video tải song song cùng lúc", "Giới hạn số video kéo đồng thời khi nhiều kênh nổ cùng lúc.", self.spn_conc)

        self.sw_sound = ToggleSwitch(checked=bool(cfg.get("sound_alert", True)), active_color="#10B981")
        self.sw_sound.toggled.connect(on_prefs_changed)
        c2.add_setting_row("Âm thanh chuông báo", "Phát tiếng chuông nhẹ khi phát hiện video mới và khi tải xong.", self.sw_sound)

        self.sw_popup = ToggleSwitch(checked=bool(cfg.get("toast_popup", True)), active_color="#10B981")
        self.sw_popup.toggled.connect(on_prefs_changed)
        c2.add_setting_row("Thẻ thông báo nổi góc màn hình", "Hiện Popup nhỏ góc dưới bên phải mà không làm văng chuột.", self.sw_popup)

        self.sw_auto_capcut = ToggleSwitch(checked=bool(cfg.get("auto_capcut", False)), active_color="#38BDF8")
        self.sw_auto_capcut.toggled.connect(on_prefs_changed)
        c2.add_setting_row(
            "✂️ Tự động đẩy vào CapCut ngay khi tải xong",
            "Nếu bật, mỗi khi tải xong video mới Tool tự tạo sẵn Project CapCut theo mẫu riêng của kênh đó (kênh chưa gắn mẫu sẽ mở Project trắng).",
            self.sw_auto_capcut,
        )

        # Cookies
        self.cmb_cookie = QComboBox()
        self.cmb_cookie.setFixedWidth(300)
        self.cmb_cookie.addItem("Không dùng Cookies (Nhanh nhất)", "none")
        self.cmb_cookie.addItem("Dùng file cookies.txt (Ổn định nhất)", "file")
        self.cmb_cookie.addItem("Trình duyệt Edge", "edge")
        self.cmb_cookie.addItem("Trình duyệt Chrome", "chrome")
        self.cmb_cookie.addItem("Trình duyệt Brave", "brave")
        self.cmb_cookie.addItem("Trình duyệt Firefox", "firefox")
        i_ck = self.cmb_cookie.findData(cfg.get("cookie_mode", "none"))
        if i_ck >= 0:
            self.cmb_cookie.setCurrentIndex(i_ck)
        self.cmb_cookie.currentIndexChanged.connect(on_prefs_changed)
        c2.add_setting_row(
            "Cookies xác thực YouTube (Bảo vệ 2 tầng)",
            "Tự động bóc ẩn danh Safari/Mobile trước để giữ an toàn Cookie; chỉ dùng Cookie khi gặp kênh giới hạn tuổi/hội viên.",
            self.cmb_cookie,
        )

        ck_wrap = QWidget()
        ck_wrap.setObjectName("TransparentBox")
        ck_lay = QHBoxLayout(ck_wrap)
        ck_lay.setContentsMargins(0, 0, 0, 0)
        ck_lay.setSpacing(6)
        self.inp_cookie_file = QLineEdit(cfg.get("cookie_file", ""))
        self.inp_cookie_file.setPlaceholderText("Đường dẫn cookies.txt (hoặc JSON)...")
        self.inp_cookie_file.setFixedWidth(220)
        self.inp_cookie_file.textChanged.connect(on_prefs_changed)
        btn_ck = QPushButton("📄 Chọn file")
        btn_ck.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ck.clicked.connect(on_pick_cookie)

        self.btn_test_cookie = QPushButton("🧪 Kiểm tra Cookie")
        self.btn_test_cookie.setObjectName("DragActionBtn")
        self.btn_test_cookie.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test_cookie.setToolTip("Kiểm tra thực chiến xem Cookie còn sống, đủ khóa LOGIN_INFO và tải được YouTube 1080p không")
        self.btn_test_cookie.clicked.connect(self.run_cookie_test)

        ck_lay.addWidget(self.inp_cookie_file)
        ck_lay.addWidget(btn_ck)
        ck_lay.addWidget(self.btn_test_cookie)
        c2.add_setting_row("File cookies.txt / Kiểm định", "Hỗ trợ chuẩn Netscape .txt và JSON (J2Team/Cookie-Editor). Tự bảo vệ chống ghi đè hỏng file gốc.", ck_wrap)

        self.cookie_status_box = QFrame()
        self.cookie_status_box.setVisible(False)
        cs_lay = QVBoxLayout(self.cookie_status_box)
        cs_lay.setContentsMargins(10, 8, 10, 8)
        cs_lay.setSpacing(3)
        self.lbl_ck_sum = QLabel("")
        self.lbl_ck_sum.setWordWrap(True)
        self.lbl_ck_det = QLabel("")
        self.lbl_ck_det.setWordWrap(True)
        cs_lay.addWidget(self.lbl_ck_sum)
        cs_lay.addWidget(self.lbl_ck_det)
        c2.add_full_widget(self.cookie_status_box)

        lay.addWidget(c2)

        # Card 3: Môi trường máy & Nhật ký thu gọn (kiểm tra ngầm 0ms không chặn mở cửa sổ!)
        c3 = SettingSectionCard("Chẩn đoán Phần cứng & Nhật ký Kỹ thuật", "Đang kiểm tra môi trường phần cứng ngầm...")
        lbl_hw_sub = c3.findChildren(QLabel)[1]
        self._sig_hw_ready.connect(lbl_hw_sub.setText)

        def _probe_hw_bg():
            try:
                caps = detect_system_capabilities()
                tls_str = "Safari/Chrome (curl_cffi)" if caps.get("tls_impersonate_ok") else "Mặc định"
                ff_str = "Nhúng chìm trong .EXE" if caps.get("ffmpeg_embedded") else ("Sẵn sàng" if caps.get("ffmpeg_ok") else "Thiếu")
                js_label = (caps.get("js_runtime_kind") or "NodeJS").upper()
                hw_s = (
                    f"FFmpeg: {ff_str}  •  "
                    f"TLS Fingerprint: {tls_str}  •  "
                    f"IP Mode: Direct Residential  •  "
                    f"{js_label}: {'Sẵn sàng' if caps['node_ok'] else 'Tự động né (Apple API)'}  •  "
                    f"GPU NVENC: {'Hỗ trợ' if caps['nvenc_ok'] else 'CPU'}"
                )
                self._sig_hw_ready.emit(hw_s)
            except Exception:
                pass

        threading.Thread(target=_probe_hw_bg, daemon=True).start()

        btn_toggle_log = QPushButton("📜 Hiện / Ẩn Nhật Ký Kỹ Thuật (Console Log)")
        btn_toggle_log.setCheckable(True)
        btn_toggle_log.setFixedWidth(300)
        c3.add_full_widget(btn_toggle_log)

        self.txt_logs = QPlainTextEdit()
        self.txt_logs.setReadOnly(True)
        self.txt_logs.setMaximumBlockCount(350)
        self.txt_logs.setFixedHeight(190)
        self.txt_logs.setVisible(False)
        self.txt_logs.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11.5px; background: #0B0E14; "
            "color: #34D399; border: 1px solid #1E2636; border-radius: 8px;"
        )
        btn_toggle_log.toggled.connect(self.txt_logs.setVisible)
        c3.add_full_widget(self.txt_logs)

        lay.addWidget(c3)
        lay.addStretch(1)
        scroll.setWidget(host)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def run_cookie_test(self):
        if self._testing_cookie:
            return
        self._testing_cookie = True
        self.btn_test_cookie.setEnabled(False)
        self.btn_test_cookie.setText("⏳ Đang kiểm tra...")
        self.cookie_status_box.setVisible(True)
        self.cookie_status_box.setStyleSheet(
            "QFrame { background-color: #17253B; border: 1px solid #38BDF8; border-radius: 7px; }"
        )
        self.lbl_ck_sum.setStyleSheet("color: #7DD3FC; font-size: 12px; font-weight: 800; background: transparent; border: none;")
        self.lbl_ck_det.setStyleSheet("color: #CBD5E1; font-size: 11.5px; background: transparent; border: none;")
        self.lbl_ck_sum.setText("⏳ Đang kiểm tra khóa xác thực YouTube & kết nối bóc luồng 1080p thực tế...")
        self.lbl_ck_det.setText("Vui lòng chờ khoảng 2 - 4 giây...")

        snap_cfg = {
            "cookie_mode": str(self.cmb_cookie.currentData() or "none"),
            "cookie_file": self.inp_cookie_file.text().strip(),
        }

        def _worker():
            from core.cookie_doctor import verify_youtube_cookies
            res = verify_youtube_cookies(snap_cfg)
            self._sig_cookie_test_done.emit(res)

        threading.Thread(target=_worker, daemon=True, name="CookieDoctorTest").start()

    def _on_cookie_test_finished(self, res: dict):
        self._testing_cookie = False
        self.btn_test_cookie.setEnabled(True)
        self.btn_test_cookie.setText("🧪 Kiểm tra Cookie")
        ok = bool(res.get("ok"))
        self.cookie_status_box.setVisible(True)
        if ok:
            self.cookie_status_box.setStyleSheet(
                "QFrame { background-color: #0D281E; border: 1.5px solid #10B981; border-radius: 7px; }"
            )
            self.lbl_ck_sum.setStyleSheet("color: #4ADE80; font-size: 12.5px; font-weight: 800; background: transparent; border: none;")
            self.lbl_ck_det.setStyleSheet("color: #E2E8F0; font-size: 11.5px; background: transparent; border: none;")
        else:
            self.cookie_status_box.setStyleSheet(
                "QFrame { background-color: #31151B; border: 1.5px solid #F43F5E; border-radius: 7px; }"
            )
            self.lbl_ck_sum.setStyleSheet("color: #FDA4AF; font-size: 12.5px; font-weight: 800; background: transparent; border: none;")
            self.lbl_ck_det.setStyleSheet("color: #F1F5F9; font-size: 11.5px; background: transparent; border: none;")

        self.lbl_ck_sum.setText(str(res.get("summary") or ""))
        self.lbl_ck_det.setText(str(res.get("detail") or ""))

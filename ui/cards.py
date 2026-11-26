# -*- coding: utf-8 -*-
"""
Hệ thống Thẻ Giao Diện Tương Phản Cao (High-Contrast Studio Cards):
- Nền thẻ #1E293B tách bạch rõ khỏi nền chính #0F172A.
- Nhãn Note màu Vàng Hổ Phách (#F59E0B chữ Đen đậm) & Ô sửa Note chữ Vàng Sáng (#FDE047) đọc rõ ngay lập tức.
- Mọi nút bấm đều sáng, sắc nét, không có bất kỳ nút tối đen nào.
"""
import os
import urllib.parse
import webbrowser

from PyQt6.QtCore import QMimeData, QPoint, Qt, QTimer, QUrl
from PyQt6.QtGui import QColor, QDrag, QFont, QFontMetrics, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.capcut_injector import BLANK_TEMPLATE_KEY
from ui.theme import (
    ToggleSwitch,
    make_rounded_thumbnail,
    reveal_in_explorer,
)

_COVER_PIX_CACHE: dict[str, QPixmap] = {}


class _ClickableLabel(QLabel):
    """Nhãn bấm được siêu nhẹ (0ms chi phí vẽ) dùng cho Thumbnail & Tiêu đề Video."""

    def __init__(self, text: str = "", on_click=None, parent=None):
        super().__init__(text, parent)
        self._on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._on_click and self.rect().contains(event.pos()):
            self._on_click()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class NoWheelComboBox(QComboBox):
    """Ngăn con lăn chuột vô tình đổi mẫu CapCut khi đang cuộn danh sách kênh."""

    def wheelEvent(self, event):
        event.ignore()


class TemplatePickerButton(QPushButton):
    """
    Nút chọn Mẫu CapCut siêu nhẹ (0ms lúc nghỉ, chỉ dựng QMenu khi người dùng click):
    Thay thế hoàn toàn 125+ QComboBox nặng nề -> cuộn danh sách 144 FPS mượt tuyệt đối!
    """

    def __init__(self, blank_label: str = "Project trắng", width: int = 118, height: int = 26, parent=None):
        super().__init__(parent)
        self._blank_label = blank_label
        self._templates: list[str] = []
        self._val: str = BLANK_TEMPLATE_KEY
        self.on_changed = None
        self.setFixedSize(width, height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("TplPickerBlank")
        self.setText(f"{self._blank_label} ▾")
        self.clicked.connect(self._open_menu)

    def currentData(self) -> str:
        return self._val

    def currentText(self) -> str:
        return self._blank_label if self._val == BLANK_TEMPLATE_KEY else self._val

    def set_state(self, templates: list[str], selected: str = BLANK_TEMPLATE_KEY):
        self._templates = list(templates)
        cur = (selected or "").strip() or BLANK_TEMPLATE_KEY
        if cur != BLANK_TEMPLATE_KEY and cur not in self._templates:
            disp = f"⚠️ {cur[:11]} ▾"
            is_blank = False
        elif cur == BLANK_TEMPLATE_KEY:
            disp = f"{self._blank_label} ▾"
            is_blank = True
        else:
            short = (cur[:12] + "…") if len(cur) > 13 else cur
            disp = f"✂️ {short} ▾"
            is_blank = False

        self._val = cur
        if self.text() != disp:
            self.setText(disp)
        want_obj = "TplPickerBlank" if is_blank else "TplPickerActive"
        if self.objectName() != want_obj:
            self.setObjectName(want_obj)
            self.style().unpolish(self)
            self.style().polish(self)

    def _open_menu(self):
        menu = QMenu(self)
        act_blank = menu.addAction(f"— {self._blank_label} —")
        act_blank.setData(BLANK_TEMPLATE_KEY)
        if self._templates:
            menu.addSeparator()
            for t in self._templates:
                prefix = "✓ ✂️ " if t == self._val else "✂️ "
                act = menu.addAction(f"{prefix}{t}")
                act.setData(t)
        chosen = menu.exec(self.mapToGlobal(QPoint(0, self.height() + 2)))
        if chosen is not None:
            new_val = str(chosen.data() or BLANK_TEMPLATE_KEY)
            if new_val != self._val:
                self.set_state(self._templates, new_val)
                if self.on_changed:
                    self.on_changed(new_val)


class DragDropFileButton(QPushButton):
    def __init__(self, file_path: str, parent=None):
        super().__init__("🖐 Kéo File", parent)
        self.file_path = file_path
        self._drag_start: QPoint | None = None
        self.setObjectName("DragActionBtn")
        self.setFixedHeight(26)
        self.setMinimumWidth(86)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(
            "Giữ chuột trái & kéo thả file MP4 thẳng vào CapCut / Premiere / Trình duyệt!\n"
            "(Hoặc bấm đơn để mở thư mục chứa file)"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._drag_start is not None
            and (event.pos() - self._drag_start).manhattanLength() < QApplication.startDragDistance()
        ):
            if self.file_path:
                reveal_in_explorer(self.file_path)
        self._drag_start = None
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton) or self._drag_start is None:
            return
        if (event.pos() - self._drag_start).manhattanLength() < QApplication.startDragDistance():
            return
        if not self.file_path or not os.path.exists(self.file_path):
            return

        self._drag_start = None
        drag = QDrag(self)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(os.path.abspath(self.file_path))])
        drag.setMimeData(mime)

        badge = QPixmap(176, 28)
        badge.fill(Qt.GlobalColor.transparent)
        p = QPainter(badge)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor("#059669"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, 176, 28, 6, 6)
        p.setPen(QColor("#FFFFFF"))
        p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        fname = os.path.basename(self.file_path)
        short = (fname[:20] + "…mp4") if len(fname) > 24 else fname
        p.drawText(badge.rect(), Qt.AlignmentFlag.AlignCenter, f"🎬 {short}")
        p.end()

        drag.setPixmap(badge)
        drag.exec(Qt.DropAction.CopyAction)
        self.setCursor(Qt.CursorShape.OpenHandCursor)


class DownloadCardWidget(QFrame):
    THUMB_W = 84
    THUMB_H = 48

    def __init__(
        self,
        video_id: str,
        on_cancel_fn,
        on_retry_fn,
        on_capcut_fn=None,
        on_dismiss_fn=None,
        templates_list: list[str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.video_id = video_id
        self._on_cancel = on_cancel_fn
        self._on_retry = on_retry_fn
        self._on_capcut = on_capcut_fn
        self._on_dismiss = on_dismiss_fn
        self._video_url = f"https://www.youtube.com/watch?v={video_id}"
        self._channel_id = ""

        self._raw_title = ""
        self._raw_status = ""
        self._last_ch = ""
        self._last_note = None
        self._last_style_key = ""
        self._last_pbar_vis = True
        self._last_title_key = None
        self._thumb_bytes: bytes | None = None
        self._res_badge = ""
        self._last_action_mode = ""
        self._last_file_path = ""
        self._templates_list: list[str] = list(templates_list or [])
        self._default_tpl: str = BLANK_TEMPLATE_KEY
        self._user_picked_tpl: str | None = None
        self.cmb_card_tpl: TemplatePickerButton | None = None
        self._btn_cc_ref: QPushButton | None = None
        self.current_state = "preparing"

        self.setFixedHeight(62)
        self.setObjectName("StudioCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 10, 6)
        lay.setSpacing(10)

        # 1. Ảnh Thumbnail Mini-HD 84x48 gọn gàng (Click mở thẳng video trên YouTube)
        self.lbl_thumb = _ClickableLabel(on_click=self._open_youtube_video)
        self.lbl_thumb.setFixedSize(self.THUMB_W, self.THUMB_H)
        self.lbl_thumb.setToolTip("🔗 Bấm để mở xem video này trên YouTube")
        self.lbl_thumb.setPixmap(make_rounded_thumbnail(None, self.THUMB_W, self.THUMB_H))
        lay.addWidget(self.lbl_thumb)

        # 2. Khối thông tin 2 dòng tinh gọn ở giữa (+ thanh tiến trình mảnh 4px khi đang kéo)
        mid_wrap = QWidget()
        mid_wrap.setObjectName("TransparentBox")
        mid_wrap.setMinimumWidth(120)
        mid = QVBoxLayout(mid_wrap)
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(2)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)

        self.lbl_note = QLabel("")
        self.lbl_note.setVisible(False)
        self.lbl_note.setStyleSheet(
            "background-color: #FBBF24; color: #0F172A; border-radius: 4px; "
            "padding: 1px 6px; font-size: 10.5px; font-weight: 900;"
        )
        top_row.addWidget(self.lbl_note)

        self.lbl_channel = _ClickableLabel("📺 YouTube", on_click=self._open_youtube_channel)
        self.lbl_channel.setToolTip("🔗 Bấm để mở kênh YouTube này")
        self.lbl_channel.setStyleSheet(
            "QLabel { color: #CBD5E1; font-size: 11.5px; font-weight: 800; }"
            "QLabel:hover { color: #38BDF8; }"
        )
        top_row.addWidget(self.lbl_channel)

        lbl_dot = QLabel("•")
        lbl_dot.setStyleSheet("color: #64748B; font-size: 11px; font-weight: 800;")
        top_row.addWidget(lbl_dot)

        self.lbl_title = _ClickableLabel("Đang lấy thông tin video...", on_click=self._open_youtube_video)
        self.lbl_title.setMinimumWidth(80)
        self.lbl_title.setStyleSheet(
            "QLabel { color: #FFFFFF; font-size: 12.5px; font-weight: 800; }"
            "QLabel:hover { color: #38BDF8; text-decoration: underline; }"
        )
        top_row.addWidget(self.lbl_title, 1)
        mid.addLayout(top_row)

        self.lbl_status = QLabel("🔍 Đang load & bóc link... • ⏱ 0.0s")
        self.lbl_status.setMinimumWidth(80)
        self.lbl_status.setStyleSheet("color: #7DD3FC; font-size: 11.5px; font-weight: 700;")
        mid.addWidget(self.lbl_status)

        self.pbar = QProgressBar()
        self.pbar.setRange(0, 100)
        self.pbar.setValue(0)
        self.pbar.setTextVisible(False)
        self.pbar.setFixedHeight(4)
        mid.addWidget(self.pbar)

        mid.addStretch(1)
        lay.addWidget(mid_wrap, 1)

        # 3. Cụm nút thao tác bên phải nhỏ gọn (26px)
        self.action_host = QWidget()
        self.action_host.setObjectName("TransparentBox")
        self.action_lay = QHBoxLayout(self.action_host)
        self.action_lay.setContentsMargins(0, 0, 0, 0)
        self.action_lay.setSpacing(5)
        lay.addWidget(self.action_host, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def set_thumbnail_bytes(self, img_bytes: bytes):
        self._thumb_bytes = img_bytes
        self.lbl_thumb.setPixmap(make_rounded_thumbnail(self._thumb_bytes, self.THUMB_W, self.THUMB_H, self._res_badge))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_elided_title()

    def _apply_elided_title(self):
        act_w = max(80, self.action_host.sizeHint().width())
        ch_w = self.lbl_channel.sizeHint().width() + (self.lbl_note.sizeHint().width() if self.lbl_note.isVisible() else 0) + 28
        avail_title = max(95, self.width() - 145 - act_w - ch_w)
        avail_status = max(150, self.width() - 140 - act_w)
        t_key = (self._raw_title, avail_title)
        if self._raw_title and t_key != self._last_title_key:
            self._last_title_key = t_key
            fm = QFontMetrics(self.lbl_title.font())
            self.lbl_title.setText(fm.elidedText(self._raw_title, Qt.TextElideMode.ElideRight, avail_title))
            self.lbl_title.setToolTip(f"{self._raw_title}\n🔗 Bấm vào tiêu đề hoặc ảnh để mở xem trên YouTube")
        if self._raw_status:
            fms = QFontMetrics(self.lbl_status.font())
            self.lbl_status.setText(fms.elidedText(self._raw_status, Qt.TextElideMode.ElideRight, avail_status))

    def update_from_task(self, task: dict):
        self.current_state = task.get("state") or "preparing"
        self._raw_title = task.get("title") or self.video_id
        self._raw_status = task.get("status_text") or ""
        self._video_url = task.get("url") or f"https://www.youtube.com/watch?v={self.video_id}"
        self._channel_id = (task.get("channel_id") or "").strip()

        ch_name = task.get("channel") or "YouTube"
        if len(ch_name) > 24:
            ch_name = ch_name[:22] + "…"
        if ch_name != self._last_ch:
            self._last_ch = ch_name
            self.lbl_channel.setText(f"📺 {ch_name}")

        note = (task.get("note") or "").strip()
        if note != self._last_note:
            self._last_note = note
            if note:
                self.lbl_note.setText(f"🏷 {note}")
                self.lbl_note.setVisible(True)
            else:
                self.lbl_note.setVisible(False)

        res_b = task.get("resolution_badge") or ""
        if res_b and res_b != self._res_badge:
            self._res_badge = res_b
            self.lbl_thumb.setPixmap(make_rounded_thumbnail(self._thumb_bytes, self.THUMB_W, self.THUMB_H, self._res_badge))

        active_states = ("preparing", "waiting_hd", "downloading", "muxing")
        if self.current_state in active_states:
            want_pbar = True
            self.pbar.setValue(int(task.get("percent") or 0))
            style_key = "waiting_hd" if self.current_state == "waiting_hd" else "active"
            action_mode = "active"
        elif self.current_state == "completed":
            want_pbar = False
            style_key = "completed"
            action_mode = "completed"
        elif self.current_state in ("server_feed", "missed"):
            want_pbar = False
            style_key = "server_feed"
            action_mode = "server_feed"
        elif self.current_state == "skipped":
            want_pbar = False
            style_key = "muted"
            action_mode = "skipped"
        elif self.current_state == "cancelled":
            want_pbar = False
            style_key = "muted"
            action_mode = "retry"
        else:
            want_pbar = False
            style_key = "failed"
            action_mode = "retry"

        if want_pbar != self._last_pbar_vis:
            self._last_pbar_vis = want_pbar
            self.pbar.setVisible(want_pbar)

        if style_key != self._last_style_key:
            self._last_style_key = style_key
            style_map = {
                "waiting_hd": "color: #FDE047; font-size: 11.5px; font-weight: 700;",
                "active": "color: #7DD3FC; font-size: 11.5px; font-weight: 700;",
                "completed": "color: #4ADE80; font-size: 11.5px; font-weight: 700;",
                "server_feed": "color: #93C5FD; font-size: 11.5px; font-weight: 700;",
                "muted": "color: #CBD5E1; font-size: 11.5px; font-weight: 600;",
                "failed": "color: #FDA4AF; font-size: 11.5px; font-weight: 700;",
            }
            self.lbl_status.setStyleSheet(style_map[style_key])

        fp = task.get("file_path") or ""
        new_def_tpl = (task.get("selected_tpl") or "").strip() or BLANK_TEMPLATE_KEY
        new_tpl_list = task.get("templates_list")
        tpl_changed = False
        if isinstance(new_tpl_list, list) and new_tpl_list != self._templates_list:
            self._templates_list = list(new_tpl_list)
            tpl_changed = True
        if new_def_tpl != self._default_tpl:
            self._default_tpl = new_def_tpl
            tpl_changed = True

        if action_mode != self._last_action_mode or (action_mode == "completed" and fp != self._last_file_path):
            self._last_action_mode = action_mode
            self._last_file_path = fp
            self._rebuild_actions(action_mode, fp)
        elif action_mode == "completed" and tpl_changed:
            self._populate_card_tpl_combo()
            self._last_title_key = None
        self._apply_elided_title()

    def get_selected_card_template(self) -> str:
        if self.cmb_card_tpl is not None:
            val = self.cmb_card_tpl.currentData()
            return str(val) if val else BLANK_TEMPLATE_KEY
        return self._user_picked_tpl or self._default_tpl or BLANK_TEMPLATE_KEY

    def refresh_card_templates(self, templates_list: list[str], default_tpl: str = BLANK_TEMPLATE_KEY):
        self._templates_list = list(templates_list)
        self._default_tpl = (default_tpl or "").strip() or BLANK_TEMPLATE_KEY
        if self.cmb_card_tpl is not None:
            self._populate_card_tpl_combo()
            self._last_title_key = None
            self._apply_elided_title()

    def _populate_card_tpl_combo(self):
        cmb = self.cmb_card_tpl
        if cmb is None:
            return
        target = self._user_picked_tpl if self._user_picked_tpl is not None else self._default_tpl
        if target != BLANK_TEMPLATE_KEY and target not in self._templates_list:
            if self._user_picked_tpl == target:
                self._user_picked_tpl = None
            target = self._default_tpl if self._default_tpl in self._templates_list else BLANK_TEMPLATE_KEY
        cmb.set_state(self._templates_list, target)
        self._sync_card_combo_look()

    def _on_card_tpl_user_changed(self, new_val: str):
        self._user_picked_tpl = str(new_val or BLANK_TEMPLATE_KEY)
        self._sync_card_combo_look()

    def _sync_card_combo_look(self):
        cmb = self.cmb_card_tpl
        if cmb is None:
            return
        val = str(cmb.currentData() or BLANK_TEMPLATE_KEY)
        is_blank = val == BLANK_TEMPLATE_KEY
        if is_blank:
            cmb.setToolTip("Đang chọn: Mở Project Trắng mới tinh trong CapCut để tự edit")
        else:
            cmb.setToolTip(f"Đang chọn cấu hình mẫu '{val}' (bấm ✂️ CapCut bên cạnh để áp ngay)")
        if self._btn_cc_ref is not None:
            if is_blank:
                self._btn_cc_ref.setToolTip("1-Click mở Project Trắng mới tinh trong CapCut với sẵn video này!")
            else:
                self._btn_cc_ref.setToolTip(
                    f"1-Click đưa thẳng video này vào Mẫu '{val}' trong CapCut (giữ thông số mẫu + thay Title + giữ PART 1)!"
                )

    def _open_youtube_video(self):
        target = self._video_url or (f"https://www.youtube.com/watch?v={self.video_id}" if self.video_id else "")
        if target:
            webbrowser.open(target)

    def _open_youtube_channel(self):
        if self._channel_id:
            webbrowser.open(f"https://www.youtube.com/channel/{self._channel_id}")
        else:
            self._open_youtube_video()

    def _make_youtube_btn(self) -> QPushButton:
        btn_yt = QPushButton("↗")
        btn_yt.setObjectName("SubtleIconBtn")
        btn_yt.setFixedSize(28, 26)
        btn_yt.setToolTip("Mở xem video này trên YouTube")
        btn_yt.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_yt.clicked.connect(self._open_youtube_video)
        return btn_yt

    def _make_tiktok_btn(self) -> QPushButton:
        btn_tt = QPushButton("🔍 TikTok")
        btn_tt.setObjectName("TikTokSearchBtn")
        btn_tt.setFixedHeight(26)
        btn_tt.setToolTip("Tìm tiêu đề video này trên TikTok (kiểm tra đã có ai đăng chưa)")
        btn_tt.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_tt.clicked.connect(self._open_tiktok_search)
        return btn_tt

    def _open_tiktok_search(self):
        raw_q = (self._raw_title or "").strip()
        if not raw_q or raw_q == "Đang lấy thông tin video...":
            raw_q = self.video_id
        search_url = f"https://www.tiktok.com/search?q={urllib.parse.quote(raw_q)}"
        webbrowser.open(search_url)

    def _rebuild_actions(self, mode: str, file_path: str):
        self._btn_cc_ref = None
        self.cmb_card_tpl = None
        while self.action_lay.count():
            child = self.action_lay.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if mode == "active":
            self.action_lay.addWidget(self._make_tiktok_btn())
            btn_cancel = QPushButton("✕ Hủy")
            btn_cancel.setObjectName("GhostDangerBtn")
            btn_cancel.setFixedSize(64, 26)
            btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_cancel.clicked.connect(lambda: self._on_cancel(self.video_id))
            self.action_lay.addWidget(btn_cancel)

        elif mode == "completed" and file_path:
            if self._on_capcut is not None:
                cmb_tpl = TemplatePickerButton(blank_label="Project trắng", width=114, height=26)
                cmb_tpl.on_changed = self._on_card_tpl_user_changed
                self.cmb_card_tpl = cmb_tpl
                btn_cc = QPushButton("✂️ CapCut")
                btn_cc.setObjectName("CapCutBtn")
                btn_cc.setFixedHeight(26)
                btn_cc.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_cc.clicked.connect(self._trigger_capcut)
                self._btn_cc_ref = btn_cc
                self._populate_card_tpl_combo()
                self.action_lay.addWidget(cmb_tpl)
                self.action_lay.addWidget(btn_cc)

            btn_drag = DragDropFileButton(file_path)

            btn_folder = QPushButton("📂")
            btn_folder.setObjectName("SubtleIconBtn")
            btn_folder.setFixedSize(28, 26)
            btn_folder.setToolTip("Mở thư mục chứa file video này (bôi đen sẵn file)")
            btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_folder.clicked.connect(lambda: reveal_in_explorer(file_path))

            btn_tt = self._make_tiktok_btn()

            btn_copy = QPushButton("📋")
            btn_copy.setObjectName("SubtleIconBtn")
            btn_copy.setFixedSize(28, 26)
            btn_copy.setToolTip("Copy tiêu đề video")
            btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_copy.clicked.connect(lambda: self._copy_with_feedback(btn_copy))

            self.action_lay.addWidget(btn_drag)
            self.action_lay.addWidget(btn_folder)
            self.action_lay.addWidget(btn_tt)
            self.action_lay.addWidget(self._make_youtube_btn())
            self.action_lay.addWidget(btn_copy)

        elif mode == "server_feed":
            self.action_lay.addWidget(self._make_tiktok_btn())

            btn_dl = QPushButton("⬇ Tải")
            btn_dl.setObjectName("RubyBtn")
            btn_dl.setFixedHeight(26)
            btn_dl.setMinimumWidth(68)
            btn_dl.setToolTip("Tải video này về máy ở chất lượng 1080p Max Speed")
            btn_dl.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_dl.clicked.connect(lambda: self._on_retry(self.video_id))
            self.action_lay.addWidget(btn_dl)
            self.action_lay.addWidget(self._make_youtube_btn())

        elif mode == "skipped":
            self.action_lay.addWidget(self._make_tiktok_btn())
            btn_dl = QPushButton("⬇ Tải")
            btn_dl.setObjectName("RubyBtn")
            btn_dl.setFixedHeight(26)
            btn_dl.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_dl.clicked.connect(lambda: self._on_retry(self.video_id))
            self.action_lay.addWidget(btn_dl)
            self.action_lay.addWidget(self._make_youtube_btn())

        else:
            self.action_lay.addWidget(self._make_tiktok_btn())
            btn_retry = QPushButton("↻ Tải Lại")
            btn_retry.setFixedHeight(26)
            btn_retry.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_retry.clicked.connect(lambda: self._on_retry(self.video_id))
            self.action_lay.addWidget(btn_retry)
            self.action_lay.addWidget(self._make_youtube_btn())

    def _trigger_capcut(self):
        if not self._on_capcut or self._btn_cc_ref is None:
            return
        chosen_tpl = self.get_selected_card_template()
        self._btn_cc_ref.setEnabled(False)
        self._btn_cc_ref.setText("⏳...")
        self._on_capcut(self.video_id, chosen_tpl)
        QTimer.singleShot(1400, self._restore_cc_btn)

    def _restore_cc_btn(self):
        if self._btn_cc_ref is not None:
            self._btn_cc_ref.setEnabled(True)
            self._btn_cc_ref.setText("✂️ CapCut")

    def _copy_with_feedback(self, btn: QPushButton):
        QApplication.clipboard().setText(self._raw_title or "")
        btn.setText("✓")
        QTimer.singleShot(1200, lambda: btn.setText("📋"))


class ChannelRowCard(QFrame):
    NOTE_SAVED_STYLE = (
        "QLineEdit { background-color: #064E3B; color: #6EE7B7; border: 1.5px solid #10B981; "
        "border-radius: 5px; padding: 1px 8px; font-weight: 800; font-size: 11.5px; }"
    )

    def __init__(
        self,
        ch_data: dict,
        is_enabled: bool,
        on_toggle_fn,
        on_note_save_fn,
        on_open_yt_fn,
        on_delete_fn,
        templates_list: list[str] | None = None,
        selected_tpl: str = BLANK_TEMPLATE_KEY,
        on_tpl_change_fn=None,
        parent=None,
    ):
        super().__init__(parent)
        self.ch_data = ch_data
        self.cid = ch_data.get("channel_id") or ""
        self.cname = ch_data.get("channel_name") or self.cid
        self.row_id = ch_data.get("id") or 0
        self._saved_note = ch_data.get("note") or ""
        self._on_note_save = on_note_save_fn
        self._on_tpl_change = on_tpl_change_fn

        # Thanh kênh siêu gọn 38px (1 dòng ngang, hiển thị được ~14 kênh cùng lúc!)
        self.setFixedHeight(38)
        self.setObjectName("StudioCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 3, 8, 3)
        lay.setSpacing(7)

        self.sw_enable = ToggleSwitch(checked=is_enabled, active_color="#10B981")
        self.sw_enable.toggled.connect(lambda chk: on_toggle_fn(self.cid, self.cname, chk))
        lay.addWidget(self.sw_enable)

        self.lbl_name = QLabel(self.cname)
        self.lbl_name.setMinimumWidth(75)
        self.lbl_name.setStyleSheet("color: #FFFFFF; font-size: 12.5px; font-weight: 800;")
        self.lbl_name.setToolTip(f"{self.cname} ({self.cid})")
        lay.addWidget(self.lbl_name, 1)

        lbl_nt_tag = QLabel("🏷")
        lbl_nt_tag.setStyleSheet("color: #FBBF24; font-size: 11.5px;")
        lbl_nt_tag.setToolTip("Nhãn Note máy (phân luồng tự động tải)")
        lay.addWidget(lbl_nt_tag)

        self.inp_note = QLineEdit(self._saved_note)
        self.inp_note.setObjectName("NoteEditBox")
        self.inp_note.setPlaceholderText("Note máy...")
        self.inp_note.setFixedWidth(112)
        self.inp_note.setFixedHeight(25)
        self.inp_note.editingFinished.connect(self._commit_note_if_changed)
        lay.addWidget(self.inp_note)

        lbl_cc_tag = QLabel("✂️")
        lbl_cc_tag.setStyleSheet("color: #38BDF8; font-size: 11.5px;")
        lbl_cc_tag.setToolTip("Mẫu CapCut riêng cho kênh này (Không chọn = Project trắng)")
        lay.addWidget(lbl_cc_tag)

        self.cmb_tpl = TemplatePickerButton(blank_label="Project trắng", width=136, height=25)
        self.set_templates_list(templates_list or [], selected_tpl)
        self.cmb_tpl.on_changed = self._on_combo_changed
        lay.addWidget(self.cmb_tpl)

        btn_yt = QPushButton("↗ Kênh")
        btn_yt.setFixedHeight(25)
        btn_yt.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_yt.setToolTip("Mở trang video của kênh trên YouTube")
        btn_yt.clicked.connect(lambda: on_open_yt_fn(self.cid))
        lay.addWidget(btn_yt)

        btn_del = QPushButton("🗑 Xóa")
        btn_del.setObjectName("GhostDangerBtn")
        btn_del.setFixedSize(60, 25)
        btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_del.clicked.connect(lambda: on_delete_fn(self.row_id, self.cid, self.cname))
        lay.addWidget(btn_del)
        self._last_elide_w = -1

    def set_templates_list(self, templates_list: list[str], selected_tpl: str = BLANK_TEMPLATE_KEY):
        cur = (selected_tpl or "").strip() or BLANK_TEMPLATE_KEY
        self.cmb_tpl.set_state(templates_list, cur)

    def _on_combo_changed(self, new_val: str):
        if self._on_tpl_change:
            self._on_tpl_change(self.cid, self.cname, str(new_val or BLANK_TEMPLATE_KEY))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        avail = max(75, self.width() - 508)
        if avail != self._last_elide_w:
            self._last_elide_w = avail
            fm = QFontMetrics(self.lbl_name.font())
            self.lbl_name.setText(fm.elidedText(self.cname, Qt.TextElideMode.ElideRight, avail))

    def _commit_note_if_changed(self):
        val = self.inp_note.text().strip()
        if val == self._saved_note:
            return
        self._saved_note = val
        self._on_note_save(self.row_id, self.cid, val)
        self.inp_note.setStyleSheet(self.NOTE_SAVED_STYLE)
        QTimer.singleShot(900, lambda: self.inp_note.setStyleSheet(""))


class SettingSectionCard(QFrame):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("SectionCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.main_lay = QVBoxLayout(self)
        self.main_lay.setContentsMargins(14, 12, 14, 12)
        self.main_lay.setSpacing(10)

        head = QVBoxLayout()
        head.setSpacing(2)
        lbl_t = QLabel(title)
        lbl_t.setStyleSheet("color: #FFFFFF; font-size: 13.5px; font-weight: 800;")
        head.addWidget(lbl_t)
        if subtitle:
            lbl_s = QLabel(subtitle)
            lbl_s.setWordWrap(True)
            lbl_s.setStyleSheet("color: #CBD5E1; font-size: 11.5px;")
            head.addWidget(lbl_s)
        self.main_lay.addLayout(head)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #334155; border: none;")
        self.main_lay.addWidget(sep)

    def add_setting_row(self, label_title: str, description: str, right_widget: QWidget):
        row = QHBoxLayout()
        row.setSpacing(12)

        txt_col = QVBoxLayout()
        txt_col.setSpacing(1)
        t = QLabel(label_title)
        t.setStyleSheet("color: #FFFFFF; font-size: 12.5px; font-weight: 700;")
        txt_col.addWidget(t)
        if description:
            d = QLabel(description)
            d.setWordWrap(True)
            d.setStyleSheet("color: #CBD5E1; font-size: 11px;")
            txt_col.addWidget(d)

        row.addLayout(txt_col, 1)
        row.addWidget(right_widget, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.main_lay.addLayout(row)

    def add_full_widget(self, widget: QWidget):
        self.main_lay.addWidget(widget)


class CapCutProjectRowCard(QFrame):
    """Thanh Project CapCut quét trực tiếp từ máy (48px gọn gàng): tích chọn trực tiếp làm Mẫu (0 copy, 0 đặt tên lại)."""

    def __init__(
        self,
        proj: dict,
        is_selected_tpl: bool,
        on_toggle_tpl_fn,
        parent=None,
    ):
        super().__init__(parent)
        self.proj = proj
        self.folder_name = proj.get("folder_name") or ""
        self.display_name = proj.get("display_name") or self.folder_name
        self.template_key = proj.get("template_key") or self.display_name
        self._on_toggle_tpl = on_toggle_tpl_fn

        self.setFixedHeight(48)
        self.setObjectName("StudioCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 5, 9, 5)
        lay.setSpacing(9)

        # 1. Ảnh bìa Project CapCut 64x36 (có bộ nhớ đệm Pixmap chống đọc ổ cứng lặp lại!)
        lbl_cov = QLabel()
        lbl_cov.setFixedSize(64, 36)
        cov_p = proj.get("cover_path") or ""
        pix = _COVER_PIX_CACHE.get(cov_p) if cov_p else None
        if pix is None:
            cov_bytes = None
            if cov_p and os.path.isfile(cov_p):
                try:
                    with open(cov_p, "rb") as f:
                        cov_bytes = f.read()
                except Exception:
                    cov_bytes = None
            pix = make_rounded_thumbnail(cov_bytes, 64, 36)
            if cov_p:
                _COVER_PIX_CACHE[cov_p] = pix
        lbl_cov.setPixmap(pix)
        lay.addWidget(lbl_cov)

        # 2. Công tắc Tích chọn dùng trực tiếp làm Mẫu
        self.sw_use = ToggleSwitch(
            checked=bool(is_selected_tpl),
            active_color="#10B981",
        )
        self.sw_use.setToolTip("Tích chọn để dùng trực tiếp Project CapCut này làm Mẫu (không tạo bản sao)")
        lay.addWidget(self.sw_use)

        # 3. Tên Project + Thông số kỹ thuật
        info_col = QVBoxLayout()
        info_col.setContentsMargins(0, 0, 0, 0)
        info_col.setSpacing(1)

        top_r = QHBoxLayout()
        top_r.setContentsMargins(0, 0, 0, 0)
        top_r.setSpacing(6)

        self.lbl_badge = QLabel()
        top_r.addWidget(self.lbl_badge)

        lbl_title = QLabel(self.template_key)
        lbl_title.setStyleSheet("color: #FFFFFF; font-size: 12.5px; font-weight: 800;")
        top_r.addWidget(lbl_title, 1)
        info_col.addLayout(top_r)

        spec = proj.get("spec_summary") or "Project CapCut"
        mod_s = proj.get("modified_str") or ""
        sub_txt = f"{spec}  •  Cập nhật: {mod_s}" if mod_s else spec
        lbl_sub = QLabel(sub_txt)
        lbl_sub.setStyleSheet("color: #94A3B8; font-size: 11px; font-weight: 600;")
        info_col.addWidget(lbl_sub)

        lay.addLayout(info_col, 1)

        # 4. Nút trạng thái tích chọn nhanh bên phải (0 hộp thoại, 0 copy thừa project)
        self.btn_pick = QPushButton()
        self.btn_pick.setFixedSize(116, 26)
        self.btn_pick.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pick.clicked.connect(lambda: self.sw_use.setChecked(not self.sw_use.isChecked()))
        lay.addWidget(self.btn_pick)

        self._sync_selected_visual(bool(is_selected_tpl))
        self.sw_use.toggled.connect(self._on_switch_toggled)

    def _on_switch_toggled(self, checked: bool):
        self._sync_selected_visual(checked)
        if self._on_toggle_tpl:
            self._on_toggle_tpl(self.folder_name, checked)

    def _sync_selected_visual(self, checked: bool):
        if checked:
            self.setStyleSheet(
                "QFrame#StudioCard { background-color: #132A26; border: 1.5px solid #10B981; border-radius: 7px; }"
            )
            self.lbl_badge.setText("✓ ĐANG DÙNG")
            self.lbl_badge.setStyleSheet(
                "background-color: #10B981; color: #022C22; border-radius: 4px; "
                "padding: 1px 6px; font-size: 10px; font-weight: 900;"
            )
            self.btn_pick.setText("✓ Đã chọn")
            self.btn_pick.setStyleSheet(
                "QPushButton { background-color: #059669; color: #FFFFFF; border: 1px solid #34D399; "
                "border-radius: 5px; font-size: 11px; font-weight: 800; }"
                "QPushButton:hover { background-color: #10B981; }"
            )
        else:
            self.setStyleSheet("")
            self.lbl_badge.setText("🎬 CAPCUT")
            self.lbl_badge.setStyleSheet(
                "background-color: #334155; color: #E2E8F0; border-radius: 4px; "
                "padding: 1px 6px; font-size: 10px; font-weight: 800;"
            )
            self.btn_pick.setText("+ Chọn mẫu")
            self.btn_pick.setStyleSheet(
                "QPushButton { background-color: #0F172A; color: #CBD5E1; border: 1px solid #475569; "
                "border-radius: 5px; font-size: 11px; font-weight: 700; }"
                "QPushButton:hover { border-color: #10B981; color: #FFFFFF; }"
            )

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.sw_use.setChecked(not self.sw_use.isChecked())
            event.accept()
            return
        super().mouseReleaseEvent(event)

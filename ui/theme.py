# -*- coding: utf-8 -*-
"""
Design System Tương Phản Cao (High-Contrast Studio Theme):
- Mọi Nút bấm (#334155 viền sáng #64748B chữ Trắng #FFFFFF), Nhãn Note (Vàng #F59E0B chữ Đen đậm),
  Ô nhập liệu (#263244 chữ Trắng) và Chữ phụ (#CBD5E1) đều đạt chuẩn tương phản cao dễ đọc tuyệt đối.
"""
import os
import subprocess
import winsound

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QRect, QRectF, QSize, Qt, pyqtProperty
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
)


def create_mercedes_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#0B0F19"))
    p.setPen(QPen(QColor("#F43F5E"), 2))
    p.drawRoundedRect(2, 2, 60, 60, 15, 15)
    p.setPen(QColor("#F43F5E"))
    font = QFont("Segoe UI", 29, QFont.Weight.Black)
    p.setFont(font)
    p.drawText(QRect(0, 0, 64, 64), Qt.AlignmentFlag.AlignCenter, "M")
    p.end()
    return QIcon(pix)


def reveal_in_explorer(file_path: str):
    if not file_path:
        return
    norm = os.path.abspath(os.path.normpath(file_path))
    if os.path.exists(norm):
        subprocess.Popen(f'explorer.exe /select,"{norm}"')
    else:
        parent = os.path.dirname(norm)
        if parent and os.path.isdir(parent):
            os.startfile(parent)


def open_media_file(file_path: str):
    if file_path and os.path.exists(file_path):
        os.startfile(os.path.normpath(file_path))


def play_alert_beep(is_complete: bool = False):
    """Phát âm báo bất đồng bộ 0ms trên Windows (TUYỆT ĐỐI không bao giờ khóa luồng GUI như winsound.Beep!)."""
    try:
        alias = "SystemAsterisk" if is_complete else "SystemExclamation"
        winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:
        pass


class ToggleSwitch(QAbstractButton):
    """Công tắc gạt tròn siêu nhẹ 0ms: không dùng timer animation để GUI phản hồi tức thì."""

    def __init__(self, checked: bool = False, active_color: str = "#10B981", parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(bool(checked))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(36, 19)
        self._active_color = QColor(active_color)
        self._off_color = QColor("#475569")
        self._offset = 19.0 if checked else 2.0
        self.toggled.connect(self._animate_to_state)

    def _animate_to_state(self, checked: bool):
        self._offset = 19.0 if checked else 2.0
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(36, 19)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        track_color = self._active_color if self.isChecked() else self._off_color
        border_color = QColor("#34D399") if self.isChecked() else QColor("#94A3B8")
        p.setPen(QPen(border_color, 1))
        p.setBrush(track_color)
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 9.0, 9.0)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(self._offset, 2.0, 15.0, 15.0))
        p.end()


class SidebarNavButton(QPushButton):
    """Nút điều hướng Sidebar trái gọn gàng, chữ sáng trắng rõ nét."""

    def __init__(self, icon_char: str, title: str, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 8, 0)
        lay.setSpacing(8)

        self.lbl_icon = QLabel(icon_char)
        self.lbl_icon.setFixedWidth(18)
        self.lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_icon.setStyleSheet("font-size: 13px; background: transparent; border: none;")

        self.lbl_text = QLabel(title)
        self.lbl_text.setStyleSheet("font-size: 12.5px; font-weight: 700; background: transparent; border: none;")

        self.lbl_badge = QLabel("")
        self.lbl_badge.setVisible(False)
        self.lbl_badge.setFixedHeight(18)
        self.lbl_badge.setMinimumWidth(22)
        self.lbl_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lay.addWidget(self.lbl_icon)
        lay.addWidget(self.lbl_text, 1)
        lay.addWidget(self.lbl_badge)

        self.toggled.connect(self._update_look)
        self._update_look(False)

    def set_badge(self, count_or_str, highlight: bool = False):
        s = str(count_or_str).strip()
        if not s or s == "0":
            self.lbl_badge.setVisible(False)
            return
        self.lbl_badge.setText(s)
        self.lbl_badge.setVisible(True)
        bg = "#E11D48" if highlight else "#2563EB"
        self.lbl_badge.setStyleSheet(
            f"background-color: {bg}; color: #FFFFFF; border-radius: 8px; "
            "padding: 0px 6px; font-size: 10.5px; font-weight: 800; border: none;"
        )

    def _update_look(self, active: bool):
        if active:
            self.setStyleSheet(
                """
                QPushButton {
                    background-color: #263349;
                    border: 1px solid #3B4D6B;
                    border-left: 3px solid #F43F5E;
                    border-radius: 6px;
                }
                """
            )
            self.lbl_text.setStyleSheet(
                "color: #FFFFFF; font-size: 12.5px; font-weight: 800; background: transparent; border: none;"
            )
        else:
            self.setStyleSheet(
                """
                QPushButton {
                    background-color: transparent;
                    border: none;
                    border-left: 3px solid transparent;
                    border-radius: 6px;
                }
                QPushButton:hover {
                    background-color: #1E293B;
                }
                """
            )
            self.lbl_text.setStyleSheet(
                "color: #E2E8F0; font-size: 12.5px; font-weight: 600; background: transparent; border: none;"
            )


class PillFilterButton(QPushButton):
    """Nút lọc viên thuốc nhỏ gọn tương phản cao."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(25)
        self.toggled.connect(self._sync_style)
        self._sync_style(False)

    def _sync_style(self, checked: bool):
        if checked:
            self.setStyleSheet(
                "QPushButton { background-color: #E11D48; color: #FFFFFF; border: 1px solid #FB7185; "
                "border-radius: 12px; padding: 0 12px; font-size: 11.5px; font-weight: 800; }"
            )
        else:
            self.setStyleSheet(
                "QPushButton { background-color: #E2E8F0; color: #0F172A; border: 1px solid #FFFFFF; "
                "border-radius: 12px; padding: 0 12px; font-size: 11.5px; font-weight: 800; }"
                "QPushButton:hover { background-color: #FFFFFF; color: #0F172A; }"
            )


def make_rounded_thumbnail(img_bytes: bytes | None, width: int = 84, height: int = 48, badge_text: str = "") -> QPixmap:
    canvas = QPixmap(width, height)
    canvas.fill(Qt.GlobalColor.transparent)

    p = QPainter(canvas)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    path = QPainterPath()
    path.addRoundedRect(0, 0, width, height, 6, 6)
    p.setClipPath(path)

    drawn = False
    if img_bytes:
        src = QPixmap()
        if src.loadFromData(img_bytes):
            scaled = src.scaled(
                width,
                height,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            sx = max(0, (scaled.width() - width) // 2)
            sy = max(0, (scaled.height() - height) // 2)
            p.drawPixmap(0, 0, scaled, sx, sy, width, height)
            drawn = True

    if not drawn:
        p.fillRect(0, 0, width, height, QColor("#293548"))
        p.setPen(QColor("#E2E8F0"))
        p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        p.drawText(canvas.rect(), Qt.AlignmentFlag.AlignCenter, "▶ YT")

    if badge_text:
        short_b = badge_text.split()[0]
        bw = min(width - 6, max(36, len(short_b) * 6 + 8))
        bx = width - bw - 3
        by = height - 16
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(15, 23, 42, 232))
        p.drawRoundedRect(bx, by, bw, 13, 3, 3)
        p.setPen(QColor("#4ADE80"))
        p.setFont(QFont("Segoe UI", 7, QFont.Weight.ExtraBold))
        p.drawText(bx, by, bw, 13, Qt.AlignmentFlag.AlignCenter, short_b)

    p.end()
    return canvas


# Lưu ý quan trọng: Không đặt background-color chung cho QWidget để tránh đè đen các nút con!
STUDIO_STYLESHEET = """
QMainWindow, QDialog, QMessageBox {
    background-color: #0F172A;
    color: #FFFFFF;
    font-family: 'Segoe UI', sans-serif;
    font-size: 12px;
}
QWidget {
    color: #FFFFFF;
    font-family: 'Segoe UI', sans-serif;
    font-size: 12px;
}
QLabel, QWidget#ScrollHost, QWidget#TransparentBox {
    background: transparent;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background: #0F172A;
}
QFrame#LeftSidebar {
    background-color: #090D16;
    border-right: 1px solid #1E293B;
}
QFrame#SidebarBotCard {
    background-color: #1E293B;
    border: 1px solid #475569;
    border-radius: 8px;
}
QFrame#StudioCard {
    background-color: #1E293B;
    border: 1px solid #475569;
    border-radius: 7px;
}
QFrame#SectionCard {
    background-color: #1E293B;
    border: 1px solid #475569;
    border-radius: 9px;
}
QFrame#SpotlightBox {
    background-color: #1E293B;
    border: 1px solid #94A3B8;
    border-radius: 7px;
}
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {
    background-color: #0F172A;
    border: 1px solid #94A3B8;
    border-radius: 6px;
    padding: 3px 9px;
    color: #FFFFFF;
    font-size: 12px;
    font-weight: 600;
    selection-background-color: #E11D48;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {
    border: 1.5px solid #38BDF8;
    background-color: #162238;
}
QLineEdit#SpotlightInput {
    border: none;
    background: transparent;
    color: #FFFFFF;
    padding: 0px 4px;
    font-size: 12px;
    font-weight: 600;
}
QLineEdit#NoteEditBox {
    background-color: #0F172A;
    color: #FDE047;
    border: 1px solid #F59E0B;
    border-radius: 5px;
    padding: 1px 8px;
    font-weight: 800;
    font-size: 11.5px;
}
QLineEdit#NoteEditBox:focus {
    border: 1.5px solid #FDE047;
    background-color: #17253B;
}
QComboBox#ChannelTplActive {
    background-color: #0C2438;
    color: #7DD3FC;
    border: 1.5px solid #38BDF8;
    border-radius: 5px;
    padding: 1px 7px;
    font-weight: 800;
    font-size: 11.5px;
}
QComboBox#ChannelTplBlank {
    background-color: #0F172A;
    color: #CBD5E1;
    border: 1px solid #64748B;
    border-radius: 5px;
    padding: 1px 7px;
    font-weight: 600;
    font-size: 11.5px;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: #1E293B;
    color: #FFFFFF;
    selection-background-color: #E11D48;
    border: 1px solid #94A3B8;
    border-radius: 6px;
}
QMenu {
    background-color: #1E293B;
    color: #FFFFFF;
    border: 1px solid #94A3B8;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 5px 14px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 700;
}
QMenu::item:selected {
    background-color: #E11D48;
    color: #FFFFFF;
}
QPushButton#TplPickerActive {
    background-color: #0C2438;
    color: #7DD3FC;
    border: 1.5px solid #38BDF8;
    border-radius: 5px;
    padding: 1px 8px;
    font-weight: 800;
    font-size: 11.5px;
    text-align: left;
}
QPushButton#TplPickerActive:hover {
    background-color: #123452;
    color: #BAE6FD;
}
QPushButton#TplPickerBlank {
    background-color: #0F172A;
    color: #CBD5E1;
    border: 1px solid #64748B;
    border-radius: 5px;
    padding: 1px 8px;
    font-weight: 600;
    font-size: 11.5px;
    text-align: left;
}
QPushButton#TplPickerBlank:hover {
    border-color: #38BDF8;
    color: #FFFFFF;
}
/* Nút bấm tiêu chuẩn gọn gàng: Nền Bạc Sáng (#E2E8F0) + Chữ Đen Đậm (#0F172A) */
QPushButton {
    background-color: #E2E8F0;
    border: 1px solid #FFFFFF;
    border-radius: 6px;
    padding: 2px 10px;
    color: #0F172A;
    font-size: 11.5px;
    font-weight: 800;
}
QPushButton:hover {
    background-color: #FFFFFF;
    border-color: #38BDF8;
    color: #020617;
}
QPushButton:pressed {
    background-color: #CBD5E1;
}
QPushButton:disabled {
    background-color: #475569;
    color: #CBD5E1;
    border-color: #64748B;
}
QPushButton#RubyBtn {
    background-color: #E11D48;
    border: 1px solid #FDA4AF;
    color: #FFFFFF;
    font-weight: 800;
}
QPushButton#RubyBtn:hover {
    background-color: #F43F5E;
    color: #FFFFFF;
}
QPushButton#DragActionBtn {
    background-color: #10B981;
    border: 1px solid #6EE7B7;
    color: #022C22;
    font-weight: 900;
}
QPushButton#DragActionBtn:hover {
    background-color: #34D399;
    color: #022C22;
}
QPushButton#CapCutBtn {
    background-color: #38BDF8;
    border: 1px solid #BAE6FD;
    color: #020617;
    font-weight: 900;
}
QPushButton#CapCutBtn:hover {
    background-color: #7DD3FC;
    color: #020617;
}
QPushButton#CapCutBlankBtn {
    background-color: #CBD5E1;
    border: 1px solid #F8FAFC;
    color: #0F172A;
    font-weight: 800;
}
QPushButton#CapCutBlankBtn:hover {
    background-color: #FFFFFF;
    border-color: #38BDF8;
    color: #020617;
}
QPushButton#SubtleIconBtn {
    background-color: #E2E8F0;
    border: 1px solid #FFFFFF;
    border-radius: 6px;
    padding: 0px;
    color: #0F172A;
    font-size: 12px;
    font-weight: 900;
}
QPushButton#SubtleIconBtn:hover {
    background-color: #FFFFFF;
    border-color: #38BDF8;
}
QPushButton#TikTokSearchBtn {
    background-color: #0F172A;
    border: 1.5px solid #22D3EE;
    border-radius: 6px;
    padding: 1px 7px;
    color: #67E8F9;
    font-size: 11px;
    font-weight: 800;
}
QPushButton#TikTokSearchBtn:hover {
    background-color: #164E63;
    border-color: #FE2C55;
    color: #FFFFFF;
}
QPushButton#GhostDangerBtn {
    background-color: #EF4444;
    border: 1px solid #FCA5A5;
    border-radius: 6px;
    padding: 2px 8px;
    color: #FFFFFF;
    font-size: 11.5px;
    font-weight: 800;
}
QPushButton#GhostDangerBtn:hover {
    background-color: #DC2626;
    border-color: #FFFFFF;
}
QScrollArea {
    border: none;
    background-color: transparent;
}
QScrollBar:vertical {
    background: #0F172A;
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #475569;
    min-height: 24px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #64748B;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QProgressBar {
    border: none;
    border-radius: 2px;
    background-color: #334155;
    height: 4px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #38BDF8, stop:1 #22D3EE);
    border-radius: 2px;
}
QToolTip {
    background-color: #1E293B;
    color: #FFFFFF;
    border: 1px solid #64748B;
    padding: 4px 8px;
}
"""

# -*- coding: utf-8 -*-
"""
Thẻ thông báo nổi góc dưới phải màn hình (Sleek Studio Toast) — không cướp chuột khi đang làm việc.
"""
import urllib.parse
import webbrowser

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.theme import make_rounded_thumbnail, reveal_in_explorer


class DesktopToastPopup(QWidget):
    _active_popups = []

    def __init__(
        self,
        header_text: str,
        channel_name: str,
        video_title: str,
        accent: str = "#E11D48",
        file_path: str = "",
        thumb_bytes: bytes | None = None,
        duration_ms: int = 8500,
    ):
        super().__init__(None)
        self.file_path = file_path
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedWidth(415)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setStyleSheet(
            f"""
            QFrame {{
                background-color: #1E293B;
                border: 1px solid #475569;
                border-left: 5px solid {accent};
                border-radius: 11px;
            }}
            QLabel {{ border: none; background: transparent; }}
            """
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 11, 14, 11)
        lay.setSpacing(8)

        top_row = QHBoxLayout()
        lbl_head = QLabel(header_text)
        lbl_head.setStyleSheet(f"color: {accent}; font-weight: 800; font-size: 12px;")
        btn_close = QPushButton("✕")
        btn_close.setObjectName("SubtleIconBtn")
        btn_close.setFixedSize(24, 24)
        btn_close.clicked.connect(self._dismiss)
        top_row.addWidget(lbl_head)
        top_row.addStretch()
        top_row.addWidget(btn_close)
        lay.addLayout(top_row)

        mid_row = QHBoxLayout()
        mid_row.setSpacing(12)

        lbl_thumb = QLabel()
        lbl_thumb.setFixedSize(108, 61)
        lbl_thumb.setPixmap(make_rounded_thumbnail(thumb_bytes, 108, 61))
        mid_row.addWidget(lbl_thumb)

        info_col = QVBoxLayout()
        info_col.setSpacing(3)
        lbl_ch = QLabel(f"📺 {channel_name}")
        lbl_ch.setStyleSheet("color: #FFFFFF; font-weight: 800; font-size: 13px;")
        info_col.addWidget(lbl_ch)

        lbl_title = QLabel(video_title)
        lbl_title.setWordWrap(True)
        lbl_title.setMaximumHeight(38)
        lbl_title.setStyleSheet("color: #E2E8F0; font-size: 12px; font-weight: 600;")
        info_col.addWidget(lbl_title)
        mid_row.addLayout(info_col, 1)
        lay.addLayout(mid_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        if file_path:
            btn_folder = QPushButton("📂 Mở Thư Mục")
            btn_folder.setObjectName("DragActionBtn")
            btn_folder.setFixedHeight(30)
            btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_folder.clicked.connect(lambda: (reveal_in_explorer(self.file_path), self._dismiss()))
            btn_row.addWidget(btn_folder)

        if video_title:
            btn_tt = QPushButton("🔍 Search TikTok")
            btn_tt.setObjectName("TikTokSearchBtn")
            btn_tt.setFixedHeight(30)
            btn_tt.setCursor(Qt.CursorShape.PointingHandCursor)
            tt_url = f"https://www.tiktok.com/search?q={urllib.parse.quote(video_title.strip())}"
            btn_tt.clicked.connect(lambda: (webbrowser.open(tt_url), self._dismiss()))
            btn_row.addWidget(btn_tt)

        if btn_row.count() > 0:
            lay.addLayout(btn_row)

        outer.addWidget(card)
        self.adjustSize()

        DesktopToastPopup._active_popups.append(self)
        DesktopToastPopup._reflow_all()
        QTimer.singleShot(duration_ms, self._dismiss)

    @classmethod
    def _reflow_all(cls):
        screen = QApplication.primaryScreen().availableGeometry()
        cur_bottom = screen.bottom() - 18
        for pop in reversed(cls._active_popups):
            if pop.isVisible() or pop == cls._active_popups[-1]:
                x = screen.right() - pop.width() - 18
                y = cur_bottom - pop.height()
                pop.move(QPoint(x, max(20, y)))
                cur_bottom = y - 10

    def _dismiss(self):
        if self in DesktopToastPopup._active_popups:
            DesktopToastPopup._active_popups.remove(self)
        self.close()
        self.deleteLater()
        DesktopToastPopup._reflow_all()

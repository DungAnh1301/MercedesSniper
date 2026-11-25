# -*- coding: utf-8 -*-
"""
Màn hình Đăng nhập Tối giản, Sang trọng (Minimalist Studio Login).
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from core.vps_client import DEFAULT_SERVER_URL, SoitubeVPSClient
from ui.theme import STUDIO_STYLESHEET, ToggleSwitch, create_mercedes_icon


class LoginDialog(QDialog):
    def __init__(self, vps_client: SoitubeVPSClient, cfg: dict, save_cfg_fn, parent=None):
        super().__init__(parent)
        self.vps = vps_client
        self.cfg = cfg
        self._save_cfg = save_cfg_fn

        self.setWindowTitle("Mercedes Sniper — Đăng nhập")
        self.setWindowIcon(create_mercedes_icon())
        self.setFixedSize(410, 385)
        self.setStyleSheet(STUDIO_STYLESHEET)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 26)
        lay.setSpacing(14)

        brand = QLabel("MERCEDES SNIPER")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.setStyleSheet("color: #F8FAFC; font-size: 22px; font-weight: 900; letter-spacing: 2.5px;")
        lay.addWidget(brand)

        sub = QLabel("Nhận tín hiệu trực tiếp 0ms • Tải chuẩn 1080p Max Speed")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color: #CBD5E1; font-size: 12.5px; margin-bottom: 6px;")
        lay.addWidget(sub)

        self.inp_user = QLineEdit(cfg.get("username", ""))
        self.inp_user.setFixedHeight(38)
        self.inp_user.setPlaceholderText("Tài khoản nhân viên")
        lay.addWidget(self.inp_user)

        pw_row = QHBoxLayout()
        pw_row.setSpacing(6)
        self.inp_pass = QLineEdit(cfg.get("password", "") if cfg.get("remember", True) else "")
        self.inp_pass.setFixedHeight(38)
        self.inp_pass.setPlaceholderText("Mật khẩu")
        self.inp_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.inp_pass.returnPressed.connect(self.do_login)

        btn_eye = QPushButton("👁")
        btn_eye.setObjectName("SubtleIconBtn")
        btn_eye.setFixedSize(38, 38)
        btn_eye.setCheckable(True)
        btn_eye.toggled.connect(
            lambda checked: self.inp_pass.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        pw_row.addWidget(self.inp_pass, 1)
        pw_row.addWidget(btn_eye)
        lay.addLayout(pw_row)

        opt_row = QHBoxLayout()
        self.sw_remember = ToggleSwitch(checked=bool(cfg.get("remember", True)), active_color="#10B981")
        lbl_rem = QLabel("Ghi nhớ đăng nhập")
        lbl_rem.setStyleSheet("color: #E2E8F0; font-size: 12.5px; font-weight: 600;")

        btn_srv = QPushButton("⚙️ Máy chủ")
        btn_srv.setFixedHeight(28)
        btn_srv.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_srv.clicked.connect(self._toggle_server_box)

        opt_row.addWidget(self.sw_remember)
        opt_row.addWidget(lbl_rem)
        opt_row.addStretch()
        opt_row.addWidget(btn_srv)
        lay.addLayout(opt_row)

        self.inp_server = QLineEdit(cfg.get("server_url") or DEFAULT_SERVER_URL)
        self.inp_server.setFixedHeight(34)
        self.inp_server.setPlaceholderText("http://soitobe.duckdns.org")
        self.inp_server.setVisible(False)
        lay.addWidget(self.inp_server)

        self.lbl_msg = QLabel("")
        self.lbl_msg.setWordWrap(True)
        self.lbl_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_msg.setStyleSheet("color: #FB7185; font-size: 12px;")
        lay.addWidget(self.lbl_msg)

        lay.addStretch()

        self.btn_login = QPushButton("Đăng Nhập & Bắt Đầu Trực Chiến")
        self.btn_login.setObjectName("RubyBtn")
        self.btn_login.setFixedHeight(42)
        self.btn_login.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_login.clicked.connect(self.do_login)
        lay.addWidget(self.btn_login)

    def _toggle_server_box(self):
        vis = not self.inp_server.isVisible()
        self.inp_server.setVisible(vis)
        self.setFixedHeight(430 if vis else 385)

    def do_login(self):
        srv = self.inp_server.text().strip() or DEFAULT_SERVER_URL
        u = self.inp_user.text().strip()
        p = self.inp_pass.text().strip()

        self.btn_login.setEnabled(False)
        self.btn_login.setText("Đang kết nối đường truyền...")
        self.lbl_msg.setStyleSheet("color: #94A3B8; font-size: 12px;")
        self.lbl_msg.setText("")
        QApplication.processEvents()

        ok, msg = self.vps.login(srv, u, p)
        self.btn_login.setEnabled(True)
        self.btn_login.setText("Đăng Nhập & Bắt Đầu Trực Chiến")

        if ok:
            self.cfg["server_url"] = srv
            self.cfg["username"] = self.vps.username
            self.cfg["remember"] = self.sw_remember.isChecked()
            self.cfg["password"] = p if self.sw_remember.isChecked() else ""
            self._save_cfg(self.cfg)
            self.accept()
        else:
            self.lbl_msg.setStyleSheet("color: #FB7185; font-size: 12px;")
            self.lbl_msg.setText(msg)

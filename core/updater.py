# -*- coding: utf-8 -*-
"""
Bộ Tự Động Cập Nhật Qua GitHub Releases (Zero-Lag Background Updater)
- Kiểm tra ngầm từ `latest.json` trên GitHub Releases CDN (0 giới hạn API, 0ms khựng GUI).
- Tải ngầm file `.exe` mới, kiểm tra chữ ký PE (`MZ`) + mã băm `SHA-256`.
- Tự động tráo file `.exe` an toàn (chờ cả tiến trình con & PyInstaller Bootloader nhả khóa),
  lưu bản dự phòng vào `%LOCALAPPDATA%\\MercedesSniper\\rollback` (không bày file `.bak` ra Desktop)
  và khởi động lại bản mới ngay lập tức!
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from typing import Callable, Optional

import requests

from core.history_store import BASE_DIR

APP_VERSION = "1.0.6"
GITHUB_OWNER = "DungAnh1301"
GITHUB_REPO = "MercedesSniper"
EXE_ASSET_NAME = "MercedesSniper_MaxSpeed.exe"

GITHUB_REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
GITHUB_RELEASES_PAGE = f"{GITHUB_REPO_URL}/releases/latest"
LATEST_MANIFEST_URL = f"{GITHUB_REPO_URL}/releases/latest/download/latest.json"
DIRECT_LATEST_EXE_URL = f"{GITHUB_REPO_URL}/releases/latest/download/{EXE_ASSET_NAME}"
GITHUB_API_LATEST_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


def parse_version(ver_str: str) -> tuple[int, ...]:
    """Chuyển chuỗi phiên bản ('v1.0.2', '1.10.0') thành tuple số nguyên để so sánh chính xác."""
    cleaned = (ver_str or "").strip().lstrip("vV")
    nums = [int(x) for x in re.findall(r"\d+", cleaned)]
    return tuple(nums) if nums else (0, 0, 0)


def is_newer_version(remote_ver: str, local_ver: str = APP_VERSION) -> bool:
    r_tup = parse_version(remote_ver)
    l_tup = parse_version(local_ver)
    max_len = max(len(r_tup), len(l_tup))
    r_pad = r_tup + (0,) * (max_len - len(r_tup))
    l_pad = l_tup + (0,) * (max_len - len(l_tup))
    return r_pad > l_pad


def check_github_update(timeout: float = 8.0) -> dict:
    """
    Kiểm tra bản phát hành mới nhất từ GitHub Releases.
    Ưu tiên đọc `latest.json` qua CDN (không bị giới hạn 60 req/giờ của GitHub API),
    nếu chưa có `latest.json` thì tự động fallback sang GitHub Releases REST API.
    """
    headers = {
        "User-Agent": f"MercedesSniper/{APP_VERSION}",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
    }
    ts = int(time.time())

    # 1. Ưu tiên đọc manifest `latest.json` trực tiếp từ Release Asset CDN
    try:
        resp = requests.get(
            f"{LATEST_MANIFEST_URL}?t={ts}",
            headers=headers,
            timeout=timeout,
            allow_redirects=True,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and data.get("version"):
                remote_ver = str(data.get("version")).strip().lstrip("vV")
                tag_name = str(data.get("tag_name") or f"v{remote_ver}")
                dl_url = str(data.get("download_url") or DIRECT_LATEST_EXE_URL)
                return {
                    "ok": True,
                    "has_update": is_newer_version(remote_ver, APP_VERSION),
                    "current_version": APP_VERSION,
                    "latest_version": remote_ver,
                    "tag_name": tag_name,
                    "download_url": dl_url,
                    "sha256": str(data.get("sha256") or "").strip().lower(),
                    "size_bytes": int(data.get("size_bytes") or 0),
                    "notes": str(data.get("notes") or "").strip(),
                    "published_at": str(data.get("published_at") or "").strip(),
                    "release_url": str(data.get("release_url") or GITHUB_RELEASES_PAGE),
                }
    except Exception:
        pass

    # 2. Fallback: Gọi GitHub REST API `/releases/latest` (hỗ trợ cả khi bạn tạo Release tay trên web GitHub)
    try:
        api_headers = dict(headers)
        api_headers["Accept"] = "application/vnd.github+json"
        resp = requests.get(
            f"{GITHUB_API_LATEST_URL}?t={ts}",
            headers=api_headers,
            timeout=timeout,
        )
        if resp.status_code == 404:
            return {
                "ok": True,
                "has_update": False,
                "current_version": APP_VERSION,
                "latest_version": APP_VERSION,
                "tag_name": f"v{APP_VERSION}",
                "download_url": DIRECT_LATEST_EXE_URL,
                "sha256": "",
                "size_bytes": 0,
                "notes": "Chưa có bản phát hành nào trên GitHub.",
                "published_at": "",
                "release_url": GITHUB_RELEASES_PAGE,
            }
        resp.raise_for_status()
        rel = resp.json()
        tag_name = str(rel.get("tag_name") or "").strip()
        remote_ver = tag_name.lstrip("vV") or APP_VERSION
        dl_url = DIRECT_LATEST_EXE_URL
        size_bytes = 0
        for asset in rel.get("assets") or []:
            a_name = str(asset.get("name") or "")
            if a_name.lower().endswith(".exe"):
                dl_url = str(asset.get("browser_download_url") or dl_url)
                size_bytes = int(asset.get("size") or 0)
                if a_name.lower() == EXE_ASSET_NAME.lower():
                    break
        return {
            "ok": True,
            "has_update": is_newer_version(remote_ver, APP_VERSION),
            "current_version": APP_VERSION,
            "latest_version": remote_ver,
            "tag_name": tag_name or f"v{remote_ver}",
            "download_url": dl_url,
            "sha256": "",
            "size_bytes": size_bytes,
            "notes": str(rel.get("body") or "").strip(),
            "published_at": str(rel.get("published_at") or "").strip(),
            "release_url": str(rel.get("html_url") or GITHUB_RELEASES_PAGE),
        }
    except Exception as exc:
        return {
            "ok": False,
            "has_update": False,
            "current_version": APP_VERSION,
            "latest_version": APP_VERSION,
            "error": str(exc),
        }


def download_update_asset(
    update_info: dict,
    progress_cb: Optional[Callable[[int, float, float], None]] = None,
) -> str:
    """
    Tải ngầm gói `.exe` mới về `%LOCALAPPDATA%\\MercedesSniper\\updates`,
    xác thực header PE (`MZ`) và mã kiểm tra `SHA-256` (nếu có).
    """
    dl_url = str(update_info.get("download_url") or DIRECT_LATEST_EXE_URL)
    ver = str(update_info.get("latest_version") or "latest")
    expected_sha = str(update_info.get("sha256") or "").strip().lower()
    expected_size = int(update_info.get("size_bytes") or 0)

    updates_dir = os.path.join(BASE_DIR, "updates")
    os.makedirs(updates_dir, exist_ok=True)
    part_path = os.path.join(updates_dir, f"MercedesSniper_MaxSpeed_v{ver}.exe.part")
    final_path = os.path.join(updates_dir, f"MercedesSniper_MaxSpeed_v{ver}.exe")

    if os.path.exists(part_path):
        try:
            os.remove(part_path)
        except OSError:
            pass

    hasher = hashlib.sha256()
    downloaded = 0
    first_chunk = b""
    last_emit = 0.0

    with requests.get(
        f"{dl_url}?t={int(time.time())}",
        headers={"User-Agent": f"MercedesSniper/{APP_VERSION}"},
        stream=True,
        timeout=(10, 60),
        allow_redirects=True,
    ) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or expected_size or 0)
        with open(part_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=262144):
                if not chunk:
                    continue
                if not first_chunk:
                    first_chunk = chunk[:4]
                f.write(chunk)
                hasher.update(chunk)
                downloaded += len(chunk)
                now = time.monotonic()
                if progress_cb and (now - last_emit >= 0.12 or (total and downloaded >= total)):
                    last_emit = now
                    pct = int(min(99, (downloaded * 100) // total)) if total > 0 else 50
                    progress_cb(pct, downloaded / (1024 * 1024), total / (1024 * 1024) if total else 0.0)

    # Kiểm tra toàn vẹn file thực thi Windows (.exe) để không bao giờ ghi đè nhầm trang lỗi HTML
    if downloaded < 5 * 1024 * 1024 or not first_chunk.startswith(b"MZ"):
        try:
            os.remove(part_path)
        except OSError:
            pass
        raise RuntimeError("File tải về không phải bộ cài .exe hợp lệ (có thể bản Release đang tải lên GitHub).")

    actual_sha = hasher.hexdigest().lower()
    if expected_sha and actual_sha != expected_sha:
        try:
            os.remove(part_path)
        except OSError:
            pass
        raise RuntimeError("Mã kiểm tra SHA-256 không khớp! Đã hủy cập nhật để bảo vệ an toàn.")

    if os.path.exists(final_path):
        try:
            os.remove(final_path)
        except OSError:
            pass
    os.replace(part_path, final_path)
    if progress_cb:
        mb = downloaded / (1024 * 1024)
        progress_cb(100, mb, mb)
    return final_path


def launch_self_updater(staged_exe_path: str) -> tuple[bool, str]:
    """
    Khởi chạy tiến trình PowerShell ngầm để tráo file `.exe` sau khi ứng dụng hiện tại thoát
    (chờ cả tiến trình GUI lẫn PyInstaller Bootloader nhả khóa file), rồi tự bật lại bản mới!
    """
    if not os.path.exists(staged_exe_path):
        return False, "Không tìm thấy gói cập nhật đã tải."

    # Chế độ chạy mã nguồn `.py` (dành cho dev)
    if not getattr(sys, "frozen", False):
        proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if os.path.isdir(os.path.join(proj_root, ".git")):
            try:
                r = subprocess.run(
                    ["git", "pull", "--ff-only"],
                    cwd=proj_root,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=20,
                )
                if r.returncode == 0:
                    return True, "Đã đồng bộ mã nguồn mới nhất qua `git pull`! Đang khởi động lại..."
            except Exception:
                pass
        return False, f"Đang chạy ở chế độ mã nguồn Python. Bản .exe mới đã tải sẵn tại:\n{staged_exe_path}"

    target_exe = os.path.abspath(sys.executable)
    updates_dir = os.path.join(BASE_DIR, "updates")
    rollback_dir = os.path.join(BASE_DIR, "rollback")
    os.makedirs(updates_dir, exist_ok=True)
    os.makedirs(rollback_dir, exist_ok=True)

    rollback_exe = os.path.join(rollback_dir, "MercedesSniper_MaxSpeed_prev.exe")
    job_path = os.path.join(updates_dir, "update_job.json")
    ps1_path = os.path.join(updates_dir, "apply_update.ps1")

    job_payload = {
        "pid": os.getpid(),
        "staged_exe": os.path.abspath(staged_exe_path),
        "target_exe": target_exe,
        "rollback_exe": rollback_exe,
        "working_dir": os.path.dirname(target_exe),
    }
    with open(job_path, "w", encoding="utf-8") as f:
        json.dump(job_payload, f, ensure_ascii=False, indent=2)

    ps1_script = r"""param([string]$JobFile)
$ErrorActionPreference = "SilentlyContinue"
if (-not (Test-Path -LiteralPath $JobFile)) { exit 1 }
$job = Get-Content -LiteralPath $JobFile -Raw -Encoding UTF8 | ConvertFrom-Json

# 1. Chờ tiến trình GUI chính thoát hẳn
if ($job.pid -gt 0) {
    $p = Get-Process -Id $job.pid -ErrorAction SilentlyContinue
    if ($p) { $p.WaitForExit(8000) }
}
Start-Sleep -Milliseconds 600

# 2. Chờ PyInstaller Bootloader dọn _MEI xong và nhả khóa file .exe đích (thử tối đa 25 lần = 10 giây)
$swapped = $false
for ($i = 0; $i -lt 25; $i++) {
    if ($i -eq 12) {
        Get-Process -ErrorAction SilentlyContinue | Where-Object {
            $_.Path -and ($_.Path -ieq $job.target_exe)
        } | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
    }
    try {
        if (Test-Path -LiteralPath $job.target_exe) {
            Copy-Item -LiteralPath $job.target_exe -Destination $job.rollback_exe -Force -ErrorAction Stop
        }
        Copy-Item -LiteralPath $job.staged_exe -Destination $job.target_exe -Force -ErrorAction Stop
        $swapped = $true
        break
    } catch {
        Start-Sleep -Milliseconds 400
    }
}

if ($swapped) {
    Remove-Item -LiteralPath $job.staged_exe -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $JobFile -Force -ErrorAction SilentlyContinue
}

# 3. Khởi chạy lại Mercedes Sniper bản mới!
if (Test-Path -LiteralPath $job.target_exe) {
    Start-Process -FilePath $job.target_exe -WorkingDirectory $job.working_dir
}
"""
    # Ghi UTF-8 có BOM (`utf-8-sig`) để Windows PowerShell 5.1 đọc chuẩn 100% đường dẫn tiếng Việt
    with open(ps1_path, "w", encoding="utf-8-sig") as f:
        f.write(ps1_script)

    creation_flags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    )
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            ps1_path,
            job_path,
        ],
        creationflags=creation_flags,
        close_fds=True,
    )
    return True, "Đang nâng cấp phiên bản mới và tự khởi động lại..."

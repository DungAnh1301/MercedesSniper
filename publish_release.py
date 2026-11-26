# -*- coding: utf-8 -*-
"""
Script tự động hóa Đóng gói (.EXE) + Kiểm định (--self-test) + Phát hành lên GitHub Releases.
Sau khi chạy lệnh này:
  1. Mã nguồn được sao lưu lên GitHub (`DungAnh1301/MercedesSniper`).
  2. File `MercedesSniper_MaxSpeed.exe` và `latest.json` (kèm SHA-256) được đẩy lên GitHub Releases.
  3. Website (soitobe.duckdns.org) và mọi máy PC đang cài Tool sẽ TỰ ĐỘNG nhận được bản cập nhật mới!
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
UPDATER_FILE = PROJECT_DIR / "core" / "updater.py"
GITHUB_REPO_SLUG = "DungAnh1301/MercedesSniper"
REMOTE_URL = f"https://github.com/{GITHUB_REPO_SLUG}.git"
EXE_NAME = "MercedesSniper_MaxSpeed.exe"


def run_cmd(args: list[str], cwd: Path = PROJECT_DIR, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )


def sync_version_in_code(clean_ver: str):
    content = UPDATER_FILE.read_text(encoding="utf-8")
    updated = re.sub(
        r'^APP_VERSION\s*=\s*"[^"]+"',
        f'APP_VERSION = "{clean_ver}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    UPDATER_FILE.write_text(updated, encoding="utf-8")
    print(f"[1/6] Đã đồng bộ APP_VERSION = {clean_ver} trong core/updater.py")


def check_syntax():
    print("[2/6] Kiểm tra cú pháp toàn bộ mã nguồn Python...")
    res = run_cmd([sys.executable, "-m", "compileall", "-q", "app.py", "core", "ui"])
    if res.returncode != 0:
        print("❌ Lỗi cú pháp Python:\n" + res.stdout + "\n" + res.stderr)
        sys.exit(1)
    print("  -> Cú pháp hợp lệ 100%.")


def find_ffmpeg_binary() -> str:
    candidates = [
        PROJECT_DIR / "ffmpeg.exe",
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
    ]
    which_ff = shutil.which("ffmpeg")
    if which_ff:
        candidates.append(Path(which_ff))
    for p in candidates:
        if p.exists():
            return str(p.resolve())
    print("❌ Không tìm thấy ffmpeg.exe để đóng gói vào bộ cài độc lập!")
    sys.exit(1)


def build_and_verify_exe(dist_dir: Path) -> Path:
    print("[3/6] Đang đóng gói PyInstaller One-File (.exe) kèm FFmpeg + QuickJS...")
    ffmpeg_bin = find_ffmpeg_binary()
    qjs_bin = PROJECT_DIR / "qjs.exe"
    build_dir = PROJECT_DIR / "build_rel_tmp"
    shutil.rmtree(dist_dir, ignore_errors=True)
    shutil.rmtree(build_dir, ignore_errors=True)

    pyi_cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--icon",
        str(PROJECT_DIR / "mercedes.ico"),
        "--name",
        "MercedesSniper_MaxSpeed",
        "--add-binary",
        f"{ffmpeg_bin};.",
    ]
    if qjs_bin.exists():
        pyi_cmd.extend(["--add-binary", f"{qjs_bin.resolve()};."])
    pyi_cmd.extend(
        [
            "--collect-all",
            "curl_cffi",
            "--hidden-import",
            "core.worker_bridge",
            "--hidden-import",
            "core.turbo_downloader",
            "--hidden-import",
            "core.cookie_doctor",
            "--hidden-import",
            "core.capcut_injector",
            "--hidden-import",
            "core.updater",
            "--hidden-import",
            "yt_dlp",
            "--distpath",
            str(dist_dir),
            "--workpath",
            str(build_dir),
            "--specpath",
            str(build_dir),
            "app.py",
        ]
    )
    res = run_cmd(pyi_cmd)
    shutil.rmtree(build_dir, ignore_errors=True)
    exe_path = dist_dir / EXE_NAME
    if res.returncode != 0 or not exe_path.exists():
        print("❌ Đóng gói PyInstaller thất bại:\n" + res.stdout[-1500:] + "\n" + res.stderr[-1500:])
        sys.exit(1)

    print("[4/6] Chạy kiểm định tự động `MercedesSniper_MaxSpeed.exe --self-test`...")
    test_res = run_cmd([str(exe_path), "--self-test"])
    if test_res.returncode != 0:
        print(f"❌ Kiểm định --self-test thất bại (mã lỗi {test_res.returncode})!")
        sys.exit(1)
    size_mb = exe_path.stat().st_size / (1024 * 1024)
    print(f"  -> Đóng gói & kiểm định thành công ({size_mb:.1f} MB)!")
    return exe_path


def compute_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(524288), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def ensure_git_and_push(tag: str, notes: str):
    print("[5/6] Đồng bộ mã nguồn lên GitHub Repository...")
    if not (PROJECT_DIR / ".git").exists():
        run_cmd(["git", "init", "-b", "main"])
    if not run_cmd(["git", "config", "user.name"]).stdout.strip():
        run_cmd(["git", "config", "user.name", "DungAnh1301"])
    if not run_cmd(["git", "config", "user.email"]).stdout.strip():
        run_cmd(["git", "config", "user.email", "dunganh1301@users.noreply.github.com"])

    # Đảm bảo repo tồn tại trên GitHub (Public để người dùng trên Web tải trực tiếp 0 cần token)
    view_repo = run_cmd(["gh", "repo", "view", GITHUB_REPO_SLUG])
    if view_repo.returncode != 0:
        print(f"  -> Đang khởi tạo kho lưu trữ Public mới: {GITHUB_REPO_SLUG}...")
        cr = run_cmd(
            [
                "gh",
                "repo",
                "create",
                GITHUB_REPO_SLUG,
                "--public",
                "--description",
                "Mercedes Sniper MaxSpeed - Real-time 0ms YouTube Sniper & 1-Click CapCut PC Studio",
            ]
        )
        if cr.returncode != 0:
            print("❌ Không thể tạo repo GitHub:\n" + cr.stderr)
            sys.exit(1)

    remotes = run_cmd(["git", "remote", "-v"]).stdout
    if "origin" not in remotes:
        run_cmd(["git", "remote", "add", "origin", REMOTE_URL])
    else:
        run_cmd(["git", "remote", "set-url", "origin", REMOTE_URL])

    run_cmd(["git", "add", "-A"])
    status = run_cmd(["git", "status", "--porcelain"]).stdout.strip()
    if status:
        commit_msg = f"Release {tag}: {notes}" if notes else f"Release {tag}"
        c_res = run_cmd(["git", "commit", "-m", commit_msg])
        if c_res.returncode != 0:
            print("❌ Git commit lỗi:\n" + c_res.stderr)
            sys.exit(1)

    run_cmd(["git", "branch", "-M", "main"])
    p_res = run_cmd(["git", "push", "-u", "origin", "main"])
    if p_res.returncode != 0:
        print("❌ Git push lỗi:\n" + p_res.stderr)
        sys.exit(1)
    print(f"  -> Đã đẩy mã nguồn lên {REMOTE_URL}")


def publish_release_assets(tag: str, clean_ver: str, notes: str, exe_path: Path, dist_dir: Path):
    print(f"[6/6] Đang xuất bản GitHub Release {tag} (EXE + latest.json)...")
    sha256_hex = compute_sha256(exe_path)
    size_bytes = exe_path.stat().st_size
    now_iso = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7))).isoformat(timespec="seconds")

    manifest = {
        "version": clean_ver,
        "tag_name": tag,
        "download_url": f"https://github.com/{GITHUB_REPO_SLUG}/releases/download/{tag}/{EXE_NAME}",
        "sha256": sha256_hex,
        "size_bytes": size_bytes,
        "notes": notes,
        "published_at": now_iso,
        "release_url": f"https://github.com/{GITHUB_REPO_SLUG}/releases/tag/{tag}",
    }
    manifest_path = dist_dir / "latest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    title = f"Mercedes Sniper MaxSpeed {tag}"
    rel_notes = notes or f"Phát hành Mercedes Sniper MaxSpeed phiên bản {tag}"

    check_rel = run_cmd(["gh", "release", "view", tag, "-R", GITHUB_REPO_SLUG])
    if check_rel.returncode == 0:
        up_res = run_cmd(
            [
                "gh",
                "release",
                "upload",
                tag,
                str(exe_path),
                str(manifest_path),
                "--clobber",
                "-R",
                GITHUB_REPO_SLUG,
            ]
        )
        run_cmd(["gh", "release", "edit", tag, "-t", title, "-n", rel_notes, "-R", GITHUB_REPO_SLUG])
        if up_res.returncode != 0:
            print("❌ Lỗi cập nhật tài nguyên Release:\n" + up_res.stderr)
            sys.exit(1)
    else:
        cr_res = run_cmd(
            [
                "gh",
                "release",
                "create",
                tag,
                str(exe_path),
                str(manifest_path),
                "-t",
                title,
                "-n",
                rel_notes,
                "-R",
                GITHUB_REPO_SLUG,
            ]
        )
        if cr_res.returncode != 0:
            print("❌ Lỗi tạo GitHub Release:\n" + cr_res.stderr)
            sys.exit(1)

    print("=" * 68)
    print(f"🎉 PHÁT HÀNH THÀNH CÔNG MERCEDES SNIPER {tag} LÊN GITHUB!")
    print(f"🔗 Trang Release : https://github.com/{GITHUB_REPO_SLUG}/releases/tag/{tag}")
    print(f"📥 Link tải EXE  : https://github.com/{GITHUB_REPO_SLUG}/releases/latest/download/{EXE_NAME}")
    print(f"🛡️ SHA-256       : {sha256_hex}")
    print("=" * 68)


def main():
    if sys.stdout and getattr(sys.stdout, "encoding", "").lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Đóng gói & Phát hành Mercedes Sniper lên GitHub Releases")
    parser.add_argument("--tag", "-t", required=True, help="Tag phiên bản (ví dụ: v1.0.0, v1.0.1)")
    parser.add_argument("--notes", "-n", default="", help="Ghi chú nội dung bản cập nhật")
    parser.add_argument("--sync-desktop", action="store_true", help="Cập nhật luôn file EXE ngoài Desktop máy này")
    args = parser.parse_args()

    clean_ver = args.tag.strip().lstrip("vV")
    if not re.match(r"^\d+\.\d+(\.\d+)?$", clean_ver):
        print("❌ Định dạng phiên bản không hợp lệ! Ví dụ hợp lệ: v1.0.0 hoặc v1.0.1")
        sys.exit(1)
    tag = f"v{clean_ver}"

    sync_version_in_code(clean_ver)
    check_syntax()

    dist_dir = PROJECT_DIR / "dist_release"
    exe_path = build_and_verify_exe(dist_dir)
    ensure_git_and_push(tag, args.notes)
    publish_release_assets(tag, clean_ver, args.notes, exe_path, dist_dir)

    if args.sync_desktop:
        desktop_exe = Path.home() / "Desktop" / EXE_NAME
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Process 'MercedesSniper_MaxSpeed*' -ErrorAction SilentlyContinue | Stop-Process -Force"],
                capture_output=True,
            )
            import time
            time.sleep(0.8)
            shutil.copy2(exe_path, desktop_exe)
            print(f"✅ Đã cập nhật file Desktop: {desktop_exe}")
        except Exception as exc:
            print(f"⚠️ Không thể ghi đè trực tiếp file Desktop (đang mở): {exc}")

    shutil.rmtree(dist_dir, ignore_errors=True)


if __name__ == "__main__":
    main()

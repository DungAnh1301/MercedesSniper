# -*- coding: utf-8 -*-
"""
Bộ Đẩy 1-Click Vào CapCut PC (Chuẩn kiến trúc CapCut 9.x Multi-Timeline + MiniDraft):
- Giữ nguyên 100% cấu trúc gốc của `mau_1` (KHÔNG đổi `dc["id"]`, giữ nguyên `timeline_layout.json`,
  `Timelines/<main_timeline_id>/`, `Dòng thời gian 01` y hệt tính năng "Sao chép Project" gốc của CapCut
  -> Trình phát hiển thị mượt 100%, không bao giờ bị đen màn hình hay tách tab lạ!).
- Đồng bộ đồng thời cả `Timelines/<id>/attachment/patch/mini_draft.json` lẫn `draft_content.json`:
  + Thay mỗi file Video chính bằng file .mp4 1080p vừa tải, giữ nguyên 100% Speed (1.2x), Volume (10.0),
    Scale ngang/dọc kéo rìa, vị trí X/Y, nền ảnh 9:16, HDR, Keyframes của `mau_1`.
  + Thay dòng chữ Title bằng Tiêu đề video mới (giữ nguyên khung vàng #ffdc00 + chữ đen đậm).
  + Giữ nguyên tuyệt đối `PART 1` và tự kéo dài toàn bộ các lớp phủ khớp khít thời lượng video mới.
- Nếu không có mẫu nào (hoặc chọn `➕ Project mới tinh`): tạo Project mới tinh đầy đủ `Timelines/` chuẩn 9.x!
"""
import copy
from datetime import datetime
import json
import os
import re
import shutil
import subprocess
import textwrap
import time
import uuid

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
BLANK_TEMPLATE_KEY = "__blank__"
_CUSTOM_DRAFT_ROOT_OVERRIDE: str = ""


def set_custom_draft_root(path_str: str | None):
    global _CUSTOM_DRAFT_ROOT_OVERRIDE
    _CUSTOM_DRAFT_ROOT_OVERRIDE = (path_str or "").strip()


def _unescape_qt_ini_value(raw_val: str) -> str:
    s = (raw_val or "").strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    s = re.sub(r"\\x([0-9a-fA-F]{2,4})", lambda m: chr(int(m.group(1), 16)), s)
    s = s.replace("\\\\", "\\")
    return os.path.normpath(s) if s else ""


def _resolve_draft_dir_candidate(cand: str) -> str:
    if not cand:
        return ""
    norm = os.path.normpath(cand)
    if os.path.isfile(os.path.join(norm, "root_meta_info.json")):
        return norm
    for sub in ("com.lveditor.draft", "CapCut Drafts", "JianyingPro Drafts"):
        sub_p = os.path.join(norm, sub)
        if os.path.isdir(sub_p):
            return sub_p
    if os.path.isdir(norm):
        return norm
    return ""


def _read_draft_root_from_global_setting(local_app: str) -> str:
    """
    Đọc trực tiếp `currentCustomDraftPath` từ file `globalSetting` của CapCut PC (hoặc JianyingPro)
    để máy nào đổi nơi lưu nháp sang ổ D:, E:, F:... trong Cài đặt CapCut cũng tự dò trúng 100%.
    """
    for app_folder in ("CapCut", "JianyingPro"):
        gs_path = os.path.join(local_app, app_folder, "User Data", "Config", "globalSetting")
        if not os.path.isfile(gs_path):
            continue
        try:
            with open(gs_path, "r", encoding="utf-8", errors="ignore") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if line.startswith("currentCustomDraftPath="):
                        val = _unescape_qt_ini_value(line.split("=", 1)[1])
                        resolved = _resolve_draft_dir_candidate(val)
                        if resolved:
                            return resolved
        except Exception:
            pass
    return ""


def get_capcut_draft_root() -> str:
    if _CUSTOM_DRAFT_ROOT_OVERRIDE:
        ov = _resolve_draft_dir_candidate(_CUSTOM_DRAFT_ROOT_OVERRIDE)
        if ov:
            return ov

    local_app = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    from_gs = _read_draft_root_from_global_setting(local_app)
    if from_gs:
        return from_gs

    for app_folder in ("CapCut", "JianyingPro"):
        def_p = os.path.join(local_app, app_folder, "User Data", "Projects", "com.lveditor.draft")
        if os.path.isdir(def_p):
            return def_p

    return os.path.join(local_app, "CapCut", "User Data", "Projects", "com.lveditor.draft")


def find_capcut_exe() -> str:
    local_app = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    for app_folder, exe_name in (("CapCut", "CapCut.exe"), ("JianyingPro", "JianyingPro.exe")):
        launcher = os.path.join(local_app, app_folder, "Apps", exe_name)
        if os.path.isfile(launcher):
            return launcher

        apps_dir = os.path.join(local_app, app_folder, "Apps")
        if os.path.isdir(apps_dir):
            ver_dirs = sorted(
                [
                    d
                    for d in os.listdir(apps_dir)
                    if os.path.isfile(os.path.join(apps_dir, d, exe_name))
                ],
                reverse=True,
            )
            if ver_dirs:
                return os.path.join(apps_dir, ver_dirs[0], exe_name)

    # Dò thêm trong Windows Registry nếu máy khác cài CapCut sang ổ D:\ / E:\ / Program Files
    if os.name == "nt":
        try:
            import winreg

            reg_targets = [
                (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall\CapCut"),
                (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall\CapCut"),
                (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\CapCut"),
            ]
            for hive, subkey in reg_targets:
                try:
                    with winreg.OpenKey(hive, subkey) as k:
                        for val_name in ("InstallLocation", "DisplayIcon", "UninstallString"):
                            try:
                                raw_v, _ = winreg.QueryValueEx(k, val_name)
                                clean_v = str(raw_v or "").strip().strip('"').split('"')[0]
                                if not clean_v:
                                    continue
                                base_d = clean_v if os.path.isdir(clean_v) else os.path.dirname(clean_v)
                                for cand in (
                                    os.path.join(base_d, "CapCut.exe"),
                                    os.path.join(base_d, "Apps", "CapCut.exe"),
                                ):
                                    if os.path.isfile(cand):
                                        return cand
                            except OSError:
                                continue
                except OSError:
                    continue
        except Exception:
            pass
    return ""


_EXTRA_SELECTED_TEMPLATES: list[str] = []
_PROJECT_SPEC_CACHE: dict[tuple[str, int], str] = {}


def set_extra_selected_templates(names: list[str] | None):
    global _EXTRA_SELECTED_TEMPLATES
    if not names:
        _EXTRA_SELECTED_TEMPLATES = []
    else:
        seen = []
        for n in names:
            s = str(n or "").strip()
            if s and s not in seen:
                seen.append(s)
        _EXTRA_SELECTED_TEMPLATES = seen


def _is_ignored_draft_folder(name: str) -> bool:
    low = (name or "").strip().lower()
    if not low or low.startswith(".") or low.startswith("_tmp_"):
        return True
    if low.startswith("cc_auto_") or low.startswith("cc_new_"):
        return True
    return False


def _is_template_folder_name(name: str) -> bool:
    low = (name or "").strip().lower()
    if _is_ignored_draft_folder(low):
        return False
    return bool(re.search(r"(^|[\s_.-])(mau|mẫu|template)", low))


def _natural_sort_key(n: str):
    return [int(tok) if tok.isdigit() else tok for tok in re.split(r"(\d+)", (n or "").lower())]


def _extract_project_spec_summary(proj_dir: str) -> str:
    dc_path = os.path.join(proj_dir, "draft_content.json")
    try:
        st = os.stat(dc_path)
        cache_key = (proj_dir, int(st.st_mtime))
        if cache_key in _PROJECT_SPEC_CACHE:
            return _PROJECT_SPEC_CACHE[cache_key]
    except Exception:
        return "Project CapCut"

    summary = "Project CapCut"
    try:
        if st.st_size > 262_144:
            # Với project lớn nhiều phụ đề (1-10MB), chỉ đọc đúng 4KB đầu tiên (tốn 0.02ms thay vì 200ms!)
            with open(dc_path, "r", encoding="utf-8", errors="ignore") as f:
                head = f.read(4096)
            m_cv = re.search(r'"canvas_config"\s*:\s*\{([^}]*)\}', head)
            ratio = ""
            if m_cv:
                cv_blk = m_cv.group(1)
                m_r = re.search(r'"ratio"\s*:\s*"([^"]+)"', cv_blk)
                if m_r:
                    ratio = m_r.group(1).strip()
                else:
                    m_w = re.search(r'"width"\s*:\s*(\d+)', cv_blk)
                    m_h = re.search(r'"height"\s*:\s*(\d+)', cv_blk)
                    if m_w and m_h:
                        w, h = int(m_w.group(1)), int(m_h.group(1))
                        if w > 0 and h > 0:
                            ratio = "9:16" if h > w else ("16:9" if w > h else "1:1")
            summary = f"Khung {ratio}" if ratio else "Project CapCut"
        else:
            with open(dc_path, "r", encoding="utf-8") as f:
                dc = json.load(f)
            cv = dc.get("canvas_config") or {}
            w = int(cv.get("width") or 0)
            h = int(cv.get("height") or 0)
            ratio = str(cv.get("ratio") or "").strip()
            if not ratio and w > 0 and h > 0:
                ratio = "9:16" if h > w else ("16:9" if w > h else "1:1")
            ratio_txt = f"Khung {ratio}" if ratio else "Khung gốc"

            mats = dc.get("materials") or {}
            speeds = {s.get("id"): float(s.get("speed") or 1.0) for s in (mats.get("speeds") or []) if s.get("id")}
            texts_cnt = len(mats.get("texts") or [])

            main_spd = 1.0
            for tr in dc.get("tracks") or []:
                if tr.get("type") == "video" and (tr.get("segments") or []):
                    seg0 = tr["segments"][0]
                    for r_id in seg0.get("extra_material_refs") or []:
                        if r_id in speeds:
                            main_spd = speeds[r_id]
                            break
                    break

            parts = [ratio_txt, f"Speed {main_spd:g}x"]
            if texts_cnt > 0:
                parts.append(f"{texts_cnt} lớp Chữ")
            summary = " • ".join(parts)
    except Exception:
        pass

    _PROJECT_SPEC_CACHE[cache_key] = summary
    return summary


def scan_all_capcut_projects() -> list[dict]:
    """
    Quét TOÀN BỘ các Project hiện có trong CapCut PC (`com.lveditor.draft` + `root_meta_info.json`),
    chỉ bỏ qua thùng rác và các bản xuất tự động `CC_Auto_` / `CC_New_`.
    """
    root = get_capcut_draft_root()
    if not os.path.isdir(root):
        return []

    store_meta: dict[str, dict] = {}
    rm_path = os.path.join(root, "root_meta_info.json")
    if os.path.isfile(rm_path):
        try:
            with open(rm_path, "r", encoding="utf-8") as f:
                rm = json.load(f)
            for item in rm.get("all_draft_store") or []:
                if int(item.get("tm_draft_removed") or 0) > 0:
                    continue
                fold = os.path.basename(str(item.get("draft_fold_path") or "").rstrip("\\/"))
                if fold and fold not in store_meta:
                    store_meta[fold] = item
        except Exception:
            pass

    projects: list[dict] = []
    for name in os.listdir(root):
        if _is_ignored_draft_folder(name):
            continue
        full = os.path.join(root, name)
        dc_file = os.path.join(full, "draft_content.json")
        if not (os.path.isdir(full) and os.path.isfile(dc_file)):
            continue

        meta_item = store_meta.get(name) or {}
        disp_name = str(meta_item.get("draft_name") or "").strip()
        if not disp_name:
            dm_file = os.path.join(full, "draft_meta_info.json")
            if os.path.isfile(dm_file):
                try:
                    disp_name = str(json.load(open(dm_file, "r", encoding="utf-8")).get("draft_name") or "").strip()
                except Exception:
                    disp_name = ""
        if not disp_name:
            disp_name = name

        tm_us = int(meta_item.get("tm_draft_modified") or 0)
        if tm_us > 1_000_000_000_000:
            mtime = tm_us / 1_000_000.0
        else:
            try:
                mtime = os.path.getmtime(dc_file)
            except Exception:
                mtime = 0.0

        try:
            mod_str = datetime.fromtimestamp(mtime).strftime("%H:%M %d/%m/%Y") if mtime > 0 else ""
        except Exception:
            mod_str = ""

        cover = os.path.join(full, "draft_cover.jpg")
        if not os.path.isfile(cover):
            cover = ""

        is_tpl = _is_template_folder_name(name) or _is_template_folder_name(disp_name)
        projects.append(
            {
                "folder_name": name,
                "display_name": disp_name,
                "is_named_template": is_tpl,
                "cover_path": cover,
                "modified_ts": mtime,
                "modified_str": mod_str,
                "spec_summary": _extract_project_spec_summary(full),
            }
        )

    projects.sort(
        key=lambda p: (
            0 if p["is_named_template"] else 1,
            _natural_sort_key(p["folder_name"]) if p["is_named_template"] else [-p["modified_ts"]],
        )
    )
    return projects


def suggest_next_template_name() -> str:
    root = get_capcut_draft_root()
    existing = set()
    if os.path.isdir(root):
        existing = {d.lower() for d in os.listdir(root)}
    idx = 1
    while f"mau_{idx}" in existing:
        idx += 1
    return f"mau_{idx}"


def clone_or_import_capcut_template(src_folder_or_path: str, target_template_name: str) -> tuple[bool, str, str]:
    """
    Nhân bản 1 Project bất kỳ đang có trên CapCut (VD: `1125 (2)`) HOẶC nhập 1 thư mục Project từ ngoài ổ cứng
    thành một Mẫu chuẩn (VD: `mau_2`, `mau_3`, `mau_4`) nằm trong kho CapCut PC.
    """
    root = get_capcut_draft_root()
    os.makedirs(root, exist_ok=True)

    clean_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (target_template_name or "").strip()).strip(" .")
    if not clean_name:
        clean_name = suggest_next_template_name()

    if os.path.isabs(src_folder_or_path) and os.path.isdir(src_folder_or_path):
        src_dir = src_folder_or_path
    else:
        src_dir = os.path.join(root, src_folder_or_path)

    if not os.path.isdir(src_dir) or not os.path.isfile(os.path.join(src_dir, "draft_content.json")):
        return False, "Thư mục chọn không phải Project CapCut hợp lệ (thiếu draft_content.json)!", ""

    dst_dir = os.path.join(root, clean_name)
    if os.path.normcase(os.path.abspath(src_dir)) == os.path.normcase(os.path.abspath(dst_dir)):
        return True, f"Project '{clean_name}' đã nằm sẵn trong kho Mẫu CapCut!", clean_name

    tmp_dir = os.path.join(root, f"_tmp_tpl_{uuid.uuid4().hex[:8]}")
    try:
        shutil.copytree(src_dir, tmp_dir)
        norm_root = os.path.normpath(root)
        norm_dst = os.path.normpath(dst_dir)
        new_did = str(uuid.uuid4()).upper()
        now_us = int(time.time() * 1_000_000)

        dm_path = os.path.join(tmp_dir, "draft_meta_info.json")
        dm = {}
        if os.path.isfile(dm_path):
            try:
                dm = json.load(open(dm_path, "r", encoding="utf-8"))
            except Exception:
                dm = {}
        dm["draft_id"] = new_did
        dm["draft_name"] = clean_name
        dm["draft_fold_path"] = norm_dst
        dm["draft_root_path"] = norm_root
        dm["tm_draft_create"] = now_us
        dm["tm_draft_modified"] = now_us
        with open(dm_path, "w", encoding="utf-8") as f:
            json.dump(dm, f, ensure_ascii=False, separators=(",", ":"))

        if os.path.exists(dst_dir):
            shutil.rmtree(dst_dir, ignore_errors=True)
        shutil.move(tmp_dir, dst_dir)

        # Cập nhật vào root_meta_info.json để hiển thị đồng bộ bên trong CapCut
        rm_path = os.path.join(root, "root_meta_info.json")
        if os.path.isfile(rm_path):
            try:
                rm = json.load(open(rm_path, "r", encoding="utf-8"))
                store = rm.setdefault("all_draft_store", [])
                store[:] = [
                    it
                    for it in store
                    if os.path.basename(str(it.get("draft_fold_path") or "").rstrip("\\/")).lower()
                    != clean_name.lower()
                ]
                store.insert(
                    0,
                    {
                        "cloud_draft_cover": False,
                        "cloud_draft_sync": False,
                        "draft_cover": f"{norm_dst}\\draft_cover.jpg",
                        "draft_fold_path": norm_dst,
                        "draft_id": new_did,
                        "draft_is_invisible": False,
                        "draft_json_file": f"{norm_dst}\\draft_content.json",
                        "draft_name": clean_name,
                        "draft_root_path": norm_root,
                        "streaming_edit_draft_ready": True,
                        "tm_draft_create": now_us,
                        "tm_draft_modified": now_us,
                        "tm_draft_removed": 0,
                        "tm_duration": int(dm.get("tm_duration") or 0),
                    },
                )
                rm["draft_ids"] = int(rm.get("draft_ids") or len(store)) + 1
                with open(rm_path, "w", encoding="utf-8") as f:
                    json.dump(rm, f, ensure_ascii=False, separators=(",", ":"))
            except Exception:
                pass

        return True, f"Đã lưu thành Mẫu CapCut '{clean_name}' thành công!", clean_name
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return False, f"Lỗi khi tạo mẫu '{clean_name}': {e}", ""


def list_capcut_templates(extra_selected: list[str] | None = None) -> list[str]:
    """
    Trả về danh sách toàn bộ Mẫu CapCut sẵn sàng để chọn:
    - Tự động gồm mọi project đặt tên `mau_1`, `mau_2`...
    - Cộng thêm mọi Project CapCut bất kỳ mà người dùng đã bật chọn trong tab `✂️ Kho Mẫu CapCut`.
    """
    root = get_capcut_draft_root()
    if not os.path.isdir(root):
        return []

    chosen_extra = set(_EXTRA_SELECTED_TEMPLATES)
    if extra_selected:
        for x in extra_selected:
            if x:
                chosen_extra.add(str(x).strip())

    named_tpls = []
    extra_tpls = []
    for name in os.listdir(root):
        if _is_ignored_draft_folder(name):
            continue
        full = os.path.join(root, name)
        if not (os.path.isdir(full) and os.path.isfile(os.path.join(full, "draft_content.json"))):
            continue
        if _is_template_folder_name(name):
            named_tpls.append(name)
        elif name in chosen_extra:
            extra_tpls.append(name)

    named_tpls.sort(key=_natural_sort_key)
    extra_tpls.sort(key=_natural_sort_key)
    return named_tpls + extra_tpls


def _resolve_ffmpeg_tools() -> tuple[str, str | None]:
    """Lấy đường dẫn ffmpeg.exe (kể cả bản nhúng chìm _MEIPASS bên trong .exe) và ffprobe.exe nếu có."""
    ffmpeg_bin = "ffmpeg"
    ffprobe_bin = shutil.which("ffprobe")
    try:
        from core.turbo_downloader import find_ffmpeg_dir
        ff_dir = find_ffmpeg_dir()
        if ff_dir:
            cand_ff = os.path.join(ff_dir, "ffmpeg.exe")
            if os.path.isfile(cand_ff):
                ffmpeg_bin = cand_ff
            cand_pr = os.path.join(ff_dir, "ffprobe.exe")
            if os.path.isfile(cand_pr):
                ffprobe_bin = cand_pr
    except Exception:
        pass
    return ffmpeg_bin, ffprobe_bin


def probe_video_media_info(video_path: str) -> dict:
    info = {
        "width": 1920,
        "height": 1080,
        "duration_us": 60_000_000,
        "has_audio": True,
    }
    ffmpeg_bin, ffprobe_bin = _resolve_ffmpeg_tools()

    # 1. Nếu máy có sẵn ffprobe.exe thì đọc JSON trực tiếp
    if ffprobe_bin:
        try:
            cmd = [
                ffprobe_bin,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type,width,height,duration",
                "-of",
                "json",
                video_path,
            ]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )
            if res.returncode == 0 and res.stdout:
                data = json.loads(res.stdout)
                streams = data.get("streams") or []
                has_aud = False
                best_dur = 0.0
                for st in streams:
                    ctype = st.get("codec_type")
                    if ctype == "video":
                        if st.get("width"):
                            info["width"] = int(st["width"])
                        if st.get("height"):
                            info["height"] = int(st["height"])
                        if st.get("duration"):
                            best_dur = max(best_dur, float(st["duration"]))
                    elif ctype == "audio":
                        has_aud = True
                fmt_dur = float((data.get("format") or {}).get("duration") or 0.0)
                final_dur = fmt_dur if fmt_dur > 0 else best_dur
                if final_dur > 0:
                    info["duration_us"] = max(100_000, int(round(final_dur * 1_000_000)))
                    info["has_audio"] = has_aud
                    return info
        except Exception:
            pass

    # 2. Tự chủ 100% trên mọi máy mới: bóc tách trực tiếp bằng chính `ffmpeg.exe` nhúng chìm!
    try:
        res_ff = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-i", video_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
        raw_err = res_ff.stderr or ""
        m_dur = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", raw_err)
        if m_dur:
            hh = int(m_dur.group(1))
            mm = int(m_dur.group(2))
            ss = float(m_dur.group(3))
            tot_sec = hh * 3600 + mm * 60 + ss
            if tot_sec > 0:
                info["duration_us"] = max(100_000, int(round(tot_sec * 1_000_000)))

        for line in raw_err.splitlines():
            if "Stream #" in line and "Video:" in line:
                m_res = re.search(r"(?:,\s*|\s)([1-9]\d{1,4})x([1-9]\d{1,4})(?:[\s,\[]|$)", line)
                if m_res:
                    info["width"] = int(m_res.group(1))
                    info["height"] = int(m_res.group(2))
                    break

        info["has_audio"] = bool(re.search(r"Stream #.*Audio:", raw_err))
    except Exception:
        pass
    return info


def _clean_display_title(raw_title: str, video_path: str) -> str:
    t = (raw_title or "").strip()
    if not t:
        base = os.path.splitext(os.path.basename(video_path))[0]
        base = re.sub(r"^\[[^\]]+\]\s*", "", base)
        base = re.sub(r"\s*[\(\[][A-Za-z0-9_-]{11}[\)\]]\s*$", "", base)
        t = base.strip()
    t = t.replace("？", "?").replace("！", "!").replace("｜", "|")
    t = re.sub(r"\s+", " ", t).strip()
    return t or "New Video"


def _wrap_title_like_template(clean_title: str) -> tuple[str, float | None]:
    n = len(clean_title)
    if n <= 62:
        lines = textwrap.wrap(clean_title, width=28, break_long_words=False, break_on_hyphens=False)
        if len(lines) > 3:
            lines = textwrap.wrap(clean_title, width=32, break_long_words=False, break_on_hyphens=False)
        return "\n".join(lines), None

    if n <= 92:
        lines = textwrap.wrap(clean_title, width=32, break_long_words=False, break_on_hyphens=False)
        return "\n".join(lines[:3]), 14.0

    lines = textwrap.wrap(clean_title, width=36, break_long_words=False, break_on_hyphens=False)
    if len(lines) > 3:
        lines = lines[:3]
        if not lines[-1].endswith("..."):
            lines[-1] = lines[-1].rstrip(" .,!?") + "..."
    return "\n".join(lines), 12.5


def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _is_part_label(txt: str) -> bool:
    clean = re.sub(r"\s+", " ", (txt or "").strip()).upper()
    return bool(re.fullmatch(r"(PART|PHẦN|PHAN|EP|TẬP|TAP)\s*\d+.*", clean))


def _patch_text_content_json(raw_content: str, wrapped_title: str, override_size: float | None) -> str:
    u16_len = _utf16_len(wrapped_title)
    c_obj = json.loads(raw_content)
    c_obj["text"] = wrapped_title
    styles = c_obj.get("styles")
    if isinstance(styles, list) and styles:
        base_style = copy.deepcopy(styles[0])
        base_style["range"] = [0, u16_len]
        if override_size is not None:
            base_style["size"] = override_size
        c_obj["styles"] = [base_style]
    return json.dumps(c_obj, ensure_ascii=False, separators=(",", ":"))


def _update_title_text_materials(texts: list[dict], new_title: str) -> bool:
    if not texts:
        return False

    wrapped_title, override_size = _wrap_title_like_template(new_title)
    target_idx = -1
    fallback_idx = -1

    for idx, t_mat in enumerate(texts):
        raw_c = t_mat.get("content") or ""
        plain = ""
        try:
            plain = (json.loads(raw_c).get("text") or "").strip()
        except Exception:
            plain = (t_mat.get("text") or raw_c).strip()

        if _is_part_label(plain):
            continue
        if fallback_idx < 0:
            fallback_idx = idx
        low = plain.lower()
        if low == "title" or "title" in low or low.startswith("what if"):
            target_idx = idx
            break

    chosen = target_idx if target_idx >= 0 else fallback_idx
    if chosen < 0:
        return False

    t_mat = texts[chosen]
    try:
        t_mat["content"] = _patch_text_content_json(t_mat.get("content") or "{}", wrapped_title, override_size)
        if "text" in t_mat:
            t_mat["text"] = wrapped_title
        if override_size is not None:
            t_mat["font_size"] = float(override_size)
        return True
    except Exception:
        return False


def has_visible_capcut_window() -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        res = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq CapCut.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=CREATE_NO_WINDOW,
        )
        cc_pids = set()
        for line in (res.stdout or "").splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[0].lower() == "capcut.exe" and parts[1].isdigit():
                cc_pids.add(int(parts[1]))
        if not cc_pids:
            return False

        user32 = ctypes.windll.user32
        found_visible = False
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def _cb(hwnd, _lparam):
            nonlocal found_visible
            if user32.IsWindowVisible(hwnd):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value in cc_pids:
                    rect = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    if (rect.right - rect.left) > 200 and (rect.bottom - rect.top) > 200:
                        found_visible = True
                        return False
            return True

        user32.EnumWindows(WNDENUMPROC(_cb), 0)
        return found_visible
    except Exception:
        return False


def restart_or_launch_capcut(force_restart: bool = False):
    cc_exe = find_capcut_exe()
    if not cc_exe:
        return

    visible = has_visible_capcut_window()
    if force_restart or not visible:
        subprocess.run(
            ["taskkill", "/F", "/IM", "CapCut.exe"],
            capture_output=True,
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
        time.sleep(0.35)

    subprocess.Popen([cc_exe], close_fds=True)


def _patch_mini_draft_in_place(
    mini_path: str,
    norm_video_path: str,
    video_filename: str,
    src_dur_us: int,
    vid_w: int,
    vid_h: int,
    has_audio: bool,
    clean_title: str,
) -> dict | None:
    """
    Cập nhật trực tiếp `Timelines/<tl_id>/attachment/patch/mini_draft.json` của CapCut 9.9!
    Trả về dict thông số thực của mẫu (`speed`, `volume`, `clip`, `uniform_scale`, `local_mat_id`, `new_total_dur`)
    để đồng bộ ngược sang `draft_content.json` chuẩn 100%!
    """
    if not os.path.isfile(mini_path):
        return None

    try:
        with open(mini_path, "r", encoding="utf-8") as f:
            mini = json.load(f)
    except Exception:
        return None

    md = mini.get("mini_draft_data")
    if not isinstance(md, dict):
        return None

    segments = md.get("segments") or []
    real_v_segs = [
        s
        for s in segments
        if s.get("type") == "segment_video"
        and isinstance(s.get("material"), dict)
        and (s["material"].get("path") or "").strip() != ""
        and not s.get("material_draft")
    ]

    # Nếu người dùng lỡ gộp `mau_1` thành "Clip ghép" (`material_drafts`), tự động bung (unwrap)
    # bản gốc 3 lớp (Video + Title + PART 1 + Khung nền) từ `material_drafts` ra Timeline chính!
    if not real_v_segs and isinstance(md.get("material_drafts"), list):
        chosen_md = None
        for cand_md in reversed(md["material_drafts"]):
            c_segs = cand_md.get("segments") or []
            has_v = any(
                s.get("type") == "segment_video" and ((s.get("material") or {}).get("path") or "").strip() != ""
                for s in c_segs
            )
            has_t = any(s.get("type") == "segment_text" for s in c_segs)
            if has_v and has_t:
                chosen_md = cand_md
                break
        if chosen_md is None:
            for cand_md in reversed(md["material_drafts"]):
                c_segs = cand_md.get("segments") or []
                if any(
                    s.get("type") == "segment_video" and ((s.get("material") or {}).get("path") or "").strip() != ""
                    for s in c_segs
                ):
                    chosen_md = cand_md
                    break

        if chosen_md is not None:
            inner_tracks = copy.deepcopy((chosen_md.get("draft") or {}).get("tracks") or [])
            clean_tracks = []
            for tr in inner_tracks:
                clean_tracks.append(
                    {
                        "attribute": int(tr.get("attribute") or 0),
                        "id": tr.get("id") or str(uuid.uuid4()).upper(),
                        "segments": list(tr.get("segments") or []),
                    }
                )
            if isinstance(md.get("draft"), dict):
                md["draft"]["tracks"] = clean_tracks
            segments = copy.deepcopy(chosen_md.get("segments") or [])
            md["segments"] = segments
            md["material_drafts"] = []
            real_v_segs = [
                s
                for s in segments
                if s.get("type") == "segment_video"
                and isinstance(s.get("material"), dict)
                and (s["material"].get("path") or "").strip() != ""
            ]

    v_segs = real_v_segs or [
        s for s in segments if s.get("type") == "segment_video" and isinstance(s.get("material"), dict)
    ]
    if not v_segs:
        return None

    main_vseg = v_segs[len(v_segs) // 2] if len(v_segs) >= 3 else v_segs[0]
    spd_obj = main_vseg.get("speed") or {}
    seg_speed = float(spd_obj.get("speed") or 1.0)
    if seg_speed <= 0:
        seg_speed = 1.0

    vmat = main_vseg["material"]
    local_mat_id = vmat.get("local_material_id") or str(uuid.uuid4()).lower()
    vmat["local_material_id"] = local_mat_id
    vmat["path"] = norm_video_path
    vmat["material_name"] = video_filename
    vmat["duration"] = src_dur_us
    vmat["width"] = vid_w
    vmat["height"] = vid_h
    vmat["has_audio"] = bool(has_audio)

    old_t_rng = main_vseg.get("target_time_range") or {}
    old_seg_target_dur = int(old_t_rng.get("duration") or 0)
    new_seg_target_dur = max(100_000, int(round(src_dur_us / seg_speed)))
    delta_dur = new_seg_target_dur - old_seg_target_dur

    if isinstance(main_vseg.get("source_time_range"), dict):
        main_vseg["source_time_range"]["start"] = 0
        main_vseg["source_time_range"]["duration"] = src_dur_us
    else:
        main_vseg["source_time_range"] = {"id": str(uuid.uuid4()).upper(), "start": 0, "duration": src_dur_us}

    if isinstance(main_vseg.get("target_time_range"), dict):
        main_vseg["target_time_range"]["duration"] = new_seg_target_dur
    else:
        main_vseg["target_time_range"] = {"id": str(uuid.uuid4()).upper(), "start": 0, "duration": new_seg_target_dur}

    # Nếu có đoạn Outro sau video chính -> đẩy nối đuôi
    main_end_old = int(old_t_rng.get("start") or 0) + old_seg_target_dur
    max_end = int(main_vseg["target_time_range"].get("start") or 0) + new_seg_target_dur
    for vs in v_segs:
        if vs is main_vseg:
            continue
        tr = vs.get("target_time_range")
        if isinstance(tr, dict):
            st = int(tr.get("start") or 0)
            if st >= main_end_old > 0:
                tr["start"] = max(0, st + delta_dur)
            max_end = max(max_end, int(tr.get("start") or 0) + int(tr.get("duration") or 0))

    new_total_dur = max_end
    if isinstance(md.get("draft"), dict):
        md["draft"]["duration"] = new_total_dur

    # Kéo dài toàn bộ các lớp chữ / hiệu ứng phủ khớp thời lượng mới & thay Title (giữ nguyên PART 1)
    text_mats = []
    for s in segments:
        if s.get("type") == "segment_video":
            continue
        tr = s.get("target_time_range")
        if isinstance(tr, dict):
            s_start = int(tr.get("start") or 0)
            tr["duration"] = max(100_000, new_total_dur - s_start)
        if s.get("type") == "segment_text" and isinstance(s.get("material"), dict):
            text_mats.append(s["material"])

    _update_title_text_materials(text_mats, clean_title)

    # Dọn `material_drafts` thừa nếu không có segment nào dùng `material_draft`
    if not any(s.get("material_draft") for s in segments):
        md["material_drafts"] = []

    with open(mini_path, "w", encoding="utf-8") as f:
        json.dump(mini, f, ensure_ascii=False, separators=(",", ":"))

    patch_json_path = os.path.join(os.path.dirname(mini_path), "patch.json")
    if os.path.isfile(patch_json_path):
        with open(patch_json_path, "w", encoding="utf-8") as f:
            f.write('{"patch_data":[]}')

    return {
        "speed": seg_speed,
        "volume": float(main_vseg.get("volume") if main_vseg.get("volume") is not None else 1.0),
        "clip": main_vseg.get("clip"),
        "uniform_scale": main_vseg.get("uniform_scale"),
        "local_mat_id": local_mat_id,
        "new_total_dur": new_total_dur,
    }


def _build_blank_draft_content(
    dc_id: str,
    norm_video_path: str,
    video_filename: str,
    local_mat_id: str,
    vid_w: int,
    vid_h: int,
    src_dur_us: int,
    has_audio: bool,
) -> dict:
    vid_mat_id = str(uuid.uuid4()).upper()
    spd_id = str(uuid.uuid4()).upper()
    ph_id = str(uuid.uuid4()).upper()
    cvs_id = str(uuid.uuid4()).upper()
    scm_id = str(uuid.uuid4()).upper()
    mcol_id = str(uuid.uuid4()).upper()
    vsep_id = str(uuid.uuid4()).upper()
    trk_id = str(uuid.uuid4()).upper()
    seg_id = str(uuid.uuid4()).upper()

    empty_mat_keys = [
        "flowers", "tail_leaders", "audios", "images", "texts", "effects", "stickers",
        "transitions", "audio_effects", "audio_fades", "beats", "material_animations",
        "placeholders", "common_mask", "chromas", "text_templates", "realtime_denoises",
        "audio_pannings", "audio_pitch_shifts", "video_trackings", "hsl", "drafts",
        "color_curves", "hsl_curves", "primary_color_wheels", "log_color_wheels",
        "video_effects", "ai_text_effects", "ai_generate_holders", "audio_balances",
        "handwrites", "manual_deformations", "manual_beautys", "plugin_effects",
        "green_screens", "shapes", "digital_humans", "digital_human_model_dressing",
        "smart_crops", "ai_translates", "audio_track_indexes", "loudnesses",
        "vocal_beautifys", "smart_relights", "time_marks", "multi_language_refs",
        "video_shadows", "video_strokes", "video_radius",
    ]
    materials = {k: [] for k in empty_mat_keys}
    materials["videos"] = [
        {
            "id": vid_mat_id,
            "unique_id": uuid.uuid4().hex,
            "type": "video",
            "duration": src_dur_us,
            "path": norm_video_path,
            "media_path": "",
            "local_id": "",
            "has_audio": bool(has_audio),
            "reverse_path": "",
            "intensifies_path": "",
            "reverse_intensifies_path": "",
            "intensifies_audio_path": "",
            "cartoon_path": "",
            "width": vid_w,
            "height": vid_h,
            "category_id": "",
            "category_name": "local",
            "material_id": "",
            "material_name": video_filename,
            "material_url": "",
            "crop": {
                "upper_left_x": 0.0, "upper_left_y": 0.0,
                "upper_right_x": 1.0, "upper_right_y": 0.0,
                "lower_left_x": 0.0, "lower_left_y": 1.0,
                "lower_right_x": 1.0, "lower_right_y": 1.0,
            },
            "crop_ratio": "free",
            "audio_fade": None,
            "crop_scale": 1.0,
            "extra_type_option": 0,
            "source": 0,
            "source_platform": 0,
            "formula_id": "",
            "check_flag": 62978047,
            "local_material_id": local_mat_id,
            "origin_material_id": "",
            "request_id": "",
            "has_sound_separated": False,
            "is_text_edit_overdub": False,
            "is_ai_generate_content": False,
            "aigc_type": "none",
            "is_copyright": False,
        }
    ]
    materials["canvases"] = [{"id": cvs_id, "type": "canvas_color", "color": "", "blur": 0.0, "image": "", "album_image": "", "image_id": "", "image_name": "", "source_platform": 0, "team_id": ""}]
    materials["placeholder_infos"] = [{"id": ph_id, "type": "placeholder_info", "meta_type": "none", "res_path": "", "res_text": "", "error_path": "", "error_text": ""}]
    materials["speeds"] = [{"id": spd_id, "type": "speed", "mode": 0, "speed": 1.0, "curve_speed": None}]
    materials["sound_channel_mappings"] = [{"id": scm_id, "type": "", "audio_channel_mapping": 0, "is_config_open": False}]
    materials["material_colors"] = [{"id": mcol_id, "is_color_clip": False, "is_gradient": False, "solid_color": "", "gradient_colors": [], "gradient_percents": [], "gradient_angle": 90.0, "width": 0.0, "height": 0.0}]
    materials["vocal_separations"] = [{"id": vsep_id, "type": "vocal_separation", "choice": 0, "removed_sounds": [], "time_range": None, "production_path": "", "final_algorithm": "", "enter_from": ""}]

    return {
        "id": dc_id,
        "version": 360000,
        "new_version": "195.0.0",
        "name": "",
        "duration": src_dur_us,
        "create_time": 0,
        "update_time": 0,
        "fps": 30.0,
        "is_drop_frame_timecode": False,
        "color_space": 0,
        "config": {
            "video_mute": False, "record_audio_last_index": 1, "extract_audio_last_index": 1,
            "original_sound_last_index": 1, "subtitle_recognition_id": "", "subtitle_taskinfo": [],
            "lyrics_recognition_id": "", "lyrics_taskinfo": [], "subtitle_sync": True,
            "lyrics_sync": True, "voice_change_sync": False, "sticker_max_index": 1,
            "adjust_max_index": 1, "material_save_mode": 0, "export_range": None,
            "maintrack_adsorb": True, "combination_max_index": 1, "attachment_info": [],
            "zoom_info_params": None, "system_font_list": [], "multi_language_mode": "none",
            "multi_language_main": "none", "multi_language_current": "none", "multi_language_list": [],
            "subtitle_keywords_config": None, "use_float_render": False, "hdr_vivid": False,
        },
        "canvas_config": {"ratio": "original", "width": vid_w, "height": vid_h, "background": None},
        "tracks": [
            {
                "id": trk_id,
                "type": "video",
                "flag": 0,
                "attribute": 0,
                "name": "",
                "segments": [
                    {
                        "id": seg_id,
                        "source_timerange": {"start": 0, "duration": src_dur_us},
                        "target_timerange": {"start": 0, "duration": src_dur_us},
                        "render_timerange": {"start": 0, "duration": 0},
                        "desc": "", "state": 0, "speed": 1.0, "is_loop": False, "is_tone_modify": False,
                        "reverse": False, "intensifies_audio": False, "cartoon": False,
                        "volume": 1.0, "last_nonzero_volume": 1.0,
                        "clip": {
                            "scale": {"x": 1.0, "y": 1.0}, "rotation": 0.0, "rotation3d": [],
                            "transform": {"x": 0.0, "y": 0.0},
                            "flip": {"vertical": False, "horizontal": False}, "alpha": 1.0,
                        },
                        "uniform_scale": {"on": True, "value": 1.0},
                        "material_id": vid_mat_id,
                        "extra_material_refs": [spd_id, ph_id, cvs_id, scm_id, mcol_id, vsep_id],
                        "render_index": 0, "keyframe_refs": [], "enable_lut": True,
                        "enable_adjust": True, "enable_hsl": False, "visible": True, "group_id": "",
                        "enable_color_curves": True, "enable_hsl_curves": True,
                        "track_render_index": 0,
                        "hdr_settings": {"mode": 1, "intensity": 1.0, "nits": 1000},
                        "hdr_vivid_settings": None, "enable_color_wheels": True,
                        "track_attribute": 0, "is_placeholder": False, "template_id": "",
                        "enable_smart_color_adjust": False, "template_scene": "default",
                        "common_keyframes": [], "caption_info": None,
                        "responsive_layout": {"enable": False, "target_follow": "", "size_layout": 0, "horizontal_pos_layout": 0, "vertical_pos_layout": 0},
                        "enable_color_match_adjust": False, "enable_color_correct_adjust": False,
                        "enable_adjust_mask": False, "raw_segment_id": "", "lyric_keyframes": None,
                        "enable_video_mask": True, "digital_human_template_group_id": "",
                        "color_correct_alg_result": "", "source": "segmentsourcenormal",
                        "enable_mask_stroke": False, "enable_mask_shadow": False,
                        "enable_color_adjust_pro": False, "segment_color_tag": "", "lumi_occlusion": None,
                    }
                ],
            }
        ],
        "group_container": None,
        "materials": materials,
        "keyframes": {"videos": [], "audios": [], "texts": [], "stickers": [], "filters": [], "adjusts": [], "handwrites": [], "effects": []},
        "keyframe_graph_list": [],
        "mutable_config": None, "cover": None, "retouch_cover": None, "extra_info": None,
        "relationships": [], "mixed_track_mode_on": False, "render_index_track_mode_on": True,
        "free_render_index_mode_on": False, "static_cover_image_path": "", "source": "default",
        "time_marks": None, "path": "", "lyrics_effects": [],
        "uneven_animation_template_info": {"composition": "", "content": "", "order": "", "sub_template_info_list": []},
        "draft_type": "video",
        "smart_ads_info": {"page_from": "", "routine": "", "draft_url": ""},
    }


def _finalize_and_register_draft(
    tmp_dir: str,
    draft_root: str,
    folder_name: str,
    draft_display_name: str,
    new_draft_id: str,
    new_total_dur: int,
    norm_video_path: str,
    video_path: str,
    video_filename: str,
    local_mat_id: str,
    vid_w: int,
    vid_h: int,
    src_dur_us: int,
):
    cover_path = os.path.join(tmp_dir, "draft_cover.jpg")
    ffmpeg_bin, _ = _resolve_ffmpeg_tools()
    try:
        subprocess.run(
            [
                ffmpeg_bin, "-y", "-ss", "00:00:02", "-i", video_path,
                "-frames:v", "1", "-vf", "scale=480:-1", "-q:v", "4", cover_path,
            ],
            capture_output=True,
            timeout=6,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        pass

    # Cập nhật sạch `draft_virtual_store.json` chỉ trỏ tới đúng `local_mat_id` của video mới
    vs_path = os.path.join(tmp_dir, "draft_virtual_store.json")
    with open(vs_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "draft_materials": [],
                "draft_virtual_store": [
                    {
                        "type": 0,
                        "value": [
                            {
                                "creation_time": 0, "display_name": "", "filter_type": 0, "id": "",
                                "import_time": 0, "import_time_us": 0, "material_color_tag": "",
                                "sort_sub_type": 0, "sort_type": 0, "subdraft_filter_type": 0,
                            }
                        ],
                    },
                    {"type": 1, "value": [{"child_id": local_mat_id, "parent_id": ""}]},
                    {"type": 2, "value": []},
                ],
            },
            f,
            separators=(",", ":"),
        )

    final_draft_dir = os.path.join(draft_root, folder_name)
    norm_final_dir = final_draft_dir.replace("\\", "/")
    norm_draft_root = draft_root.replace("\\", "/")
    now_sec = int(time.time())
    now_us = int(time.time() * 1_000_000)
    vid_file_size = os.path.getsize(video_path)

    meta_path = os.path.join(tmp_dir, "draft_meta_info.json")
    dm = {}
    if os.path.isfile(meta_path):
        try:
            dm = json.load(open(meta_path, "r", encoding="utf-8"))
        except Exception:
            dm = {}

    dm.update(
        {
            "cloud_draft_cover": False,
            "cloud_draft_sync": False,
            "draft_cover": "draft_cover.jpg",
            "draft_id": new_draft_id,
            "draft_name": draft_display_name,
            "draft_fold_path": norm_final_dir,
            "draft_root_path": norm_draft_root,
            "draft_is_invisible": False,
            "tm_draft_create": now_us,
            "tm_draft_modified": now_us,
            "tm_duration": new_total_dur,
            "draft_timeline_materials_size_": vid_file_size,
            "draft_materials": [
                {
                    "type": 0,
                    "value": [
                        {
                            "ai_group_type": "",
                            "create_time": now_sec,
                            "duration": src_dur_us,
                            "enter_from": 0,
                            "extra_info": video_filename,
                            "file_Path": norm_video_path,
                            "height": vid_h,
                            "id": local_mat_id,
                            "import_time": now_sec,
                            "import_time_ms": now_us,
                            "item_source": 1,
                            "material_color_tag": "",
                            "md5": "",
                            "metetype": "video",
                            "roughcut_time_range": {"duration": src_dur_us, "start": 0},
                            "sub_time_range": {"duration": -1, "start": -1},
                            "type": 0,
                            "width": vid_w,
                        }
                    ],
                },
                {"type": 1, "value": []},
                {"type": 2, "value": []},
                {"type": 3, "value": []},
                {"type": 6, "value": []},
                {"type": 7, "value": []},
                {"type": 8, "value": []},
            ],
        }
    )
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(dm, f, ensure_ascii=False, separators=(",", ":"))

    if os.path.exists(final_draft_dir):
        shutil.rmtree(final_draft_dir, ignore_errors=True)
    shutil.move(tmp_dir, final_draft_dir)

    root_meta_path = os.path.join(draft_root, "root_meta_info.json")
    rm = {"all_draft_store": [], "draft_ids": 1, "root_path": norm_draft_root}
    if os.path.isfile(root_meta_path):
        try:
            rm = json.load(open(root_meta_path, "r", encoding="utf-8"))
        except Exception:
            pass

    store = rm.setdefault("all_draft_store", [])
    new_entry = {
        "cloud_draft_cover": False,
        "cloud_draft_sync": False,
        "draft_cloud_last_action_download": False,
        "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": f"{norm_final_dir}\\draft_cover.jpg",
        "draft_fold_path": norm_final_dir,
        "draft_id": new_draft_id,
        "draft_is_ai_shorts": False,
        "draft_is_cloud_temp_draft": False,
        "draft_is_infinite_canvas_draft": False,
        "draft_is_invisible": False,
        "draft_is_pippit_draft": False,
        "draft_is_web_article_video": False,
        "draft_json_file": f"{norm_final_dir}\\draft_content.json",
        "draft_name": draft_display_name,
        "draft_new_version": "",
        "draft_root_path": norm_draft_root,
        "draft_timeline_materials_size": vid_file_size,
        "draft_type": "",
        "draft_web_article_video_enter_from": "",
        "pippit_avatar_url": "",
        "pippit_extra_info": "",
        "pippit_id": "",
        "pippit_user_name": "",
        "streaming_edit_draft_ready": True,
        "tm_draft_cloud_completed": "",
        "tm_draft_cloud_entry_id": -1,
        "tm_draft_cloud_modified": 0,
        "tm_draft_cloud_parent_entry_id": -1,
        "tm_draft_cloud_space_id": -1,
        "tm_draft_cloud_user_id": -1,
        "tm_draft_create": now_us,
        "tm_draft_modified": now_us,
        "tm_draft_removed": 0,
        "tm_duration": new_total_dur,
    }
    store.insert(0, new_entry)
    rm["draft_ids"] = int(rm.get("draft_ids") or len(store)) + 1
    with open(root_meta_path, "w", encoding="utf-8") as f:
        json.dump(rm, f, ensure_ascii=False, separators=(",", ":"))


def create_capcut_draft_from_template(
    video_path: str,
    video_title: str = "",
    template_name: str = "mau_1",
    auto_launch_capcut: bool = True,
    force_restart_if_open: bool = False,
) -> tuple[bool, str, str]:
    if not video_path or not os.path.isfile(video_path):
        return False, "Không tìm thấy file video .mp4 trên ổ cứng!", ""

    draft_root = get_capcut_draft_root()
    os.makedirs(draft_root, exist_ok=True)

    use_blank = (not template_name) or (template_name == BLANK_TEMPLATE_KEY)
    tpl_dir = ""
    if not use_blank:
        cand_dir = os.path.join(draft_root, template_name)
        if os.path.isdir(cand_dir) and os.path.isfile(os.path.join(cand_dir, "draft_content.json")):
            tpl_dir = cand_dir
        else:
            avail = list_capcut_templates()
            if avail:
                template_name = avail[0]
                tpl_dir = os.path.join(draft_root, template_name)
            else:
                use_blank = True

    media = probe_video_media_info(video_path)
    src_dur_us = media["duration_us"]
    vid_w = media["width"]
    vid_h = media["height"]
    norm_video_path = os.path.abspath(video_path).replace("\\", "/")
    video_filename = os.path.basename(video_path)
    clean_title = _clean_display_title(video_title, video_path)

    short_slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", clean_title).strip()
    short_slug = re.sub(r"\s+", " ", short_slug)[:38].strip()
    ts_tag = datetime.now().strftime("%H%M%S")

    if auto_launch_capcut and (force_restart_if_open or not has_visible_capcut_window()):
        subprocess.run(
            ["taskkill", "/F", "/IM", "CapCut.exe"],
            capture_output=True,
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
        time.sleep(0.25)

    staging_root = os.path.join(os.path.dirname(draft_root), "_sniper_staging")
    os.makedirs(staging_root, exist_ok=True)

    # ==========================================================
    # NHÁNH A: TẠO PROJECT MỚI TINH KHÔNG CÓ MẪU (CHUẨN CAPCUT 9.9 TIMELINES)
    # ==========================================================
    if use_blank:
        draft_display_name = f"[Mới] {short_slug}" if short_slug else f"[Mới] Video_{ts_tag}"
        folder_name = f"CC_New_{datetime.now().strftime('%m%d_%H%M%S')}_{re.sub(r'[^A-Za-z0-9_-]+', '_', short_slug)[:22]}".strip("_")
        tmp_dir = os.path.join(staging_root, folder_name)
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)
        os.makedirs(tmp_dir, exist_ok=True)

        new_dc_id = str(uuid.uuid4()).upper()
        new_draft_id = str(uuid.uuid4()).upper()
        local_mat_id = str(uuid.uuid4()).lower()
        now_us = int(time.time() * 1_000_000)

        tl_sub_dir = os.path.join(tmp_dir, "Timelines", new_dc_id)
        for sub in ("Resources", "adjust_mask", "matting", "smart_crop", "common_attachment"):
            os.makedirs(os.path.join(tmp_dir, sub), exist_ok=True)
        os.makedirs(tl_sub_dir, exist_ok=True)

        dc = _build_blank_draft_content(
            dc_id=new_dc_id,
            norm_video_path=norm_video_path,
            video_filename=video_filename,
            local_mat_id=local_mat_id,
            vid_w=vid_w,
            vid_h=vid_h,
            src_dur_us=src_dur_us,
            has_audio=bool(media["has_audio"]),
        )
        dc_out = json.dumps(dc, ensure_ascii=False, separators=(",", ":"))

        for target_folder in (tmp_dir, tl_sub_dir):
            for fn in ("draft_content.json", "draft_content.json.bak", "template-2.tmp"):
                with open(os.path.join(target_folder, fn), "w", encoding="utf-8") as f:
                    f.write(dc_out)

        with open(os.path.join(tmp_dir, "timeline_layout.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "dockItems": [
                        {
                            "dockIndex": 0,
                            "ratio": 1,
                            "timelineIds": [new_dc_id],
                            "timelineNames": ["Dòng thời gian 01"],
                        }
                    ],
                    "layoutOrientation": 1,
                },
                f,
                ensure_ascii=False,
                separators=(",", ":"),
            )

        proj_json = json.dumps(
            {
                "config": {
                    "color_space": -1,
                    "hdr_vivid": False,
                    "mixed_track_mode_on": False,
                    "render_index_track_mode_on": False,
                    "use_float_render": False,
                },
                "create_time": now_us,
                "id": str(uuid.uuid4()).upper(),
                "main_timeline_id": new_dc_id,
                "timelines": [
                    {
                        "create_time": now_us,
                        "id": new_dc_id,
                        "is_marked_delete": False,
                        "name": "Dòng thời gian 01",
                        "update_time": now_us,
                    }
                ],
                "update_time": now_us,
                "version": 0,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with open(os.path.join(tmp_dir, "Timelines", "project.json"), "w", encoding="utf-8") as f:
            f.write(proj_json)
        with open(os.path.join(tmp_dir, "Timelines", "project.json.bak"), "w", encoding="utf-8") as f:
            f.write(proj_json)

        with open(os.path.join(tmp_dir, "draft_biz_config.json"), "w", encoding="utf-8") as f:
            json.dump({"timeline_settings": {new_dc_id: {"linkage_enabled": True}}}, f)
        with open(os.path.join(tmp_dir, "draft_agency_config.json"), "w", encoding="utf-8") as f:
            json.dump({"is_auto_agency_enabled": False, "use_converter": False, "video_resolution": 720, "marterials": []}, f)

        _finalize_and_register_draft(
            tmp_dir=tmp_dir,
            draft_root=draft_root,
            folder_name=folder_name,
            draft_display_name=draft_display_name,
            new_draft_id=new_draft_id,
            new_total_dur=src_dur_us,
            norm_video_path=norm_video_path,
            video_path=video_path,
            video_filename=video_filename,
            local_mat_id=local_mat_id,
            vid_w=vid_w,
            vid_h=vid_h,
            src_dur_us=src_dur_us,
        )

        if auto_launch_capcut:
            restart_or_launch_capcut(force_restart=force_restart_if_open)

        dur_min = (src_dur_us / 1_000_000) / 60.0
        return (
            True,
            f"Đã tạo Project CapCut mới tinh '{draft_display_name}' ({dur_min:.1f} phút, không áp mẫu)!",
            draft_display_name,
        )

    # ==========================================================
    # NHÁNH B: GIỮ NGUYÊN 100% `mau_1` (SAO CHÉP CHUẨN GỐC CAPCUT, CHỈ THAY VIDEO + TITLE)
    # ==========================================================
    tpl_dc_path = os.path.join(tpl_dir, "draft_content.json")
    try:
        with open(tpl_dc_path, "r", encoding="utf-8") as f:
            raw_dc_text = f.read()
        dc = json.loads(raw_dc_text)
    except Exception as e:
        return False, f"Không đọc được cấu trúc mẫu '{template_name}': {e}", ""

    uses_subdraft = "./subdraft/" in raw_dc_text
    draft_display_name = f"[Auto] {short_slug}" if short_slug else f"[Auto] Video_{ts_tag}"
    folder_name = f"CC_Auto_{datetime.now().strftime('%m%d_%H%M%S')}_{re.sub(r'[^A-Za-z0-9_-]+', '_', short_slug)[:22]}".strip("_")

    tmp_dir = os.path.join(staging_root, folder_name)
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir, ignore_errors=True)

    def _ignore_unused(cur_dir, names):
        if not uses_subdraft and os.path.abspath(cur_dir) == os.path.abspath(tpl_dir):
            return [n for n in names if n == "subdraft"]
        return []

    shutil.copytree(tpl_dir, tmp_dir, ignore=_ignore_unused)

    # QUAN TRỌNG SỐ 1: GIỮ NGUYÊN `dc["id"]` CỦA MẪU (y hệt chức năng "Sao chép" gốc của CapCut!)
    # để `timeline_layout.json`, `Timelines/<tl_id>/` và `Trình phát` khớp nhau 100%!
    tl_id = dc.get("id") or ""
    new_draft_id = str(uuid.uuid4()).upper()

    # Bước B1: Nếu mẫu có `Timelines/<tl_id>/attachment/patch/mini_draft.json` (CapCut 9.9),
    # cập nhật trực tiếp `mini_draft.json` trước và đọc thông số chuẩn từ đó!
    mini_info = None
    tl_sub_dir = os.path.join(tmp_dir, "Timelines", tl_id) if tl_id else ""
    if tl_sub_dir and os.path.isdir(tl_sub_dir):
        mini_path = os.path.join(tl_sub_dir, "attachment", "patch", "mini_draft.json")
        mini_info = _patch_mini_draft_in_place(
            mini_path=mini_path,
            norm_video_path=norm_video_path,
            video_filename=video_filename,
            src_dur_us=src_dur_us,
            vid_w=vid_w,
            vid_h=vid_h,
            has_audio=bool(media["has_audio"]),
            clean_title=clean_title,
        )

    # Bước B2: Cập nhật đồng bộ `draft_content.json` (ở cả thư mục gốc lẫn `Timelines/<tl_id>/`)
    mats = dc.setdefault("materials", {})
    videos_list = mats.setdefault("videos", [])
    tracks = dc.setdefault("tracks", [])

    video_tracks = [tr for tr in tracks if tr.get("type") == "video" and tr.get("segments")]
    if not video_tracks:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return create_capcut_draft_from_template(
            video_path=video_path,
            video_title=video_title,
            template_name=BLANK_TEMPLATE_KEY,
            auto_launch_capcut=auto_launch_capcut,
            force_restart_if_open=force_restart_if_open,
        )

    main_vtrack = video_tracks[0]
    vsegs = main_vtrack["segments"]
    # Nếu `vsegs` toàn là "Clip ghép" rỗng path (do người dùng gộp trong mẫu), rút gọn về 1 segment video chính!
    vmat_by_id = {v.get("id"): v for v in videos_list}
    if all(not ((vmat_by_id.get(s.get("material_id")) or {}).get("path") or "").strip() for s in vsegs):
        main_seg = vsegs[0]
        main_seg["target_timerange"] = {"start": 0, "duration": 0}
        vsegs = [main_seg]
        main_vtrack["segments"] = vsegs
        main_seg_idx = 0
        if videos_list:
            videos_list[:] = [videos_list[0]]
            main_seg["material_id"] = videos_list[0].get("id")
    else:
        main_seg_idx = (len(vsegs) // 2) if len(vsegs) >= 3 else 0
        main_seg = vsegs[main_seg_idx]
    main_mat_id = main_seg.get("material_id")

    # Ưu tiên lấy Speed / Volume / Scale mới nhất từ `mini_draft.json` (nếu có)
    seg_speed = float(mini_info["speed"]) if mini_info else float(main_seg.get("speed") or 1.0)
    extra_refs = set(main_seg.get("extra_material_refs") or [])
    if not mini_info:
        for sp_obj in mats.get("speeds") or []:
            if sp_obj.get("id") in extra_refs and sp_obj.get("mode", 0) == 0 and sp_obj.get("speed"):
                seg_speed = float(sp_obj["speed"])
                break
    if seg_speed <= 0:
        seg_speed = 1.0

    main_seg["speed"] = seg_speed
    for sp_obj in mats.get("speeds") or []:
        if sp_obj.get("id") in extra_refs and sp_obj.get("mode", 0) == 0:
            sp_obj["speed"] = seg_speed

    if mini_info:
        main_seg["volume"] = mini_info["volume"]
        main_seg["last_nonzero_volume"] = mini_info["volume"]
        if isinstance(mini_info.get("clip"), dict) and isinstance(main_seg.get("clip"), dict):
            mc = mini_info["clip"]
            if "scale" in mc and isinstance(mc["scale"], dict):
                main_seg["clip"]["scale"] = {"x": mc["scale"].get("x", 1.0), "y": mc["scale"].get("y", 1.0)}
            if "transform" in mc and isinstance(mc["transform"], dict):
                main_seg["clip"]["transform"] = {"x": mc["transform"].get("x", 0.0), "y": mc["transform"].get("y", 0.0)}
        if isinstance(mini_info.get("uniform_scale"), dict):
            main_seg["uniform_scale"] = {
                "on": bool(mini_info["uniform_scale"].get("on", False)),
                "value": float(mini_info["uniform_scale"].get("value", 1.0)),
            }

    local_mat_id = (mini_info["local_mat_id"] if mini_info else "") or str(uuid.uuid4()).lower()
    replaced_vmat = False
    for vmat in videos_list:
        if vmat.get("id") == main_mat_id or (not replaced_vmat and len(videos_list) == 1):
            vmat["path"] = norm_video_path
            vmat["material_name"] = video_filename
            vmat["duration"] = src_dur_us
            vmat["width"] = vid_w
            vmat["height"] = vid_h
            vmat["has_audio"] = bool(media["has_audio"])
            if not mini_info and vmat.get("local_material_id"):
                local_mat_id = vmat["local_material_id"]
            else:
                vmat["local_material_id"] = local_mat_id
            replaced_vmat = True
            break

    old_seg_target_dur = int((main_seg.get("target_timerange") or {}).get("duration") or dc.get("duration") or 0)
    new_seg_target_dur = max(100_000, int(round(src_dur_us / seg_speed)))
    delta_dur = new_seg_target_dur - old_seg_target_dur

    main_seg["source_timerange"] = {"start": 0, "duration": src_dur_us}
    main_seg.setdefault("target_timerange", {"start": 0, "duration": new_seg_target_dur})
    main_seg["target_timerange"]["duration"] = new_seg_target_dur

    for after_seg in vsegs[main_seg_idx + 1 :]:
        t_rng = after_seg.get("target_timerange")
        if isinstance(t_rng, dict) and "start" in t_rng:
            t_rng["start"] = max(0, int(t_rng["start"]) + delta_dur)

    last_vseg_tr = vsegs[-1].get("target_timerange") or {}
    new_total_dur = (
        int(mini_info["new_total_dur"])
        if mini_info
        else (int(last_vseg_tr.get("start", 0)) + int(last_vseg_tr.get("duration", new_seg_target_dur)))
    )
    dc["duration"] = new_total_dur

    # Kéo dài toàn bộ các lớp chữ (Title, PART 1) và hiệu ứng trên các track phụ phủ hết video mới
    for tr in tracks:
        if tr is main_vtrack:
            continue
        for seg in tr.get("segments") or []:
            trng = seg.get("target_timerange")
            if isinstance(trng, dict):
                s_start = int(trng.get("start") or 0)
                trng["duration"] = max(100_000, new_total_dur - s_start)

    _update_title_text_materials(mats.get("texts") or [], clean_title)

    dc_out = json.dumps(dc, ensure_ascii=False, separators=(",", ":"))
    write_dirs = [tmp_dir]
    if tl_sub_dir and os.path.isdir(tl_sub_dir):
        write_dirs.append(tl_sub_dir)

    for wdir in write_dirs:
        for fn in ("draft_content.json", "draft_content.json.bak", "template-2.tmp"):
            with open(os.path.join(wdir, fn), "w", encoding="utf-8") as f:
                f.write(dc_out)

    # Cập nhật tên file video mới trong `key_value.json` nếu có
    kv_path = os.path.join(tmp_dir, "key_value.json")
    if os.path.isfile(kv_path):
        try:
            kv = json.load(open(kv_path, "r", encoding="utf-8"))
            for v in kv.values():
                if isinstance(v, dict) and v.get("materialCategory") == "media":
                    v["materialName"] = video_filename
            with open(kv_path, "w", encoding="utf-8") as f:
                json.dump(kv, f, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            pass

    _finalize_and_register_draft(
        tmp_dir=tmp_dir,
        draft_root=draft_root,
        folder_name=folder_name,
        draft_display_name=draft_display_name,
        new_draft_id=new_draft_id,
        new_total_dur=new_total_dur,
        norm_video_path=norm_video_path,
        video_path=video_path,
        video_filename=video_filename,
        local_mat_id=local_mat_id,
        vid_w=vid_w,
        vid_h=vid_h,
        src_dur_us=src_dur_us,
    )

    if auto_launch_capcut:
        restart_or_launch_capcut(force_restart=force_restart_if_open)

    dur_min = (new_total_dur / 1_000_000) / 60.0
    return (
        True,
        f"Đã tạo Project CapCut '{draft_display_name}' từ mẫu '{template_name}' "
        f"(Speed {seg_speed:g}x • Thời lượng {dur_min:.1f} phút)!",
        draft_display_name,
    )

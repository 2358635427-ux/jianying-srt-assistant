"""
JianYing (剪映) draft project manager.

Handles:
- Auto-detecting the JianYing draft directory on Windows/macOS
- Reading root_meta_info.json to enumerate projects
- Parsing draft_content.json / draft_info.json to find & modify subtitle tracks
"""

from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from srt_processor import SubtitleEntry


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DraftInfo:
    draft_id: str
    name: str
    path: Path
    created_at: str = ""
    modified_at: str = ""

    def __str__(self) -> str:
        return f"{self.name} ({self.modified_at[:10] if self.modified_at else '?'})"


# ---------------------------------------------------------------------------
# Path detection
# ---------------------------------------------------------------------------

def _default_draft_dirs() -> List[Path]:
    """Return platform-specific default JianYing draft directories."""
    system = platform.system()
    candidates: List[Path] = []

    if system == "Windows":
        appdata = os.environ.get("LOCALAPPDATA", "")
        if appdata:
            candidates.append(
                Path(appdata)
                / "JianyingPro"
                / "User Data"
                / "Projects"
                / "com.lveditor.draft"
            )
    elif system == "Darwin":  # macOS
        candidates.append(
            Path.home()
            / "Movies" / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft"
        )
    else:
        candidates.append(
            Path.home()
            / ".config" / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft"
        )

    return candidates


def auto_detect_draft_dir() -> Optional[Path]:
    """Auto-detect the JianYing draft directory. Returns None if not found."""
    for candidate in _default_draft_dirs():
        if candidate.is_dir():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Draft listing — reads root_meta_info.json
# ---------------------------------------------------------------------------

def list_drafts(draft_dir: Path) -> List[DraftInfo]:
    """
    List all draft projects found under draft_dir.

    Reads root_meta_info.json which contains an `all_draft_store` array
    with metadata for every draft project.
    """
    drafts: List[DraftInfo] = []
    if not draft_dir.is_dir():
        return drafts

    root_meta = draft_dir / "root_meta_info.json"
    if not root_meta.exists():
        # Fallback: iterate subdirectories (older JianYing versions)
        return _list_drafts_fallback(draft_dir)

    try:
        meta = json.loads(root_meta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _list_drafts_fallback(draft_dir)

    all_drafts = meta.get("all_draft_store", [])
    if not all_drafts:
        return _list_drafts_fallback(draft_dir)

    for entry in all_drafts:
        name = entry.get("draft_name", "")
        draft_id = entry.get("draft_id", "")
        fold_path_str = entry.get("draft_fold_path", "")
        created = entry.get("tm_draft_create", "") or entry.get("tm_create", "")
        modified = entry.get("tm_draft_modified", "") or entry.get("tm_modify", "")

        # Resolve the draft folder path
        if fold_path_str:
            fold_path = Path(fold_path_str)
        else:
            # Construct from draft_id (folder name)
            fold_path = draft_dir / name

        # Only include drafts whose folder actually exists
        if not fold_path.is_dir():
            # Try matching by draft_id / folder name in the draft directory
            for child in draft_dir.iterdir():
                if child.is_dir() and child.name == name:
                    fold_path = child
                    break
            else:
                continue

        drafts.append(DraftInfo(
            draft_id=draft_id,
            name=name,
            path=fold_path,
            created_at=str(created),
            modified_at=str(modified),
        ))

    # Sort by modified time descending (most recent first)
    drafts.sort(key=lambda d: d.modified_at, reverse=True)
    return drafts


def _list_drafts_fallback(draft_dir: Path) -> List[DraftInfo]:
    """Fallback: iterate subdirectories and try draft_meta_info.json (older versions)."""
    drafts: List[DraftInfo] = []
    for item in sorted(draft_dir.iterdir()):
        if not item.is_dir() or item.name.startswith("."):
            continue
        meta_file = item / "draft_meta_info.json"
        if not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            name = meta.get("name", item.name)
        except (json.JSONDecodeError, UnicodeDecodeError):
            name = item.name

        drafts.append(DraftInfo(
            draft_id=item.name,
            name=name,
            path=item,
        ))

    drafts.sort(key=lambda d: d.modified_at, reverse=True)
    return drafts


# ---------------------------------------------------------------------------
# Subtitle extraction
# ---------------------------------------------------------------------------

def _find_content_files(draft_path: Path) -> List[Path]:
    """
    Find usable content files in a draft directory.

    Checks (in order):
      1. draft_content.json  — old JianYing format
      2. Walk subdraft/ dirs for draft_content.json with text tracks
    Returns list of Paths that contain subtitle data.
    """
    candidates: List[Path] = []

    # 1) Direct draft_content.json (old format)
    direct = draft_path / "draft_content.json"
    if direct.exists():
        candidates.append(direct)

    # 2) Search subdraft directories
    subdraft_dir = draft_path / "subdraft"
    if subdraft_dir.is_dir():
        for root, _dirs, files in os.walk(subdraft_dir):
            for f in files:
                if f == "draft_content.json":
                    candidates.append(Path(root) / f)

    return candidates


def _parse_content_tracks(content_file: Path) -> List[dict]:
    """Parse a content JSON file and return subtitle segments."""
    content = json.loads(content_file.read_text(encoding="utf-8"))
    tracks = content.get("tracks", [])
    segments: List[dict] = []

    for track_idx, track in enumerate(tracks):
        track_type = (track.get("type", "") or track.get("track_type", "") or "").lower()
        is_text = (
            track_type in ("text", "subtitle", "lyric", "caption")
            or "subtitle" in track_type
            or "text" in track_type
        )
        if not is_text:
            segs = track.get("segments", [])
            if segs:
                st = (segs[0].get("type", "") or segs[0].get("sub_type", "") or "").lower()
                if "subtitle" in st or "text" in st:
                    is_text = True

        if not is_text:
            continue

        for seg_idx, seg in enumerate(track.get("segments", [])):
            text = seg.get("content", "") or seg.get("text", "")
            if not text:
                continue

            start_ms = seg.get("start_ms") or seg.get("start", 0)
            if isinstance(start_ms, (int, float)):
                start_ms = int(start_ms * 1000) if start_ms < 1000 else int(start_ms)
            else:
                start_ms = 0

            duration_ms = seg.get("duration_ms") or seg.get("duration", 2000)
            if isinstance(duration_ms, (int, float)):
                duration_ms = int(duration_ms * 1000) if duration_ms < 100 else int(duration_ms)
            else:
                duration_ms = 2000

            segments.append({
                "text": str(text),
                "start_ms": start_ms,
                "end_ms": start_ms + duration_ms,
                "_track_index": track_idx,
                "_seg_index": seg_idx,
                "_source_file": str(content_file),
            })

    return segments


def extract_subtitles_from_draft(draft_path: Path) -> List[dict]:
    """
    Extract subtitle entries from a JianYing draft.

    Tries draft_content.json (old format) first, then searches subdraft
    directories. If no content files are found, raises an error with
    instructions to export SRT from JianYing first.
    """
    content_files = _find_content_files(draft_path)

    if not content_files:
        # Check if this is an encrypted (new format) draft
        info_file = draft_path / "draft_info.json"
        if info_file.exists():
            raise FileNotFoundError(
                f"该草稿使用了新版剪映的加密格式，无法直接读取字幕内容。\n\n"
                f"请使用以下方法：\n"
                f"1. 在剪映中打开该草稿\n"
                f"2. 导出字幕为 SRT 文件（菜单 → 导出 → 字幕）\n"
                f"3. 在本程序中切换到【手动模式】，上传导出的 SRT 文件进行处理\n"
                f"4. 处理完成后，将新的 SRT 文件导入剪映"
            )
        raise FileNotFoundError(
            f"未找到字幕内容文件。\n"
            f"请在剪映中导出字幕为 SRT 文件，然后使用本程序的【手动模式】处理。"
        )

    # Collect all segments from all content files
    all_segments: List[dict] = []
    for cf in content_files:
        segs = _parse_content_tracks(cf)
        all_segments.extend(segs)

    if not all_segments:
        raise ValueError(
            "草稿内容文件中未找到字幕轨道。\n"
            "请在剪映中导出字幕为 SRT 文件，然后使用本程序的【手动模式】处理。"
        )

    return all_segments


def apply_subtitles_to_draft(
    draft_path: Path,
    processed_texts: List[str],
    processed_start_ms: List[int],
    processed_end_ms: List[int],
) -> bool:
    """
    Overwrite subtitle segments in a draft's content file.

    Tries draft_content.json (old format) first, then subdraft content files.
    """
    content_files = _find_content_files(draft_path)

    if not content_files:
        info_file = draft_path / "draft_info.json"
        if info_file.exists():
            raise FileNotFoundError(
                f"该草稿使用了新版剪映的加密格式，无法直接写入字幕内容。\n\n"
                f"请使用手动模式：\n"
                f"1. 在剪映中导出字幕为 SRT\n"
                f"2. 在本程序中处理 SRT 文件\n"
                f"3. 将处理后的 SRT 导入剪映"
            )
        raise FileNotFoundError("未找到可写入的字幕内容文件。")

    modified_count = 0
    segment_idx = 0

    for cf in content_files:
        # Backup
        backup_file = Path(str(cf) + ".bak")
        if not backup_file.exists():
            backup_file.write_bytes(cf.read_bytes())

        content = json.loads(cf.read_text(encoding="utf-8"))
        tracks = content.get("tracks", [])

        for track in tracks:
            track_type = (track.get("type", "") or track.get("track_type", "") or "").lower()
            is_text = (
                track_type in ("text", "subtitle", "lyric", "caption")
                or "subtitle" in track_type
                or "text" in track_type
            )
            if not is_text:
                segs = track.get("segments", [])
                if segs:
                    st = (segs[0].get("type", "") or segs[0].get("sub_type", "") or "").lower()
                    if "subtitle" in st or "text" in st:
                        is_text = True

            if not is_text:
                continue

            for seg in track.get("segments", []):
                text = seg.get("content", "") or seg.get("text", "")
                if not text:
                    continue
                if segment_idx >= len(processed_texts):
                    break

                seg["content"] = processed_texts[segment_idx]
                if "start" in seg:
                    seg["start"] = processed_start_ms[segment_idx] / 1000.0
                if "start_ms" in seg:
                    seg["start_ms"] = processed_start_ms[segment_idx]
                if "duration" in seg:
                    seg["duration"] = (
                        processed_end_ms[segment_idx] - processed_start_ms[segment_idx]
                    ) / 1000.0
                if "duration_ms" in seg:
                    seg["duration_ms"] = (
                        processed_end_ms[segment_idx] - processed_start_ms[segment_idx]
                    )

                segment_idx += 1
                modified_count += 1

        cf.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")

    return modified_count > 0


# ---------------------------------------------------------------------------
# Conversion: JianYing segments ↔ SRT
# ---------------------------------------------------------------------------

def segments_to_srt_entries(segments: List[dict]) -> List[SubtitleEntry]:
    """Convert raw JianYing segments to SubtitleEntry list."""
    entries: List[SubtitleEntry] = []
    for i, seg in enumerate(segments, 1):
        entries.append(SubtitleEntry(
            index=i,
            start_ms=seg["start_ms"],
            end_ms=seg["end_ms"],
            text=seg["text"],
        ))
    return entries


def srt_entries_to_segment_data(entries: List[SubtitleEntry]) -> Tuple[List[str], List[int], List[int]]:
    """Convert SubtitleEntry list to parallel lists for apply_subtitles_to_draft()."""
    texts = [e.text for e in entries]
    starts = [e.start_ms for e in entries]
    ends = [e.end_ms for e in entries]
    return texts, starts, ends

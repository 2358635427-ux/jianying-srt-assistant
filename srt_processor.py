"""
SRT subtitle parsing, text splitting, and timestamp redistribution.

Handles:
- Parsing .srt files into structured entries
- Splitting long lines at semantic/word boundaries
- Redistributing timestamps proportionally
- Merging short adjacent subtitles
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SubtitleEntry:
    index: int
    start_ms: int
    end_ms: int
    text: str

    @property
    def start_str(self) -> str:
        return _ms_to_timestamp(self.start_ms)

    @property
    def end_str(self) -> str:
        return _ms_to_timestamp(self.end_ms)

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def char_count(self) -> int:
        return len(self.text)

    def to_srt_block(self, index: int) -> str:
        return f"{index}\n{self.start_str} --> {self.end_str}\n{self.text}\n"


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

_TIMESTAMP_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


def _parse_timestamp(ts: str) -> int:
    """Parse SRT timestamp 'HH:MM:SS,mmm' → milliseconds."""
    m = _TIMESTAMP_RE.match(ts.strip())
    if not m:
        raise ValueError(f"Invalid timestamp: {ts!r}")
    h, mi, s, ms = map(int, m.groups())
    return ((h * 60 + mi) * 60 + s) * 1000 + ms


def _ms_to_timestamp(ms: int) -> str:
    """Convert milliseconds → SRT timestamp 'HH:MM:SS,mmm'."""
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ---------------------------------------------------------------------------
# SRT parsing
# ---------------------------------------------------------------------------

def parse_srt(text: str) -> List[SubtitleEntry]:
    """Parse raw SRT content into a list of SubtitleEntry objects."""
    entries: List[SubtitleEntry] = []
    blocks = re.split(r"\n\s*\n", text.strip())

    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue

        # Parse index (may be absent or malformed — we handle gracefully)
        idx: int
        time_line: str
        try:
            idx = int(lines[0].strip())
            time_line = lines[1].strip()
            text_lines = lines[2:]
        except ValueError:
            # Index missing, assume line 0 is the timestamp
            idx = len(entries) + 1
            time_line = lines[0].strip()
            text_lines = lines[1:]

        # Parse timestamp line
        parts = time_line.split("-->")
        if len(parts) != 2:
            continue

        start_ms = _parse_timestamp(parts[0])
        end_ms = _parse_timestamp(parts[1])
        text = "\n".join(text_lines).strip()

        # Replace literal \n / <br> / <br/> in text
        text = text.replace("<br/>", "\n").replace("<br>", "\n").replace("\\n", "\n")
        # Collapse multiple spaces
        text = re.sub(r"[ \t]+", " ", text)
        # Collapse 3+ newlines
        text = re.sub(r"\n{3,}", "\n\n", text)

        if text:  # skip truly empty entries
            entries.append(SubtitleEntry(idx, start_ms, end_ms, text))

    # Re-index sequentially
    for i, e in enumerate(entries, 1):
        e.index = i

    return entries


def entries_to_srt(entries: List[SubtitleEntry]) -> str:
    """Convert SubtitleEntry list → SRT file content string."""
    return "\n".join(e.to_srt_block(i) for i, e in enumerate(entries, 1)) + "\n"


# ---------------------------------------------------------------------------
# Text splitting engine
# ---------------------------------------------------------------------------

# Chinese punctuation marks that serve as natural split points
_CJK_SPLIT_RE = re.compile(
    r"([，,。！？；：、」" "'" r'"' r"）\)】\]》>\.\!\?\;\:\n])"
)

# Chinese characters range
_CJK_CHAR_RE = re.compile(r"[一-鿿㐀-䶿\U00020000-\U0002a6df]")

# English word boundary (split at spaces while keeping punctuation attached)
_EN_WORD_SPLIT_RE = re.compile(r"(\s+)")


def _is_primarily_cjk(text: str) -> bool:
    """Heuristic: text is primarily CJK if >40% of letters are CJK."""
    letters = [c for c in text if c.isalpha() or _CJK_CHAR_RE.match(c)]
    if not letters:
        return True  # default to CJK for punctuation-only text
    cjk_count = sum(1 for c in letters if _CJK_CHAR_RE.match(c))
    return cjk_count / len(letters) > 0.4


def _split_cjk_line(text: str, max_chars: int) -> List[str]:
    """Split a CJK text line at punctuation boundaries, respecting max_chars."""
    # First, split at punctuation boundaries
    segments: List[str] = []
    current = ""

    for ch in text:
        current += ch
        if _CJK_SPLIT_RE.match(ch) and len(current) >= max_chars * 0.4:
            segments.append(current)
            current = ""
    if current.strip():
        segments.append(current)

    # Merge short trailing segments
    result: List[str] = []
    for seg in segments:
        if result and len(result[-1]) + len(seg) <= max_chars:
            result[-1] += seg
        else:
            result.append(seg)

    # Force-split any segment that still exceeds max_chars
    final: List[str] = []
    for seg in result:
        while len(seg) > max_chars:
            # Find best split point within the last max_chars chars
            chunk = seg[:max_chars]
            # Try to find a split point in the last 40% of chunk
            match = None
            search_start = int(max_chars * 0.6)
            for m in _CJK_SPLIT_RE.finditer(chunk[search_start:]):
                match = m
            if match:
                split_at = search_start + match.end()
            else:
                split_at = max_chars
            final.append(seg[:split_at])
            seg = seg[split_at:].lstrip()
        if seg.strip():
            final.append(seg)

    return final or [text]


def _split_en_line(text: str, max_chars: int) -> List[str]:
    """Split English text at word boundaries, respecting max_chars."""
    words = _EN_WORD_SPLIT_RE.split(text)  # alternates word, whitespace, word, ...
    lines: List[str] = []
    current = ""

    for token in words:
        if not token:
            continue
        is_space = token.isspace()

        if not current:
            current = token
            continue

        candidate = current + token
        if len(candidate.rstrip()) <= max_chars:
            current = candidate
        else:
            trimmed = current.rstrip()
            if trimmed:
                lines.append(trimmed)
            if is_space:
                current = ""
            else:
                current = token

    if current.strip():
        lines.append(current.rstrip())

    # Force-split any line that still exceeds max_chars
    final: List[str] = []
    for line in lines:
        while len(line) > max_chars:
            # Try to split at last space in range
            chunk = line[:max_chars]
            last_space = chunk.rfind(" ")
            if last_space > max_chars * 0.5:
                final.append(line[:last_space].rstrip())
                line = line[last_space:].lstrip()
            else:
                final.append(line[:max_chars])
                line = line[max_chars:]
        if line.strip():
            final.append(line.strip())

    return final or [text]


def split_subtitle_text(text: str, max_chars: int) -> List[str]:
    """
    Split subtitle text so each piece fits within max_chars.
    Returns list of single-line strings (no embedded newlines).
    """
    # First, flatten any existing newlines to spaces
    flat = text.replace("\n", " ").strip()
    flat = re.sub(r"\s+", " ", flat)

    if len(flat) <= max_chars:
        return [flat]

    if _is_primarily_cjk(flat):
        return _split_cjk_line(flat, max_chars)
    else:
        return _split_en_line(flat, max_chars)


# ---------------------------------------------------------------------------
# Timestamp redistribution
# ---------------------------------------------------------------------------

def redistribute_timestamps(
    original: SubtitleEntry,
    pieces: List[str],
    min_start_ms: Optional[int] = None,
    min_gap_ms: int = 30,
) -> List[SubtitleEntry]:
    """
    Distribute the original entry's time range across split pieces,
    proportionally to character count. Ensures minimum gap between entries.
    """
    if not pieces:
        return []

    total_chars = sum(len(p) for p in pieces)
    if total_chars == 0:
        total_chars = 1

    total_duration = original.duration_ms - min_gap_ms * (len(pieces) - 1)
    if total_duration <= 0:
        # Edge case: very short duration with many pieces
        # Assign equal time slices
        per_duration = max(50, original.duration_ms // len(pieces))
        total_duration = per_duration * len(pieces)

    start = original.start_ms if min_start_ms is None else max(original.start_ms, min_start_ms)
    entries: List[SubtitleEntry] = []

    for i, piece in enumerate(pieces):
        char_ratio = len(piece) / total_chars
        piece_duration = max(200, int(total_duration * char_ratio))
        piece_start = start
        piece_end = piece_start + piece_duration
        entries.append(
            SubtitleEntry(
                index=len(entries) + 1,
                start_ms=piece_start,
                end_ms=piece_end,
                text=piece,
            )
        )
        start = piece_end + min_gap_ms

    return entries


# ---------------------------------------------------------------------------
# Merge short adjacent subtitles (optional optimization)
# ---------------------------------------------------------------------------

def merge_short_entries(
    entries: List[SubtitleEntry],
    max_chars: int,
    max_gap_ms: int = 500,
) -> List[SubtitleEntry]:
    """
    Merge adjacent entries if their combined text fits within max_chars
    and the gap between them is <= max_gap_ms.
    """
    if len(entries) < 2:
        return entries

    merged: List[SubtitleEntry] = [entries[0]]

    for curr in entries[1:]:
        prev = merged[-1]
        gap = curr.start_ms - prev.end_ms
        combined = prev.text + " " + curr.text

        if gap <= max_gap_ms and len(combined) <= max_chars:
            merged[-1] = SubtitleEntry(
                index=prev.index,
                start_ms=prev.start_ms,
                end_ms=curr.end_ms,
                text=combined,
            )
        else:
            merged.append(curr)

    return merged


# ---------------------------------------------------------------------------
# Main processing pipeline
# ---------------------------------------------------------------------------

def process_srt_entries(
    entries: List[SubtitleEntry],
    max_chars: int,
    mode: str = "general",
    merge: bool = True,
) -> List[SubtitleEntry]:
    """
    Full processing pipeline:
    1. Split long entries to fit max_chars
    2. Optionally merge short adjacent entries
    3. Enforce single-line constraint
    4. Apply English capitalization if in en_only mode
    """
    result: List[SubtitleEntry] = []

    for entry in entries:
        pieces = split_subtitle_text(entry.text, max_chars)

        if len(pieces) == 1 and pieces[0] == entry.text:
            # No split needed
            result.append(SubtitleEntry(
                index=0,
                start_ms=entry.start_ms,
                end_ms=entry.end_ms,
                text=pieces[0],
            ))
        else:
            # Split and redistribute timestamps
            last_end = result[-1].end_ms + 30 if result else None
            split_entries = redistribute_timestamps(entry, pieces, last_end)
            result.extend(split_entries)

    # Ensure no overlapping timestamps
    result = _fix_overlaps(result)

    # Optional merge
    if merge:
        result = merge_short_entries(result, max_chars)

    # Apply English mode capitalization
    if mode == "en_only":
        for e in result:
            e.text = _capitalize_sentence(e.text)

    # Re-index
    for i, e in enumerate(result, 1):
        e.index = i

    return result


def _fix_overlaps(entries: List[SubtitleEntry]) -> List[SubtitleEntry]:
    """Ensure no timestamp overlaps between adjacent entries."""
    if len(entries) < 2:
        return entries

    fixed = [entries[0]]
    for curr in entries[1:]:
        if curr.start_ms < fixed[-1].end_ms:
            curr.start_ms = fixed[-1].end_ms + 1
        if curr.end_ms <= curr.start_ms:
            curr.end_ms = curr.start_ms + 200  # minimum 200ms duration
        fixed.append(curr)
    return fixed


def _capitalize_sentence(text: str) -> str:
    """Capitalize the first letter of the sentence."""
    if not text:
        return text

    for i, ch in enumerate(text):
        if ch.isalpha():
            return text[:i] + ch.upper() + text[i + 1:]
    return text


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def process_srt_content(srt_text: str, chinese_limit: int, english_limit: int | None, mode: str) -> str:
    """
    High-level entry point: parse SRT text, process it, return new SRT text.
    If english_limit is None, uses the same limit for both languages
    (dynamically applied per-entry based on content detection).
    """
    entries = parse_srt(srt_text)

    # Determine per-entry limit based on content
    def get_limit(text: str) -> int:
        if english_limit is not None and not _is_primarily_cjk(text):
            return english_limit
        return chinese_limit

    # Group consecutive same-language entries for consistent processing
    result: List[SubtitleEntry] = []
    for entry in entries:
        limit = get_limit(entry.text)
        pieces = split_subtitle_text(entry.text, limit)

        if len(pieces) == 1 and pieces[0] == entry.text:
            result.append(SubtitleEntry(
                index=0,
                start_ms=entry.start_ms,
                end_ms=entry.end_ms,
                text=pieces[0],
            ))
        else:
            last_end = result[-1].end_ms + 30 if result else None
            split_entries = redistribute_timestamps(entry, pieces, last_end)
            result.extend(split_entries)

    result = _fix_overlaps(result)
    result = merge_short_entries(result, max(chinese_limit, english_limit or chinese_limit))

    if mode == "en_only":
        for e in result:
            e.text = _capitalize_sentence(e.text)

    for i, e in enumerate(result, 1):
        e.index = i

    return entries_to_srt(result)

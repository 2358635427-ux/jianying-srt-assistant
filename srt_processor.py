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
from typing import Dict, List, Optional, Set, Tuple

import jieba
import jieba.posseg as pseg


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


def _find_cjk_split_pos(text: str, max_chars: int) -> int:
    """Find the best split position that doesn't break a Chinese word."""
    search_start = int(max_chars * 0.6)

    # First, try to find a punctuation split point
    chunk = text[:max_chars]
    match = None
    for m in _CJK_SPLIT_RE.finditer(chunk[search_start:]):
        match = m
    if match:
        return search_start + match.end()

    # No punctuation — use jieba word boundaries
    tokens = list(jieba.tokenize(text))
    # Scan backwards from max_chars to find a legal split position
    for p in range(max_chars, search_start - 1, -1):
        legal = True
        for _word, start, end in tokens:
            if start < p < end:
                legal = False
                break
        if legal:
            return p
    return max_chars


def _split_cjk_line(text: str, max_chars: int) -> List[str]:
    """Split a CJK text line at word/punctuation boundaries, respecting max_chars."""
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
            split_at = _find_cjk_split_pos(seg, max_chars)
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

# -- Dialogue boundary detection ------------------------------------------------
# Content-aware: uses jieba keyword overlap + named-entity tracking to decide
# whether two subtitle entries belong to the same speaker / continuous thought.

# Words that strongly suggest a new speaker (greetings, conversation openers)
_GREETING_MARKERS: Set[str] = {
    # Chinese
    "你好", "您好", "嗨", "嘿", "哈喽", "大家好", "各位", "请问",
    "喂", "那个", "话说", "对了", "哎", "哎呀", "哦对了",
}

# English greeting/openers — full words
_EN_GREETINGS: Set[str] = {
    "hello", "hi", "hey", "yo", "well", "okay", "ok", "alright",
    "oh", "ah", "uh", "um", "eh", "wow", "oops", "ugh",
    "good morning", "good afternoon", "good evening",
}

# Address terms / vocatives — lines starting with these are independent utterances
_EN_VOCATIVES: Set[str] = {
    "dad", "mom", "mum", "daddy", "mommy", "mummy",
    "sir", "ma'am", "madam", "mister", "miss", "doctor",
    "professor", "officer", "boss", "captain", "commander",
    "bro", "dude", "man", "buddy", "pal", "mate",
    "honey", "darling", "sweetie", "sweetheart", "baby", "babe",
    "son", "dear", "love", "boy", "girl", "guys", "folks",
    "mr.", "mrs.", "ms.", "dr.",
}

# English exclamations — short standalone utterances
_EN_EXCLAMATIONS: Set[str] = {
    "yes", "no", "yeah", "nope", "yep", "sure", "maybe",
    "thanks", "thank you", "please", "sorry", "excuse me",
    "great", "fine", "good", "perfect", "excellent", "wonderful",
    "stop", "wait", "look", "listen", "come on", "go",
    "what", "why", "when", "where", "who", "how",
    "really", "seriously", "absolutely", "definitely", "exactly",
    "help", "watch out", "careful", "hurry", "quick",
}

def _extract_first_token(text: str) -> str:
    """Extract the first word/token from text (before any punctuation or space)."""
    text = text.lstrip()
    m = re.match(r"[\w'.]+", text)
    return m.group(0).lower() if m else ""


def _looks_like_conversation_starter(text: str) -> bool:
    """Check if text starts like a new speaker's turn (greeting / vocative / exclamation)."""
    first = _extract_first_token(text)
    if not first:
        return False
    if first in _EN_GREETINGS or first in _EN_VOCATIVES or first in _EN_EXCLAMATIONS:
        return True
    # Also check 2-word openers: "good morning", "thank you", etc.
    first_two = " ".join(text.lstrip().split()[:2]).lower().rstrip(",.;:!?")
    if first_two in _EN_GREETINGS or first_two in _EN_EXCLAMATIONS:
        return True
    return False

# Continuation words — the next line continues the same speaker's thought
_CONTINUATION_MARKERS: Set[str] = {
    "但", "但是", "而", "而且", "所以", "因此", "因为", "如果",
    "虽然", "然而", "不过", "可是", "却", "则", "于是", "接着",
    "然后", "况且", "此外", "另外", "还", "也", "又", "再",
    "就", "便", "才", "并", "并且", "同样", "同时", "最后",
    "终于", "当然", "果然", "忽然", "突然", "于是", "总之",
    "那", "那么", "这", "这个", "那个", "这些",
    "先", "首先", "随后", "之后", "后来", "不仅", "不光",
    "不只", "除非", "无论", "不管", "既然", "以至", "以便",
    "以免", "省得", "免得", "与其", "宁可", "宁愿",
    "其实", "反正", "按理", "总之", "不过", "毕竟",
}


# -- Punctuation-free sentence boundary detection ----------------------------------
# Chinese sentence-final particles (modal particles, aspect markers)
# These strongly suggest a preceding clause/sentence is complete.
_CN_SENTENCE_ENDERS: Set[str] = {
    "了", "吧", "吗", "呢", "啊", "呀", "哦", "嘛", "呗", "啦",
    "的", "地", "得", "着", "过", "么", "哇", "哈", "哟", "喽",
}

# Chinese sentence starters — words that typically begin a new clause/sentence
_CN_SENTENCE_STARTERS: Set[str] = {
    # Pronouns (r)
    "我", "你", "您", "他", "她", "它", "我们", "你们", "他们", "她们",
    "自己", "大家", "别人", "人家", "谁", "什么", "哪", "哪儿", "怎么",
    # Demonstratives (r)
    "这", "那", "这个", "那个", "这些", "那些", "这里", "那里",
    # Time words (t)
    "今天", "昨天", "明天", "现在", "刚才", "之前", "以后", "后来",
    "然后", "首先", "接着", "随后", "最后", "终于", "最近",
    # Conjunctions that start new thoughts (c)
    "但是", "可是", "不过", "所以", "因此", "那么", "而且", "并且",
    "然而", "于是", "总之", "另外", "此外", "还有", "其实",
    # Adverbs (d)
    "当然", "突然", "忽然", "果然", "居然", "竟然", "反正",
    "也许", "大概", "可能", "应该", "一定", "肯定", "确实",
    "已经", "曾经", "正在", "将要", "一直", "总是",
    # Prepositions (p)
    "在", "从", "对", "向", "把", "被", "让", "给", "为", "以",
    "关于", "对于", "至于", "按照", "根据", "经过", "通过",
    # Common sentence-initial verbs
    "有", "是", "像", "觉得", "认为", "希望", "知道", "想",
}

# English sentence starters — first words that typically begin sentences
_EN_SENTENCE_STARTERS: Set[str] = {
    # Subject pronouns (strong sentence starts)
    "i", "you", "he", "she", "it", "we", "they",
    # Demonstratives
    "this", "that", "these", "those", "there", "here",
    # Question words (strong sentence starts)
    "what", "why", "when", "where", "how", "who", "which",
    # Possessives as subjects
    "my", "your", "his", "her", "its", "our", "their",
    # Conjunctions that start new thoughts (NOT "and"/"but"/"so" —
    # those are usually continuations in subtitle context)
    "well", "now", "then",
    "however", "therefore", "also", "still",
    # Common sentence-starting adverbs
    "no", "not", "never", "always", "maybe", "perhaps",
    "really", "actually", "honestly", "seriously",
    "let", "please", "look", "listen",
}


def _get_first_word(text: str) -> str:
    """Extract the first meaningful word from text (lowercased)."""
    text = text.lstrip()
    m = re.match(r"[\w']+", text)
    return m.group(0).lower() if m else ""


def _get_last_word(text: str) -> str:
    """Extract the last word/punctuation from text."""
    text = text.rstrip()
    m = re.search(r"[\w。！？.!?]+$", text)
    return m.group(0) if m else ""


def _looks_like_sentence_starter(text: str) -> bool:
    """Check if text starts like a new sentence (without requiring punctuation)."""
    if not text:
        return False
    first = _get_first_word(text)
    if not first:
        return False
    # English check
    if first.lower() in _EN_SENTENCE_STARTERS:
        return True
    # Chinese check — use jieba to get the first token
    tokens = list(pseg.cut(text.lstrip()))
    if tokens:
        first_word, first_flag = tokens[0]
        if first_word in _CN_SENTENCE_STARTERS:
            return True
        # POS-based: pronouns (r), time words (t), conjunctions (c) start sentences
        if first_flag in ("r", "t", "c"):
            return True
    return False


def _looks_like_sentence_ender(text: str) -> bool:
    """Check if text ends like a complete sentence (without requiring punctuation)."""
    if not text:
        return False
    # Punctuation check
    if text.rstrip()[-1] in "。！？.!?":
        return True
    # Chinese sentence-final particles
    tokens = list(pseg.cut(text.rstrip()))
    if tokens:
        last_word, last_flag = tokens[-1]
        if last_word in _CN_SENTENCE_ENDERS:
            return True
        # POS-based: modal particles (y), aspect particles (u)
        if last_flag == "y":
            return True
    return False


def _is_sentence_boundary(prev_text: str, next_text: str) -> bool:
    """Detect sentence boundary between two texts using both
    punctuation and linguistic patterns (works without punctuation).

    Returns True if next_text likely starts a new sentence.
    """
    prev = prev_text.rstrip()
    nxt = next_text.lstrip()
    if not prev or not nxt:
        return True  # first entry starts a new sentence

    # 1. Punctuation-based (strong signal)
    if prev.endswith(("。", "！", "？", ".", "!", "?")):
        ch2 = nxt[:2] if len(nxt) >= 2 else ""
        if ch2 not in _CONTINUATION_MARKERS:
            return True

    # 2. English continuation conjunctions → NOT a boundary
    first_en = _get_first_word(nxt)
    if first_en in ("and", "but", "or", "so", "because", "then", "also", "plus"):
        return False

    # 3. Greeting / vocative → new sentence
    if _looks_like_conversation_starter(nxt):
        return True

    # 3. Sentence-ender + sentence-starter → strong boundary
    prev_ends = _looks_like_sentence_ender(prev)
    next_starts = _looks_like_sentence_starter(nxt)
    if prev_ends and next_starts:
        return True

    # 4. Sentence starter → check continuity for confirmation
    if next_starts:
        continuity = _compute_continuity_score(prev, nxt)
        # Lower threshold: if next looks like a sentence start, only need mild
        # topic discontinuity.  Also handle neutral scores (0.50) from short/
        # English text where jieba POS yields few keywords.
        if continuity < 0.45:
            return True

    # 5. Sentence ender alone with moderate topic shift
    if prev_ends:
        continuity = _compute_continuity_score(prev, nxt)
        if continuity < 0.35:
            return True

    return False


# -- Subtitle text normalization ------------------------------------------------
# Title abbreviations that keep their period
_TITLE_ABBREVS: Set[str] = {
    "Mr", "Mrs", "Ms", "Miss", "Dr", "Prof", "St", "Sr", "Jr",
    "Mt", "Capt", "Col", "Gen", "Lt", "Maj", "Rev", "Hon",
}
_TITLE_RE = re.compile(
    r'\b(' + '|'.join(re.escape(a) for a in _TITLE_ABBREVS) + r')\.',
    re.IGNORECASE,
)


def _normalize_subtitle_text(text: str) -> str:
    """Remove sentence punctuation from subtitle text while preserving
    contractions (you're, it's), compound words (twenty-one), and
    title abbreviations (Mr., Mrs., Ms., Dr.).

    Strips: . , ! ?
    Keeps:  ' (contractions)  - (compounds)  . (titles)
    """
    if not text:
        return text

    # Step 1: protect title abbreviations (Mr. → Mr__TDOT__)
    text = _TITLE_RE.sub(r'\1__TDOT__', text)

    # Step 2: remove . , ! ? (sentence punctuation)
    for ch in ('.', ',', '!', '?'):
        text = text.replace(ch, '')

    # Step 3: restore title dots
    text = text.replace('__TDOT__', '.')

    # Step 4: clean up whitespace
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


def _capitalize_pronoun_i(text: str) -> str:
    """Capitalize standalone lowercase 'i' to 'I' everywhere in text."""
    return re.sub(r'\bi\b', 'I', text)


# -- Proper noun capitalization -------------------------------------------------
# Unambiguous proper nouns: safe to capitalize because they have no conflicting
# common-noun meaning. Ambiguous words (may, march, grace, rose, apple, etc.)
# are deliberately EXCLUDED to avoid false positives.

_PROPER_NOUNS: Set[str] = {
    # Months
    "january", "february", "march", "april", "june",
    "july", "august", "september", "october", "november", "december",
    # Days
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    # Continents
    "asia", "europe", "africa", "antarctica", "oceania",
    # Countries
    "china", "england", "france", "germany", "japan", "korea",
    "india", "russia", "canada", "australia", "brazil", "italy", "spain",
    "mexico", "egypt", "greece", "sweden", "norway", "denmark",
    "finland", "poland", "ukraine", "thailand", "vietnam", "indonesia",
    "malaysia", "singapore", "pakistan", "bangladesh", "philippines",
    "nigeria", "kenya", "argentina", "chile", "colombia",
    "peru", "venezuela", "portugal", "belgium", "switzerland",
    "austria", "hungary", "romania", "ireland", "israel",
    "iran", "iraq", "syria", "lebanon", "jordan",
    "kuwait", "qatar", "oman", "yemen", "mongolia", "nepal",
    "cambodia", "laos", "myanmar", "ethiopia", "ghana", "morocco",
    "iceland", "croatia", "serbia", "bulgaria", "lithuania", "latvia",
    "estonia", "slovenia", "albania", "armenia", "georgia",
    # Nationalities / Languages
    "chinese", "english", "french", "german", "japanese", "korean",
    "russian", "italian", "spanish", "arabic", "dutch", "swedish",
    "norwegian", "danish", "finnish", "polish", "ukrainian",
    "portuguese", "greek", "turkish", "hebrew", "latin",
    "hindi", "bengali", "urdu", "swahili", "vietnamese",
    # Major cities
    "beijing", "shanghai", "tokyo", "london", "paris",
    "berlin", "rome", "madrid", "moscow", "seoul",
    "bangkok", "dubai", "sydney", "melbourne",
    "toronto", "vancouver", "montreal", "mumbai", "delhi", "cairo",
    "istanbul", "vienna", "prague", "warsaw", "budapest", "athens",
    "oslo", "helsinki", "lisbon", "brussels", "amsterdam",
    "chicago", "boston", "seattle", "philadelphia", "miami",
    "houston", "phoenix", "detroit", "denver", "atlanta",
    "baltimore", "dallas", "portland", "las vegas", "orlando",
    # US States
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "ohio", "oklahoma", "oregon", "tennessee", "texas",
    "utah", "vermont", "virginia", "wisconsin", "wyoming",
    # Oceans / Seas / Rivers / Mountains
    "pacific", "atlantic", "mediterranean", "caribbean", "arctic",
    "nile", "amazon", "mississippi", "yangtze", "ganges",
    "himalayas", "alps", "rockies", "andes",
    # Holidays
    "christmas", "easter", "thanksgiving", "halloween",
    "hanukkah", "diwali", "ramadan",
    # Organizations / Brands (single-meaning proper nouns)
    "unesco", "nato", "nasa", "fbi", "cia",
    "hollywood", "broadway",
    "google", "microsoft", "facebook", "amazon", "twitter",
    "tiktok", "youtube", "netflix", "spotify", "uber", "tesla",
    "nintendo", "playstation", "xbox",
    "disney", "marvel", "starbucks", "nike", "adidas",
}

# Fixed-form capitalization: always replace these with correct form
_ALWAYS_CAPS: Dict[str, str] = {
    "ok": "OK", "okay": "OK",
    "im": "I'm", "ive": "I've", "ill": "I'll", "id": "I'd",
    "dont": "Don't", "cant": "Can't", "wont": "Won't",
    "isnt": "Isn't", "arent": "Aren't", "wasnt": "Wasn't",
    "werent": "Weren't", "hasnt": "Hasn't", "havent": "Haven't",
    "hadnt": "Hadn't", "doesnt": "Doesn't", "didnt": "Didn't",
    "couldnt": "Couldn't", "wouldnt": "Wouldn't", "shouldnt": "Shouldn't",
    "theyd": "They'd", "theyll": "They'll", "theyve": "They've",
    "wed": "We'd", "well": "We'll", "weve": "We've", "were": "We're",
    "youd": "You'd", "youll": "You'll", "youve": "You've", "youre": "You're",
    "hed": "He'd", "hell": "He'll", "shed": "She'd", "shell": "She'll",
    "thats": "That's", "whats": "What's", "whos": "Who's", "hows": "How's",
    "heres": "Here's", "theres": "There's", "lets": "Let's",
}


def _capitalize_proper_nouns(text: str) -> str:
    """Capitalize known proper nouns and fixed-form abbreviations.

    Uses a curated dictionary of unambiguous proper nouns (countries, cities,
    months, days, etc.) and fixed-form corrections (ok→OK, im→I'm, etc.).
    Common nouns like 'city', 'river', 'language' are left lowercase.
    """
    if not text:
        return text

    words = text.split()
    result: List[str] = []

    for word in words:
        # Strip punctuation for lookup
        clean = re.sub(r'^[^a-zA-Z]*|[^a-zA-Z]*$', '', word)
        lower = clean.lower()

        if lower in _ALWAYS_CAPS:
            word = word.replace(clean, _ALWAYS_CAPS[lower])
        elif lower in _PROPER_NOUNS and lower == clean:
            word = word.replace(clean, clean[0].upper() + clean[1:].lower())

        result.append(word)

    return ' '.join(result)


def _extract_keywords(text: str) -> Set[str]:
    """Extract content words (nouns, verbs, adjectives) for topic comparison.

    Falls back to English word-splitting when jieba POS yields too few results
    (common with English-only text where jieba tags everything as 'eng').
    """
    words = list(pseg.cut(text))
    result = {
        word for word, flag in words
        if flag.startswith(("n", "v", "a")) and len(word) >= 2
    }
    # Fallback for English text: jieba tags most English words as 'eng' or 'x',
    # so extract meaningful words manually (skip stopwords, short words)
    if len(result) < 2 and not _is_primarily_cjk(text):
        _EN_STOPWORDS = {"the", "a", "an", "is", "are", "was", "were", "be",
                          "been", "am", "in", "on", "at", "to", "for", "of",
                          "and", "or", "but", "so", "if", "it", "its", "this",
                          "that", "with", "from", "by", "as", "not", "no", "we",
                          "you", "he", "she", "they", "my", "your", "his", "her"}
        en_words = re.findall(r"[a-zA-Z]{3,}", text.lower())
        result = {w for w in en_words if w not in _EN_STOPWORDS}
    return result


def _extract_names(text: str) -> Set[str]:
    """Extract person names (jieba 'nr' tag) for speaker tracking."""
    words = pseg.cut(text)
    return {word for word, flag in words if flag == "nr"}


def _compute_continuity_score(text1: str, text2: str) -> float:
    """Score 0-1: how likely these two texts belong to the same speaker.

    1.0 = nearly certain same speaker (high keyword overlap)
    0.0 = nearly certain different speaker (no overlap, different names)
    """
    kw1 = _extract_keywords(text1)
    kw2 = _extract_keywords(text2)

    if not kw1 or not kw2:
        return 0.50  # not enough data → neutral

    # Jaccard similarity of content words
    union = kw1 | kw2
    overlap = kw1 & kw2
    if not union:
        return 0.50
    jaccard = len(overlap) / len(union)

    # Name-shift penalty: different person names → likely different speaker
    names1 = _extract_names(text1)
    names2 = _extract_names(text2)
    name_penalty = 0.0
    if names1 and names2:
        name_overlap = names1 & names2
        if not name_overlap:
            name_penalty = 0.40  # strong penalty for completely different names

    score = max(0.0, jaccard - name_penalty)
    return score


def _is_dialogue_boundary(prev_text: str, next_text: str) -> bool:
    """Content-aware dialogue boundary detection.

    Returns True when two texts likely belong to different speakers or
    independent sentences that should NOT be merged together.

    Decision order (strongest → weakest):
    1. Greetings → boundary
    2. Continuation markers → NOT boundary (override)
    3. Content continuity via keyword/name overlap
    4. Punctuation-based heuristics (augment, not decide)
    """
    prev = prev_text.rstrip()
    nxt = next_text.lstrip()
    if not prev or not nxt:
        return False

    # ── 1. Greeting/openers/vocatives → new speaker ──
    first_two_cn = nxt[:2]
    if first_two_cn in _GREETING_MARKERS or nxt[:4] in _GREETING_MARKERS:
        return True
    # English conversation starters (greetings, dad/mom/sir, yes/no, etc.)
    if _looks_like_conversation_starter(nxt):
        return True

    # ── 2. Continuation markers → same speaker (STRONG override) ──
    ch1 = nxt[:1] if nxt else ""
    ch2 = nxt[:2] if len(nxt) >= 2 else ""
    if ch1 in _CONTINUATION_MARKERS or ch2 in _CONTINUATION_MARKERS:
        return False

    # ── 3. Content continuity (core signal) ──
    continuity = _compute_continuity_score(prev, nxt)

    if continuity >= 0.50:
        return False   # significant topic overlap → same speaker
    if continuity <= 0.10:
        return True    # almost no overlap → different speaker

    # ── 4. Sentence-ending punctuation + low/moderate continuity ──
    has_sentence_end = prev.endswith(
        ("。", "！", "？", ".", "!", "?", "」", "』", "：", "∶")
    )
    if has_sentence_end and continuity < 0.35:
        return True

    # Question-answer pairs: often different speakers but not always
    is_question = prev.endswith(("？", "?"))
    if is_question and continuity < 0.30:
        return True

    # ── 5. Default: lean toward SAME speaker (merge) when uncertain ──
    # Subtitle dialogues often have short sentences with few keywords,
    # so neutral continuity is not a reliable boundary signal.
    return False


def _split_at_dialogue_boundaries(
    entries: List[SubtitleEntry],
) -> List[SubtitleEntry]:
    """Scan entries for internal dialogue boundaries and split at them.

    When a merged entry contains patterns like "...yesterday. Dad, can you...",
    splits it at the conversation boundary with proportional timestamps.
    """
    # Match: sentence-ending punctuation, optional quote/paren, whitespace,
    # then an English vocative/greeting (case-insensitive)
    _VOCATIVES = (
        r"Dad|Mom|Mum|Daddy|Mommy|Mummy|Sir|Ma['’]?am|Madam|Mister|Miss"
        r"|Doctor|Professor|Officer|Boss|Captain|Commander"
        r"|Bro|Dude|Man|Buddy|Pal|Mate"
        r"|Honey|Darling|Sweetie|Sweetheart|Baby|Babe"
        r"|Son|Dear|Love|Boy|Girl|Guys|Folks"
        r"|Mr\.|Mrs\.|Ms\.|Dr\."
        r"|Hello|Hi|Hey|Yo|Well|Okay|Ok|Alright"
        r"|Oh|Ah|Uh|Um|Eh|Wow|Oops|Ugh"
        r"|Yes|No|Yeah|Nope|Yep|Sure|Thanks|Please|Sorry"
        r"|Wait|Stop|Look|Listen|Really|Seriously|Help"
    )
    # Group 1: punctuation+space, Group 2: the vocative word
    _BOUNDARY_RE = re.compile(
        r"([.!?。！？]['\"」】)]?\s+)"
        r"(" + _VOCATIVES + r")"
        r"(?:[,!.\s]|$)",
        re.IGNORECASE,
    )

    result: List[SubtitleEntry] = []
    for entry in entries:
        text = entry.text
        matches = list(_BOUNDARY_RE.finditer(text))
        if not matches:
            result.append(entry)
            continue

        duration = entry.end_ms - entry.start_ms
        if duration <= 0:
            duration = 1000

        # Split at the vocative word boundary (after sentence-ending punctuation)
        split_positions = []
        for m in matches:
            split_positions.append(m.start(2))  # start of the vocative word

        # Build parts
        parts: List[str] = []
        last = 0
        for pos in split_positions:
            part = text[last:pos].strip()
            if part:
                parts.append(part)
            last = pos
        tail = text[last:].strip()
        if tail:
            parts.append(tail)

        if len(parts) <= 1:
            result.append(entry)
            continue

        total_chars = sum(len(p) for p in parts)
        if total_chars == 0:
            result.append(entry)
            continue

        start_ms = entry.start_ms
        for part in parts:
            part_duration = int(duration * len(part) / total_chars)
            end_ms = min(start_ms + part_duration, entry.end_ms)
            result.append(SubtitleEntry(
                index=0,
                start_ms=start_ms,
                end_ms=end_ms,
                text=part,
            ))
            start_ms = end_ms + 30

    return result


def merge_short_entries(
    entries: List[SubtitleEntry],
    max_chars: int,
    max_gap_ms: int = 500,
    detect_dialogue: bool = True,
) -> List[SubtitleEntry]:
    """
    Merge adjacent entries if their combined text fits within max_chars
    and the gap between them is <= max_gap_ms.

    When detect_dialogue=True, prevents merging across speaker/topic boundaries.
    """
    if len(entries) < 2:
        return entries

    merged: List[SubtitleEntry] = [entries[0]]

    for curr in entries[1:]:
        prev = merged[-1]
        gap = curr.start_ms - prev.end_ms
        combined = prev.text + " " + curr.text

        boundary = detect_dialogue and _is_dialogue_boundary(prev.text, curr.text)

        if gap <= max_gap_ms and len(combined) <= max_chars and not boundary:
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
    capitalize_line: bool = False,
    capitalize_sentence: bool = True,
    detect_dialogue: bool = True,
    normalize: bool = True,
) -> List[SubtitleEntry]:
    """
    Full processing pipeline:
    1. Split long entries to fit max_chars
    2. Optionally merge short adjacent entries
    3. Enforce single-line constraint
    4. Optionally apply English capitalization (en_only mode)
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
        result = merge_short_entries(result, max_chars, detect_dialogue=detect_dialogue)

    # Active dialogue splitting — scan merged entries for internal conversation boundaries
    if detect_dialogue:
        result = _split_at_dialogue_boundaries(result)

    # Text normalization: remove sentence punctuation, preserve contractions/compounds/titles
    if normalize:
        for e in result:
            e.text = _normalize_subtitle_text(e.text)

    # Capitalization (both modes — sentence-level takes priority)
    if mode == "en_only":
        # 1. Fix proper nouns and fixed forms (OK, I'm, Don't, Beijing, Monday…)
        for e in result:
            e.text = _capitalize_proper_nouns(e.text)
        # 2. Capitalize standalone 'i' → 'I'
        for e in result:
            e.text = _capitalize_pronoun_i(e.text)
        # 3. Sentence-level or per-line capitalization
        if capitalize_sentence:
            for i, e in enumerate(result):
                is_start = (i == 0) or _is_sentence_boundary(result[i - 1].text, e.text)
                e.text = _capitalize_entry_sentences(e.text, is_start)
        elif capitalize_line:
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


_SENTENCE_BOUNDARY_RE = re.compile(r'[.!?。]["\'」】)]?\s+([a-z])')


def _capitalize_sentence(text: str) -> str:
    """Capitalize the first letter of the text (used for sentence starts)."""
    if not text:
        return text

    for i, ch in enumerate(text):
        if ch.isalpha():
            return text[:i] + ch.upper() + text[i + 1:]
    return text


def _capitalize_entry_sentences(text: str, is_sentence_start: bool) -> str:
    """Apply sentence-level capitalization to a subtitle entry.

    - If is_sentence_start, capitalize the first alpha character.
    - Always capitalize letters after sentence-ending punctuation (.!?).
    """
    if not text:
        return text

    chars = list(text)

    # Capitalize first letter if this entry starts a new sentence
    if is_sentence_start:
        for i, ch in enumerate(chars):
            if ch.isalpha():
                chars[i] = ch.upper()
                break

    # Capitalize after sentence-ending punctuation within the entry
    for m in _SENTENCE_BOUNDARY_RE.finditer(text):
        idx = m.start(1)
        chars[idx] = chars[idx].upper()

    return ''.join(chars)


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def process_srt_content(srt_text: str, chinese_limit: int, english_limit: int | None, mode: str, capitalize_line: bool = False, capitalize_sentence: bool = True, detect_dialogue: bool = True, normalize: bool = True) -> str:
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
    result = merge_short_entries(result, max(chinese_limit, english_limit or chinese_limit), detect_dialogue=detect_dialogue)

    if detect_dialogue:
        result = _split_at_dialogue_boundaries(result)

    # Text normalization: remove sentence punctuation
    if normalize:
        for e in result:
            e.text = _normalize_subtitle_text(e.text)

    # Capitalization
    if mode == "en_only":
        for e in result:
            e.text = _capitalize_proper_nouns(e.text)
        for e in result:
            e.text = _capitalize_pronoun_i(e.text)
        if capitalize_sentence:
            for i, e in enumerate(result):
                is_start = (i == 0) or _is_sentence_boundary(result[i - 1].text, e.text)
                e.text = _capitalize_entry_sentences(e.text, is_start)
        elif capitalize_line:
            for e in result:
                e.text = _capitalize_sentence(e.text)

    for i, e in enumerate(result, 1):
        e.index = i

    return entries_to_srt(result)

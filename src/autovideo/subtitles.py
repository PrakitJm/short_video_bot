"""Thai subtitle lines (never split inside a word) and the .ass file built from them."""
import unicodedata
from bisect import bisect_left
from pathlib import Path

from pythainlp.tokenize import word_tokenize


def visible_len(s: str) -> int:
    # Thai vowel/tone marks (category Mn) sit above/below a letter and take no width.
    return sum(1 for c in s if unicodedata.category(c) != "Mn")


def split_lines(text: str, max_chars: int = 20) -> list[tuple[int, str]]:
    """Greedy-pack pythainlp words into lines; a space (Thai phrase break) always ends a line.
    Returns (char offset in text, line)."""
    lines, cur, cur_start, pos = [], "", 0, 0
    for tok in word_tokenize(text, engine="newmm", keep_whitespace=True):
        if cur.strip() and (tok.isspace() or visible_len((cur + tok).strip()) > max_chars):
            lines.append((cur_start, cur.strip()))
            cur = ""
        if not cur.strip():
            cur, cur_start = "", pos + len(tok) - len(tok.lstrip())
        cur += tok
        pos += len(tok)
    if cur.strip():
        lines.append((cur_start, cur.strip()))
    return lines


def timed_lines(text: str, words: list[dict], duration: float, max_chars: int = 20) -> list[tuple[float, float, str]]:
    """Give each line the start time of the first TTS word at or after it; it ends when the next line starts."""
    positions, starts, cursor = [], [], 0
    for w in words:
        i = text.find(w["text"], cursor)
        if i < 0:
            continue  # TTS normalised this word (e.g. digits); its neighbours still carry the timing
        positions.append(i)
        starts.append(w["start"])
        cursor = i + len(w["text"])
    lines = split_lines(text, max_chars)
    begins = []
    for off, _ in lines:
        k = bisect_left(positions, off)
        begins.append(starts[k] if k < len(starts) else (begins[-1] if begins else 0.0))
    begins[0] = 0.0
    ends = begins[1:] + [duration]
    return [(b, e, line) for b, e, (_, line) in zip(begins, ends, lines)]


def _ts(t: float) -> str:
    cs = round(t * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def write_ass(path: Path, events: list[tuple[float, float, str]], width: int, height: int, font: str,
              size: int = 90, align: int = 2) -> None:
    # align: ASS numpad position, 2 = bottom centre, 8 = top centre.
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,6,2,{align},60,60,{height // 3},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    body = "".join(
        f"Dialogue: 0,{_ts(s)},{_ts(e)},Default,,0,0,0,,{text.replace('{', '(').replace('}', ')')}\n"
        for s, e, text in events
    )
    path.write_text(header + body, encoding="utf-8")


def font_family(fonts_dir: Path) -> str:
    # "Kanit-Bold.ttf" -> "Kanit"; libass finds the file via the render step's fontsdir.
    ttf = sorted(fonts_dir.glob("*.ttf"))
    return ttf[0].stem.split("-")[0] if ttf else "Sans"

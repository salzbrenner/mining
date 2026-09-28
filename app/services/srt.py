"""SRT parsing — shared groundwork for the Scan feature (SPEC.md §4)."""

import re
from dataclasses import dataclass
from pathlib import Path

_TIME_RE = re.compile(r"(\d+):(\d{2}):(\d{2}),(\d{3})")
_BLOCK_RE = re.compile(
    r"\d+\s*\n(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n(.*?)(?=\n\s*\n|\Z)",
    re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class SrtLine:
    start_ms: int
    end_ms: int
    text: str

    @property
    def start_seconds(self) -> int:
        return self.start_ms // 1000

    @property
    def end_seconds(self) -> int:
        return self.end_ms // 1000

    @property
    def timestamp_label(self) -> str:
        total = self.start_seconds
        m, s = divmod(total, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _parse_time(s: str) -> int:
    h, mi, sec, ms = map(int, _TIME_RE.fullmatch(s).groups())
    return ((h * 60 + mi) * 60 + sec) * 1000 + ms


def parse(path: str | Path) -> list[SrtLine]:
    # utf-8-sig transparently strips a BOM if present, which some SRT
    # exports (including yt-dlp's on some tracks) include.
    text = Path(path).read_text(encoding="utf-8-sig")
    result = []
    for block in _BLOCK_RE.finditer(text):
        start, end, body = block.groups()
        clean = _TAG_RE.sub("", body).strip()
        clean = "\n".join(line.strip() for line in clean.splitlines() if line.strip())
        if clean:
            result.append(
                SrtLine(
                    start_ms=_parse_time(start), end_ms=_parse_time(end), text=clean
                )
            )
    return result

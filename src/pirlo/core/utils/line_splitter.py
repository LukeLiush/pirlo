# src/pirlo/core/utils/line_splitter.py
from __future__ import annotations

import re

_LINE_BREAK = re.compile(r"\r\n|\r|\n")

CONTINUATION_MARK = " …"


class LineSplitter:
    """Incrementally splits streamed text into lines on \\n, \\r\\n, and bare \\r.

    Bare \\r counts as a break so progress bars that redraw in place still surface
    as lines. Lines longer than max_len are cut into pieces ending in CONTINUATION_MARK.
    """

    def __init__(self, max_len: int = 8192) -> None:
        self._max_len: int = max_len
        self._buffer: str = ""

    def feed(self, text: str) -> list[str]:
        """Accepts the next chunk of text and returns every line it completed."""
        data = self._buffer + text
        # A trailing \r may be the first half of a \r\n split across chunks; hold it back
        held_cr = data.endswith("\r")
        if held_cr:
            data = data[:-1]
        parts = _LINE_BREAK.split(data)
        remainder = parts.pop()
        lines: list[str] = []
        for part in parts:
            lines.extend(self._cap(part))
        while len(remainder) > self._max_len:
            lines.append(remainder[: self._max_len] + CONTINUATION_MARK)
            remainder = remainder[self._max_len :]
        self._buffer = remainder + ("\r" if held_cr else "")
        return lines

    def flush(self, text: str = "") -> list[str]:
        """Returns the remaining lines at end of stream, including a final unterminated line."""
        lines = self.feed(text)
        tail = self._buffer.rstrip("\r")
        self._buffer = ""
        if tail:
            lines.extend(self._cap(tail))
        return lines

    def _cap(self, line: str) -> list[str]:
        pieces: list[str] = []
        while len(line) > self._max_len:
            pieces.append(line[: self._max_len] + CONTINUATION_MARK)
            line = line[self._max_len :]
        pieces.append(line)
        return pieces

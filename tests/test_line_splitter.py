# tests/test_line_splitter.py
from __future__ import annotations

from pirlo.core.utils.line_splitter import CONTINUATION_MARK, LineSplitter


def test_splits_on_newlines_and_keeps_partial_line_buffered():
    s = LineSplitter()
    assert s.feed("a\nb\npar") == ["a", "b"]
    assert s.feed("tial\n") == ["partial"]


def test_crlf_split_across_chunks_is_one_break():
    s = LineSplitter()
    assert s.feed("a\r") == []
    assert s.feed("\nb\n") == ["a", "b"]


def test_bare_carriage_return_surfaces_progress_updates():
    s = LineSplitter()
    assert s.feed("10%\r50%\r") == ["10%"]
    assert s.flush("100%") == ["50%", "100%"]


def test_flush_returns_unterminated_last_line():
    s = LineSplitter()
    assert s.feed("done") == []
    assert s.flush() == ["done"]
    assert s.flush() == []


def test_empty_lines_are_preserved():
    assert LineSplitter().feed("a\n\nb\n") == ["a", "", "b"]


def test_overlong_line_is_cut_and_marked_without_losing_content():
    s = LineSplitter(max_len=10)
    lines = s.feed("x" * 25) + s.flush()
    assert lines == [
        "x" * 10 + CONTINUATION_MARK,
        "x" * 10 + CONTINUATION_MARK,
        "x" * 5,
    ]


def test_overlong_line_arriving_whole_is_cut():
    s = LineSplitter(max_len=4)
    assert s.feed("abcdefghij\n") == [
        "abcd" + CONTINUATION_MARK,
        "efgh" + CONTINUATION_MARK,
        "ij",
    ]

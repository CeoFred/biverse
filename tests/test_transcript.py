"""Pasted and imported transcripts, and clearing the transcript."""

from __future__ import annotations

import pytest

from biverse.summary import SermonLog, TranscriptError, parse_transcript, references_in, summarise

SRT = ("1\n00:00:01,000 --> 00:00:04,000\nTurn with me to John chapter 3 verse 16\n\n"
       "2\n00:00:05,000 --> 00:00:09,500\nFor God so loved the world\n\n"
       "3\n00:00:09,500 --> 00:00:12,000\nFor God so loved the world\n")
VTT = "WEBVTT\n\n00:01.000 --> 00:04.000\n<v Pastor>Hello church\n\n01:05.000 --> 01:07.000\nRomans 8 28\n"


def test_srt():
    assert parse_transcript(SRT) == [(1.0, "Turn with me to John chapter 3 verse 16"),
                                     (5.0, "For God so loved the world")]


def test_webvtt():
    assert parse_transcript(VTT) == [(1.0, "Hello church"), (65.0, "Romans 8 28")]


def test_plain_text_with_biverse_times():
    lines = parse_transcript("10:30:01 Good morning church\n10:30:09 open to Romans 8 verse 28\nand read\n")
    assert lines == [(0.0, "Good morning church"), (8.0, "open to Romans 8 verse 28 and read")]


def test_plain_text_without_times_gets_estimated_times():
    lines = parse_transcript("﻿# Notes\nGood morning church.\n\nLet us read Psalm 23 together.\n")
    assert [t for t, _ in lines] == [0.0, 1.2]
    assert lines[1][1] == "Let us read Psalm 23 together."


def test_sermon_record_json():
    log = SermonLog(100.0)
    log.add_line("Grace and peace", when=110.0)
    import json
    assert parse_transcript(json.dumps(log.to_dict())) == [(10.0, "Grace and peace")]


@pytest.mark.parametrize("text, why", [
    ("", "no text"),
    ("   \n ", "no text"),
    ("{\\rtf1\\ansi hello}", "RTF"),
    ("<!DOCTYPE html><html><body>hi</body></html>", "HTML"),
    ("<div>hello</div>", "HTML"),
    ('{"title": "x"}', "not a Biverse sermon record"),
    ("12 34 56", "no words"),
    ("ab\x00cd", "binary"),
    ("WEBVTT\n\n00:01.000 --> 00:02.000\n\n", "no text"),
])
def test_unaccepted_formats_are_refused(text, why):
    with pytest.raises(TranscriptError) as exc:
        parse_transcript(text)
    assert why.lower() in str(exc.value).lower()


def test_references_are_found_in_pasted_text():
    refs = references_in(parse_transcript(SRT))
    assert refs == [(1.0, "John 3:16")]


def test_clear_and_add_lines():
    log = SermonLog(0.0)
    log.add_line("first", when=10.0)
    log.add_ref("John 3:16", when=10.0)
    log.clear()
    assert log.empty() and log.refs == [] and log.duration == 0
    assert summarise(log)["words"] == 0
    log.add_lines([(0.0, "one"), (30.0, "two")], [(30.0, "Romans 8:28")])
    log.add_lines([(0.0, "three")])
    assert log.lines == [(0.0, "one"), (30.0, "two"), (35.0, "three")]
    assert log.refs == [(30.0, "Romans 8:28")]
    assert log.duration == 35.0

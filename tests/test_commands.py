from __future__ import annotations

import pytest

from biverse import commands as C
from biverse.commands import parse_command


@pytest.mark.parametrize("text,cmd", [
    ("next verse", C.NEXT_VERSE),
    ("Next verse, please.", C.NEXT_VERSE),
    ("let us read the next verse together", C.NEXT_VERSE),
    ("and the following verse says", C.NEXT_VERSE),
    ("next", C.NEXT_VERSE),
    ("Next.", C.NEXT_VERSE),
    ("okay next please", C.NEXT_VERSE),
    ("go back", C.PREV_VERSE),
    ("Go back.", C.PREV_VERSE),
    ("let's go back", C.PREV_VERSE),
    ("previous verse", C.PREV_VERSE),
    ("go back a verse", C.PREV_VERSE),
    ("the verse before that", C.PREV_VERSE),
    ("next chapter", C.NEXT_CHAPTER),
    ("move to the next chapter", C.NEXT_CHAPTER),
    ("previous chapter", C.PREV_CHAPTER),
    ("go back a chapter", C.PREV_CHAPTER),
])
def test_commands(text, cmd):
    assert parse_command(text) == cmd


@pytest.mark.parametrize("text", [
    "next week we will have a retreat",
    "go back to Egypt and see",
    "the next thing I want to tell you",
    "who is next in line for the choir",
    "he looked back at the city",
    "back in the days of Noah",
    "",
    "John 3:16",
])
def test_not_commands(text):
    assert parse_command(text) is None

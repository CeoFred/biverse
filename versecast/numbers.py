"""Text normalisation for the reference parser.

``normalise(text, mode)`` lowercases, strips punctuation and turns number
words into digit tokens, returning a list of tokens.

Rules (see DECISIONS.md / the spec §5.1):
  * "twenty eight" -> 28, "one hundred and nineteen" / "a hundred nineteen" -> 119
  * adjacent independent numbers are NOT merged: "three sixteen" -> 3 16,
    "one nineteen" -> 1 19 (the parser's Psalm fallback handles 119).
  * first/1st/one/i -> 1, second/2nd/two/ii -> 2, third/3rd/three/iii -> 3,
    but ordinals and roman numerals only before a numbered book name.
  * typed mode: ``:`` and ``.`` between digits become ``:`` tokens (chapter /
    verse separator); ``-`` ``–`` ``—`` become "to"; letters and digits are
    split apart ("jn3:16" -> jn 3 : 16, "1cor" -> 1 cor).
"""

from __future__ import annotations

import re

from .books import NUMBERED_BASE_TOKENS

UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
}
TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
# Homophones the recogniser sometimes produces for numbers.
HOMOPHONES = {"won": "one"}

ORDINAL_PREFIX = {
    "first": "1", "1st": "1", "i": "1", "one": "1", "1": "1",
    "second": "2", "2nd": "2", "ii": "2", "two": "2", "2": "2",
    "third": "3", "3rd": "3", "iii": "3", "three": "3", "3": "3",
}

_DASHES = u"-–—"


def _read_small(tokens, i):
    """Read a number 0..99 made of words starting at ``i``."""
    n = len(tokens)
    t = tokens[i]
    if t in TENS:
        value = TENS[t]
        if i + 1 < n and tokens[i + 1] in UNITS and UNITS[tokens[i + 1]] > 0:
            return value + UNITS[tokens[i + 1]], i + 2
        return value, i + 1
    if t in TEENS:
        return TEENS[t], i + 1
    if t in UNITS:
        return UNITS[t], i + 1
    return None, i


def _read_number(tokens, i):
    n = len(tokens)
    t = tokens[i]
    hundreds = None
    j = i
    if t == "hundred":
        hundreds, j = 1, i + 1
    elif i + 1 < n and tokens[i + 1] == "hundred" and (t == "a" or (t in UNITS and UNITS[t] > 0)):
        hundreds, j = (1 if t == "a" else UNITS[t]), i + 2
    if hundreds is not None:
        value = hundreds * 100
        k = j
        if k < n and tokens[k] == "and":
            k += 1
        if k < n:
            rest, k2 = _read_small(tokens, k)
            if rest is not None and rest > 0:
                return value + rest, k2
        return value, j
    return _read_small(tokens, i)


def words_to_numbers(tokens):
    """Replace runs of number words with digit tokens (see module docs)."""
    out = []
    i = 0
    n = len(tokens)
    while i < n:
        # Ordinal / roman prefix immediately before a numbered book.
        tok = tokens[i]
        if tok in ORDINAL_PREFIX and i + 1 < n and tokens[i + 1] in NUMBERED_BASE_TOKENS:
            out.append(ORDINAL_PREFIX[tok])
            i += 1
            continue
        value, j = _read_number(tokens, i)
        if value is not None:
            out.append(str(value))
            i = j
        else:
            out.append(tok)
            i += 1
    return out


def _clean_typed(text):
    text = re.sub(r"(\d)\s*[:.]\s*(?=\d)", r"\1 : ", text)
    # "twenty-eight": a hyphen between letters is just a word joiner.
    text = re.sub(u"(?<=[a-z])[%s](?=[a-z])" % _DASHES, " ", text)
    text = re.sub(u"[%s]" % _DASHES, " to ", text)
    # 1st/2nd/3rd stay whole, everything else splits letters from digits.
    text = re.sub(r"(?<=[a-z])(?=\d)", " ", text)
    text = re.sub(r"(?<=\d)(?!(?:st|nd|rd|th)\b)(?=[a-z])", " ", text)
    return text


def tokenize(text, mode="speech"):
    text = (text or "").lower().replace(u"’", "'")
    if mode == "typed":
        text = _clean_typed(text)
    text = text.replace("'", "")
    # Keep ":" tokens (typed separator); drop everything else that is not a word.
    text = re.sub(r"[^a-z0-9:\s]", " ", text)
    return text.split()


def normalise(text, mode="speech"):
    tokens = tokenize(text, mode)
    tokens = [HOMOPHONES.get(t, t) for t in tokens]
    return words_to_numbers(tokens)


def number_to_words(n):
    """Spell 0..999 the way a speech recogniser would ("one hundred nineteen")."""
    names = {v: k for k, v in UNITS.items()}
    names.update({v: k for k, v in TEENS.items()})
    names.update({v: k for k, v in TENS.items() if k != "fourty"})
    if n < 20:
        return names[n]
    if n < 100:
        tens, unit = divmod(n, 10)
        return names[tens * 10] + ("" if unit == 0 else " " + names[unit])
    hundreds, rest = divmod(n, 100)
    words = names[hundreds] + " hundred"
    if rest:
        words += " " + number_to_words(rest)
    return words

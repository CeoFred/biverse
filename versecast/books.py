"""The 66 books of the Protestant canon.

Each book has:
  * ``number`` – 1..66 in canonical order (matches the database)
  * ``code``   – USFM-style three-character code
  * ``name``   – display name
  * ``ref_name`` – name used in a reference label ("Psalm 23:1")
  * ``spoken`` – lowercase names as a speech recogniser would produce them
                 (full names plus common mis-transcriptions). Valid in both
                 speech and typed mode.
  * ``typed``  – abbreviations, valid in typed mode only (words like "is",
                 "am", "ex" and "song" occur in ordinary speech).
  * ``strict`` – the bare one-word name is also an everyday word or name. In
                 speech mode it only counts when followed by chapter *and*
                 verse, or by the explicit word "chapter".

Numbered books are listed with a digit prefix ("1 corinthians"); the number
normaliser turns "first", "one", "i", "1st" into that digit beforehand.
"""

from __future__ import annotations



class Book(object):
    __slots__ = ("number", "code", "name", "ref_name", "spoken", "typed", "strict")

    def __init__(self, number, code, name, spoken, typed, strict=False, ref_name=None):
        self.number = number
        self.code = code
        self.name = name
        self.ref_name = ref_name or name
        self.spoken = tuple(spoken)
        self.typed = tuple(typed)
        self.strict = strict

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Book(%d, %s)" % (self.number, self.name)


# Bases for numbered books: spoken variants and typed abbreviations.
_NUMBERED_BASES = {
    "samuel": (("samuel", "samuels"), ("sam", "sa", "sm", "sml")),
    "kings": (("kings", "king"), ("kgs", "ki", "kin", "kg")),
    "chronicles": (("chronicles", "chronicle", "chronicals"), ("chr", "chron", "ch", "chro")),
    "corinthians": (("corinthians", "corinthian", "corinthian's"), ("cor", "co", "corin")),
    "thessalonians": (("thessalonians", "thessalonian", "thessalonica"), ("thess", "thes", "th", "ths")),
    "timothy": (("timothy", "timothy's"), ("tim", "ti", "tm")),
    "peter": (("peter",), ("pet", "pe", "pt", "ptr")),
    "john": (("john",), ("jn", "jhn", "joh", "jo")),
}

#: Every token that can follow a numbered-book prefix ("1", "first", "i" ...).
NUMBERED_BASE_TOKENS = frozenset(
    w.split()[0] for spoken, typed in _NUMBERED_BASES.values() for w in spoken + typed
)


def _numbered(n, base):
    spoken, typed = _NUMBERED_BASES[base]
    return (
        tuple("%d %s" % (n, s) for s in spoken),
        tuple("%d %s" % (n, t) for t in typed),
    )


def _nb(number, code, name, n, base):
    spoken, typed = _numbered(n, base)
    return Book(number, code, name, spoken, typed)


BOOKS = [
    Book(1, "GEN", "Genesis", ("genesis", "genesys", "genisis"), ("gen", "ge", "gn")),
    Book(2, "EXO", "Exodus", ("exodus", "exodos"), ("exod", "exo", "ex", "exd")),
    Book(3, "LEV", "Leviticus", ("leviticus", "leviticus's"), ("lev", "le", "lv")),
    Book(4, "NUM", "Numbers", ("numbers",), ("num", "nu", "nm", "nb"), strict=True),
    Book(5, "DEU", "Deuteronomy", ("deuteronomy", "deuteronomie"), ("deut", "deu", "de", "dt")),
    Book(6, "JOS", "Joshua", ("joshua",), ("josh", "jos", "jsh")),
    Book(7, "JDG", "Judges", ("judges",), ("judg", "jdg", "jg", "jdgs"), strict=True),
    Book(8, "RUT", "Ruth", ("ruth",), ("rth", "ru"), strict=True),
    _nb(9, "1SA", "1 Samuel", 1, "samuel"),
    _nb(10, "2SA", "2 Samuel", 2, "samuel"),
    _nb(11, "1KI", "1 Kings", 1, "kings"),
    _nb(12, "2KI", "2 Kings", 2, "kings"),
    _nb(13, "1CH", "1 Chronicles", 1, "chronicles"),
    _nb(14, "2CH", "2 Chronicles", 2, "chronicles"),
    Book(15, "EZR", "Ezra", ("ezra",), ("ezr",)),
    Book(16, "NEH", "Nehemiah", ("nehemiah", "nehemia"), ("neh", "ne")),
    Book(17, "EST", "Esther", ("esther",), ("esth", "est", "es")),
    Book(18, "JOB", "Job", ("job",), ("jb",), strict=True),
    Book(19, "PSA", "Psalms", ("psalm", "psalms", "salm", "salms", "the psalms", "palms", "psalter"),
         ("ps", "psa", "pss", "psm", "pslm"), ref_name="Psalm"),
    Book(20, "PRO", "Proverbs", ("proverbs", "proverb"), ("prov", "pro", "prv", "pr")),
    Book(21, "ECC", "Ecclesiastes",
         ("ecclesiastes", "ecclesiastics", "ecclesiastic", "ecclesiastes's", "ecclesiasties"),
         ("eccl", "ecc", "eccles", "ec", "qoh")),
    Book(22, "SNG", "Song of Solomon",
         ("song of solomon", "song of songs", "songs of solomon", "songs of songs",
          "song of soloman", "song of salomon", "canticles", "psalm of solomon", "psalms of solomon"),
         ("song", "sos", "sng", "ss", "cant", "song of sol")),
    Book(23, "ISA", "Isaiah", ("isaiah", "isaiahs", "isaiah's", "isaya"), ("isa", "is")),
    Book(24, "JER", "Jeremiah", ("jeremiah", "jeremiahs"), ("jer", "je", "jr")),
    Book(25, "LAM", "Lamentations", ("lamentations", "lamentation"), ("lam", "la")),
    Book(26, "EZK", "Ezekiel", ("ezekiel", "ezekial", "ezekiel's"), ("ezek", "eze", "ezk")),
    Book(27, "DAN", "Daniel", ("daniel",), ("dan", "da", "dn")),
    Book(28, "HOS", "Hosea", ("hosea", "hosier"), ("hos", "ho")),
    Book(29, "JOL", "Joel", ("joel",), ("joe", "jl"), strict=True),
    Book(30, "AMO", "Amos", ("amos",), ("am", "amo"), strict=True),
    Book(31, "OBA", "Obadiah", ("obadiah", "obediah"), ("obad", "ob", "oba")),
    Book(32, "JON", "Jonah", ("jonah",), ("jnh", "jon")),
    Book(33, "MIC", "Micah", ("micah",), ("mic", "mc")),
    Book(34, "NAM", "Nahum", ("nahum",), ("nah", "na")),
    Book(35, "HAB", "Habakkuk", ("habakkuk", "habakuk", "habbakuk", "habakkuk's", "habacuc"), ("hab", "hb")),
    Book(36, "ZEP", "Zephaniah", ("zephaniah", "zephania"), ("zeph", "zep", "zp")),
    Book(37, "HAG", "Haggai", ("haggai", "hagai"), ("hag", "hg")),
    Book(38, "ZEC", "Zechariah", ("zechariah", "zachariah", "zacharias", "zecharia", "zakaria"), ("zech", "zec", "zc")),
    Book(39, "MAL", "Malachi", ("malachi", "malachai", "malika"), ("mal", "ml")),
    Book(40, "MAT", "Matthew", ("matthew", "matthews", "mathew"), ("matt", "mat", "mt")),
    Book(41, "MRK", "Mark", ("mark",), ("mrk", "mk", "mr", "mar"), strict=True),
    Book(42, "LUK", "Luke", ("luke",), ("luk", "lk", "lu")),
    # "jog": small-model mis-hearings of "john" (strict, so only with chapter + verse)
    Book(43, "JHN", "John", ("john", "jog", "johns"), ("jn", "jhn", "joh"), strict=True),
    Book(44, "ACT", "Acts", ("acts", "acts of the apostles", "the acts of the apostles"), ("act", "ac"), strict=True),
    Book(45, "ROM", "Romans", ("romans", "roman"), ("rom", "ro", "rm")),
    _nb(46, "1CO", "1 Corinthians", 1, "corinthians"),
    _nb(47, "2CO", "2 Corinthians", 2, "corinthians"),
    Book(48, "GAL", "Galatians", ("galatians", "galatian", "galicians"), ("gal", "ga")),
    Book(49, "EPH", "Ephesians", ("ephesians", "ephesian"), ("eph", "ephes")),
    Book(50, "PHP", "Philippians",
         ("philippians", "philippines", "filipinos", "filipino", "philippine", "phillipians", "filipians",
          "philippians's", "philadelphians"),
         ("phil", "php", "pp", "phi")),
    Book(51, "COL", "Colossians", ("colossians", "colossian", "collosians"), ("col",)),
    _nb(52, "1TH", "1 Thessalonians", 1, "thessalonians"),
    _nb(53, "2TH", "2 Thessalonians", 2, "thessalonians"),
    _nb(54, "1TI", "1 Timothy", 1, "timothy"),
    _nb(55, "2TI", "2 Timothy", 2, "timothy"),
    Book(56, "TIT", "Titus", ("titus",), ("tit",), strict=True),
    Book(57, "PHM", "Philemon", ("philemon", "philemon's"), ("philem", "phm", "pm")),
    Book(58, "HEB", "Hebrews", ("hebrews", "hebrew"), ("heb",)),
    Book(59, "JAS", "James", ("james",), ("jas", "jm", "jms"), strict=True),
    _nb(60, "1PE", "1 Peter", 1, "peter"),
    _nb(61, "2PE", "2 Peter", 2, "peter"),
    _nb(62, "1JN", "1 John", 1, "john"),
    _nb(63, "2JN", "2 John", 2, "john"),
    _nb(64, "3JN", "3 John", 3, "john"),
    Book(65, "JUD", "Jude", ("jude",), ("jud", "jd"), strict=True),
    Book(66, "REV", "Revelation", ("revelation", "revelations", "the revelation", "book of revelation"),
         ("rev", "re", "rv", "apoc")),
]

BY_NUMBER = {b.number: b for b in BOOKS}
BY_CODE = {b.code: b for b in BOOKS}


def _key(name):
    return tuple(name.replace("'", "").split())


# Mis-hearings by the small Vosk model that are also ordinary words. They count
# only like strict names: followed by chapter AND verse, or by "chapter".
# Collected by synthesising "turn to <book> chapter four" in several voices.
MISHEARD_STRICT = {
    19: ("sam",),                         # psalm
    42: ("look",),                        # luke
    48: ("relations",),                   # galatians
    49: ("evasions",),                    # ephesians
    51: ("collections", "collisions"),    # colossians
}


def _build_index(include_typed):
    """Map token tuples to (book, is_strict_name)."""
    index = {}
    for number, names in MISHEARD_STRICT.items():
        for name in names:
            index[_key(name)] = (BY_NUMBER[number], True)
    for book in BOOKS:
        names = list(book.spoken)
        # Display names are always valid ("1 samuel", "song of solomon").
        names.append(book.name.lower())
        for name in names:
            key = _key(name)
            index[key] = (book, book.strict and len(key) == 1)
        if include_typed:
            for name in book.typed:
                key = _key(name)
                # Never let an abbreviation shadow a full name of another book.
                if key not in index:
                    index[key] = (book, False)
    return index


SPOKEN_INDEX = _build_index(include_typed=False)
TYPED_INDEX = _build_index(include_typed=True)
MAX_NAME_TOKENS = max(len(k) for k in TYPED_INDEX)


def match_book(tokens, i, typed=False):
    """Longest book name starting at ``tokens[i]``.

    Returns ``(book, n_tokens, is_strict_name)`` or ``None``.
    """
    index = TYPED_INDEX if typed else SPOKEN_INDEX
    for length in range(min(MAX_NAME_TOKENS, len(tokens) - i), 0, -1):
        hit = index.get(tuple(tokens[i:i + length]))
        if hit is not None:
            return hit[0], length, hit[1]
    return None


def get(number):
    return BY_NUMBER[number]


# -- fuzzy matching (speech only) -------------------------------------------------

_FUZZY_NAMES = sorted({("".join(k), book) for k, (book, _strict) in SPOKEN_INDEX.items()
                       if not any(t.isdigit() for t in k) and len("".join(k)) >= 4},
                      key=lambda x: x[0])
_COMMON = frozenset("""the and with turn me to that this there their these those then than them they what when
where which while who whom whose will would shall should could have has had was were are is be been being
for from into onto upon over under about after before chapter verse verses please open read let us our
your you yours his her its it not now nation nations matter mother father brother sister people""".split())


def fuzzy_match_book(tokens, i, min_ratio=0.75, margin=0.08):
    """A recogniser's near-miss spelling of a book name at ``tokens[i]``.

    Neural recognisers often get the shape of a rare name almost right
    ("Habakku", "Nebamiah", "Pileman", "Zephynia"). Compares 1-3 joined tokens
    with every spoken name and returns ``(book, n_tokens)`` when one name is
    clearly the closest. Only called by the parser when a chapter-and-verse
    structure follows, so ordinary words cannot become books.
    """
    import difflib
    best = None
    for length in (3, 2, 1):
        if i + length > len(tokens):
            continue
        parts = tokens[i:i + length]
        if any(not p.isalpha() for p in parts) or parts[0] in _COMMON:
            continue
        cand = "".join(parts)
        if len(cand) < 5:  # "Ruke" could be Ruth or Luke: too short to guess
            continue
        scores = []
        for name, book in _FUZZY_NAMES:
            if abs(len(name) - len(cand)) > max(3, len(name) // 3):
                continue
            r = difflib.SequenceMatcher(None, cand, name).ratio()
            scores.append((r, book.number, book, length))
        if not scores:
            continue
        scores.sort(key=lambda x: -x[0])
        top = scores[0]
        runner = next((s for s in scores[1:] if s[1] != top[1]), None)
        if top[0] >= min_ratio and (runner is None or top[0] - runner[0] >= margin):
            if best is None or top[0] > best[0]:
                best = top
    if best is None:
        return None
    return best[2], best[3]

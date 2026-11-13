from __future__ import annotations

import pytest

from versecast import books
from versecast.numbers import normalise, number_to_words
from versecast.parser import parse, parse_typed


def labels(text, mode="speech", **kw):
    return [r.label() for r in parse(text, mode=mode, **kw)]


# ---------------------------------------------------------------------------
# number words


@pytest.mark.parametrize("n", range(0, 177))
def test_number_words(n):
    assert normalise(number_to_words(n)) == [str(n)]


@pytest.mark.parametrize("text,expected", [
    ("twenty eight", ["28"]),
    ("one hundred and nineteen", ["119"]),
    ("a hundred nineteen", ["119"]),
    ("a hundred and fifty", ["150"]),
    ("hundred and nineteen", ["119"]),
    ("three sixteen", ["3", "16"]),
    ("one nineteen", ["1", "19"]),
    ("twenty twenty", ["20", "20"]),
    ("forty thirty one", ["40", "31"]),
    ("one hundred and the", ["100", "and", "the"]),
    ("first corinthians", ["1", "corinthians"]),
    ("second kings", ["2", "kings"]),
    ("third john", ["3", "john"]),
    ("i samuel", ["1", "samuel"]),
    ("ii samuel", ["2", "samuel"]),
    ("iii john", ["3", "john"]),
    ("i think so", ["i", "think", "so"]),
    ("first we pray", ["first", "we", "pray"]),
    ("won", ["1"]),
])
def test_normalise_speech(text, expected):
    assert normalise(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("jn3:16", ["jn", "3", ":", "16"]),
    ("1cor 13:4-7", ["1", "cor", "13", ":", "4", "to", "7"]),
    ("1st john 4.8", ["1", "john", "4", ":", "8"]),
    (u"rom 8:28–30", ["rom", "8", ":", "28", "to", "30"]),
    ("twenty-eight", ["28"]),
    ("John 3:16!", ["john", "3", ":", "16"]),
])
def test_normalise_typed(text, expected):
    assert normalise(text, "typed") == expected


# ---------------------------------------------------------------------------
# every spoken name of every book


def _spoken_cases():
    for book in books.BOOKS:
        for name in book.spoken + (book.name.lower(),):
            yield pytest.param(book.number, name, id="%s-%s" % (book.code, name))


@pytest.mark.parametrize("number,name", list(_spoken_cases()))
def test_every_spoken_name(number, name):
    refs = parse("and now %s chapter one verse one please" % name)
    assert len(refs) == 1, refs
    r = refs[0]
    assert (r.book, r.chapter, r.verse_start, r.verse_end) == (number, 1, 1, 1)


@pytest.mark.parametrize("book", books.BOOKS, ids=lambda b: b.code)
def test_every_book_number_form(book):
    # "<book> <c> <v>" in words, with the last chapter and verse of the book
    from versecast.versification import VERSE_COUNTS
    counts = VERSE_COUNTS[book.number - 1]
    c = len(counts)
    v = counts[-1]
    if c == 1:
        text = "%s chapter one verse %s" % (book.name.lower(), number_to_words(v))
    else:
        text = "%s %s %s" % (book.name.lower(), number_to_words(c), number_to_words(v))
    refs = parse(text)
    assert [(r.book, r.chapter, r.verse_start) for r in refs] == [(book.number, c, v)], text


@pytest.mark.parametrize("book", books.BOOKS, ids=lambda b: b.code)
def test_every_book_typed_abbreviations(book):
    for abbr in book.typed:
        ref = parse_typed("%s 1:1" % abbr)
        assert ref is not None and ref.book == book.number, abbr


def test_names_are_unambiguous():
    seen = {}
    for book in books.BOOKS:
        for name in set(book.spoken + (book.name.lower(),)):
            key = tuple(name.replace("'", "").split())
            assert seen.setdefault(key, book.number) == book.number, name


def test_sixty_six_books():
    assert len(books.BOOKS) == 66
    assert [b.number for b in books.BOOKS] == list(range(1, 67))
    assert len({b.code for b in books.BOOKS}) == 66


# ---------------------------------------------------------------------------
# patterns from §5.3


@pytest.mark.parametrize("text,expected", [
    ("john three sixteen", ["John 3:16"]),
    ("john chapter three verse sixteen", ["John 3:16"]),
    ("john three verse sixteen", ["John 3:16"]),
    ("john three colon sixteen", ["John 3:16"]),
    ("john chapter three and verse sixteen", ["John 3:16"]),
    ("john three sixteen to eighteen", ["John 3:16-18"]),
    ("john three sixteen through eighteen", ["John 3:16-18"]),
    ("john three sixteen thru eighteen", ["John 3:16-18"]),
    ("john three sixteen till eighteen", ["John 3:16-18"]),
    ("john three sixteen until eighteen", ["John 3:16-18"]),
    ("john chapter three verses sixteen to eighteen", ["John 3:16-18"]),
    ("john chapter three verses sixteen to verse eighteen", ["John 3:16-18"]),
    ("john chapter three", ["John 3"]),
    ("romans eight", ["Romans 8"]),
    ("psalm twenty three", ["Psalm 23"]),
    ("the book of john chapter three verse sixteen", ["John 3:16"]),
    ("the book of romans chapter eight verse twenty eight", ["Romans 8:28"]),
    ("romans eight twenty eight", ["Romans 8:28"]),
    ("genesis one one", ["Genesis 1:1"]),
    ("revelation twenty two twenty one", ["Revelation 22:21"]),
    ("revelations twenty two twenty one", ["Revelation 22:21"]),
    ("matthew twenty eight nineteen", ["Matthew 28:19"]),
    ("isaiah forty thirty one", ["Isaiah 40:31"]),
    ("isaiah fifty three five", ["Isaiah 53:5"]),
    ("acts two thirty eight", ["Acts 2:38"]),
    ("acts of the apostles two thirty eight", ["Acts 2:38"]),
    ("song of solomon two four", ["Song of Solomon 2:4"]),
    ("song of songs two four", ["Song of Solomon 2:4"]),
    ("philippines four thirteen", ["Philippians 4:13"]),
    ("filipinos four thirteen", ["Philippians 4:13"]),
    ("ecclesiastics three one", ["Ecclesiastes 3:1"]),
    ("habakuk two four", ["Habakkuk 2:4"]),
    ("proverbs three five to six", ["Proverbs 3:5-6"]),
    ("lamentations three twenty two", ["Lamentations 3:22"]),
    ("hebrews eleven one", ["Hebrews 11:1"]),
    # mis-transcriptions seen from the small Vosk model in CI
    ("please turn in your bible to jog chapter three were sixteen", ["John 3:16"]),
    ("romans eight versus twenty eight", ["Romans 8:28"]),
    ("we were sixteen people", []),
    # number homophones in the chapter position
    ("that genesis to eighteen is not marriage", ["Genesis 2:18"]),
    ("genesis too verse eighteen", ["Genesis 2:18"]),
    ("philippians for thirteen says i can do all things", ["Philippians 4:13"]),
    ("romans eight for we know", ["Romans 8"]),          # "for" after a chapter is not a verse
    ("john three sixteen to eighteen", ["John 3:16-18"]),  # ranges unaffected
    ("turn to genesis to read", []),
    # small-model mis-hearings of book names it does not know
    ("turn to zakaria four six", ["Zechariah 4:6"]),
    ("malika three ten", ["Malachi 3:10"]),
    ("philadelphians four thirteen", ["Philippians 4:13"]),
    ("galicians two twenty", ["Galatians 2:20"]),
    ("collections three twenty three", ["Colossians 3:23"]),
    ("look two ten", ["Luke 2:10"]),
    ("sam twenty three one", ["Psalm 23:1"]),
    # ...which are ordinary words, so they need chapter and verse
    ("look two people came", []),
    ("our collections three times a year", []),
    ("sam twenty three", []),
    # neural recognisers write digits and colons
    ("That is Genesis 2:18.", ["Genesis 2:18"]),
    ("Turn to John 3:16-18, please.", ["John 3:16-18"]),
    ("Philippians 413 says I can do all things", ["Philippians 4:13"]),
    ("Romans 828", ["Romans 8:28"]),
    ("First Corinthians 13:4 to 7", ["1 Corinthians 13:4-7"]),
    # merged chapter+verse digits, also for strict books ("Job 120" = Job 1:20)...
    ("Job 120", ["Job 1:20"]),
    ("job one hundred twenty", ["Job 1:20"]),
    ("John 316", ["John 3:16"]),
    ("Mark 1015", ["Mark 10:15"]),
    # ...but not when a quantity follows
    ("my job 365 days a year", []),
    ("mark 120 people came", []),
    ("acts 210 times", []),
    # Parakeet writes "habakkuk two four" as "Habakkuk 2-4"; a dash is a range only after C:V
    ("and then Habakkuk 2-4, and Haggai 2-9.", ["Habakkuk 2:4", "Haggai 2:9"]),
    ("Romans 8 verses 28-30", ["Romans 8:28-30"]),
    ("we met 2-3 times", []),
    # near-miss spellings from neural recognisers, only with chapter-and-verse structure
    ("Turn with me to Habakku chapter 3 verse 5.", ["Habakkuk 3:5"]),
    ("Turn with me to Nebamiah 3 verse 5.", ["Nehemiah 3:5"]),
    ("Turn with me to Zephynia chapter 3 verse 5.", ["Zephaniah 3:5"]),
    ("Turn with me to Pileman chapter 1 verse 5.", ["Philemon 1:5"]),
    ("Turn with me to Lannations chapter 3 verse 5.", ["Lamentations 3:5"]),
    ("Turn with me to Psalm of Solomon chapter 3 verse 5.", ["Song of Solomon 3:5"]),
    ("Turn with me to Judges chapter 3 verse a 5.", ["Judges 3:5"]),
    # ...never from short or ordinary words, and no stray relative verse
    ("Turn with me to Ruke chapter 3 verse 5.", []),
    ("the nations chapter 3 verse 5", []),
    ("my mother chapter 3 verse 5", []),
    ("Habakku is a prophet", []),
    ("john three sixteen to ninety", ["John 3:16-36"]),  # range end clamped
    ("john three eighteen to sixteen", ["John 3:18"]),  # backwards range ignored
])
def test_patterns(text, expected):
    assert labels(text) == expected


# ---------------------------------------------------------------------------
# numbered books


@pytest.mark.parametrize("text,expected", [
    ("first john one nine", ["1 John 1:9"]),
    ("one john one nine", ["1 John 1:9"]),
    ("i john one nine", ["1 John 1:9"]),
    ("1st john 1 9", ["1 John 1:9"]),
    ("second timothy three sixteen", ["2 Timothy 3:16"]),
    ("two timothy three sixteen", ["2 Timothy 3:16"]),
    ("one corinthians thirteen four through seven", ["1 Corinthians 13:4-7"]),
    ("first corinthians thirteen four to seven", ["1 Corinthians 13:4-7"]),
    ("second corinthians five seventeen", ["2 Corinthians 5:17"]),
    ("first samuel seventeen forty five", ["1 Samuel 17:45"]),
    ("second samuel seven twelve", ["2 Samuel 7:12"]),
    ("first kings eighteen twenty one", ["1 Kings 18:21"]),
    ("second kings two eleven", ["2 Kings 2:11"]),
    ("first chronicles four ten", ["1 Chronicles 4:10"]),
    ("second chronicles seven fourteen", ["2 Chronicles 7:14"]),
    ("first thessalonians five seventeen", ["1 Thessalonians 5:17"]),
    ("second thessalonians three three", ["2 Thessalonians 3:3"]),
    ("first timothy four twelve", ["1 Timothy 4:12"]),
    ("first peter five seven", ["1 Peter 5:7"]),
    ("second peter three nine", ["2 Peter 3:9"]),
    ("second john one six", ["2 John 1:6"]),
    ("third john one two", ["3 John 1:2"]),
    ("three john chapter one verse four", ["3 John 1:4"]),
])
def test_numbered_books(text, expected):
    assert labels(text) == expected


# ---------------------------------------------------------------------------
# Psalm 119 fallback


@pytest.mark.parametrize("text,expected", [
    ("psalm one nineteen", ["Psalm 119"]),
    ("psalm one nineteen one hundred and five", ["Psalm 119:105"]),
    ("psalm one nineteen verse eleven", ["Psalm 119:11"]),
    ("psalm one hundred nineteen eleven", ["Psalm 119:11"]),
    ("psalm one twenty one one", ["Psalm 121:1"]),
    ("psalm one three", ["Psalm 1:3"]),  # valid as it stands, no fallback
    ("psalm one fifty six", ["Psalm 150:6"]),
    ("psalm one hundred and fifty", ["Psalm 150"]),
    ("psalms ninety one one", ["Psalm 91:1"]),
])
def test_psalm_fallback(text, expected):
    assert labels(text) == expected


# ---------------------------------------------------------------------------
# strict books


@pytest.mark.parametrize("text", [
    "i lost my job three years ago",
    "my job three days",
    "mark two people",
    "acts like a child",
    "numbers one to ten",
    "james two of us went",
    "john three of them",
    "ruth one more time",
    "jude two",
    "amos five",
    "titus two",
    "joel one",
    "judges four",
    "mark my words",
    "the acts five of the apostles",
])
def test_strict_negatives(text):
    assert labels(text) == []


@pytest.mark.parametrize("text,expected", [
    ("mark chapter two", ["Mark 2"]),
    ("mark two seventeen", ["Mark 2:17"]),
    ("job chapter one", ["Job 1"]),
    ("job nineteen twenty five", ["Job 19:25"]),
    ("acts chapter two", ["Acts 2"]),
    ("numbers six twenty four", ["Numbers 6:24"]),
    ("numbers chapter six verses twenty four to twenty six", ["Numbers 6:24-26"]),
    ("james one five", ["James 1:5"]),
    ("jude chapter one verse twenty four", ["Jude 1:24"]),
    ("titus two eleven", ["Titus 2:11"]),
    ("ruth one sixteen", ["Ruth 1:16"]),
    ("joel two twenty eight", ["Joel 2:28"]),
    ("amos five twenty four", ["Amos 5:24"]),
    ("judges six twelve", ["Judges 6:12"]),
])
def test_strict_positives(text, expected):
    assert labels(text) == expected


def test_strict_can_be_disabled():
    assert labels("mark two", strict=False) == ["Mark 2"]


def test_typed_mode_ignores_strict():
    assert labels("mark 2", mode="typed") == ["Mark 2"]


# ---------------------------------------------------------------------------
# invalid references


@pytest.mark.parametrize("text", [
    "john thirty two",
    "john chapter thirty verse two",
    "jude chapter two verse one",
    "genesis fifty one one",
    "romans seventeen one",
    "john three ninety",
    "psalm two hundred",
    "revelation twenty three one",
    "obadiah chapter two verse one",
])
def test_invalid(text):
    assert labels(text) == []


@pytest.mark.parametrize("text", ["John 30:2", "Jude 2:1", "gen 51:1", "ps 151", "rev 22:22"])
def test_invalid_typed(text):
    assert parse_typed(text) is None


# ---------------------------------------------------------------------------
# typed forms


@pytest.mark.parametrize("text,expected", [
    ("jn3:16", "John 3:16"),
    ("jn 3:16", "John 3:16"),
    ("John 3:16", "John 3:16"),
    ("1 cor 13:4-7", "1 Corinthians 13:4-7"),
    ("1cor 13:4-7", "1 Corinthians 13:4-7"),
    ("1 cor 13 4-7", "1 Corinthians 13:4-7"),
    ("I Cor 13:4", "1 Corinthians 13:4"),
    ("ps 23", "Psalm 23"),
    ("ps 23:1", "Psalm 23:1"),
    ("Psalm 119:105", "Psalm 119:105"),
    ("gen 1:1", "Genesis 1:1"),
    ("gen 1.1", "Genesis 1:1"),
    ("rev 22:21", "Revelation 22:21"),
    ("phil 4:13", "Philippians 4:13"),
    ("mt 5:3-12", "Matthew 5:3-12"),
    ("mk 16:15", "Mark 16:15"),
    (u"rom 8:28–30", "Romans 8:28-30"),
    (u"rom 8:28—30", "Romans 8:28-30"),
    ("2tim3:16", "2 Timothy 3:16"),
    ("1 jn 1:9", "1 John 1:9"),
    ("song 2:4", "Song of Solomon 2:4"),
    ("is 53:5", "Isaiah 53:5"),
    ("ex 20:3", "Exodus 20:3"),
    ("jude 3", "Jude 1:3"),
    ("phlm 1", None),
    ("heb 11", "Hebrews 11"),
    ("john 3 16", "John 3:16"),
    ("1 Corinthians 13", "1 Corinthians 13"),
])
def test_typed(text, expected):
    ref = parse_typed(text)
    assert (ref.label() if ref else None) == expected


@pytest.mark.parametrize("text", ["for god so loved", "the lord is my shepherd", "love is patient", "", "   "])
def test_typed_phrases_are_not_references(text):
    assert parse_typed(text) is None


# ---------------------------------------------------------------------------
# relative verses and multiple references


def test_relative_verse():
    refs = parse("and look at verse seventeen")
    assert len(refs) == 1 and refs[0].relative and refs[0].book is None
    assert (refs[0].verse_start, refs[0].verse_end) == (17, 17)


def test_relative_range():
    refs = parse("verses sixteen to eighteen")
    assert (refs[0].verse_start, refs[0].verse_end, refs[0].relative) == (16, 18, True)


def test_relative_disabled():
    assert parse("verse seventeen", relative=False) == []


def test_relative_word_without_number():
    assert parse("the next verse says") == []


@pytest.mark.parametrize("text,expected", [
    ("romans eight twenty eight and john three sixteen", ["Romans 8:28", "John 3:16"]),
    ("compare genesis one one with john one one", ["Genesis 1:1", "John 1:1"]),
    ("psalm twenty three and psalm ninety one", ["Psalm 23", "Psalm 91"]),
    ("read john three sixteen then verse seventeen", ["John 3:16", "verse 17"]),
    ("first john one nine and second chronicles seven fourteen", ["1 John 1:9", "2 Chronicles 7:14"]),
])
def test_multiple(text, expected):
    assert labels(text) == expected


def test_reference_metadata():
    (ref,) = parse("please turn to john chapter three verse sixteen now")
    assert ref.source_text == "john chapter 3 verse 16"
    assert ref.confidence == 1.0 and ref.explicit_verse and not ref.relative
    (ref,) = parse("romans eight")
    assert not ref.explicit_verse and ref.verse_start == 1 and ref.confidence < 0.9


def test_fuzzy_references_have_low_confidence():
    from versecast.parser import AUTO_MIN_CONFIDENCE
    (ref,) = parse("Turn with me to Habakku chapter 3 verse 5.")
    assert ref.confidence < AUTO_MIN_CONFIDENCE
    (ref,) = parse("turn to habakkuk chapter 3 verse 5")
    assert ref.confidence >= AUTO_MIN_CONFIDENCE

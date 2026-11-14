#!/usr/bin/env python3
"""Generate labelled sermon transcripts for ``tools/bench_quotes.py``.

    python tools/make_quote_transcripts.py            # writes tests/data/quotes/generated-*.txt

Real transcripts are the real test; these fill the gap until there are
enough of them and keep the benchmark repeatable (fixed seeds). Each file
mixes original sermon talk, much of it full of Bible words ("the children of
Israel", "the Lord is good", "faith", "grace") that must not be taken for a
quote, with quotes spoken the way preachers and recognisers deliver them:

* any of the bundled translations (mostly KJV), whole or in part
* "thee"/"thou"/"-eth" modernised, words dropped, words misheard
* introduced ("the Bible says…") or not, split over two utterances

Lines are lower case without punctuation, as the recogniser writes them.
"""

from __future__ import annotations

import argparse
import os
import random
import re
import sys
from typing import List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from biverse import books  # noqa: E402

OUT = os.path.join(ROOT, "tests", "data", "quotes")

FAMOUS = """John 3:16; Romans 8:28; Philippians 4:13; Jeremiah 29:11; Proverbs 3:5; Proverbs 3:6; Isaiah 40:31;
Psalm 23:1; Psalm 23:4; Psalm 46:10; Psalm 119:105; Matthew 6:33; Matthew 11:28; Matthew 28:19; Romans 3:23;
Romans 6:23; Romans 10:9; Romans 12:2; Romans 5:8; 1 Corinthians 13:4; 2 Corinthians 5:17; Galatians 2:20;
Galatians 5:22; Ephesians 2:8; Ephesians 6:11; Philippians 4:6; Philippians 4:7; Hebrews 11:1; Hebrews 11:6;
Hebrews 13:5; Hebrews 12:2; James 1:2; James 4:7; 1 Peter 5:7; 1 John 1:9; 1 John 4:8; Revelation 3:20;
Revelation 21:4; John 14:6; John 10:10; John 1:1; John 11:25; John 8:32; John 15:5; John 14:27; Genesis 1:1;
Joshua 1:9; Isaiah 53:5; Isaiah 41:10; Isaiah 26:3; Micah 6:8; Lamentations 3:22; Lamentations 3:23;
Psalm 37:4; Psalm 91:1; Psalm 121:1; Psalm 27:1; Psalm 34:8; Psalm 51:10; Psalm 118:24; Psalm 139:14;
Matthew 5:14; Matthew 5:16; Matthew 7:7; Matthew 19:26; Matthew 22:37; Mark 11:24; Mark 16:15; Luke 1:37;
Luke 6:31; Acts 1:8; Acts 2:38; Acts 4:12; Acts 16:31; 2 Timothy 1:7; 2 Timothy 3:16; Deuteronomy 31:6;
Nehemiah 8:10; Proverbs 18:10; Proverbs 22:6; Ecclesiastes 3:1; Isaiah 9:6; Isaiah 54:17; Isaiah 55:8;
Malachi 3:10; Zephaniah 3:17; Habakkuk 2:3; Exodus 14:14; Numbers 6:24; Ruth 1:16; 1 Samuel 16:7;
2 Chronicles 7:14; Job 19:25; Colossians 3:23; 1 Thessalonians 5:16; 1 Thessalonians 5:18; 2 Peter 3:9;
Jude 1:24; 3 John 1:2; Hebrews 4:12; Hebrews 4:16; Ephesians 3:20; Ephesians 4:32; 1 Corinthians 10:13;
1 Corinthians 15:58; 2 Corinthians 12:9; Galatians 6:9; Romans 8:1; Romans 8:31; Romans 8:37; Romans 15:13"""

# Original sermon talk. Much of it is full of Bible words on purpose.
TALK = """good morning church it is good to be in the house of the lord today
turn to your neighbour and tell them god has a plan for your life
we are continuing our series on the life of faith this morning
the children of israel wandered in the wilderness for forty years before they entered the land
some of you came in here carrying a heavy load this morning and i want you to know god sees you
when moses stood before pharaoh he did not have an army he had a word from the lord
the lord is good all the time and all the time the lord is good
can somebody give god a shout of praise in this place
grace is not something you earn it is something you receive
i remember when i first gave my life to jesus i was nineteen years old
david was a shepherd boy before he was a king and god was preparing him in the fields
the prophets spoke about a coming king and the people waited for hundreds of years
faith is not a feeling it is a decision to trust what god has said
we do not serve a god who is far away we serve a god who is near
the disciples were afraid in the boat but jesus was sleeping in the storm
let me tell you about a woman in our church who prayed for her son for ten years
some people think the church is a museum for saints but it is a hospital for sinners
abraham did not know where he was going but he knew who was leading him
when you pray do not just bring your list bring your heart
the apostle paul wrote many of his letters from a prison cell
the blood of jesus is enough for every sin and every shame
your past does not disqualify you from your future in god
there is power in the name of jesus and there is power in prayer
god is not finished with you yet so do not give up
the lord will make a way where there seems to be no way
we give thanks for the word of god and for the fellowship of the saints
joseph was sold by his brothers but god turned it around for good
the kingdom of god is not about food and drink it is about the life of the spirit
elijah ran from jezebel and sat under a tree and asked god to take his life
how many of you know that the enemy comes to fight you when you are close to a breakthrough
the house of israel and the house of judah were divided but god had a plan to bring them together
jesus went up the mountain and taught the people about the kingdom
let us bow our heads and pray together as a family
i want to talk to you this morning about the faithfulness of god
the son of man came to seek and to save the lost and that includes you
in the land of egypt the people cried out and god heard their cry
we serve a mighty god who parted the sea and made a way through the waters
the holy spirit is our helper our comforter and our guide
nobody is too far gone for the love of god
the early church met in houses and shared everything they had
gideon was hiding in a winepress when the angel called him a mighty man of valour
peter denied jesus three times but jesus restored him by the sea
god does not call the qualified he qualifies the called
our church is going to feed families in the community next saturday
if you are visiting with us today we are so glad you are here
please stand as we read the word of the lord together
the walls of jericho fell down after the people marched around them for seven days
daniel kept praying even when it was against the law of the land
the widow gave two small coins and jesus said she gave more than all the rich
ruth followed naomi back to bethlehem and found a new family in the people of god
you cannot pour from an empty cup so spend time with the lord every morning
jesus wept at the tomb of lazarus because he loved his friend
the cross is the place where love and justice meet
when the prodigal son came home the father ran to meet him
there is a difference between knowing about god and knowing god
the israelites built a golden calf while moses was on the mountain with god
salvation is a gift you cannot buy it you can only receive it by faith
the god of abraham isaac and jacob is the same god we worship today
let the redeemed of the lord say so in this house
we need to be people of the word and people of prayer
the shepherd leaves the ninety nine to go after the one sheep that is lost
nehemiah rebuilt the wall of jerusalem in fifty two days
god spoke to samuel in the night when he was just a boy in the temple
the lord your god is with you wherever you go this week
amen you can be seated
i know some of you are going through a valley right now
when hannah prayed in the temple the priest thought she was drunk
the gospel is good news for the poor and the broken hearted
we were made to worship and we were made for relationship with our creator
jesus fed five thousand people with five loaves and two fish
some of you have been praying for a long time and you are wondering if god hears you
paul and silas sang hymns at midnight in the prison and the doors opened
the son of god became a man so that we could become children of god
there are seasons of planting and there are seasons of harvest
mary sat at the feet of jesus while martha was busy in the kitchen
god is calling you to step out of the boat this year
the church is not a building it is the people of god
the first commandment is about loving god and the second is about loving people
esther was born for such a time as this and so are you
the lord fought for israel and he will fight for you
thank you lord for your mercy that is new every day
we have a giving moment now and you can give online or at the back
next week we will look at the book of acts and the birth of the church
zacchaeus climbed a tree to see jesus and jesus went to his house for dinner
the spirit of the lord is moving in this place today
abraham believed god and it was counted to him as righteousness
your situation is not bigger than your god
the people of god must be a people of love
we bless you lord and we give you all the glory
jonah ran from god but god did not stop calling him
it is not by might nor by power but by the spirit of god that we overcome
love your neighbour as yourself is easy to say and hard to do""".split("\n")

# Allusions in that talk: suggesting these verses is right, but not required.
ALLUSIONS = {
    "the blood of jesus is enough for every sin and every shame": [
        "1 John 1:7"],
    "paul and silas sang hymns at midnight in the prison and the doors opened": [
        "Acts 16:25", "Acts 16:26"],
    "the children of israel wandered in the wilderness for forty years before they entered the land": [
        "Joshua 5:6", "Numbers 32:13", "Numbers 14:33", "Numbers 14:34", "Joshua 14:10", "Acts 7:36",
        "Deuteronomy 8:2", "Deuteronomy 2:7", "Amos 2:10", "Amos 5:25", "Acts 13:18"],
    "the kingdom of god is not about food and drink it is about the life of the spirit": [
        "Romans 14:17"],
    "the son of man came to seek and to save the lost and that includes you": [
        "Luke 19:10", "Matthew 18:11"],
    "the walls of jericho fell down after the people marched around them for seven days": [
        "Hebrews 11:30", "Joshua 6:20"],
    "jesus wept at the tomb of lazarus because he loved his friend": [
        "John 11:35"],
    "the god of abraham isaac and jacob is the same god we worship today": [
        "Exodus 3:6", "Exodus 3:15", "Exodus 3:16", "Exodus 4:5", "Exodus 6:3", "Matthew 22:32", "Mark 12:26",
        "Luke 20:37", "Acts 3:13", "Acts 7:32"],
    "let the redeemed of the lord say so in this house": [
        "Psalm 107:2"],
    "the shepherd leaves the ninety nine to go after the one sheep that is lost": [
        "Luke 15:4", "Matthew 18:12"],
    "the lord your god is with you wherever you go this week": [
        "Joshua 1:9"],
    "jesus fed five thousand people with five loaves and two fish": [
        "Matthew 14:17", "Matthew 14:19", "Matthew 14:21", "Mark 6:38", "Mark 6:41", "Mark 6:44", "Luke 9:13",
        "Luke 9:16", "John 6:9", "John 6:10", "Matthew 16:9", "Mark 8:19"],
    "mary sat at the feet of jesus while martha was busy in the kitchen": [
        "Luke 10:39", "Luke 10:40"],
    "esther was born for such a time as this and so are you": [
        "Esther 4:14"],
    "the lord fought for israel and he will fight for you": [
        "Joshua 10:14", "Joshua 10:42", "Joshua 23:3", "Joshua 23:10", "Exodus 14:14", "Deuteronomy 1:30",
        "Deuteronomy 3:22"],
    "thank you lord for your mercy that is new every day": [
        "Lamentations 3:22", "Lamentations 3:23"],
    "abraham believed god and it was counted to him as righteousness": [
        "Romans 4:3", "Galatians 3:6", "James 2:23", "Genesis 15:6"],
    "it is not by might nor by power but by the spirit of god that we overcome": [
        "Zechariah 4:6"],
    "love your neighbour as yourself is easy to say and hard to do": [
        "Matthew 22:39", "Mark 12:31", "Leviticus 19:18", "Galatians 5:14", "Romans 13:9", "James 2:8",
        "Matthew 19:19", "Luke 10:27"],
    "gideon was hiding in a winepress when the angel called him a mighty man of valour": [
        "Judges 6:12"],
    "zacchaeus climbed a tree to see jesus and jesus went to his house for dinner": [
        "Luke 19:4", "Luke 19:5"],
    "abraham did not know where he was going but he knew who was leading him": [
        "Hebrews 11:8"],
}


LEADS = ["", "", "the bible says", "listen to this", "jesus said", "paul writes", "it is written", "the word says",
         "remember what the scripture says", "look at this", "the psalmist says", "god says", "hear the word",
         "i love this verse", "write this down"]
TAILS = ["", "", "", "amen", "hallelujah", "can somebody say amen", "glory to god", "that is the word",
         "come on", "somebody shout"]
MODERN = {"thee": "you", "thou": "you", "thy": "your", "thine": "your", "ye": "you", "hath": "has",
          "doth": "does", "unto": "to", "art": "are", "shalt": "shall", "wilt": "will", "saith": "says"}
MISHEAR = {"the": "a", "and": "in", "his": "is", "him": "them", "their": "there", "son": "sun", "heaven": "haven",
           "peace": "piece", "pray": "prey", "hear": "here", "know": "no", "whole": "hole", "soul": "sole",
           "for": "four", "to": "two", "through": "threw", "wait": "weight", "not": "knot", "be": "bee",
           "faith": "face", "him.": "them", "sins": "since", "right": "write", "one": "won", "made": "maid"}


def clean(text: str) -> List[str]:
    text = text.lower().replace(u"’", "'").replace("'", "")
    return re.sub(r"[^a-z0-9\s]", " ", text).split()


def modernise(ws: List[str]) -> List[str]:
    out = []
    for w in ws:
        w = MODERN.get(w, w)
        if len(w) > 5 and w.endswith("eth"):
            w = w[:-3] + "s"
        out.append(w)
    return out


def noisy(ws: List[str], rng: random.Random, drop: float, mishear: float) -> List[str]:
    out = []
    for w in ws:
        r = rng.random()
        if r < drop:
            continue
        if r < drop + mishear and w in MISHEAR:
            w = MISHEAR[w]
        out.append(w)
    return out


def utterances(ws: List[str], rng: random.Random) -> List[List[str]]:
    out = []
    i = 0
    while i < len(ws):
        n = rng.randint(7, 15)
        out.append(ws[i:i + n])
        i += n
    if len(out) > 1 and len(out[-1]) < 3:
        last = out.pop()
        out[-1] = out[-1] + last
    return out


def talk(rng: random.Random) -> List[str]:
    """One sentence of sermon talk as utterances; allusions keep their loose (~) labels."""
    text = rng.choice(TALK)
    refs = ALLUSIONS.get(text)
    label = ("   => " + "; ".join("~" + r for r in refs)) if refs else ""
    return [" ".join(u) + label for u in utterances(clean(text), rng)]


def quote(bible, ref: Tuple[int, int, int], rng: random.Random) -> Tuple[List[str], str]:
    roll = rng.random()
    code = "KJV" if roll < 0.6 else "WEB" if roll < 0.85 else rng.choice(["ASV", "BBE", "YLT"])
    text = bible.verse(code, *ref) or bible.verse("KJV", *ref)
    ws = clean(text)
    kind = rng.random()
    note = code
    if kind < 0.55 or len(ws) < 12:
        part = ws
    elif kind < 0.85:
        part = ws[:max(8, int(len(ws) * rng.uniform(0.55, 0.85)))]
        note += " first part"
    else:
        start = rng.randint(0, max(0, len(ws) - 10))
        part = ws[start:start + rng.randint(9, 14)]
        note += " middle"
    if code == "KJV" and rng.random() < 0.4:
        part = modernise(part)
        note += " modernised"
    level = rng.random()
    if level < 0.4:
        part2 = part
    elif level < 0.8:
        part2 = noisy(part, rng, 0.06, 0.06)
        note += " light noise"
    else:
        part2 = noisy(part, rng, 0.12, 0.10)
        note += " heavy noise"
    return part2, note


def label(ref: Tuple[int, int, int]) -> str:
    return "%s %d:%d" % (books.get(ref[0]).ref_name, ref[1], ref[2])


def make(bible, seed: int, refs: List[Tuple[int, int, int]], talk_per_quote: Tuple[int, int]) -> List[str]:
    rng = random.Random(seed)
    lines = ["# generated by tools/make_quote_transcripts.py (seed %d); do not edit by hand" % seed]
    for ref in refs:
        for _ in range(rng.randint(*talk_per_quote)):
            lines += talk(rng)
        ws, note = quote(bible, ref, rng)
        lead = clean(rng.choice(LEADS))
        tail = clean(rng.choice(TAILS))
        lines.append("# %s: %s" % (label(ref), note))
        parts = utterances(lead + ws, rng)
        if tail:
            parts[-1] = parts[-1] + tail
        for u in parts:
            lines.append("%s   => %s" % (" ".join(u), label(ref)))
    for _ in range(3):
        lines += talk(rng)
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args(argv)
    from biverse.bible import open_default
    from biverse.parser import parse_typed
    bible = open_default()
    famous = []
    for part in FAMOUS.replace("\n", " ").split(";"):
        r = parse_typed(part.strip())
        famous.append((r.book, r.chapter, r.verse_start))
    rng = random.Random(7)
    pool = [(b, c, v) for (b, c), n in sorted(bible._counts.items()) for v in range(1, n + 1)]
    rng.shuffle(pool)
    others = [p for p in pool if 10 <= len((bible.verse("KJV", *p) or "").split()) <= 40][:80]
    os.makedirs(args.out, exist_ok=True)
    sets = [("generated-famous.txt", 1, famous, (1, 3)), ("generated-random.txt", 2, others, (1, 3)),
            ("generated-talk.txt", 3, [], (0, 0))]
    for name, seed, refs, between in sets:
        if name == "generated-talk.txt":  # long stretches of sermon talk with no quote at all
            r = random.Random(seed)
            lines = ["# generated by tools/make_quote_transcripts.py (seed %d); no quotes, only allusions" % seed,
                     "#! labelled"]
            for _ in range(250):
                lines += talk(r)
        else:
            lines = make(bible, seed, refs, between)
        with open(os.path.join(args.out, name), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print("wrote %s (%d lines, %d quotes)" % (name, len(lines), len(refs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

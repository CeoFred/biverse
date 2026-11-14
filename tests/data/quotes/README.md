# Quoted-verse benchmark transcripts

`tools/bench_quotes.py` runs the quoted-verse matcher (`biverse/quotes.py`) over every `.txt`
file here. `tests/test_quotes.py` runs it too and fails if fewer than 90 % of quotes are found,
if there is more than 1 false suggestion per 1,000 words, or if anything would go live wrongly.

## Format

One utterance per line, as the recogniser delivers final text (lower case, no punctuation is
fine). A line that contains a quote ends with `=> Ref`:

```
the bible says for god so loved the world that he gave   => John 3:16
his only begotten son amen                               => John 3:16
abraham believed god and it was counted to him           => ~Romans 4:3; ~Genesis 15:6
```

- `=> John 3:16-17` for a quote of a range.
- `=> ~Ref` for an allusion or a loose paraphrase: suggesting it is right, but not required.
- Several labels are separated by `;`. `#` starts a comment.
- `#! labelled` marks a labelled file that contains no quotes at all.

## Adding a real sermon

1. Save the transcript as a `.txt` file (any line length; a file without labels is cut into
   utterances of about 12 words).
2. `python tools/bench_quotes.py sermon.txt --review review.tsv` lists every suggestion with
   the words it matched and the utterance. Mark each one right or wrong.
3. Add `=> Ref` to the lines that really quote a verse (and `=> ~Ref` to allusions), put the file
   here, and run `python tools/bench_quotes.py --show`.

The `generated-*.txt` files come from `tools/make_quote_transcripts.py` (fixed seeds); do not
edit them by hand.

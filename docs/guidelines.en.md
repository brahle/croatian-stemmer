# Labeling guidelines (English summary)

The authoritative guidelines are in Croatian: [guidelines.hr.md](guidelines.hr.md).
Participants see the same text at `/static/guidelines.hr.html`; this summary is
served at `/static/guidelines.en.html`.

## The task

Each item shows a word in a sentence from a language corpus and asks one question:

- **Word pair**: do the two words, each in its own sentence, share a lemma?
  Answers: "Same lemma", "Different lemmas", "Not sure".
- **Lemma**: what is the dictionary lemma of this word? The corpus suggestion is
  filled in; confirm or correct it, then choose "Confirm lemma".
- **Stem**: is the proposed stem acceptable for this word? Answers: "Accept stem",
  "Reject stem", "Not sure".

Always read the whole sentence; the meaning in context decides.

## What a lemma is

- Nouns: nominative singular (kuće → kuća, ljudi → čovjek); plural-only nouns stay plural (škare, vrata).
- Adjectives: masculine nominative singular, positive degree (lijepa → lijep; brži → brz, najbolji → dobar).
- Verbs: infinitive (pisao → pisati). Aspect pairs are different lemmas: *pisati* and *napisati*.
  Do not type the reflexive *se* (bojim se → bojati); the lemma field takes one word.
- Diminutives and augmentatives are separate lemmas (kućica is not *kuća*).
- Pronouns, numerals and invariable words: the usual dictionary form (njega → on).

Type lemmas in lower case with diacritics (č, ć, đ, š, ž), no spaces or punctuation.

## Pairs

"Same lemma" means both words are forms of the same dictionary word, with the same
meaning and part of speech. Different aspect, diminutives, and homographs with a
different meaning or part of speech are different lemmas.

## Stems

Accept a stem if all usual forms of the lemma could be reduced to it and words of a
different meaning would not be. Reject it if it is too long (keeps an ending, so
forms of one lemma would get different stems) or too short (would merge unrelated words).

## Irregular form

Tick "Irregular form / exception" when the word is an irregular form of its lemma
(*ljudi* from *čovjek*, *išao* from *ići*). It does not change the answer.

## When to choose "Not sure"

Whenever you cannot answer reliably: an ambiguous form the sentence does not
resolve, a typo or broken word in the source, an unknown word, or a proper name you
are unsure how to inflect. "Not sure" is not a mistake; a wrong confident answer
harms the dataset more.

## Corpus suggestions

Suggested lemmas were produced automatically and can be wrong. Use them as hints.

## Reliability checks

Some items may have a known answer and are used to estimate how reliable answers
are. Treat every item with the same care.

## Shortcuts

Keys 1, 2 and 3 choose the answers in the order shown (when the cursor is not in the lemma field).

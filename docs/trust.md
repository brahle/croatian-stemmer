# Trust model

This is the maintainers' description of how the labeling app (from 0.3.0) weighs votes,
places annotators in tiers and decides item states: the current model and its parameters.
The data-protection assessment ([labeling-dpia.md](labeling-dpia.md)) describes the same
processing at the level of its logic, without numbers. A change to the code, the parameters
or the formulas that stays within that logic is recorded here and in the changelog and does
not reopen the assessment; the assessment's section "When this assessment must be
revisited" lists the changes that do. The code is
`src/croatian_stemmer/labeling/scoring.py`: one pure function, `score(inputs, params)`,
with no I/O, no clock and no randomness. The database side (the watermark barrier,
the loader, the publication fence and the scheduled job) is
`src/croatian_stemmer/labeling/web/scoring_run.py`; operating it is described in
[labeling-web.md](labeling-web.md), the offline commands in [labeling.md](labeling.md)
and what the assessment relies on in "Data-protection details" below. The public page
"Kako radi pouzdanost" (`/legal/trust.{hr,en}`) explains the same rules in plain words,
without parameter values, links here for them, and carries the formulas below in its
appendix.

## The model and its assumptions

Each annotator a has, per kind (`pair`, `lemma`, `stem`), one accuracy θ: the
probability that a definite answer of theirs is the true class. An item has a true
class z among K classes. Under the one-coin Dawid-Skene model (Dawid and Skene 1979;
the one-coin variant is Algorithm 2 of Zhang, Chen, Zhou and Jordan, JMLR 17, 2016) a
vote equals z with probability θ and each other class with probability
(1 − θ)/(K − 1), independently across annotators given z. The posterior of an item is
then a softmax over classes of the log prior plus the summed weights of the votes for
each class, where a vote's weight is w(θ, K) = ln(θ(K − 1)/(1 − θ)). With K = 2 and a
uniform prior, one vote at accuracy θ gives posterior θ, which is what makes the
numbers readable.

Class sets and priors:

- `pair` (`same`, `different`) and `stem` (`accept`, `reject`) have K = 2. With
  `class_prior: "estimated"` (the default) the prior π is estimated per kind and
  sampling stratum inside the fit: π_c = (Σ q_i(c) + 1)/(N + 2) over the non-gold items
  of the stratum that have at least one counted definite vote, from the item
  posteriors q of the previous pass (uniform before the first). `"uniform"` fixes
  π = 1/2.
- `lemma`: the classes are the m distinct lemmas that counted votes name, plus one
  class "other" that stands for every lemma nobody voted (the empty string in the
  code, `OTHER`). K = max(`lemma_k`, m + 1) with `lemma_k` = 3; each voted lemma has
  prior 1/K and "other" has (K − m)/K. Ties between classes go to a voted lemma before
  "other". A lemma vote's class is its normalised lemma (`word()`: NFC, casefolded).

θ is clipped to [0.5, θ_max(tier)] before any weight is computed. The ceiling bounds any
one account's influence; the floor means an inaccurate account is ignored rather than
inverted. Adversarial accounts are handled by flags and quarantine, not by negative
weights.

The assumptions do not hold exactly. Votes are not independent given the truth:
everyone who sees the corpus suggestion is pulled towards it, so errors correlate. The
one-coin model ignores class-specific error rates. Leave-one-out soft counts are a
robustness variant, not maximum likelihood. For these reasons the 0.95 resolution
threshold is treated as a heuristic until the calibration gate (below) measures it on
held-out items, separately for answers that agree with the suggestion and answers that
do not. Two agreeing `qualified` votes on a lemma item (θ = 0.80, K = 3) already give
0.970, which is exactly the case the `agrees` cell exists to check, since two people
copying a wrong suggestion agree.

## Inputs

A run reads the five append-only journals (`items`, `judgments`, `consents`,
`admin_events`, `trust_events`) up to one commit-safe watermark, the item metadata
(kind, stratum, suggestion fields, the calibration and review sample bits and the
calibration rank) and the parameter set stored in the run row. Everything that can
change (status, anchors, gold, tier memory, curator decisions on items, calibration
draws, cohort membership) is derived from those journals inside `score`; no mutable
table and no earlier run's output is read.

- Eligibility. An annotator's votes count when they are in the profiling cohort (a
  `privacy` row at 1.3 or later, `terms` at 1.1 or later and `participation` at 1.0 or
  later, each with `age_threshold = 18`) and their status, after this run's own
  decisions, is not blocked, quarantined or erased. Only cohort members are scored or
  flagged. Someone who has not yet passed the 1.3 gate has no score row and no counted
  vote; the first run after they pass includes their earlier answers.
- Counted first answers. Per item, epoch (see reopening below) and admission group, the
  first `votes_low_cap` (5) `low` and `votes_expert_cap` (3) `expert` admitted first
  answers of eligible annotators, in seq order. Answers beyond the cap are kept but not
  counted. Items with valid gold are exempt from the cap; anchors' answers on
  review-sample items are counted without using a slot.
- Votes. For each counted (annotator, item), the latest revision in the epoch. A latest
  `unsure` is an abstention. With `discard_previous` on the latest reopen only answers
  after it count.
- Hard observations. For each cohort member who is not blocked (quarantined people are
  still evaluated), their first definite answer on each item with valid gold, if it was
  recorded before the item's first `gold.disclosed` event and the person is not one of
  the gold's supporters (the anchors behind `anchor_consensus` gold, the curator who
  set `curator` gold). For audit gold the answer must also be older than the gold delay:
  its UTC day must be at most `as_of_day − gold_delay_days` (1), so an answer given on
  day D counts from the runs of day D + 1 and exact counts change at most daily (the plan
  says "before"; the code counts the day itself, matching the notice's "from the following day").
  Each observation is a hit or a miss, discriminating or not (blind showing, or gold
  whose answer differs from the suggestion; every `stem` observation is
  discriminating), and suggestion-wrong or not.
- Anchors are the annotators whose latest `anchor.*` event at the watermark is a grant;
  they come only from the trusted list.

## Algorithm

Per kind, in `fit()`:

1. Votes are ordered by (seq, judgment id), annotators by id, items by (corpus id, item
   id); every sum iterates in these orders so floating-point sums are reproducible.
2. Tiers are computed first from gold-only evidence (next section) and fixed for the
   rest of the run.
3. Prior (α₀, β₀) = `prior_anchor` (18, 2) for anchors, else `prior` (4, 2). h and m are
   the hard hits and misses over all valid gold of the kind (qualification and audit,
   discriminating or not).
4. θ⁽⁰⁾ = clip((α₀ + h)/(α₀ + β₀ + h + m)).
5. For `iterations` (10) passes, a fixed count rather than a convergence test:
   - weights from the previous θ; 0 for annotators whose votes are not counted;
   - for every non-gold item with at least two counted definite votes, and every vote v
     on it by a: q is the posterior of the item from the other votes alone
     (leave-one-out, with π); if the other votes' weights sum to at least
     `soft_min_info` (1.0), then s_a += λ·q(c(v)) and u_a += λ·(1 − q(c(v))) with
     λ = `soft_weight` = 0.5. These are expected correct and incorrect counts under the
     peers' view. An item whose other votes carry no weight adds nothing, so
     zero-information items cannot drag θ to 0.5, and a 0.5/0.5 posterior adds the same
     to both counters;
   - peer cap: when s_a + u_a exceeds `peer_cap_ratio` (1.0) × max(h + m,
     `peer_cap_floor` (12)), both are scaled down to that limit. Peer evidence never
     outweighs gold evidence by more than the ratio, however many items a clique agrees
     on;
   - θ⁽ᵗ⁾ = clip((α₀ + h + s)/(α₀ + β₀ + h + m + s + u));
   - π is re-estimated from this pass's item posteriors;
   - soft counts start from zero in every pass; they are never carried over.
6. The values of the last pass are final: `theta_mean`, the weight, `soft_hits` and
   `soft_misses` in the score row. The score row's `weight` is reported at K = 2 for
   every kind; item posteriors use each item's own K.
7. Item posteriors use all counted votes (no leave-one-out), the final weights and π;
   then calibration, states and the release rule.

Gold items never add soft counts (gold is hard evidence) and never enter π. The cap is
what stops a clique: an account with 30 gold answers of which 20 are hits, plus 1,000
items on which a clique agrees with it, has s + u ≤ 30, so θ ≤ (4 + 20 + 30)/(6 + 30 +
30) = 0.818, and it is not promoted because promotion reads gold only (its gold-only
bound, with all 30 discriminating, is 0.539).

## Tiers, ceilings and known-answer rates

Per (annotator, kind), first match wins:

| tier | condition | θ ceiling (weight at K = 2) | known-answer rate |
|---|---|---|---|
| not counted | blocked, erased, or outside the profiling cohort | votes not counted | — |
| `quarantined` | quarantined at the watermark or by this run | votes not counted | 10 % |
| `anchor` | anchor at the watermark | 0.98 (3.89) | 0 % |
| `established` | promoted or kept (below) | 0.95 (2.94) | 5 % |
| `qualified` | passed qualification for the kind | 0.80 (1.39) | 10 % |
| `new` | otherwise | 0.78 (1.27) | 10 % |

Promotion to `established` needs, for the kind: promotion readiness on (next
sections); at least `established_disc_gold` (30) discriminating observations;
theta_lb ≥ `established_theta_lb` (0.75); at least `established_votes` (100) items whose
latest answer is definite; and the hard-item floor: for `pair` and `lemma` at least 5
suggestion-wrong observations with at least 60 % hits, for `stem` at least 5
observations of each class with at least 60 % hits in each. A person already
`established` (the latest `tier.changed` event says so) keeps the tier while promotion
readiness is on, the 30 discriminating observations and the hard-item floor still hold
on currently valid evidence with the accuracy lowered to 50 %, and theta_lb ≥
`established_keep_theta_lb` (0.70). Only the accuracy thresholds have hysteresis; the
evidence floors are re-checked every run, so a retracted gold item that removes the
suggestion-wrong evidence demotes.

theta_lb uses discriminating observations only: μ = (α₀ + hits)/(α₀ + β₀ + n), and the
bound is the normal approximation of the Beta 5th percentile (formula 7 below). With the
prior (4, 2), 27 of 30 gives 0.767 (promoted) and 26 of 30 gives 0.732 (not). Peer
agreement never promotes.

Qualification: the first `qualification_n` (12) definite answers on the kind's
announced qualification items, always shown without the suggestion for `pair` and
`lemma`; at least `qualification_hits` (9) correct passes. It is a fixed function of
those 12 answers, so it never changes once decided; there is no retake. `qualified` is
lost only through quarantine or blocking.

Known-answer checks are served unannounced at the tier's `gold_rate`; a quarter of them
(`wrong_suggestion_pick` 0.25) come from gold whose answer differs from the suggestion
(`pair`, `lemma`); for `stem` the classes alternate. 20 % (`blind_rate`) of `pair` and
`lemma` showings omit the suggestion, at the same rate on gold and on other items. Which
showings are checks, which are blind and the order of picks are keyed hashes
(HMAC-SHA256) of the `audit_key` stored in the database; no route returns it and the
bundle does not contain it. An item stops being served as a check after
`gold_max_serves` (150) showings.

Readiness, per kind, from the active valid gold pools at the watermark:

| capability | on when |
|---|---|
| qualification | `pair`/`lemma`: at least `readiness.qualification_pool` (60) qualification items; `stem`: at least `readiness.stem_qualification_pool` (16) with each class at least 25 % |
| audit serving, `accuracy` flag | `pair`/`lemma`: at least `readiness.audit_pool` (100) audit items; `stem`: at least `readiness.stem_audit_pool` (30), each class at least 25 % |
| `copy` flag | `pair`/`lemma`: at least `readiness.wrong_suggestion_pool` (15) suggestion-wrong audit items |
| promotion | audit ready, the suggestion-wrong pool ready (`pair`/`lemma`), and at least `readiness.anchors` (1) anchor |

Tier memory: when an annotator's base tier (the tier their evidence gives, ignoring a
quarantine) differs from the latest `tier.changed` event, the run appends one. That
event is what the `established` keep rule reads.

## Gold decided by a run

- Support check: `anchor_consensus` gold whose support no longer holds at the watermark
  (a supporter is no longer an anchor, is blocked, quarantined or erased, a supporting
  judgment is no longer that supporter's latest definite answer with the same class, or
  the support was redacted at an erasure) is invalid for the whole run, and the run
  appends `gold.retracted {reason: support}`.
- Contest: when the posterior from `established` and `anchor` votes only, supporters
  excluded, goes against the gold with confidence ≥ `gold_contest_confidence` (0.95) on
  at least `gold_contest_min_votes` (3) such votes, the run appends `gold.contested`. A
  reactivated item is not contested again until a new expert vote arrives.
- Consensus gold: on an item that is not gold and not in the calibration or review
  sample, when `anchor_consensus_votes` eligible anchors agree (1 while there is one
  anchor, 2 with more; the parameter overrides it) and no `established` vote disagrees,
  the run appends `gold.set {source: anchor_consensus}` with the supporting annotator
  and judgment ids, if the pool that would receive it is below target: `stem`
  qualification up to 16 then audit up to 30, each class held to at least 25 %;
  `pair`/`lemma` only when the answer differs from the suggestion, into the audit pool
  until 15 such items exist. Agreeing `pair`/`lemma` gold is never created this way;
  hr500k supplies it, and from 0.3.4 also suggestion-wrong gold, from gold-reserve decoy
  items (items prepared to show a suggestion the corpus contradicts, see
  [labeling.md](labeling.md)). Gold-reserve items are never in a seed or expert queue.

Decided events are written when the run publishes and take effect from the next run.

## Calibration gate

Every item has a fixed calibration sample bit (`audit_sample_rate`, 10 %), a fixed
review sample bit (`review_sample_rate`, 2 %, only for items outside the calibration
sample) and a fixed 64-bit rank, written when the item is imported. Sampled items never
become gold of any source.

Anchors' answers on calibration-sampled items are always references, never votes:
they are left out of the counted votes, the fit, every leave-one-out posterior and
every flag, whether or not the item is in a drawn evaluation set.

Cells: `pair/agrees`, `pair/differs`, `lemma/agrees`, `lemma/differs` (whether the crowd
winner equals what the suggestion implies) and `stem/none`. For each cell the
population is the calibration-sampled items whose crowd votes (anchors excluded) meet
the model rule. The first run under a policy at which the population has at least
`calibration_n` (30) items draws the 30 with the lowest rank and appends
`calibration.drawn {kind, cell, calibration_key, items, population}`; later runs under
the same policy evaluate that frozen set. `calibration_key` is the sha256 of
`SCORING_VERSION` and every parameter except `calibration_n`, `calibration_lb`,
`release_min_voters`, `gold_pool_warn`, `quarantine_review_days` and the two sample
rates, so any change that can alter a vote, weight, tier or state draws a new set,
reusing references already given. A redraw under the same policy happens only when the
curator asks (`calibration.redraw_requested`).

A member is a success when the crowd rule still holds and every anchor's first definite
answer on it equals the crowd winner; a failure when it differs, the anchor answered only
`unsure`, two anchors differ, the crowd rule no longer holds, or the reference is still
pending. A cell passes when its set is full (30), at least `resolve_confidence` (0.95) of
it succeeds and the Wilson 95 % lower bound is at least `calibration_lb` (0.80): 29 of
30 passes (bound 0.833), 28 fails. Items that meet the model rule are `resolved` in a
passed cell and `provisional` otherwise; a cell that later fails sends them back.

## Item states

`n_low` and `n_expert` are the counted first answers of the current epoch. The model
rule is: confidence ≥ `resolve_confidence` (0.95), at least `resolve_min_votes` (2)
distinct voters for the winning class whose θ is at least `resolve_vote_min_theta`
(0.70; votes that carry evidence for the answer, so neither the class prior nor a
worthless or dissenting vote stands in for the second vote), and a vote for the winner
from an `established` or `anchor` annotator. A past run's parameters without
`resolve_vote_min_theta` are read as `null`, the 0.3.0 rule (any two distinct voters),
so replays reproduce what those runs published.
Per item, first match wins:

1. `ambiguous`: the latest of `item.ambiguous` and `item.reopened` is `item.ambiguous`.
2. `resolved` by `adjudication`: an `item.adjudicated` event newer than the latest
   reopen. It is the curator's decision, not a vote; the posterior keeps the crowd's
   view.
3. `contested` (two or more anchors only): two anchors' counted votes in the epoch
   disagree.
4. Anchor check: on a calibration- or review-sampled item whose crowd votes meet the
   model rule and which has an anchor's definite answer in the epoch. With one anchor
   the item is `resolved` to the anchor's answer (`resolution_source` `reference` or
   `review`) whether or not it agrees with the crowd and whatever the cell's
   calibration. With two or more, any disagreement between anchors or with the crowd
   winner makes it `contested`. A single anchor answer never resolves an item alone,
   because the crowd rule (two votes) must already hold.
5. Model rule met: `resolved` (`model`) when the item's cell has passed, else
   `provisional`.
6. `contested`: no valid gold and both budgets full (`n_low` ≥ 5 and `n_expert` ≥ 3).
7. `needs_expert`: no valid gold and `n_low` ≥ 5; served only to `established` and
   anchor annotators.
8. `open`.

Reopening starts a new epoch with a fresh budget; with `discard_previous` the earlier
answers also leave the posterior. Per-corpus overrides (`corpora`) may change
`resolve_confidence` (never below 0.9), `resolve_min_votes` (never below 2) and the two
caps; nothing lets one anchor vote resolve an item.

Priority, which the scheduler orders by: 1.0 with no counted vote, otherwise 1 − (p₁ −
p₂), the margin between the top two classes; 0.05 for a `resolved` (not adjudicated) or
`provisional` item that is not yet releasable, so it still collects the vote a release
needs. Release rule: at least `release_min_voters` (3) distinct voters and no pivotal
one (the model rule still holds, with the same winner, after removing any single vote).
It is evaluated on the crowd votes (anchors' votes excluded) for every source, so an
anchor's vote never makes a row public.

## Flags and quarantine

Per run, annotator and kind, over answers after the latest `annotator.cleared` event:

| flag | signal | |
|---|---|---|
| `fast` | median of the last 30 timed definite answers < max(1 s, 0.25 × the anchors' median for the kind; the anchor term only once anchors have 100 timed answers outside the calibration sample) | hard |
| `straight` | at least 12 identical definite answers in a row (`pair`, `stem`) | hard |
| `accuracy` | below 60 % over the last 20 audit checks, at least 12 seen (when audit is ready) | hard |
| `copy` | at least 5 suggestion-wrong checks at most 40 % right while other checks are at least 90 % right (when the suggestion-wrong pool is ready) | hard |
| `review_loss` | at least 10 of the person's latest votes on items where all anchors gave one answer (calibration sample excluded), more than 30 % losing | hard |
| `burst` | at least 400 answers in a 60-minute window, together with `fast` | hard |
| `unsure_heavy` | more than 60 % unsure over the last 50 answers | reported |
| `disagree` | agreement with resolved answers below 50 % over at least 40 | reported |

Two different hard flag names in one run, on an active, non-anchor cohort member,
quarantine the person in the same run (their votes leave this run's posteriors). The
names are counted across kinds: `fast` on `pair` and `fast` on `lemma` is one flag;
`fast` with `burst` is two. Quarantine is silent in the UI and visible in the person's
export. The curator reviews it within `quarantine_review_days` (14); without a decision,
the first run on or after the 14th day releases it (`annotator.cleared {reason:
review_deadline}`). Anchors are never quarantined automatically, and nothing blocks
automatically. `signup_burst` (5 new profiles in 10 minutes) is a live dashboard
alert, not a run output.

## Worked example

Kind `pair`, one non-gold item with three counted votes, `class_prior: "uniform"`,
other parameters default, no anchors. `tests/labeling/test_scoring.py` pins these values
to 1e-6.

| annotator | tier | gold seen / hits | θ⁽⁰⁾ | vote |
|---|---|---|---|---|
| A | established | 40 / 36 | 40/46 = 0.869565 | same |
| B | new | 0 / 0 | 4/6 = 0.666667 | different |
| C | qualified | 15 / 12 | 16/21 = 0.761905 | same |

Pass 1: w_A = 1.897120, w_B = 0.693147, w_C = 1.163151. Leave-one-out: without A,
p_same = 0.615385, so s_A = 0.5 × 0.615385 = 0.307692 and u_A = 0.192308; without B,
p_same = 0.955224 and B voted `different`, so s_B = 0.022388 and u_B = 0.477612; without
C, p_same = 0.769231, s_C = 0.384615, u_C = 0.115385. θ⁽¹⁾: A 0.866832, B 0.618829,
C 0.762075. No cap applies (each s + u is 0.5, below 12).

After pass 10: θ_A = 0.867360, θ_B = 0.618876, θ_C = 0.762816; weights 1.877817,
0.484781, 1.168179; soft hits / misses A 0.332248 / 0.167752, B 0.022695 / 0.477305,
C 0.400538 / 0.099462.

Item posterior: S_same = 3.045996, S_different = 0.484781, p_same = 0.928323. The model
rule is not met (0.928 < 0.95), so the item is `open` with priority 1 − (0.928323 −
0.071677) = 0.143354. Its posterior row holds two classes with `votes` 2 / 1 and
`established_votes` 1 / 0.

Variants with the same tiers:

- B quarantined from the start: B's vote is not counted; w_A = 1.887185, w_C =
  1.176857, p_same = 0.955385 ≥ 0.95 with two votes and an established vote for the
  winner, so the rule is met: `resolved` if the `pair/agrees` cell has passed, else
  `provisional`.
- Two `established` votes at θ = 0.85 agreeing: 0.9698, rule met.
- One anchor at its prior mean 0.9: 0.90, not met (one vote, below 0.95).
- Three `new` accounts at the 0.78 ceiling agreeing: 0.9781, not met (no `established`
  or anchor vote). Two of them: 0.9263, not met on confidence either.
- Two votes, an established one and a new one (the owner decided that an item needs two
  votes): an `established` annotator at the promotion floor (27 of 30
  discriminating, θ = 31/36 = 0.861111, w = 1.824549) and a `new` one at the 0.78
  ceiling (w = 1.265666) agreeing give 0.956487, rule met. Two such votes resolve
  whenever the established θ is at least 0.842742. Up to 0.3.0 the `new` ceiling was
  0.75 (w = 1.098612): the same pair gave 0.948980 and needed a third vote, since only
  an established θ of 0.863636 or more reached 0.95 with a new vote.
- The second vote must carry evidence for the answer (`resolve_vote_min_theta`, 0.70):
  it counts only when it is for the winning class and its author's θ is at least 0.70.
  With an estimated class prior the prior alone can lift one established vote above
  0.95 (with π_same = 0.9 a single vote at θ ≥ 0.678 does), so up to 0.3.0 any second
  vote then resolved the item: a known-bad one (θ clipped to 0.5, weight 0), a θ 0.6
  one, or even a vote for the other class. None of these counts now, under either
  prior. A `new` account with no evidence yet sits at its prior mean 4/6 (0.666667),
  below the floor, so its vote never completes the two; one correct known-answer item
  takes it to 5/7 = 0.714286 and four take it to the 0.78 ceiling. (Agreement counts
  too: θ includes the capped peer evidence, so a few agreements with established
  voters also lift it.) Up to 0.3.0 such a fresh vote resolved next to an established
  θ of 0.904762 or more. With a uniform prior, one established vote at the ceiling
  alone is 0.95 − 2⁻⁵², just short.
- Anchors: one anchor vote never resolves (one vote); two anchors agreeing do, as
  before (both are far above the floor).

## Formulas

Symbols: θ an annotator's accuracy, K the number of classes, π_c the prior of class c,
w a vote's weight, h and m hard hits and misses on gold, α₀ and β₀ the prior, s and u the
soft hits and misses (peer evidence) of annotator a, λ = `soft_weight`, q the
leave-one-out posterior of the item from the other votes and c(v) the class of vote v,
clip() the clipping to [0.5, ceiling of the tier], ρ and f the peer cap's ratio and floor
(`peer_cap_ratio`, default 1.0, and `peer_cap_floor`, default 12), n and hits the
discriminating observations and their hits, p₁ and p₂ the two highest class probabilities
of an item. 1.645 is the standard normal quantile for the 5th percentile, not a
parameter.

```
w(θ, K) = ln(θ · (K − 1) / (1 − θ))
P(z = c | votes) ∝ π_c · exp(Σ w(θ_a, K) over the votes for c)
θ⁽⁰⁾ = clip((α₀ + h) / (α₀ + β₀ + h + m))
s_a += λ · q(c(v)),  u_a += λ · (1 − q(c(v)))
s_a + u_a ≤ ρ · max(h + m, f)
θ⁽ᵗ⁾ = clip((α₀ + h + s) / (α₀ + β₀ + h + m + s + u))
θ_lb = μ − 1.645 · √(μ(1 − μ) / (α₀ + β₀ + n + 1)),  μ = (α₀ + hits) / (α₀ + β₀ + n)
priority = 1 − (p₁ − p₂)
```

## Parameters

The defaults are `DEFAULT_PARAMS` in `scoring.py`; `validate_params()` requires every
key, refuses extra keys and bounds every number (`_NUMBERS`, `CORPUS_OVERRIDES`).
`theta_min` is fixed at 0.5. The live set is `label_setting['scoring_params']`, edited
in the curator dashboard ("Bodovanje"); a change replaces the whole object, appends
`params.changed {old_sha256, new_sha256, diff}` and is copied into each run row with
its `params_sha256`. `SCORING_VERSION` ("2.0", also the parameter set's `version`) is
bumped whenever the pure function changes behaviour for identical inputs.

## Determinism and replay

Identical inputs and parameters give identical outputs: a fixed iteration count, the
sort orders above, no unsorted dictionary iteration, no clock (`as_of_day` is an input),
Python floats only (no NumPy) and every float rounded to 9 decimals before hashing.
`inputs_sha256` covers the watermark, `as_of_day` and, per journal, the row count and an
order-independent hash of the canonical rows; `outputs_sha256` covers every output,
including the events the run decided. A golden `outputs_sha256` for a synthetic fixture
is committed in `tests/labeling/test_scoring.py`.

`croatian-stemmer-labels score --bundle FILE --output OUT` replays a run from its
restricted bundle alone, with no database and no audit key. A later privacy action can
change a past run's inputs: an erasure (re-keyed judgments and consents, redacted
events), the 90-day timing retention or a redaction. The replay then reports
`inputs_match: false` and the journals whose hash changed with their row counts then and
now, and does not claim an output mismatch (`outputs_match: null`).

## What a person sees

The card on "Moji podaci" → "Pouzdanost" (`/api/me/trust`) is a simplified view. Its
constants live in `web/trust_view.py`, not in the scoring parameters. Per kind it shows
the tier and a band of the latest run's θ: `visoka` (high) at θ ≥ 0.85, `dobra` (good) at
θ ≥ 0.75, `treba_paznje` (needs attention) below, and "not enough data" with fewer than 12
(`MIN_CHECKS`) known-answer checks. Check counts are rounded down to tens; agreement with
resolved items is rounded to 5 % and shown only with at least 20 resolved items. A
quarantine is silent: `/api/me` and the card show status `active` and the base tier. A
block is shown with its reason.

The self-service export (`/api/me/export.json`) has a `trust` section: every retained run
(per kind the tier including `quarantined`, qualified, θ, weight, lower bound, known-answer
totals by type, peer agreement and disagreement, every flag with its signal values, the
counts), every status and trust event about the person (quarantines with flags, clears,
anchor grants and revocations, tier changes) and a plain-language meaning of each field
in both languages. It does not say which answers were checks on items still in use, since
that would map the active check pool; on request by email the curator retires those items
and sends the per-answer results within one month. Answers on retired or retracted
known-answer items carry `checked_against_known_answer` without a request.

The curator dashboard ("Karantena") lists open quarantines with their age, flags and
signal values and alerts at 7 days, so the 14-day review deadline is not missed.

## Data-protection details

These are the implementation facts behind the data-protection assessment, which describes
them only by category. Operation is in [labeling-web.md](labeling-web.md) ("Consent, legal
documents and data-subject rights", "Trust system"), the release procedure and
`release-check` rules in [labeling.md](labeling.md).

Where each category of personal data lives:

| category | store |
|---|---|
| sign-in identity | `label_annotator` (subject, verified email); the Keycloak realm (name, Google id) |
| consent records | `label_consent` (document, version, `age_threshold` = 18, time, locale, UI version) |
| answers | `label_judgment` (item, answer, lemma, irregular flag, revision, time, `client_version`, `presentation`, admission) |
| answer timing | `label_judgment.elapsed_ms`, curator-only |
| showings | `label_assignment` |
| derived per person | `label_annotator_score`, one row per run, annotator and kind |
| derived per item | `label_item_posterior` per run; per-vote rows with pseudonymous ids in `resolved.jsonl` |
| events | `label_admin_event`, `label_trust_event` |
| trusted list | `label_trusted_email` (email, its hash, a note of at most a first name) |
| erasure requests | `label_erasure_request` (Keycloak user id until the curator confirms its deletion) |
| erasure list | outside the database: Keycloak user id and request date, 60 days, for re-applying erasures after a restore |
| edge logs | the reverse proxy only; the app runs uvicorn with `--no-access-log` |

Retention mechanics: the retention task runs at startup and daily. It deletes
`label_annotator_score` and `label_item_posterior` rows 30 days after their run finished
(pinned runs included; the latest done run is kept while it is the latest), sets
`elapsed_ms` to NULL 90 days after the answer, and deletes unanswered `label_assignment`
rows 30 days after they were last shown. `label_scoring_run` rows hold no personal data and
are kept. The Keycloak user is deleted by hand by the curator within 30 days of an erasure
(not yet automated). The erasure list kept outside the database for backup restores holds
the Keycloak user id and request date for 60 days (backup retention of 14 days plus a
margin).

Scoring cadence: while `scoring_enabled` is on (off after migration 003), the background
task checks every `LABELING_SCORING_INTERVAL` seconds (default 600). Only the profiling
cohort (privacy 1.3 or later, terms 1.1 or later, participation 1.0 or later, each with
`age_threshold = 18`) is scored, flagged or counted, identically in every run and at
answer time.

Bounded influence, in numbers: per item and epoch at most 5 `low` and 3 `expert` first
answers count; tier ceilings 0.78 / 0.80 / 0.95 / 0.98; the daily cap of 3000 answers
(`LABELING_DAILY_CAP`) and per-minute rate limits.

Erasure keeps the journal sequence numbers of the moved rows, because the watermark needs
them. An insider who also kept the old history could therefore guess which new id followed
which old one; the assessment accepts this with the other re-linking risks.

Inference from releases, the worked example behind the assessment's residual risk: three
`established` voters at θ = 0.85 all answer A on a `pair` item with a uniform prior; the
confidence is 0.9945, and 0.9698 without any one of them, so the row appears in the higher
band. Had the third answered B, the posterior would be 0.85 and there would be no row.
Someone who knows how two voters answered therefore learns how the third did. The release
rule (at least `release_min_voters` crowd voters and no pivotal one) narrows this; it does
not close it.

Security facts the assessment summarises: the browser uses PKCE S256; the backend accepts
only RS256 access tokens checked for issuer, audience, expiry and client; restricted routes
need the curator role; the container runs as a non-root user; the app keeps no IP
addresses; scoring is pure Python with no external calls, so no third-party service or language
model takes part in it; the audit key that decides which showings are checks never leaves the database
and is not in any bundle.

## Where the code differs from the design

- Anchors' answers on calibration-sampled items are references whether or not the item
  is in a drawn set, and are removed from the counted votes outright; the design spoke
  only of the first anchor answer on an evaluation-set item.
- Tier memory records the base tier and ignores quarantine, so a quarantine never
  produces a `tier.changed` event and a released person keeps their earned tier. The θ
  of a quarantined person is clipped at their base tier's ceiling (their weight is 0
  anyway).
- Quarantine needs two distinct hard flag names, counted across kinds.
- `readiness.qualification_pool` (60) is a parameter; the design's default listing
  left it out.
- `gold.disclosed` is not a moderation event: it does not take the moderation lock and
  does not make a run stale or superseded, because every answer up to a run's watermark
  predates it and it never changes that run's outputs.
  `calibration.redraw_requested` is a moderation event.
- `disagree` compares a person's counted definite votes with the resolved answers
  directly (not leave-one-out), with fixed thresholds (40 items, 50 %) that are not
  parameters.
- The score row's `weight` is computed at K = 2 for every kind.

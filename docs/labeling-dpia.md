# Data protection impact assessment: trust-weighted labeling

- Version 1.0, 18 October 2026.
- Applies to the labeling web app of croatian-stemmer 0.3.0 and 0.3.1 (scoring version
  2.0, privacy notice 1.3, terms 1.1, participation statement 1.0).
- Prepared by the implementing agent, as the owner decided (Nexus decision 5ee0e7ef,
  question 18).
- Read by: ____________________ (date: __________)
- This is the controller's own assessment under GDPR Art. 35. It is not legal advice and
  has had no external legal review (decision 5ee0e7ef, questions 1-2).

It must be read by the owner before `scoring_enabled` is first switched on, and updated
before any of the changes listed under "Review triggers", in particular before any V3
leaderboard or reward.

## Conclusion in short

Trust scoring is profiling (Art. 4(4)): the app evaluates each participant's reliability
and behaviour and acts on it. The effects on a person are small and stay inside a
voluntary, unpaid volunteer site: their answers count more or less, they see a slightly
different mix of items, and their answers can be set aside for at most 14 days unless a
person decides otherwise. Blocking is only ever a human decision with a written reason
that the person sees. The data are pseudonymous linguistic judgments of adults, not
special categories. With the measures below, no high residual risk remains, so prior
consultation with AZOP under Art. 36 is not required. The residual risks that remain
(re-linking retained answers after an erasure from copies that exist for a while, and
inference about one vote from public labels by someone who already knows the other
votes) are named in section 6 with the reason each is accepted.

## 1. Why this assessment is done

AZOP's list of processing operations that require a DPIA (decision of 21 December 2018,
KLASA 004-04/18-01/01) was checked:

- Item 3, processing of children's data for profiling or automated decisions: does not
  apply. The minimum age is 18 since 0.2.3 (decision 5ee0e7ef, question 19); every
  consent row records `age_threshold = 18` and nobody outside that cohort is scored.
- Item 1, systematic and extensive profiling or automated decision-making that helps
  decide access to a service, and item 11, systematic monitoring of an individual's
  behaviour: arguable. Scores decide how much answers count and an automatic quarantine
  sets answers aside, and the abuse signals look at answer timing and behaviour over
  time, though access to the site itself never depends on them.
- Two criteria of the EDPB-endorsed WP248 guidelines apply: evaluation or scoring, and
  systematic monitoring (per-answer timing and behaviour over time).

Because the case is arguable, the assessment is done rather than argued away.

## 2. The processing (Art. 35(7)(a))

### 2.1 Context

The controller is the person named in the privacy notice (`LABELING_CONTROLLER_NAME`,
contact `LABELING_CONTROLLER_EMAIL`). The site collects human judgments about Croatian
words (whether two forms share a lemma, the lemma of a form, whether a proposed stem is
acceptable) from volunteers who sign in. Since 0.3.0 every answer is a vote whose weight
depends on how reliable its author has proven to be; the result is a dataset of labels,
published in aggregate under CC BY-SA 4.0 with a CC0 waiver for the labels alone. The
model is documented in [trust.md](trust.md); operation in
[labeling-web.md](labeling-web.md).

### 2.2 Purposes

1. Build a reliable labelled dataset for evaluating and improving the stemmer.
2. Trust scoring: estimate per participant and task kind (pair, lemma, stem) an
   accuracy θ, a tier and the weight of their votes, so that careful work counts more
   and careless or copied work counts less.
3. Abuse detection: notice answering at inhuman speed, copying the visible suggestion,
   identical answers in long runs, poor accuracy on known-answer checks, systematic
   losing against the owner's checks, and bursts.
4. Silent automatic quarantine: set aside, for at most 14 days pending review, the
   votes of someone with two different hard abuse flags.
5. Curation: restricted exports for the curator, and reproducibility of each scoring
   run from a restricted bundle.
6. Public releases of aggregate labels.
7. Keeping answers after a person erases their account, so the dataset and its earlier
   releases stay consistent.

### 2.3 What the system does

Trust scoring. Every 600 seconds by default (`LABELING_SCORING_INTERVAL`), and only
while the curator has switched `scoring_enabled` on (it is off after migration 003), a
run computes, per annotator and kind: θ under a one-coin Dawid-Skene model, a lower bound
from known-answer checks only, a tier (new, qualified, established, anchor,
quarantined), the weight of their votes, flags with their signal values and counts. The
run is a pure function of append-only journals up to a commit-safe watermark and can be
reproduced offline from a restricted bundle. A run that missed a moderation event
(block, clear, erasure, anchor change, gold change, item decision, parameter change) is
discarded as superseded and rerun.

Known-answer checks ("gold"). Items with an answer known in advance are mixed in
unannounced at 10 % of showings (5 % for established annotators), a quarter of them on
items where the suggestion is wrong. 20 % of pair and lemma showings omit the suggestion
("blind"), at the same rate on checks and other items. Which showings are checks is
decided by a secret key in the database. A new participant first answers 12 announced
qualification items per kind, always shown without a suggestion; 9 correct makes them
`qualified`, with no retake. `established` needs at least 30 discriminating checks,
a lower bound of at least 0.75, at least 100 definite answers and at least 5 checks
where the suggestion is wrong with at least 60 % right (stem: at least 5 per class, 60 %
each); it is kept at a lower bound of at least 0.70 and at least 50 % on the hard items.
Agreement with other people refines θ but is capped and never promotes. Checks count from
the UTC day after the answer (gold delay of one day), so visible numbers change at
most daily.

Abuse detection and quarantine. Hard flags: `fast` (median of the last 30 answer times
below max(1 s, 0.25 × the anchors' median)), `straight` (12 or more identical answers in
a row on pair or stem), `accuracy` (below 60 % over the last 20 unannounced checks, with
at least 12 seen), `copy` (at least 5 wrong-suggestion checks at most 40 % right while
other checks are at least 90 % right), `review_loss` (at least 10 votes on items an
anchor also answered, more than 30 % losing), `burst` (400 or more answers in 60
minutes, together with `fast`). Reported only: `unsure_heavy` (more than 60 % unsure
over the last 50), `disagree` (below 50 % agreement with resolved items over at least
40). The dashboard also alerts on `signup_burst`. Two different hard flags in one run on
an active, non-anchor person quarantine them automatically: their votes stop counting,
they get more known-answer checks, labeling continues, and nothing in the UI tells them
(`/api/me` and the trust card show status "active"). The curator reviews within 14 days
(the dashboard lists open quarantines and alerts at 7 days) and releases, keeps or
blocks; if nobody decides, the first run after 14 days releases it automatically.
Blocking is only by a person, with a written reason, and is shown to the person with
that reason.

Item labels. Each item gets a posterior over its answers. An item resolves only with
confidence of at least 0.95, at least 2 votes from different people and a vote from an
established or anchor annotator for the winner, and only once the calibration cell
passed (30 sampled reference items, at least 29 matching the owner's answer, Wilson
bound at least 0.80); before that it is provisional. One anchor answer never resolves
an item alone. The owner is the only anchor; their answer on a checked item is final.

Exports. Restricted curator files: the judgment exports (`export.tsv`,
`export.jsonl`), the resolved exports (`resolved.tsv`, and `resolved.jsonl` with
per-vote rows carrying pseudonymous ids), the annotators export (score rows and status,
no email) and the run bundle (journal rows up to the watermark, including answer
timing; never the secret key).

Public releases. GitHub release assets of github.com/brahle/croatian-stemmer only:
aggregate labels, a summary, a dataset card, the parameters and checksums. No
annotator ids, no counts, no timestamps other than the release date. An item appears
only with at least 3 crowd voters and no pivotal voter; `release-check` enforces this
and fails closed.

Keeping answers after erasure. Erasure deletes the identity at once and moves the
person's answers and consent records to a new random id with new row ids, day-level
times and no timing (section 5.6).

### 2.4 Data subjects

- Participants: adult volunteers (18 or over, self-confirmed at the gate) who sign in
  through the Keycloak realm, typically with a Google account. Unpaid; participation
  is voluntary and can end at any time.
- Anchors: people on the trusted list, matched by verified email. Today only the owner.
- The curator: today also the owner.

### 2.5 Data categories

| category | content | where |
|---|---|---|
| sign-in identity | Keycloak subject, verified email; in Keycloak also name and Google id | `label_annotator`; Keycloak realm |
| consent records | document, version, age threshold 18, time, locale, UI version | `label_consent` |
| answers | item, answer, lemma, irregular flag, revision, time, client version, shown blind or with suggestion, admission | `label_judgment` |
| answer timing | `elapsed_ms` per answer | `label_judgment.elapsed_ms` (curator-only) |
| showings | which items were shown, when, how often | `label_assignment` |
| derived per person | θ, lower bound, tier and base tier, weight, flags with signal values, check counts by type, peer agreement, counts, resolved agreement | `label_annotator_score` per run |
| derived per item | class probabilities, weights, per-vote rows with pseudonymous ids and tiers | `label_item_posterior` per run, restricted exports |
| events | status changes with reasons, quarantines with flags, clears, anchor grants and revocations, tier changes, gold events with supporting ids | `label_admin_event`, `label_trust_event` |
| trusted list | email, its hash, a curator note of at most a first name | `label_trusted_email` |
| edge logs | IP address, user agent, path, time | the reverse proxy in front of the app, not the app |

No special categories (Art. 9) are processed. The answers are judgments about words.
The lemma field is free text, so a person could type something about themselves;
`release-check` refuses any released value containing `@`, and released lemmas are
judgments on public corpus words.

The app itself sets no cookies, keeps no persistent browser storage, runs no analytics
or tracking and logs no IP addresses (the server's access log is off); IP addresses
exist only in the edge logs.

### 2.6 Recipients

- The hosting provider named in the notice (`LABELING_HOSTING_SUMMARY`), as processor.
- The identity provider used to sign in (Google, when the realm brokers it) for the
  sign-in itself; this is unchanged since V1 and not part of scoring.
- The curator (the owner) for restricted exports and bundles.
- Research recipients of a restricted bundle, only under a written data-sharing
  agreement (decision 5ee0e7ef, question 21) that forbids re-identification, limits
  keeping to at most 1 year and obliges deletion on notice.
- The public, through GitHub release assets: aggregate labels only, which are not
  personal data for a member of the public (section 4, R9).

### 2.7 Retention

| store | retention |
|---|---|
| sign-in identity in the app | until erasure; never-consented profiles erased 30 days after creation |
| Keycloak user | deleted manually by the curator within 30 days of an erasure (automation is task 9387e33d) |
| answers and consent records | kept; after erasure under a new random id with day-level timestamps |
| answer timing (`elapsed_ms`) | set to NULL 90 days after the answer; NULL at once on erasure |
| showings (`label_assignment`) | unanswered rows deleted 30 days after last shown; answered rows until erasure |
| score rows and item posteriors | deleted 30 days after their run finished, pinned runs included; the latest done run is kept while it is the latest |
| scoring run rows | kept (no personal data) |
| admin and trust events | kept; identifying erasure details only until the erasure is completed; redacted on erasure |
| database backups | 14 days |
| edge logs (IP addresses) | the period in `LABELING_EDGE_LOG_RETENTION`, stated in the notice; fixing the log store's retention is a rollout prerequisite |
| curator downloads of restricted files | kept locally only, deleted within 30 days and at once when an erasure is completed for a pseudonym they contain |
| bundles shared under an agreement | at most 1 year |
| erasure list kept outside the database | 60 days (backup retention plus margin) |
| public releases | permanent, never rewritten |

The retention job runs at startup and daily, independently of scoring, so data expire
even when no runs happen and right after a restore.

### 2.8 Systems

One stateless container (non-root, read-only root filesystem) and a PostgreSQL database
on the owner's Kubernetes cluster, behind a TLS-terminating reverse proxy; a Keycloak
realm for sign-in (PKCE, RS256 access tokens checked for issuer, audience, expiry and
client); database backups with 14-day retention. The scoring code is pure Python with no
external service calls; no language model or third-party API sees any data. Known
gap, tracked separately: NetworkPolicy is not enforced on the cluster that hosts the
app, so isolation rests on authentication and the ingress.

### 2.9 Legal bases

| processing | basis |
|---|---|
| creating the profile at sign-in, before the gate | Art. 6(1)(b), steps at the person's request before entering the terms |
| taking part under the terms, including the licence of contributions | Art. 6(1)(b) |
| recording answers and publishing the aggregated dataset | consent, Art. 6(1)(a), through the separate participation statement |
| trust scoring, abuse detection, quarantine, rate limits, blocking | Art. 6(1)(f), balanced in section 3.5; the notice is information, not consent |
| keeping answers after erasure under a new random id | Art. 6(1)(f), with Art. 17(3)(d) and the safeguards of Art. 89(1), balanced in section 3.6 |
| edge security logs | Art. 6(1)(f) |
| keeping consent records | Art. 6(1)(c) with Art. 7(1) |

Profiling only after the 1.3 notice: only people who accepted privacy notice 1.3 or
later, terms 1.1 and participation 1.0, all with age threshold 18, are scored, flagged
or counted. Answers of anyone else are stored but not scored or counted until they pass
the 1.3 gate; the next run then includes their earlier answers. Everyone meets the 1.3
gate at their next contribution.

## 3. Necessity and proportionality (Art. 35(7)(b))

### 3.1 Why weighting is needed at all

The contributors are unknown volunteers. An unweighted majority is easy to distort:
the visible corpus suggestion pulls everyone the same way, a script can copy it or look
the sentence up in the public corpus, and several accounts can agree with each other.
Checking every item by hand is not possible: the owner has about 2-3 hours for expert
work in total (decision 5ee0e7ef, questions 23-24), against tens of thousands of items.
Weighting each vote by demonstrated accuracy is the least intrusive way to get labels
whose quality can be stated: it uses only what people do on the site, it affects only
how much their answers count, and it can be measured (the calibration gate). Not
weighting would mean either publishing labels of unknown quality or not running a
public crowd at all.

### 3.2 Why each input

| input | used for | why it is needed | minimisation |
|---|---|---|---|
| answers, including revisions | the votes; θ | the purpose itself | pseudonymous id; latest revision counts |
| shown blind or with suggestion | which checks are discriminating | a check where the suggestion was visible and right says little about skill | same blind rate for everyone, on checks and other items |
| known-answer checks | θ from hard evidence; promotion; `accuracy`, `copy` | the only evidence of accuracy that peers cannot inflate | person sees only daily totals; per-answer results on request |
| answer timing | `fast` (median of the last 30) and, with it, `burst` | the cheapest reliable sign of scripted answering | curator-only, never shown or released; NULL after 90 days and at erasure |
| peer agreement | refines θ between checks | checks are sparse; agreement fills in | half weight, capped at max(h + m, 12) soft observations, never promotes |
| consent rows | the profiling cohort | nobody is profiled before being informed, nobody under 18 | only document, version, age threshold, time, locale, UI version |
| status changes | excluding blocked and quarantined votes; review deadline | moderation must take effect | reasons visible to the person in their export |
| trusted-list anchors | expert references and checks | an independent reference is needed to calibrate | only email hash matching in the app; the list never leaves the dashboard |
| curator item decisions | adjudication, ambiguity, reopening | disputes need a human outcome | about items, not people |

### 3.3 Data minimisation choices

- Pseudonymous ids everywhere: judgments, events, scores, exports and bundles reference
  a random annotator id, never the login subject or email. No file export contains an
  email.
- No IP addresses in the app, no cookies, no tracking, no analytics.
- Day-level timestamps and no timing after erasure.
- Answer timing kept 90 days, then NULL.
- Score and posterior rows kept 30 days after their run.
- The person-facing card is coarse: a band (high θ ≥ 0.85, good ≥ 0.75, needs
  attention < 0.75, not enough data below 12 checks), check counts rounded down to
  tens, agreement rounded to 5 % with at least 20 resolved items.
- Public releases are aggregate only.
- The trusted list holds an email, its hash and at most a first name, only while the
  entry is active.

### 3.4 Information and rights

The privacy notice 1.3, shown before anyone is profiled, has a section on trust
assessment (profiling): what is computed, from what, the effects (weight, more checks,
an automatic review pause of at most 14 days that is not announced on the site and can
be seen in the self-service export, blocking only by a person with a stated reason), the
legal basis and balancing, a link to the public page "Kako radi pouzdanost" with the
logic and formulas, and how to object. The erasure screen and the notice say that
answers stay under a new random id.

Access: "Moji podaci" → "Pouzdanost" shows per kind the tier and band; quarantine is
never shown there, a block is, with its reason. The self-service JSON export contains a
`trust` section: every retained run (per kind: tier including quarantined, qualified, θ,
weight, lower bound, known-answer check totals by type, peer agreement and
disagreement, every flag with its values, counts), every status and trust event about
the person (quarantines with flags, clears, anchor grants and revocations, tier
changes) and plain-language meanings of each field. It says that which answers were
checks on items still in use is not included; on request by email the controller
retires those items and sends the per-answer result within one month. Answers on
retired or retracted known-answer items are marked `checked_against_known_answer`
without a request.

Objection (Art. 21): by email to the controller. The consequence is that the person's
answers are no longer used (status blocked, reason objection) and erasure is offered.
Erasure is self-service at any time.

### 3.5 Balancing test for trust scoring (Art. 6(1)(f))

Interest. The controller has a legitimate interest in a dataset of known quality for
research on Croatian stemming, and in protecting a public volunteer project from
scripted, copied or malicious contributions. Contributors share that interest: their
work is worth more when bad work does not dilute it.

Necessity. Section 3.1: no less intrusive means gives labels of stated quality from
unknown volunteers. Each input is justified in section 3.2 and reduced in 3.3.

Impact on the person. Low. The outputs act only inside the site: how much their answers
count and which items they see. They are not public, not used for anything outside the
site, not combined with other data and not shared except as pseudonymous restricted
bundles under an agreement. Participation is voluntary and unpaid; nothing about money,
employment, legal status or reputation depends on it. The data are adults' judgments
about words. The worst automated outcome is that their answers do not count for at most
14 days without a person deciding; the person can keep labeling and can see in their
export that it happened and why.

Reasonable expectations. People are told before they are profiled (the 1.3 gate) and
the logic is public. Someone contributing to a crowd-labelling project expects some
quality control.

Safeguards. Two distinct hard flags before any automatic action; anchors never
quarantined automatically; a 14-day review deadline with automatic release; blocking
only by a person with a reason; full visibility in the export; easy objection and
erasure; retention limits; no scoring before the notice.

Result: the controller's interests are not overridden by the participants' interests,
rights and freedoms.

### 3.6 Balancing test for keeping answers after erasure

What is kept. The person's answers and consent records, moved to a new random id with
new row ids, timestamps cut to the day and no timing. Their identity (sign-in subject,
email, Keycloak user), their score rows in every run, their anchor status, the reasons
and signal values in events about them, and the support of consensus gold they backed
are deleted or redacted in the same transaction.

Why it is needed. The dataset is the purpose of the project (decision 5ee0e7ef,
question 20). Every label is computed from all counted votes; removing one person's
votes would change or remove labels that may already be in permanent public releases,
break the reproducibility of earlier runs and could undo items other people's work
resolved. Art. 17(3)(d) allows the controller to keep data needed for scientific
research where erasure would seriously impair that research, with the safeguards of
Art. 89(1): here pseudonymisation, deletion of the identity, day-level times, no timing,
and aggregate-only publication.

Basis. Continued processing of the retained answers rests on the controller's
legitimate interest in a scientific dataset (Art. 6(1)(f)). The participation statement
(consent) covers recording answers while the account exists. The change of basis at
erasure is not silent: the notice says before the person consents, and again on the
erasure screen, that answers stay in the dataset under a new random id. EDPB Guidelines
05/2020 on consent say a controller may not quietly move processing from withdrawn
consent to another basis; informing in advance, and the research exemption, are what
this design relies on. Without legal review this remains the main legal judgement call
of the design, and it is recorded here so the owner reads it.

Impact. Low. After erasure nothing in the live database links the person to the new id;
what could be learned by someone who could still link them (section 6) is how they
judged Croatian words, which is not sensitive.

Result: keeping the answers is justified. A person who wants their answers gone rather
than kept can object first: their answers then stop being used (status blocked, reason
objection), and the erasure of a blocked person deletes their answers instead of moving
them.

## 4. Risks to rights and freedoms (Art. 35(7)(c))

Likelihood: remote, possible, likely. Severity for the person: minimal, limited,
significant. Residual is after the measures of section 5.

| # | risk | likelihood | severity | main measures | residual |
|---|---|---|---|---|---|
| R1 | Wrong automatic quarantine of an honest person (fast reader, unlucky checks) | possible | minimal: answers set aside, nothing else changes | two different hard flags; anchors exempt; 14-day review and automatic release; export shows it; objection | low |
| R2 | Silent quarantine: the person cannot contest what they are not told | likely when a quarantine happens | minimal | notice and trust page say pauses happen without notice and for how long; export shows each with flags and values; human review within 14 days | low |
| R3 | Unfair weighting from model error, including correlated errors through the suggestion | possible | minimal: only vote weight inside the site | gold-only promotion; tier ceilings; θ floor 0.5 (no negative weight); peer cap; calibration gate; blind showings | low |
| R4 | Wrong blocking | remote | limited: no further participation | never automatic; written reason shown to the person; objection by email; votes recomputed when unblocked | low |
| R5 | Re-identification of an erased person from retained answers | remote | minimal: how someone judged words | re-keying with new row ids; day-level time; no timing; redaction of events; gold support redacted; scores deleted; backups 14 days; curator download rules; recipients told to delete | low, accepted (section 6) |
| R6 | Re-identification or profiling from behaviour in restricted files (timing, answer patterns, per-vote rows) | remote | limited | curator-only; no email in any file; download rules; bundles only under agreement, at most 1 year; timing NULL after 90 days | low |
| R7 | Known-answer leakage: checks become predictable or their answers known | possible | minimal for persons (integrity risk) | secret key never leaves the database or enters a bundle; responses identical for checks and other items; export gives daily totals only; disclosure ends an item's use as a check; served-out retirement at 150 showings | low |
| R8 | Misuse of restricted exports or bundles by the curator or a recipient | remote | limited | written agreement forbidding re-identification; at most 1 year; deletion notices on erasure; local copies deleted within 30 days; no emails | low, accepted for a recipient ignoring a notice (section 6) |
| R9 | Inference about one vote from public releases | remote | minimal | aggregate only; no ids, counts or timestamps; three-voter and non-pivot rules; owner-decided rows carry no band; release-check fails closed | low, accepted (section 6) |
| R10 | Data-sharing recipients outside the controller's control | remote | limited | only pseudonymous bundles; agreement terms; nothing shared by default | low |
| R11 | Profiling people who were not informed, or minors | remote | limited | profiling cohort requires notice 1.3, terms 1.1, participation 1.0 with age 18; others not scored | low |
| R12 | Breach of the database (pseudonymous behaviour plus emails) | remote | limited | authentication on every route; no IP in the app; non-root read-only container; 14-day backups; known gap: no enforced NetworkPolicy (tracked) | low to medium, as before V2 |
| R13 | Function creep: scores used for rankings, rewards or outside the site | remote today | limited to significant if it happened | not built; any such change is a review trigger (section 9) | low |

Notes on the larger ones:

- R1 and R2. The flags are blunt by design and an honest person can trip one (a fast
  expert can trip `fast`). One flag never acts; two different flags are needed in the
  same run, counted across kinds. The effect is limited to the dataset's weighting and
  the duration is bounded: after 14 days without a human decision the next run releases
  the quarantine. The owner chose silence so that an honest mistake is not met with an
  accusation (decision 5ee0e7ef, question 14); the transparency is moved to the notice,
  the public page and the export. A person who erases during a quarantine has their
  answers deleted rather than moved.
- R7. Gold is mainly a risk to the dataset, but it touches a right: the access export
  could map the active check pool if it listed per-answer results. The export therefore
  gives totals, and per-answer detail is given on request after the items are retired
  (so the answer can no longer be used as a test), within the one month of Art. 12(3).
- R9. See section 6.2.

## 5. Measures (Art. 35(7)(d))

### 5.1 Pseudonymisation and minimisation

Random annotator ids in all processing and files; identity only in `label_annotator`
(subject, verified email) and the Keycloak realm; no emails in any file export; the
trusted list never leaves the dashboard and its entries hold only an email, its hash and
a first-name note. Other measures as in section 3.3.

### 5.2 Bounded influence

Per item and epoch at most 5 low and 3 expert first answers count; answers beyond are
kept but not counted, so a flood of accounts cannot exhaust or contest an item. Tier
ceilings (new 0.78, qualified 0.80, established 0.95, anchor 0.98; new was 0.75 up to
0.3.0) bound one account's weight. Peer evidence counts half and is capped. Promotion
reads known-answer checks only. Resolution needs an established or anchor vote for the
winner and two people; one anchor answer never resolves an item alone. Daily cap of 3000
answers and per-minute rate limits.

### 5.3 Quarantine safeguards

Two different hard flags; anchors never automatically; votes stop counting but nothing
else changes; review within 14 days (dashboard alert at 7); automatic release after 14
days without a decision; keep and block only by a person with a reason; the export
shows every quarantine with its flags and values and how it ended; objection by email.

### 5.4 Exports and releases

Restricted files are curator-only. The download dialog states the rule: keep locally
only, delete within 30 days and at once when an erasure is completed for a pseudonym the
file contains. Bundles go to third parties only under a written data-sharing agreement,
for at most 1 year.

Public releases are built only from a pinned run that is not stale (no moderation event
after its watermark), by `croatian-stemmer-labels release`, and checked by
`croatian-stemmer-labels release-check`, which fails closed unless: the file set and each
file's columns equal the allowlist; no column name mentions annotators, emails,
creation times, timing, tiers, weights, counts, votes or flags; no value contains `@` or
equals any annotator id; no item is a known-answer item still in use; every model,
reference or review row has at least 3 distinct counted crowd voters and no pivotal one;
and only model rows carry a confidence band. Releases are published only as GitHub
release assets of the croatian-stemmer repository and never rewritten.

### 5.5 The publication fence and append-only journals

Judgments, consents, admin events, trust events and item audit rows are append-only,
enforced by database triggers; the only permitted changes are the erasure re-keying and
redaction, the deletion of an erased blocked or quarantined person's rows, and nulling
`elapsed_ms`. A scoring run only appends the events it decided. It publishes only if no
moderation event (block, clear, erasure, anchor change, gold change, item decision,
parameter change) arrived after its watermark; otherwise it is superseded and rerun.
So a run can never publish over a block, a release from quarantine or an erasure it did
not see, and every run can be replayed and checked.

### 5.6 Erasure in V2

In one transaction: answers and consents move to a new random id N with new row ids,
day-level time and no timing (deleted instead if the person was blocked or quarantined at
that moment); other admin and trust events about the old id O are redacted to {kind,
from, to, run_id} (no reasons, flags or signal values); consensus gold O supported is
retracted (reason erasure) and its support redacted to {"redacted": true}; O's anchor is
revoked; a trusted-list entry matching O's verified email loses its email, hash and
label; O's score rows are deleted in every run. N starts with no tier memory and no
anchor status and is scored from the moved answers at the next run. The Keycloak user is
deleted by the curator within 30 days. A restore of an older backup re-applies the
erasures requested after it, from the erasure list kept outside the database for 60
days.

### 5.7 Retention

As in section 2.7, enforced by the daily retention job for scores, posteriors, timing
and showings.

### 5.8 Profiling only after the notice

The profiling cohort rule (section 2.9) is evaluated identically by every run and at
answer time; scoring itself is off after migration 003 until the owner has read this
assessment and switches it on.

## 6. Residual risks and why they are accepted

### 6.1 Linking retained answers to an erased person

After an erasure, nothing in the live database links O to N. Someone holding O's
pre-erasure history could still match it to N by items, answers and days: the
curator's local downloads until they are deleted (at once at erasure completion, at the
latest 30 days after download), a database backup for up to 14 days, or a data-sharing
recipient who ignores a deletion notice (indefinitely). The journal sequence numbers of
the moved rows are kept for the watermark, so an insider who also kept O's history could
guess which N followed which O.

Accepted because: the identity link is deleted at once; the copies are restricted and
short-lived, and recipients are bound by an agreement; what could be learned is how
someone judged Croatian words, which is not sensitive; and keeping the contributions is
the purpose of the dataset (decision 5ee0e7ef, question 20). The privacy notice states
this risk in one sentence.

### 6.2 Inference from public releases

Whether a row appears, and its confidence band, depend on every counted vote. Example:
three established voters at θ = 0.85 all answer A; confidence 0.9945, and 0.9698 without
any one of them, so the row appears in the higher band. Had the third answered B, the
posterior would be 0.85 and there would be no row. Someone who knows how two voters
answered therefore learns how the third answered. The three-voter and non-pivot rules
narrow this; they do not close it, and no useful label release can.

For a member of the public the rows carry no identifier and nobody's participation is
shown anywhere, so this needs outside knowledge that a particular person voted on a
particular item, which in practice only that person or someone watching them has: the
release is anonymous for them. For the controller while the account exists, the rows on
items the person voted on relate to them, which is processing the person consented to
(publication of aggregated labels). After an erasure, see 6.1.

Accepted because: the inference requires knowing two other votes and that the person
voted on the item; it reveals one judgment about a word; and the alternative, publishing
nothing, defeats the purpose.

### 6.3 Others

- A competent person who earns `established` on several accounts and then votes wrong on
  chosen items can resolve some items wrongly; the damage is bounded by the accounts and
  items, `review_loss` catches systematic losing against the owner, and blocking
  reverses it at the next run. This is a dataset risk, not a risk to anyone's rights.
- A single anchor's mistakes become final answers on checked items (decision 5ee0e7ef,
  questions 23-24); three established reviewers can contest gold.

## 7. Art. 22 assessment

| outcome | automated | effect on the person | duration | human involvement |
|---|---|---|---|---|
| weight of answers | yes | how much their answers count in a volunteer dataset; no effect outside the site; not public | each run | not needed |
| more known-answer checks | yes | a slightly different mix of items | each run | not needed |
| automatic quarantine (silent) | yes | answers stop counting for a while; nothing changes in what they can do or see (sign-in, labeling, export, erasure all continue) | at most 14 days unless the curator decides to keep it | review by the curator within 14 days; anyone may write to object |
| blocking | no | no further participation; shown with the reason | until lifted | curator decision with a written reason |

None of the automated outcomes affects legal rights, money, access to a necessary
service, employment or reputation; participation is voluntary and unpaid. The silent
quarantine has even less effect on the person than a visible one: they can do
everything as before and only the dataset's weighting changes, for at most 14 days. On
that assessment Art. 22(1) is not engaged. Transparency is kept by the notice, the
public trust page and the export.

## 8. Conclusion and prior consultation

Each risk in section 4 is low after the measures, the breach risk R12 being low to
medium and unchanged by V2. The remaining risks of section 6 are limited in likelihood
(they need copies that exist only briefly or under an agreement, or outside knowledge of
other votes) and in severity (judgments about words, no special categories, no effect
outside a voluntary site). No high residual risk remains. Prior consultation with AZOP
under Art. 36 is therefore not required.

The owner may switch `scoring_enabled` on once they have read this document, they are on
the trusted list and have passed the 1.3 gate, and the hr500k known-answer items are
imported (rollout steps in [labeling-web.md](labeling-web.md)).

## 9. Review triggers

This assessment and the Art. 22 assessment must be redone before any of:

- V3 leaderboards, points made public, rewards or badges shown to others (it must be
  updated before any V3 leaderboard);
- any use of scores outside the site;
- paid participation;
- a longer quarantine, or any automatic blocking;
- new data categories (for example new behavioural signals, device or location data,
  free-text comments);
- sharing with a new kind of recipient, or publishing anything per vote or per
  contributor.

If a reassessment finds a similarly significant effect under Art. 22, the decision gets
human review before it takes effect.

## Differences from the plan

The plan put this document in server-config-ivanka
(`environments/marica/apps/labeling/DPIA.md`), next to the records of processing. It
lives in this repository as `docs/labeling-dpia.md` instead, next to the code and
documents it describes, so it is versioned with the app release it applies to.

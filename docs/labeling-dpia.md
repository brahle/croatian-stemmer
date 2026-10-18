# Data protection impact assessment: crowd labeling with trust scoring

- Version 2.0, 18 October 2026.
- Controller: the person named as controller in the privacy notice (set at deployment as
  `LABELING_CONTROLLER_NAME`, contact `LABELING_CONTROLLER_EMAIL`).
- Status: draft for the controller's sign-off. Signed off: ____________________
  (date: __________)
- Scope: the labeling web app of croatian-stemmer from 0.3.0 on, with privacy notice 1.3,
  until a change listed in section 7 is made. The current model and its parameters are in
  [trust.md](trust.md), operation in [labeling-web.md](labeling-web.md).
- The controller's own assessment under GDPR Art. 35, prepared by the implementing agent;
  not legal advice, and without external legal review.

## 1. Why an assessment is done

AZOP's list of operations requiring a DPIA (decision of 21 December 2018, KLASA
004-04/18-01/01) was checked. Item 3 (profiling of children) does not apply: only people
who confirmed they are 18 or over are scored. Items 1 (profiling that helps decide access
to a service) and 11 (systematic monitoring of behaviour) are arguable: scores decide how
much answers count, a pause sets answers aside, and abuse signals watch timing and
behaviour. Two WP248 criteria apply (scoring, systematic monitoring), so the assessment is
done rather than argued away.

## 2. The processing (Art. 35(7)(a))

### 2.1 Purposes

Volunteers sign in and judge Croatian words: whether two forms share a lemma, the lemma of
a form, whether a proposed stem is acceptable. Every answer is a vote weighted by how
reliable its author has proven to be. The purposes are:

1. an open, reliable labelled dataset for the stemmer;
2. trust scoring, so careful work counts more than careless or copied work;
3. detecting scripted, copied or careless answering, and setting it aside for review;
4. curation by the controller, with restricted exports and reproducible calculations;
5. publishing aggregate labels;
6. keeping answers after erasure, so the dataset and its releases stay consistent.

### 2.2 Data subjects

Adult volunteers (18 or over, self-confirmed) who sign in through a sign-in server, usually
with a Google account; unpaid, voluntary, free to stop at any time. Experts are
participants on a trusted list kept by the controller; today the controller is the only
expert and the only curator.

### 2.3 Data categories

- Sign-in identity: in the app, the sign-in account identifier and verified email; in the
  sign-in server, also the Google account identifier and first and last name.
- A random participant identifier (pseudonym), to which everything below is linked.
- Consent records: document, version, time, language, app version, age confirmation.
- Answers: the answer, a typed lemma, the irregular-form flag, revision and time, app
  version, and whether the corpus suggestion was shown.
- Answer timing (time per answer) and showings (which items were shown, when, how often).
- Derived reliability data: per person and kind, an accuracy estimate, a level, the weight
  of their answers, abuse signals with their values and check counts; per item, answer
  probabilities and each counted vote's contribution under the pseudonym.
- Event records: status and level changes with reasons, pauses with their signals, expert
  grants and revocations.
- The trusted list: an expert's email, its hash and a note of at most a first name.
- Edge logs at the reverse proxy: IP address, time, path, user agent. The app keeps no
  access log and never sees IP addresses.

No special-category (Art. 9) or criminal-offence (Art. 10) data are processed. The
free-text lemma field could carry something personal, so releases refuse values that look
like contact data. The app sets no cookies, keeps no persistent browser storage and runs
no analytics or tracking.

### 2.4 Recipients and processors

- Google (Google Ireland Limited and Google LLC): sign-in provider and independent
  controller of the Google account. Sign-in may be processed in the United States under
  the EU-U.S. Data Privacy Framework adequacy decision, the only transfer outside the
  EU/EEA.
- The hosting provider (processor) running the app, database, sign-in server and reverse
  proxy, named with its country in the privacy notice from the deployment configuration.
  This assessment assumes it is in the EU/EEA, as the notice's section on transfers
  implies.
- The controller as curator: restricted exports and calculation bundles.
- Researchers, only under a written agreement: a pseudonymous package without names or
  emails, kept at most one year, no re-identification, erased people's rows deleted on
  notice.
- The public: item texts and aggregate labels, attached to releases of the croatian-stemmer
  repository on GitHub.

No other processors; no language model or third-party API sees the data.

### 2.5 Legal bases

| processing | basis |
|---|---|
| creating the profile at first sign-in, before acceptance | Art. 6(1)(b), steps before taking part |
| taking part under the terms, including the licence of contributions | Art. 6(1)(b) |
| recording answers and publishing the aggregated dataset | consent, Art. 6(1)(a), through the participation statement |
| trust scoring, abuse detection, pauses, rate limits, blocking | Art. 6(1)(f), balanced in 3.3 |
| keeping answers after erasure under a new random identifier | Art. 6(1)(f) with Art. 17(3)(d) and 89(1), balanced in 3.4 |
| edge security logs | Art. 6(1)(f) |
| keeping consent records | Art. 6(1)(c) with Art. 7(1) |

Only people who accepted privacy notice 1.3 or later, the terms and the participation
statement, with the age confirmation, are scored, flagged or counted.

### 2.6 Retention

These are the periods the privacy notice (section 6) promises; they must stay equal.

| data | kept |
|---|---|
| profile in the app (sign-in account identifier, email) | until erasure; a profile that never accepts is erased 30 days after the first sign-in |
| account on the sign-in server (name, email) | until erasure; deleted within 30 days of an erasure request, the app keeping only the account identifier with the request until then |
| answers | indefinitely; on erasure moved to a new random identifier with only the day of each answer, or deleted if the profile was blocked or set aside |
| time taken per answer | 90 days from the answer; at once on erasure |
| showings | unanswered: 30 days after last shown; answered: until erasure |
| reliability assessments (per person and per item) | 30 days after their calculation; the latest results until replaced |
| records of status and level changes | as long as the answers; on erasure reduced to the kind of change |
| consent records | as long as the answers given under them, moving or deleted with them |
| trusted-list entry | until removed or erasure |
| files the controller downloads | at most 30 days, and at once when an erasure is completed for a pseudonym they contain |
| packages shared with researchers | as the agreement says, at most one year |
| database backups | the period printed in the notice from the deployment configuration (14 days as assessed) |
| edge logs | the period printed in the notice from the deployment configuration |
| published releases | permanently, never changed |

A retention task applies these at startup and daily, whether or not scoring runs.

### 2.7 The logic of trust scoring

For each participant and kind of task the app estimates how likely their answers are to be
right. The estimate rests mainly on items whose answer is known in advance, mixed in
unannounced; some items are shown without the corpus suggestion, so that judging can be
told apart from confirming. Newcomers first take an announced knowledge check. Agreement
with other participants refines the estimate between checks, but counts for less, is
capped and never by itself raises a level. Each level (new, qualified, established,
expert) caps the estimate so no one account dominates, and an unreliable account is
ignored rather than counted in reverse.

The estimate sets how much each answer weighs when an item's label is computed. A label is
accepted only when enough independent, reliable answers agree, one of them from an
experienced participant, and once a sample checked against the controller's own answers
shows the rule holds.

Signs of abuse are: answering faster than reading allows, long runs of identical answers,
poor accuracy on known-answer items, repeating a wrong suggestion, systematic disagreement
with the expert, and bursts of volume. One sign does nothing; two different signs in one
calculation pause the person's answers for review ("set aside").

Inputs: answers and revisions, whether the suggestion was shown, known-answer results,
timing, agreement with others, consent records and status. The calculation repeats
periodically and is reproducible.

The outputs affect three things, all inside the project: how much the person's own answers
weigh; which items they are shown (how often checks appear, and whether items needing an
experienced voter are offered); and whether their answers are set aside pending review.
Nothing else depends on them: not access, money or ranking, nor anything outside the
project.

## 3. Necessity and proportionality (Art. 35(7)(b))

### 3.1 Necessity and minimisation

The contributors are unknown volunteers. An unweighted majority is easy to distort: the
suggestion pulls everyone the same way, a script can copy it, accounts can agree with each
other. Checking every item by hand is impossible: the controller has a few hours of expert
time against tens of thousands of items. Weighting by demonstrated accuracy is the least
intrusive way to labels of stated quality; the alternatives are labels of unknown quality
or no public crowd.

Each input is needed: known-answer results are the only evidence others cannot inflate;
the suggestion's visibility shows which checks test skill; timing is the cheapest sign of
scripting; agreement fills gaps between checks. Everything uses the pseudonym and no
export contains an email; timing is controller-only and short-lived; the site shows a
coarse view and the export the detail; the trusted list never leaves the dashboard.

### 3.2 Information and rights

The privacy notice, accepted before profiling, explains what is computed and from what,
the effects including the unannounced pause of at most 14 days, the basis and balancing,
and objection; the public page "How reliability works" explains the logic. The notice and
erasure screen say answers stay under a new random identifier.

"My data" shows a simplified view; the self-service export holds every retained
calculation about the person, every signal with its values, every status and level change
and the meaning of each field. It omits which answers were checks on items still in use,
which would reveal them; on request the controller retires those items and sends the
results within one month. Objection (Art. 21) is by email: the answers are then no longer
used (status blocked, reason "objection") and erasure is offered. Erasure is self-service.

### 3.3 Balancing test: trust scoring (Art. 6(1)(f))

Interest: a dataset of known quality for research on Croatian, and protecting a volunteer
project from scripted, copied or malicious contributions, which contributors share.

Necessity: 3.1.

Impact: low. The outputs act only inside the site, in the three ways of 2.7. They are not
public, not combined with other data, and shared only pseudonymously under an agreement.
Nothing about money, employment, legal status or reputation depends on them, and the data
are judgments about words. The worst automated outcome is that a person's answers do not
count for at most 14 days without a human decision, while they keep labeling and can see
why in their export.

Expectations: people are told before profiling and the logic is public; crowd contributors
expect quality control.

Safeguards: 4.2.

Result: the controller's interests are not overridden by the participants' interests,
rights and freedoms.

### 3.4 Balancing test: keeping answers after erasure

What is kept: answers and consent records under a new random identifier with new record
identifiers, times cut to the day, no timing. In the same step the identity is deleted
(the sign-in account within 30 days), as are the person's assessments, expert status and
the reasons and values in records about them; known answers they backed as an expert are
withdrawn.

Why: the dataset is the purpose. Every label is computed from all counted votes; removing
one person's votes would change labels already in permanent releases, break reproduction
of earlier calculations and undo items others' work resolved. Art. 17(3)(d) permits
keeping data needed for scientific research where erasure would seriously impair it, with
the Art. 89(1) safeguards: pseudonymisation, deletion of the identity, day-level times, no
timing, aggregate-only publication.

Basis: legitimate interest in a scientific dataset (Art. 6(1)(f)); consent covers
recording answers while the account exists. EDPB Guidelines 05/2020 forbid quietly moving
processing from withdrawn consent to another basis; here the change is announced before
consent and again on the erasure screen, and rests on the research exemption. Without legal
review this is the design's main legal judgement call.

Impact: low. Nothing in the live database links the person to the new identifier, and a
linker would learn only how they judged words.

Result: justified. A person who wants the answers gone can object first; once blocked for
that reason, erasure deletes them instead of moving them.

## 4. Risks and safeguards (Art. 35(7)(c) and (d))

### 4.1 Risks

Residual risk is after the safeguards in 4.2.

| risk | likelihood | severity | residual |
|---|---|---|---|
| an honest person's answers set aside by mistake | possible | minimal | low |
| a silent pause cannot be contested by someone unaware of it | likely when a pause happens | minimal | low |
| unfair weighting from model error, including errors correlated through the suggestion | possible | minimal | low |
| wrong blocking | remote | limited | low |
| re-linking an erased person to retained answers | remote | minimal | low, accepted (5.1) |
| re-identification or profiling from restricted files | remote | limited | low |
| known-answer items become predictable | possible | minimal (integrity risk) | low |
| inference about one vote from public releases | remote | minimal | low, accepted (5.2) |
| profiling people not yet informed, or minors | remote | limited | low |
| database breach (pseudonymous behaviour plus emails) | remote | limited | low to medium, unchanged by scoring |
| function creep: scores used for rankings, rewards or outside the project | remote | limited to significant | low while section 7 is respected |

### 4.2 Safeguards

Review pauses. A pause needs two different signs in one calculation; experts are never
paused automatically. During a pause the answers stop counting and more checks appear; the
person can still sign in, label, download data and erase. The controller reviews every
pause within 14 days and ends it, keeps it or blocks; if nobody decides, it ends
automatically after 14 days. Keeping and blocking are human decisions, and a block is
shown with its reason. Erasing during a pause or block deletes the answers.

Why silent, and its limits. The signs are blunt and an honest mistake can trigger them;
announcing a pause would accuse an honest person and teach a script what to avoid.
Transparency moves to the notice, the public trust page and the export, which shows each
pause with its signs, values and outcome. Silence is acceptable only because the effect is
limited to the weight of the person's own answers, bounded in time and reviewed by a
person.

Bounded influence. Levels cap one account's weight; agreement is capped and never
promotes; only a limited number of answers per item count; a label needs several reliable
people, one experienced, and one expert answer never decides alone; rate limits apply.

No per-person publication. Releases carry no identifiers, levels, weights, estimates,
signals, counts or timestamps other than the release date, and are never rewritten. They
are built only from a calculation no later decision has overtaken, and an automated check
refuses any release with a column off the allowlist, anything that looks like an
identifier or contact data, a known-answer item still in use, or a label that rests on too few
voters or on a single deciding vote.

Restricted files are controller-only, contain no emails or the key that picks checks,
and carry the download rule of 2.6. Erasure is immediate (3.4), and a restored backup gets
later erasures re-applied.

Integrity. Answers, consents and events are append-only apart from erasure, redaction and
timing retention; a calculation that missed a moderation decision is discarded and rerun.

Security. Every request that touches personal data is authenticated; restricted functions need the curator role;
connections are encrypted; the app runs with minimal privileges and holds no IP addresses;
backups have limited retention. Network-level isolation inside the hosting environment is
incomplete and tracked separately, hence the breach risk of low to medium.

Scoring is off after installation until the controller switches it on, and applies only to
people past the notice gate.

### 4.3 Article 22

Weighting and the mix of items are automated but affect only how much answers count in a
volunteer dataset. The pause is automated, lasts at most 14 days without a human decision
and changes nothing in what the person can do. Blocking is never automated. None affects
legal rights, money, access to a necessary service, employment or reputation, so Art.
22(1) is not engaged. Transparency is kept by the notice, the trust page and the export,
and anyone may ask for a person to review a decision.

## 5. Residual risks accepted

### 5.1 Re-linking retained answers after erasure

Nothing in the live database links the old pseudonym to the new one. Someone holding the
earlier history could still match it by items, answers and days: the controller's
downloads until deleted, a backup until it expires, or a researcher ignoring a deletion
notice. Accepted because the identity is deleted at once, those copies are restricted,
short-lived or bound by agreement, the content is how someone judged words, and keeping
contributions is the dataset's purpose. The notice states this risk.

### 5.2 Inference from public releases

Whether a label appears, and its confidence, depend on every counted vote, so someone who
knows the other votes on an item can deduce the last one. The voter rules narrow this but
no useful release can close it ([trust.md](trust.md) has an example). For the public, rows
carry no identifier and participation is never shown, so the inference needs outside
knowledge that a given person voted on a given item: for them the release is anonymous.
For the controller, while the account exists, such rows relate to the person, which is the
publication they consented to. Accepted because it needs that outside knowledge, reveals
one judgment about a word, and publishing nothing defeats the purpose.

### 5.3 Dataset risks

Someone who earns the established level on several accounts can resolve chosen items
wrongly; the damage is bounded, disagreement with the expert is one of the signs, and
blocking reverses it. The single expert's mistakes become final on items they check;
established participants can contest them. These are risks to the dataset, not to rights.

## 6. Conclusion and prior consultation

Trust scoring is profiling (Art. 4(4)), but its effects stay inside a voluntary, unpaid
site: answers count more or less, the mix of items changes slightly, and answers can be
set aside for at most 14 days unless a person decides otherwise; blocking is only a human
decision. The data are pseudonymous judgments of adults about words. Each risk is low after the safeguards, the breach risk low to medium and
unchanged by scoring. No high residual risk remains, so prior consultation with AZOP under
Art. 36 is not required. Scoring may be switched on once the controller has signed off
this assessment.

## 7. When this assessment must be revisited

Review this assessment, including the Art. 22 analysis, before any of these takes effect:

- a new purpose, or any use of scores or other derived data outside the project;
- a new category of personal data, such as behavioural signals from inputs not listed in
  2.7, device or location data, or free-text comments about people;
- special-category or criminal-offence data;
- participation by children, or a lower minimum age;
- a new recipient or kind of recipient, a new processor, or hosting or processing in a new
  country, in particular outside the EU/EEA;
- publishing anything per person or per vote: leaderboards, public points, badges, levels
  shown to others, contributor lists;
- a retention period longer than those in 2.6, or dropping a deletion;
- scores affecting anything beyond the weight of the person's own answers, the mix of items
  they are shown and their own set-aside, for example access, rewards or ranking;
- automated blocking or exclusion, a pause without human review, or a review period longer
  than 14 days;
- paid participation;
- a change of legal basis, or scoring people before they are informed.

Code changes, parameter and threshold tuning, and changes to the scoring formula or abuse
signals that stay within the logic of 2.7 (the same inputs, the same three effects, the
same safeguards) do not require revisiting. They are recorded in [trust.md](trust.md) and
the changelog. If a reassessment finds a legal or similarly significant effect under Art.
22, that decision gets human review before it takes effect.

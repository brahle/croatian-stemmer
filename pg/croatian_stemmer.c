/*
 * croatian_stemmer.c — Croatian stemmer (Ljubešić-Pandžić algorithm + autoresearch)
 *
 * Pure C implementation with no external dependencies. Uses byte-level string
 * matching (no regex). Mirrors src/croatian_stemmer/stemmer.py: every step
 * below has a Python counterpart, and tests/test_c_parity.py checks that the
 * two agree.
 *
 * Pipeline (croatian_stem):
 *  1. Stop words are returned unchanged
 *  2. Optional naj- superlative prefix peel (regular -ij comparative case
 *     forms stem the positive; otherwise a fallback path)
 *  3. Per word (stem_word_inner, Python _stem_word):
 *     a. morphophonological transformations
 *     b. the -je-/-ije- verb theme with its ending (class-checked), else
 *        suffix stripping via ordered rules (greedy + non-greedy) with
 *        thematic-vowel and -ova-/-iva-/-uj- normalization
 *     c. post-stemming clean-up: -ići compound -šl- -> -đ-, comparative
 *        -ij, fleeting a in -ak/-ac, -dak/-tk, -kš/-pš comparatives, velar
 *        -gn presents, passive-participle jotation reversal,
 *        -stan/-iran/-ivan/participle -an and fleeting-a -an, monosyllabic
 *        -ov/-ev plural, cluster jotation reversal (no single-consonant
 *        depalatalization)
 *  4. Terminal-i normalization for -ih adjective inputs
 *  5. Final fleeting a in -tar/-bar/-dar and fleeting -ao (Python _fleeting_ar)
 *
 * All lengths compared against Python's len() are codepoint counts; buffers
 * are indexed by byte. Every post-stemming step only shortens the stem (or
 * keeps its byte length), so it is edited in place.
 */

#include "croatian_stemmer.h"
#include "croatian_stemmer_rules.h"

#include <stdlib.h>
#include <string.h>
#include <ctype.h>

/* ------------------------------------------------------------------ */
/*  UTF-8 helpers                                                     */
/* ------------------------------------------------------------------ */

/* Count UTF-8 codepoints in s[0:byte_len]. */
static int
utf8_cplen(const char *s, int byte_len)
{
	int	cplen = 0;
	int	i;

	for (i = 0; i < byte_len; i++)
	{
		if ((s[i] & 0xC0) != 0x80)
			cplen++;
	}
	return cplen;
}

/* Byte offset where the last codepoint of s[0:byte_len] starts (or -1). */
static int
last_codepoint_start(const char *s, int byte_len)
{
	int	i;

	if (byte_len <= 0)
		return -1;
	i = byte_len - 1;
	while (i > 0 && ((unsigned char) s[i] & 0xC0) == 0x80)
		i--;
	return i;
}

/*
 * Byte offset where the n-th codepoint from the end (n >= 1, Python s[-n])
 * starts, or -1 if s has fewer than n codepoints.
 */
static int
codepoint_from_end(const char *s, int byte_len, int n)
{
	int	off = byte_len;

	while (n-- > 0)
	{
		off = last_codepoint_start(s, off);
		if (off < 0)
			return -1;
	}
	return off;
}

/* Byte offset of the codepoint with index n (Python s[n:]), clamped to the end. */
static int
codepoint_offset(const char *s, int byte_len, int n)
{
	int	i;

	for (i = 0; i < byte_len; i++)
	{
		if ((s[i] & 0xC0) != 0x80)
		{
			if (n == 0)
				return i;
			n--;
		}
	}
	return byte_len;
}

static bool
is_ascii_vowel(unsigned char c)
{
	return c == 'a' || c == 'e' || c == 'i' || c == 'o' || c == 'u';
}

/*
 * Python `s[-n] in chars`: true iff the n-th codepoint from the end of
 * s[0:byte_len] is one of the codepoints of the UTF-8 string `chars`.
 */
static bool
codepoint_in(const char *s, int byte_len, int n, const char *chars)
{
	int		off = codepoint_from_end(s, byte_len, n);
	int		end;
	int		cp_len;
	const char *c;

	if (off < 0)
		return false;
	end = (n == 1) ? byte_len : codepoint_from_end(s, byte_len, n - 1);
	cp_len = end - off;

	for (c = chars; *c;)
	{
		int	c_len = 1;

		while ((c[c_len] & 0xC0) == 0x80)
			c_len++;
		if (c_len == cp_len && memcmp(c, s + off, cp_len) == 0)
			return true;
		c += c_len;
	}
	return false;
}

/* True iff the last codepoint of s[0:byte_len] is an ASCII vowel. */
static bool
last_codepoint_is_ascii_vowel(const char *s, int byte_len)
{
	return codepoint_in(s, byte_len, 1, "aeiou");
}

/*
 * Croatian "has vowel" over s[0:prefix_len], judging a syllabic r by its
 * neighbours in the whole s[0:full_len]. Syllabic r stands between
 * consonants (trg, krv, prst, crkva) or starts the word before a consonant
 * (rđa). A stem-final r after a consonant (br-oj, str-oj, vjetr) is not
 * syllabic: it closes the syllable before. Python marks R with
 * re.sub(r"(^|[^aeiou])r(?=[^aeiou])") on the whole word and slices; an r
 * that sub skips always follows a marked R, so testing each r is the same.
 */
static bool
has_vowel_in(const char *s, int prefix_len, int full_len)
{
	int	i;

	for (i = 0; i < prefix_len; i++)
	{
		unsigned char c = (unsigned char) s[i];

		if ((c & 0xC0) == 0x80)
			continue;	/* UTF-8 continuation */

		if (is_ascii_vowel(c))
			return true;

		if (c == 'r')
		{
			bool prev_is_vowel = false;

			if (i > 0)
				prev_is_vowel = is_ascii_vowel((unsigned char) s[i - 1]);
			/* The next codepoint must exist and be a consonant. */
			if (!prev_is_vowel && i + 1 < full_len &&
				!is_ascii_vowel((unsigned char) s[i + 1]))
				return true;
		}
	}
	return false;
}

/* Python _has_vowel(s): any vowel or syllabic r in s[0:byte_len]. */
static bool
has_vowel(const char *s, int byte_len)
{
	return has_vowel_in(s, byte_len, byte_len);
}

/*
 * Python _has_vowel_before(s, cut): a vowel in s[:-cut] (cut in
 * codepoints), judging a syllabic r by the whole word (cvr-čak, škr-tac,
 * smr-zla: the r is syllabic before the cut).
 */
static bool
has_vowel_before(const char *s, int byte_len, int cut)
{
	int	prefix_len = codepoint_from_end(s, byte_len, cut);

	return has_vowel_in(s, prefix_len < 0 ? 0 : prefix_len, byte_len);
}

/*
 * has_vowel() of the candidate s[0:keep] + tail, without building it in the
 * caller. A syllabic r at the seam depends on the tail's first letter.
 */
static bool
candidate_has_vowel(const char *s, int keep, const char *tail)
{
	int		tail_len = (int) strlen(tail);
	char   *buf = malloc(keep + tail_len + 1);
	bool	result;

	if (!buf)
		return false;
	memcpy(buf, s, keep);
	memcpy(buf + keep, tail, tail_len);
	buf[keep + tail_len] = '\0';
	result = has_vowel(buf, keep + tail_len);
	free(buf);
	return result;
}

/*
 * Count syllable nuclei, as Python _syllables(): vowel groups plus a
 * syllabic r between consonants (trg, prst). A stem-final r after a
 * consonant (vjetr, žanr) is not counted: it closes the syllable before it.
 * The long jat reflex -ije- is one syllable (dijel, snijeg). Scans left to
 * right like re.findall(r"ije|[aeiou]+|(?:^|(?<=[^aeiou]))r(?=[^aeiou])").
 */
static int
count_syllables(const char *s, int byte_len)
{
	int	n = 0;
	int	i = 0;

	while (i < byte_len)
	{
		unsigned char c = (unsigned char) s[i];

		if (i + 3 <= byte_len && memcmp(s + i, "ije", 3) == 0)
		{
			n++;
			i += 3;
		}
		else if (is_ascii_vowel(c))
		{
			n++;
			while (i < byte_len && is_ascii_vowel((unsigned char) s[i]))
				i++;
		}
		else
		{
			if (c == 'r' &&
				(i == 0 || !is_ascii_vowel((unsigned char) s[i - 1])) &&
				i + 1 < byte_len && !is_ascii_vowel((unsigned char) s[i + 1]))
				n++;
			i++;	/* continuation bytes never match the cases above */
		}
	}
	return n;
}

static bool
ends_with(const char *word, int word_len, const char *suffix, int suffix_len)
{
	if (suffix_len > word_len)
		return false;
	return memcmp(word + word_len - suffix_len, suffix, suffix_len) == 0;
}

static bool
ends_with_str(const char *word, int word_len, const char *suffix)
{
	return ends_with(word, word_len, suffix, (int) strlen(suffix));
}

static bool
starts_with(const char *word, int word_len, const char *prefix, int prefix_len)
{
	if (prefix_len > word_len)
		return false;
	return memcmp(word, prefix, prefix_len) == 0;
}

/* True iff s[0:byte_len] equals one of the NULL-terminated `set` entries. */
static bool
in_string_set(const char *s, int byte_len, const char *const *set)
{
	for (; *set; set++)
	{
		if ((int) strlen(*set) == byte_len && memcmp(*set, s, byte_len) == 0)
			return true;
	}
	return false;
}

/*
 * Replace the last cut_bytes of the stem with `tail`, in place. The tail is
 * never longer than what it replaces, so the buffer always has room.
 */
static void
replace_tail(char *stem, int *p_len, int cut_bytes, const char *tail)
{
	int	keep = *p_len - cut_bytes;
	int	tail_len = (int) strlen(tail);

	memcpy(stem + keep, tail, tail_len);
	*p_len = keep + tail_len;
	stem[*p_len] = '\0';
}

/* ------------------------------------------------------------------ */
/*  Stop-word lookup                                                  */
/* ------------------------------------------------------------------ */

bool
croatian_is_stopword(const char *word)
{
	int	lo = 0;
	int	hi = N_STOP_WORDS - 1;

	while (lo <= hi)
	{
		int	mid = (lo + hi) / 2;
		int	cmp = strcmp(word, stop_words[mid]);

		if (cmp == 0)
			return true;
		else if (cmp < 0)
			hi = mid - 1;
		else
			lo = mid + 1;
	}
	return false;
}

/* ------------------------------------------------------------------ */
/*  Phase 1: morphophonological transformations                       */
/* ------------------------------------------------------------------ */

/* Returns a malloc'd transformed copy (or copy of original if nothing matched). */
static char *
apply_transforms(const char *word, int word_len)
{
	int	i;

	for (i = 0; i < N_TRANSFORMS; i++)
	{
		if (ends_with(word, word_len, transforms[i].from, transforms[i].from_len))
		{
			int		prefix_len = word_len - transforms[i].from_len;
			int		to_len = (int) strlen(transforms[i].to);
			int		result_len = prefix_len + to_len;
			char   *result = malloc(result_len + 1);

			if (!result)
				return NULL;
			memcpy(result, word, prefix_len);
			memcpy(result + prefix_len, transforms[i].to, to_len);
			result[result_len] = '\0';
			return result;
		}
	}

	{
		char *result = malloc(word_len + 1);

		if (result)
		{
			memcpy(result, word, word_len);
			result[word_len] = '\0';
		}
		return result;
	}
}

/* ------------------------------------------------------------------ */
/*  Phase 2: the -je- theme and ordered suffix-stripping rules        */
/* ------------------------------------------------------------------ */

/* Verbal prefixes, longest first, used to find the root a -je- follows. */
static const char *const verb_prefixes[] = {
	"pred", "pod", "nad", "raz", "ras",
	"pre", "pri", "pro",
	"do", "iz", "na", "ne", "ob", "od", "po", "sa", "za",
	"o", "s", "u",
};

/*
 * Codepoint length of the stem after one leading verbal prefix (the first
 * listed prefix it starts with), keeping at least one letter.
 */
static int
root_after_prefix_cplen(const char *stem, int stem_len)
{
	int		cp = utf8_cplen(stem, stem_len);
	size_t	i;

	for (i = 0; i < sizeof(verb_prefixes) / sizeof(verb_prefixes[0]); i++)
	{
		int	p_len = (int) strlen(verb_prefixes[i]);	/* ASCII */

		if (starts_with(stem, stem_len, verb_prefixes[i], p_len) && cp > p_len)
			return cp - p_len;
	}
	return cp;
}

/*
 * -je-/-ije- verbs (vidjeti, voljela, donijeli): the jat reflex is their
 * thematic vowel, which the present and the -io participle drop (vidi,
 * vidio, volio, donio). Strip it with the infinitive or l-participle ending.
 * A stem shorter than three letters is left alone (cijela, bijeli, tijelo).
 *
 * Long -ije- is thematic only in -nijeti/-rijeti verbs (donijeti,
 * umrijeti), and only -nijeti keeps it in the l-participle (donijela, but
 * umro/umrla): elsewhere -ije- is a root (podijeliti, odijelo, strijela,
 * primijetiti). Short -je- needs a root of its own before it: after a
 * prefix plus a single consonant it is part of the root (sav-jet, za-vjet,
 * po-djela, do-djela, raz-djela, po-sjet), and a candidate in s is the
 * sjet- root (posjetiti, podsjetiti, prisjetiti).
 *
 * Returns the stem's byte length, or -1 if the word has no such ending or
 * the check fails (no fallback to a shorter ending, like Python).
 */
static int
strip_je_theme(const char *word, int word_len)
{
	static const char *const endings[] = {
		"ijeti", "jeti",
		"ijela", "ijeli", "ijelo", "ijele", "jela", "jeli", "jelo", "jele",
	};
	size_t i;

	for (i = 0; i < sizeof(endings) / sizeof(endings[0]); i++)
	{
		int	e_len = (int) strlen(endings[i]);

		if (ends_with(word, word_len, endings[i], e_len))
		{
			int	cand_len = word_len - e_len;

			if (utf8_cplen(word, cand_len) <= 2 || !has_vowel(word, cand_len))
				return -1;
			if (endings[i][0] == 'i')	/* -ije- */
			{
				const char *allowed = strcmp(endings[i], "ijeti") == 0 ? "nr" : "n";

				if (!codepoint_in(word, cand_len, 1, allowed))
					return -1;
			}
			else if (word[cand_len - 1] == 's' ||
					 root_after_prefix_cplen(word, cand_len) == 1)
				return -1;
			return cand_len;
		}
	}
	return -1;
}

/*
 * Verbal endings that follow the thematic vowel (rad-i-la, gled-a-ti):
 * l-participle, infinitive, present person endings, imperative, aorist and
 * imperfect, past and present gerund. Case endings (-lu, -lom, -ama, ...)
 * are absent.
 */
static const char *const thematic_endings[] = {
	"l", "la", "li", "lo", "le", "o", "lu", "lom", "lima", "lama",
	"lih", "lim", "log", "loga", "loj", "lome", "lomu",
	"ti", "t",
	"m", "š", "mo", "te", "ju",
	"j", "jmo", "jte",
	"h", "še", "smo", "ste", "hu",
	"vši", "jući",
	/* -j- present of vowel stems (dobi-je, razumi-jem, pozna-je) */
	"je", "jem", "ješ", "jemo", "jete",
	NULL
};

/* Byte length of the UTF-8 codepoint starting at s. */
static int
codepoint_bytes(const char *s)
{
	int	n = 1;

	while ((s[n] & 0xC0) == 0x80)
		n++;
	return n;
}

/*
 * Byte length of the pattern atom at pat: one literal codepoint, or a whole
 * `[...]`/`[^...]` class.
 */
static int
atom_bytes(const char *pat)
{
	if (*pat == '[')
		return (int) (strchr(pat, ']') - pat) + 1;
	return codepoint_bytes(pat);
}

/* Number of atoms in a stem-ending pattern. */
static int
count_atoms(const char *pat)
{
	int	n = 0;

	for (; *pat; pat += atom_bytes(pat))
		n++;
	return n;
}

/*
 * True iff the codepoint s[0:cp_len] matches the atom at pat: equal to a
 * literal, in a `[...]` class or not in a `[^...]` class (any letter,
 * Croatian or not, like the regex).
 */
static bool
atom_matches(const char *pat, const char *s, int cp_len)
{
	const char *c;
	const char *end;
	bool		negated;

	if (*pat != '[')
		return codepoint_bytes(pat) == cp_len && memcmp(pat, s, cp_len) == 0;

	end = strchr(pat, ']');
	negated = pat[1] == '^';
	for (c = pat + (negated ? 2 : 1); c < end; c += codepoint_bytes(c))
	{
		if (codepoint_bytes(c) == cp_len && memcmp(c, s, cp_len) == 0)
			return !negated;
	}
	return negated;
}

/*
 * The head (the stem before its ending, s[0:head_len]) against the rule's
 * head constraint: HEAD_ALL needs every codepoint in head_class
 * (`[^aeiou]+raj`), HEAD_SOME at least one (`.*[aeiou].*ij`).
 */
static bool
head_matches(const char *s, int head_len, const StemRule *rule)
{
	int	i;

	if (rule->head_mode == HEAD_ANY)
		return true;

	for (i = 0; i < head_len; i += codepoint_bytes(s + i))
	{
		bool in_class = atom_matches(rule->head_class, s + i,
									 codepoint_bytes(s + i));

		if (rule->head_mode == HEAD_ALL && !in_class)
			return false;
		if (rule->head_mode == HEAD_SOME && in_class)
			return true;
	}
	return rule->head_mode == HEAD_ALL;
}

/*
 * True iff the stem matches the rule's stem pattern: it ends in one of the
 * rule's endings (atoms matched codepoint by codepoint) with at least
 * min_extra codepoints before it (".+" needs one, ".*" none) that satisfy
 * the head constraint.
 */
static bool
stem_matches(const char *stem, int stem_len, const StemRule *rule)
{
	int	stem_cp;
	int	i;

	if (rule->n_stem_ends == 0)
		return true;	/* catch-all (.+ or .+?) */

	stem_cp = utf8_cplen(stem, stem_len);
	for (i = 0; i < rule->n_stem_ends; i++)
	{
		const char *pat = rule->stem_ends[i];
		int		n_atoms = count_atoms(pat);
		int		head_len;
		int		off;

		if (stem_cp < n_atoms + rule->min_extra)
			continue;

		head_len = codepoint_offset(stem, stem_len, stem_cp - n_atoms);
		for (off = head_len; *pat; pat += atom_bytes(pat))
		{
			int	cp_len = codepoint_bytes(stem + off);

			if (!atom_matches(pat, stem + off, cp_len))
				break;
			off += cp_len;
		}
		if (*pat == '\0' && head_matches(stem, head_len, rule))
			return true;
	}
	return false;
}

/* A verb root before a derivational suffix: three letters and a vowel. */
static bool
is_root(const char *stem, int stem_len)
{
	return utf8_cplen(stem, stem_len) > 2 && has_vowel(stem, stem_len);
}

/*
 * Iterate through rules in declared order; within each rule, suffixes are
 * already sorted by gen_rules_c.py to match Python regex greediness:
 *   greedy  .+   → ascending byte length (first match = longest stem)
 *   lazy    .+?  → descending byte length (first match = shortest stem)
 *
 * The stem is word[0:returned length], except that the thematic-vowel and
 * -ova-/-iva-/-uj- steps may rewrite its tail in place. *p_has_ending says
 * whether the matched rule removed a non-empty ending (Python
 * _Stripped.ending).
 */
static int
strip_suffixes_inplace(char *word, int word_len, bool *p_has_ending)
{
	int	i;

	for (i = 0; i < N_RULES; i++)
	{
		const StemRule *rule = &rules[i];
		int	j;

		/*
		 * Mirror Python's `^(stem)(s1|s2|...)$` semantics: the regex picks
		 * exactly one (stem, suffix) split per rule (the regex's first match
		 * in greedy/non-greedy order), then the outer code applies the
		 * validity check once. If validity fails the whole rule is abandoned
		 * — we do NOT keep trying shorter/different suffixes within the rule.
		 */
		for (j = 0; j < rule->n_suffixes; j++)
		{
			int		suffix_len = (int) strlen(rule->suffixes[j]);
			int		stem_len;
			int		stem_cp;
			bool	verbal;

			if (!ends_with(word, word_len, rule->suffixes[j], suffix_len))
				continue;

			stem_len = word_len - suffix_len;
			if (stem_len <= 0)
				continue;

			if (!stem_matches(word, stem_len, rule))
				continue;

			/* Found the rule's regex match — validity gate applies once. */
			stem_cp = utf8_cplen(word, stem_len);
			if (!(stem_cp > 1 && has_vowel(word, stem_len)))
				break;	/* abandon rule, mirror Python's `re.match` semantics */

			/*
			 * Thematic vowel: verb rules keep it on the stem (radi-la,
			 * gleda-ti) while the bare forms lose it to the catch-all
			 * (radi -> rad, gleda -> gled). Drop it so they agree. Only
			 * non-catch-all rules with a verbal ending count.
			 */
			verbal = !rule->lazy &&
				in_string_set(word + stem_len, suffix_len, thematic_endings);

			/*
			 * The short infinitive -t (gleda-t, radi-t) needs a root
			 * syllable before the thematic vowel: in brat and vrat the r
			 * before -at is not syllabic, so -t is not an ending. Python
			 * moves on to the next rule.
			 */
			if (verbal && suffix_len == 1 && word[stem_len] == 't' &&
				!has_vowel(word, codepoint_from_end(word, stem_len, 1)))
				break;

			*p_has_ending = suffix_len > 0;

			/*
			 * -ovati/-ivati verbs: the infinitive stem -ova-/-iva-
			 * alternates with the present -uj- (djelova-ti/djeluj-e,
			 * pokaziva-ti/pokazuj-e). Map all three to one -iv stem. The
			 * root before the suffix needs three letters and a vowel of
			 * its own: in struj-a the -uj- is part of the root.
			 */
			if (verbal &&
				(ends_with(word, stem_len, "ova", 3) ||
				 ends_with(word, stem_len, "iva", 3)) &&
				is_root(word, stem_len - 3))
			{
				replace_tail(word, &stem_len, 3, "iv");
				return stem_len;
			}
			if (ends_with(word, stem_len, "uj", 2) && !rule->lazy &&
				is_root(word, stem_len - 2))
			{
				replace_tail(word, &stem_len, 2, "iv");
				return stem_len;
			}
			if (verbal && stem_cp > 3 &&
				(word[stem_len - 1] == 'a' || word[stem_len - 1] == 'i') &&
				has_vowel(word, stem_len - 1))
				return stem_len - 1;
			return stem_len;
		}
	}
	*p_has_ending = false;
	return word_len;	/* no rule fired */
}

/* ------------------------------------------------------------------ */
/*  Phase 3: post-stemming clean-up                                   */
/* ------------------------------------------------------------------ */

/*
 * Passive participles of i-verbs jotate the root before -en
 * (objav-iti -> objavlj-en, učin-iti -> učinj-en, vrat-iti -> vrać-en,
 * izgrad-iti -> izgrađ-en). The first matching ending wins.
 */
static const struct
{
	const char *ending;
	const char *root;
}			jotated_participle[] = {
	{"šćen", "st"}, {"šten", "st"}, {"žđen", "zd"},
	{"pljen", "p"}, {"bljen", "b"}, {"vljen", "v"},
	{"mljen", "m"},
	/* sl jotates to šlj (misl-iti -> mišljen, zamišljen, osmišljen). */
	{"šljen", "sl"}, {"ljen", "l"}, {"njen", "n"},
	{"đen", "d"}, {"ćen", "t"},
	/*
	 * i-verbs whose root already ends in a palatal (završ-iti, uključ-iti,
	 * ulož-iti) keep it in the participle (završen, uključen, uložen).
	 */
	{"čen", "č"}, {"šen", "š"}, {"žen", "ž"},
	/*
	 * e-verbs in -sti keep the root dental after -e- (dovesti -> doved-en,
	 * donijeti -> dones-en, plesti -> plet-en).
	 */
	{"eden", "ed"}, {"esen", "es"}, {"ezen", "ez"}, {"eten", "et"},
	/*
	 * i-verbs with a root in vowel + r do not jotate (otvor-iti -> otvoren,
	 * ostvar-iti -> ostvaren, uvjer-iti -> uvjeren, proširiti -> proširen).
	 */
	{"oren", "or"}, {"aren", "ar"}, {"eren", "er"}, {"iren", "ir"},
	/*
	 * -oj- roots keep j (spoj-iti -> spojen); vowel roots insert -v-
	 * (otkri-ti -> otkriven, obu-ti -> obuven), which goes with -en.
	 */
	{"ojen", "oj"}, {"iven", ""}, {"uven", ""},
	/* bi-ti/vi-ti compounds insert -j- instead (ubijen, razvijen). */
	{"bijen", "b"}, {"vijen", "v"},
};

/* Present-tense endings: -stati verbs build the present on -stan-. */
static const char *const present_endings[] = {
	"e", "em", "eš", "emo", "ete", "u", "i", "imo", "ite", NULL
};

/*
 * Python's `transformed[len(stemmed):]`: the part of the transformed word
 * past the stem's codepoint length. The stem may have been rewritten, so
 * this slices by count, not by matching the stem as a prefix.
 */
static const char *
transformed_rest(const char *transformed, int trans_len,
				 const char *stem, int stem_len, int *p_rest_len)
{
	int	off = codepoint_offset(transformed, trans_len,
								   utf8_cplen(stem, stem_len));

	*p_rest_len = trans_len - off;
	return transformed + off;
}

/*
 * Reverse a stem-final alternation: the first `from` the stem ends with is
 * replaced by `to` if the candidate has a vowel and more than one codepoint.
 * Returns true if the stem changed; on a match with an invalid candidate the
 * scan still stops, like the Python dict loop.
 */
static bool
reverse_alternation(char *stem, int *p_len,
					const char *const (*table)[2], size_t n)
{
	size_t k;

	for (k = 0; k < n; k++)
	{
		int	from_len = (int) strlen(table[k][0]);

		if (ends_with(stem, *p_len, table[k][0], from_len))
		{
			int		keep = *p_len - from_len;
			int		new_cp = utf8_cplen(stem, keep) +
				utf8_cplen(table[k][1], (int) strlen(table[k][1]));

			if (candidate_has_vowel(stem, keep, table[k][1]) && new_cp > 1)
			{
				replace_tail(stem, p_len, from_len, table[k][1]);
				return true;
			}
			return false;
		}
	}
	return false;
}

/*
 * The post-stemming chain of Python _stem_word, applied to the stem in
 * place. `transformed` is the word after transformations (some steps look
 * at the ending that was stripped).
 */
static void
apply_post_processing(char *stem, int *p_len, bool has_ending,
					  const char *transformed, int trans_len)
{
	int		len = *p_len;
	int		rest_len;
	const char *rest;

	/*
	 * -ići compounds (doći, proći, naći, poći, izaći): the l-participle and
	 * the adjective prošli build on -šl-, the present on -đ- (došla/dođe,
	 * prošli/prođe, našli/nađem, pošla/pođu). When a case or gender ending
	 * follows the l, map vowel + šl to vowel + đ, so these forms meet the
	 * present and keep apart from dodati/prodati/nada.
	 */
	if (has_ending && utf8_cplen(stem, len) > 2 &&
		ends_with_str(stem, len, "šl") && codepoint_in(stem, len, 3, "aeiou"))
		replace_tail(stem, &len, (int) strlen("šl"), "đ");

	/*
	 * Comparative -ij-: strip it first, so the positive stem then goes
	 * through the same participle and fleeting-a steps as the positive
	 * (kompliciranij -> kompliciran -> komplicir, složenij -> slož).
	 * Velar, sibilant and palatal stems never take -ij- (they jotate:
	 * jak -> jači, brz -> brži), so -ij after them belongs to a noun
	 * (akcija, strategija, misija, vizija).
	 */
	if (ends_with(stem, len, "ij", 2) && utf8_cplen(stem, len) > 3 &&
		!codepoint_in(stem, len, 3, "cčćđfghjkszšž") &&
		has_vowel(stem, len - 2))
		replace_tail(stem, &len, 2, "");

	/*
	 * Fleeting a in -ak: postupak/postupka/postupaka, odlazak/odlaska. Drop
	 * the a and devoice the consonant before k as the oblique forms do.
	 * Stems with a stable a (korak/koraka) get the same -Ck stem in every
	 * form, so nothing splits. -dak/-tak are left to the -dak/-tk steps.
	 * The vowel check judges a syllabic r by the whole candidate (cvr-čak);
	 * devoicing keeps a consonant a consonant, so the stem itself serves.
	 */
	if (utf8_cplen(stem, len) > 4 && ends_with(stem, len, "ak", 2) &&
		!codepoint_in(stem, len, 3, "aeioudt"))
	{
		int	c_off = codepoint_from_end(stem, len, 3);

		if (has_vowel_in(stem, c_off, len))
		{
			static const char *const devoice[][2] = {
				{"z", "s"}, {"ž", "š"}, {"b", "p"}, {"g", "k"},
			};
			const char *voiceless = NULL;
			size_t	k;

			for (k = 0; k < sizeof(devoice) / sizeof(devoice[0]); k++)
			{
				if (ends_with_str(stem, len - 2, devoice[k][0]))
					voiceless = devoice[k][1];
			}
			if (voiceless)
			{
				/* Voiced and voiceless pairs have the same byte length. */
				memcpy(stem + c_off, voiceless, strlen(voiceless));
			}
			replace_tail(stem, &len, 2, "k");
		}
	}

	/*
	 * Fleeting a in -ac nouns (kupac/kupca/kupci, stranac, borac): the
	 * nominative and genitive plural keep the a that the other forms lose.
	 * Generalizes the v0.1 -nac/-mac/-vac/-rac/... transformations.
	 */
	if (utf8_cplen(stem, len) > 4 && ends_with(stem, len, "ac", 2) &&
		!last_codepoint_is_ascii_vowel(stem, len - 2) &&
		has_vowel_before(stem, len, 3))
		replace_tail(stem, &len, 2, "c");

	/*
	 * -dak nouns alternate like -tak ones: the oblique forms devoice the d
	 * before k (pogodak/pogotka, napredak/napretka, dohodak/dohotka) and
	 * the plural drops it (pogoci). Read vowel + dak as vowel + tk. The
	 * short -dak stems the -aci plural of -datak nouns leaves (podak from
	 * podaci, zadak, dodak) already match the -tk step's output and are
	 * untouched.
	 */
	if (utf8_cplen(stem, len) > 5 && ends_with(stem, len, "dak", 3) &&
		codepoint_in(stem, len, 4, "aeiou"))
		replace_tail(stem, &len, 3, "tk");

	/*
	 * -tak nouns lose the t before the plural -ci (podatak/podatka/podaci,
	 * trenutak/trenuci, gubitak/gubici); a vowel + tk stem drops the t to
	 * meet the plural.
	 */
	if (utf8_cplen(stem, len) > 5 && ends_with(stem, len, "tk", 2) &&
		last_codepoint_is_ascii_vowel(stem, len - 2))
		replace_tail(stem, &len, 2, "k");

	/* Comparatives in -š- after k/p (lak-š-i, mek-š-i, ljep-š-i). */
	if ((ends_with_str(stem, len, "kš") || ends_with_str(stem, len, "pš")) &&
		utf8_cplen(stem, len) > 3)
		replace_tail(stem, &len, (int) strlen("š"), "");

	/*
	 * Velar -ći verbs take -n- in the present (pomog-n-e, stig-n-u,
	 * dig-n-eš) but not in the l-participle (pomogla, stigao). Drop it
	 * after g.
	 */
	if (ends_with(stem, len, "gn", 2) && utf8_cplen(stem, len) > 3)
		replace_tail(stem, &len, 1, "");

	/*
	 * Passive participles of i-verbs jotate the root before -en. Strip -en
	 * and undo the jotation. After a non-palatal consonant -en is too often
	 * a noun or adjective (jesen, leden, bazen) to strip.
	 */
	{
		size_t k;

		for (k = 0; k < sizeof(jotated_participle) / sizeof(jotated_participle[0]); k++)
		{
			const char *ending = jotated_participle[k].ending;
			const char *root = jotated_participle[k].root;
			int		e_len = (int) strlen(ending);

			if (ends_with(stem, len, ending, e_len))
			{
				int	keep = len - e_len;

				if (utf8_cplen(stem, keep) + utf8_cplen(root, (int) strlen(root)) > 2 &&
					candidate_has_vowel(stem, keep, root))
					replace_tail(stem, &len, e_len, root);
				break;
			}
		}
	}

	rest = transformed_rest(transformed, trans_len, stem, len, &rest_len);

	/*
	 * -stati verbs build the present on -stan- (posta-n-e, osta-n-u), which
	 * the -an noun rule hands over as postan; drop -an to meet posta-la.
	 * Only with a present-tense ending: bare koristan/bolestan are
	 * adjectives.
	 */
	if (ends_with(stem, len, "stan", 4) && utf8_cplen(stem, len) > 4 &&
		in_string_set(rest, rest_len, present_endings) &&
		has_vowel(stem, len - 2))
		replace_tail(stem, &len, 2, "");

	/*
	 * -irati verbs form their participle in -iran (organiziran, planiran);
	 * its a is not fleeting (organizirana), so drop -an to meet
	 * organizir-ati.
	 */
	else if (ends_with(stem, len, "iran", 4) && utf8_cplen(stem, len) > 5)
		replace_tail(stem, &len, 2, "");

	/*
	 * a-verb participles keep their a (napisana, povezana, održana), while
	 * fleeting-a adjectives lose it (jasna, obavezna). -ovati/-ivati
	 * participles (očekivana, imenovanog) join the -iv stem these verbs get
	 * in strip_suffixes_inplace(). The bare form stays with fleeting-a.
	 */
	else if ((ends_with(stem, len, "ivan", 4) || ends_with(stem, len, "ovan", 4)) &&
			 utf8_cplen(stem, len) > 6 && rest_len > 0)
		replace_tail(stem, &len, 4, "iv");

	/*
	 * A -an stem left by an ending after s/z, a palatal or h is likewise a
	 * participle (nouns with a stable -an mostly have -lan/-ran/-van/-kan/
	 * -tan: plan, ekran, Ivan): drop -an to meet napis-ati.
	 */
	else if ((ends_with_str(stem, len, "san") || ends_with_str(stem, len, "zan") ||
			  ends_with_str(stem, len, "čan") || ends_with_str(stem, len, "ćan") ||
			  ends_with_str(stem, len, "žan") || ends_with_str(stem, len, "šan") ||
			  ends_with_str(stem, len, "han")) &&
			 utf8_cplen(stem, len) > 5 && rest_len > 0)
		replace_tail(stem, &len, 2, "");

	/*
	 * Fleeting-a removal: Croatian nominative masculine forms insert an "a"
	 * between consonant clusters (e.g., važan/važna, slobodan/slobodna).
	 * Remove it to unify with oblique forms that lack the fleeting vowel.
	 * -stan adjectives also lose the t in the oblique forms
	 * (koristan/korisna, svjestan/svjesna, izvrstan/izvrsna).
	 */
	else if (ends_with(stem, len, "an", 2) && utf8_cplen(stem, len) > 3 &&
			 !last_codepoint_is_ascii_vowel(stem, len - 2))
	{
		bool	stan = ends_with(stem, len - 2, "st", 2);
		const char *tail = stan ? "sn" : "n";	/* -stan -> -sn, -Can -> -Cn */
		int		cut = stan ? 4 : 2;
		int		keep = len - cut;

		if (candidate_has_vowel(stem, keep, tail) &&
			utf8_cplen(stem, keep) + (int) strlen(tail) > 1)
			replace_tail(stem, &len, cut, tail);
	}

	/*
	 * Plural -ov-/-ev- extension: monosyllabic masculine nouns add -ov-
	 * (after hard consonants) or -ev- (after soft) before plural endings.
	 * Strip to unify with singular: planov→plan, ratov→rat, kraljev→kralj.
	 * Longer stems keep it: there -ov/-ev is mostly the possessive
	 * adjective suffix (premijerov, prijateljev), a separate lemma.
	 */
	if (utf8_cplen(stem, len) > 3 &&
		(ends_with(stem, len, "ov", 2) || ends_with(stem, len, "ev", 2)))
	{
		int	keep = len - 2;

		if (count_syllables(stem, keep) == 1 && utf8_cplen(stem, keep) > 2)
			replace_tail(stem, &len, 2, "");
	}

	/*
	 * Reverse cluster jotation in short stems (up to 7 codepoints) to unify
	 * comparative/derived forms with their base: skuplj→skup, dublj→dub.
	 *
	 * No single-consonant depalatalization (ž -> g, č -> k, š -> s). A stem
	 * ending in a palatal is read as the root's own: the ending cannot tell
	 * a comparative or e-verb present (jači, piše) from an i-/a-verb or
	 * noun with a palatal root (traži, priča, naš, riječ), and undoing it
	 * merged tražiti with trag, pokušati with pokus and naš with nas.
	 */
	if (utf8_cplen(stem, len) <= 7)
	{
		static const char *const jotation[][2] = {
			{"plj", "p"}, {"blj", "b"}, {"vlj", "v"}, {"mlj", "m"},
			{"šć", "st"}, {"žd", "zd"},
		};

		reverse_alternation(stem, &len, jotation,
							sizeof(jotation) / sizeof(jotation[0]));
	}

	*p_len = len;
}

/*
 * Full inner pipeline (Python _stem_word): apply transformations, strip the
 * -je- theme or run the rules, then post-processing.
 * Returns malloc'd stem and writes its byte length into *p_len.
 */
static char *
stem_word_inner(const char *word, int word_len, int *p_len)
{
	char   *transformed = apply_transforms(word, word_len);
	char   *stem;
	int		trans_len;
	int		stem_len;
	bool	has_ending;

	if (!transformed)
		return NULL;
	trans_len = (int) strlen(transformed);

	stem = malloc(trans_len + 1);
	if (!stem)
	{
		free(transformed);
		return NULL;
	}
	memcpy(stem, transformed, trans_len + 1);

	/* The -je- theme always strips a non-empty verbal ending. */
	has_ending = true;
	stem_len = strip_je_theme(stem, trans_len);
	if (stem_len < 0)
		stem_len = strip_suffixes_inplace(stem, trans_len, &has_ending);
	stem[stem_len] = '\0';

	apply_post_processing(stem, &stem_len, has_ending, transformed, trans_len);
	free(transformed);

	*p_len = stem_len;
	return stem;
}

/* ------------------------------------------------------------------ */
/*  Comparative-case + terminal-i normalizers                         */
/* ------------------------------------------------------------------ */

/*
 * If `word` ends in a regular -ij comparative case ending (-ijima, -ijih,
 * -ijoj, -ijem, …), strip the ending. Returns malloc'd stem, or NULL.
 *
 * Endings ordered longest-first to match Python iteration semantics.
 */
static char *
normalize_regular_comparative_case(const char *word, int word_len)
{
	static const char *const endings[] = {
		"ijima", "ijega", "ijemu",
		"ijeg", "ijem", "ijim", "ijih", "ijoj",
		"iji", "ije", "ija", "iju",
	};
	size_t i;

	for (i = 0; i < sizeof(endings) / sizeof(endings[0]); i++)
	{
		int e_len = (int) strlen(endings[i]);

		if (ends_with(word, word_len, endings[i], e_len))
		{
			int		cand_len = word_len - e_len;
			char   *out;

			if (utf8_cplen(word, cand_len) > 1 && has_vowel(word, cand_len))
			{
				out = malloc(cand_len + 1);
				if (!out)
					return NULL;
				memcpy(out, word, cand_len);
				out[cand_len] = '\0';
				return out;
			}
			break;	/* Python breaks on first ending match (no fallback). */
		}
	}
	return NULL;
}

/*
 * If the original word ended in -ih and the stem ends in -i with codepoint
 * length > 2, drop the final -i. Returns a malloc'd new stem or strdup(stem).
 */
static char *
normalize_terminal_i_case(const char *word, int word_len,
						  const char *stem, int stem_len)
{
	if (ends_with(word, word_len, "ih", 2) &&
		stem_len > 0 && stem[stem_len - 1] == 'i' &&
		utf8_cplen(stem, stem_len) > 2)
	{
		int	cand_len = stem_len - 1;

		if (utf8_cplen(stem, cand_len) > 1 &&
			has_vowel(stem, cand_len))
		{
			char *out = malloc(cand_len + 1);

			if (!out)
				return NULL;
			memcpy(out, stem, cand_len);
			out[cand_len] = '\0';
			return out;
		}
	}

	{
		char *out = malloc(stem_len + 1);

		if (!out)
			return NULL;
		memcpy(out, stem, stem_len);
		out[stem_len] = '\0';
		return out;
	}
}

/* ------------------------------------------------------------------ */
/*  Phase 4: final fleeting-a normalization                           */
/* ------------------------------------------------------------------ */

/*
 * Python _fleeting_ar, applied in place to every non-stop-word stem.
 *
 * Fleeting a in -tar/-bar/-dar: metar/metra, dobar/dobra, Zadar/Zadra. The
 * nominative keeps the a that the other forms lose. Applied to every stem,
 * a stable-a word (kadar/kadra aside) gets the same -tr/-br/-dr stem in all
 * its forms, so it does not split.
 *
 * Fleeting -ao: posao/posla, topao/topla, misao/misli, okrugao/okrugla.
 * The masculine loses the l (pos-a-o -> pos), the other forms keep it after
 * a consonant (posl-a). Drop a stem-final l after a consonant so both meet;
 * a-verb participles (čeka-la) have a vowel before the l.
 */
static void
fleeting_ar(char *stem)
{
	int	len = (int) strlen(stem);
	int	cp = utf8_cplen(stem, len);

	if (cp > 4 &&
		(ends_with(stem, len, "tar", 3) || ends_with(stem, len, "bar", 3) ||
		 ends_with(stem, len, "dar", 3)) &&
		has_vowel_before(stem, len, 3))
	{
		replace_tail(stem, &len, 2, "r");
		return;
	}

	if (cp > 3 && stem[len - 1] == 'l' &&
		codepoint_in(stem, len, 2, "bcdfghkmnprstvzčćđšž") &&
		has_vowel_before(stem, len, 2))
		replace_tail(stem, &len, 1, "");
}

/* ------------------------------------------------------------------ */
/*  Public entry point                                                */
/* ------------------------------------------------------------------ */

/*
 * Python _stem_raw: the naj- superlative path or the default path, before
 * the final fleeting-a step. Returns a malloc'd stem.
 */
static char *
stem_raw(const char *word, int word_len)
{
	char   *result;

	/* naj- superlative prefix. Inner ≥ 2 codepoints, full ≥ 5. */
	if (starts_with(word, word_len, "naj", 3) && utf8_cplen(word, word_len) > 4)
	{
		const char *inner = word + 3;
		int		inner_len = word_len - 3;
		char   *cand;
		int		cand_len;

		/*
		 * Regular -ij comparative case form: stem the positive like any
		 * other word (najsloženiji -> složen -> slož, najkompliciraniji ->
		 * komplicir).
		 */
		cand = normalize_regular_comparative_case(inner, inner_len);
		if (cand)
		{
			result = stem_word_inner(cand, (int) strlen(cand), &cand_len);
			free(cand);
			return result;
		}

		cand = stem_word_inner(inner, inner_len, &cand_len);
		if (!cand)
			return NULL;

		if (cand_len != inner_len ||
			memcmp(cand, inner, inner_len) != 0)
		{
			result = normalize_terminal_i_case(word, word_len, cand, cand_len);
			free(cand);
			return result;
		}

		/*
		 * Inner word unchanged — stem the full word, then if the result
		 * still starts with "naj" and the remainder is valid, peel naj-.
		 */
		free(cand);
		cand = stem_word_inner(word, word_len, &cand_len);
		if (!cand)
			return NULL;

		if (starts_with(cand, cand_len, "naj", 3) &&
			utf8_cplen(cand, cand_len) > 4)
		{
			int		stripped_len = cand_len - 3;

			if (has_vowel(cand + 3, stripped_len) &&
				utf8_cplen(cand + 3, stripped_len) > 1)
			{
				result = normalize_terminal_i_case(word, word_len,
												   cand + 3, stripped_len);
				free(cand);
				return result;
			}
		}

		result = normalize_terminal_i_case(word, word_len, cand, cand_len);
		free(cand);
		return result;
	}

	/* Default path. */
	{
		int		stem_len;
		char   *stem = stem_word_inner(word, word_len, &stem_len);

		if (!stem)
			return NULL;
		result = normalize_terminal_i_case(word, word_len, stem, stem_len);
		free(stem);
		return result;
	}
}

char *
croatian_stem(const char *word)
{
	int		word_len;
	char   *result;

	if (!word || !*word)
	{
		char *empty = malloc(1);

		if (empty)
			empty[0] = '\0';
		return empty;
	}

	word_len = (int) strlen(word);

	/* Stop words are returned unchanged. */
	if (croatian_is_stopword(word))
	{
		char   *out = malloc(word_len + 1);

		if (!out)
			return NULL;
		memcpy(out, word, word_len + 1);
		return out;
	}

	result = stem_raw(word, word_len);
	if (result)
		fleeting_ar(result);
	return result;
}

/*
 * croatian_stemmer.c — Croatian stemmer (Ljubešić-Pandžić algorithm + autoresearch)
 *
 * Pure C implementation with no external dependencies. Uses byte-level string
 * matching (no regex). Mirrors src/croatian_stemmer/stemmer.py.
 *
 * Pipeline:
 *  1. Lexicon lookup (canonical lemma stem for listed forms)
 *  2. Optional naj- superlative prefix peel (with fallback path)
 *  3. Morphophonological transformations
 *  4. Suffix stripping via ordered rules (greedy + non-greedy)
 *  5. Post-stemming clean-up: fleeting-a, ov/ev plural, comparative -ij,
 *     jotation reversal, depalatalization
 *  6. Terminal-i normalization for -ih adjective inputs
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

/* True iff the last codepoint of s[0:byte_len] is an ASCII vowel. */
static bool
last_codepoint_is_ascii_vowel(const char *s, int byte_len)
{
	int		off = last_codepoint_start(s, byte_len);
	char	c;

	if (off < 0)
		return false;
	if (byte_len - off != 1)
		return false;	/* multibyte = Croatian consonant */
	c = s[off];
	return c == 'a' || c == 'e' || c == 'i' || c == 'o' || c == 'u';
}

/*
 * Croatian "has vowel" — any of aeiou, OR a syllabic R (an 'r' bordered by
 * non-vowels or word boundaries: trg, krv, prst).
 */
static bool
has_vowel(const char *s, int byte_len)
{
	int	i;

	for (i = 0; i < byte_len; i++)
	{
		unsigned char c = (unsigned char) s[i];

		if ((c & 0xC0) == 0x80)
			continue;	/* UTF-8 continuation */

		if (c == 'a' || c == 'e' || c == 'i' || c == 'o' || c == 'u')
			return true;

		if (c == 'r')
		{
			bool prev_is_vowel = false;
			bool next_is_vowel = false;

			if (i > 0)
			{
				unsigned char p = (unsigned char) s[i - 1];

				prev_is_vowel = (p == 'a' || p == 'e' || p == 'i' ||
								 p == 'o' || p == 'u');
			}
			{
				int j = i + 1;

				while (j < byte_len && ((unsigned char) s[j] & 0xC0) == 0x80)
					j++;
				if (j < byte_len)
				{
					unsigned char n = (unsigned char) s[j];

					next_is_vowel = (n == 'a' || n == 'e' || n == 'i' ||
									 n == 'o' || n == 'u');
				}
			}
			if (!prev_is_vowel && !next_is_vowel)
				return true;
		}
	}
	return false;
}

static bool
ends_with(const char *word, int word_len, const char *suffix, int suffix_len)
{
	if (suffix_len > word_len)
		return false;
	return memcmp(word + word_len - suffix_len, suffix, suffix_len) == 0;
}

static bool
starts_with(const char *word, int word_len, const char *prefix, int prefix_len)
{
	if (prefix_len > word_len)
		return false;
	return memcmp(word, prefix, prefix_len) == 0;
}

/* ------------------------------------------------------------------ */
/*  Lexicon lookup                                                    */
/* ------------------------------------------------------------------ */

static const LexiconEntry *
lexicon_find(const char *word)
{
	int	lo = 0;
	int	hi = N_LEXICON - 1;

	while (lo <= hi)
	{
		int	mid = (lo + hi) / 2;
		int	cmp = strcmp(word, lexicon[mid].form);

		if (cmp == 0)
			return &lexicon[mid];
		else if (cmp < 0)
			hi = mid - 1;
		else
			lo = mid + 1;
	}
	return NULL;
}

const char *
croatian_lexicon_canonical(const char *word)
{
	const LexiconEntry *e = lexicon_find(word);

	return e ? e->canonical : NULL;
}

bool
croatian_is_stopword(const char *word)
{
	const LexiconEntry *e = lexicon_find(word);

	return e != NULL && e->is_stop;
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
/*  Phase 2: ordered suffix-stripping rules                           */
/* ------------------------------------------------------------------ */

/*
 * For stem patterns like ".+(class)suffix", the leading ".+" requires the
 * stem to have at least one codepoint beyond the matched ending. We enforce
 * that here by comparing codepoint lengths after a byte-level ends_with hit.
 */
static bool
stem_matches(const char *stem, int stem_len,
			 const char *const *stem_ends, int n_stem_ends)
{
	int	i;

	if (n_stem_ends == 0)
		return true;	/* catch-all (.+ or .+?) */

	for (i = 0; i < n_stem_ends; i++)
	{
		int	end_byte_len = (int) strlen(stem_ends[i]);

		if (!ends_with(stem, stem_len, stem_ends[i], end_byte_len))
			continue;
		if (utf8_cplen(stem, stem_len) >
			utf8_cplen(stem_ends[i], end_byte_len))
			return true;
	}
	return false;
}

/*
 * Iterate through rules in declared order; within each rule, suffixes are
 * already sorted by gen_rules_c.py to match Python regex greediness:
 *   greedy  .+   → ascending byte length (first match = longest stem)
 *   lazy    .+?  → descending byte length (first match = shortest stem)
 *
 * Writes the resulting stem length into *out_len. Returns the byte buffer
 * (the caller does not free; the buffer is the input `transformed` truncated
 * via the returned length).
 */
static int
strip_suffixes_inplace(const char *transformed, int trans_len)
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

			if (!ends_with(transformed, trans_len, rule->suffixes[j], suffix_len))
				continue;

			stem_len = trans_len - suffix_len;
			if (stem_len <= 0)
				continue;

			if (!stem_matches(transformed, stem_len,
							  rule->stem_ends, rule->n_stem_ends))
				continue;

			/* Found the rule's regex match — validity gate applies once. */
			if (utf8_cplen(transformed, stem_len) > 1 &&
				has_vowel(transformed, stem_len))
				return stem_len;
			break;	/* abandon rule, mirror Python's `re.match` semantics */
		}
	}
	return trans_len;	/* no rule fired */
}

/* ------------------------------------------------------------------ */
/*  Phase 3: post-stemming clean-up                                   */
/* ------------------------------------------------------------------ */

/*
 * Apply the post-stemming chain in order:
 *   - fleeting-a (Cn → C̄n with C consonant; e.g. važan → važn → važ via -an)
 *   - plural -ov / -ev extension stripping
 *   - comparative -ij stripping (early-exit return)
 *   - jotation reversal (early-exit return)
 *   - depalatalization (early-exit return)
 *
 * Mutates *p_stem (re-allocated as needed) and *p_len.
 */
static bool
apply_post_processing(char **p_stem, int *p_len)
{
	char   *stem = *p_stem;
	int		len = *p_len;

	/* Fleeting-a: stem ends in "Can" (C non-vowel) and codepoint length > 3. */
	if (len >= 3 && ends_with(stem, len, "an", 2) &&
		utf8_cplen(stem, len) > 3)
	{
		/* Codepoint immediately before "an" must be a non-vowel. */
		if (!last_codepoint_is_ascii_vowel(stem, len - 2))
		{
			/* Build candidate = stem[:-2] + "n". */
			int		new_len = len - 1;
			char   *candidate = malloc(new_len + 1);

			if (!candidate)
				return false;
			memcpy(candidate, stem, len - 2);
			candidate[len - 2] = 'n';
			candidate[new_len] = '\0';

			if (has_vowel(candidate, new_len) &&
				utf8_cplen(candidate, new_len) > 1)
			{
				free(stem);
				stem = candidate;
				len = new_len;
			}
			else
			{
				free(candidate);
			}
		}
	}

	/* Plural -ov / -ev extension: strip if stem stays > 2 codepoints. */
	if (utf8_cplen(stem, len) > 3)
	{
		const char *ext = NULL;

		if (ends_with(stem, len, "ov", 2))
			ext = "ov";
		else if (ends_with(stem, len, "ev", 2))
			ext = "ev";

		if (ext)
		{
			int	candidate_len = len - 2;

			if (has_vowel(stem, candidate_len) &&
				utf8_cplen(stem, candidate_len) > 2)
			{
				stem[candidate_len] = '\0';
				len = candidate_len;
			}
		}
	}

	/* Comparative -ij stripping: early-exit return. */
	if (utf8_cplen(stem, len) > 3 && ends_with(stem, len, "ij", 2))
	{
		int	candidate_len = len - 2;

		if (has_vowel(stem, candidate_len))
		{
			stem[candidate_len] = '\0';
			len = candidate_len;
			*p_stem = stem;
			*p_len = len;
			return true;
		}
	}

	/* Jotation reversal: short stems only (codepoint length ≤ 7). */
	if (utf8_cplen(stem, len) <= 7)
	{
		static const struct { const char *from; int from_len;
							  const char *to; int to_len; } jot[] = {
			/* Multi-byte first to allow ordering parity with Python dict. */
			{"plj", 3, "p", 1}, {"blj", 3, "b", 1},
			{"vlj", 3, "v", 1}, {"mlj", 3, "m", 1},
			{"šć",  4, "st", 2}, {"žd",  3, "zd", 2},
		};
		size_t k;

		for (k = 0; k < sizeof(jot) / sizeof(jot[0]); k++)
		{
			if (ends_with(stem, len, jot[k].from, jot[k].from_len))
			{
				int		prefix_len = len - jot[k].from_len;
				int		new_len = prefix_len + jot[k].to_len;
				char   *candidate = malloc(new_len + 1);

				if (!candidate)
					return false;
				memcpy(candidate, stem, prefix_len);
				memcpy(candidate + prefix_len, jot[k].to, jot[k].to_len);
				candidate[new_len] = '\0';

				if (has_vowel(candidate, new_len) &&
					utf8_cplen(candidate, new_len) > 1)
				{
					free(stem);
					*p_stem = candidate;
					*p_len = new_len;
					return true;
				}
				free(candidate);
				break;	/* match-and-stop, like Python */
			}
		}
	}

	/* Depalatalization: very short stems only (codepoint length ≤ 3). */
	if (utf8_cplen(stem, len) <= 3)
	{
		static const struct { const char *from; int from_len;
							  const char *to; int to_len; } dep[] = {
			{"ž", 2, "g", 1}, {"č", 2, "k", 1},
			{"đ", 2, "d", 1}, {"š", 2, "s", 1},
		};
		size_t k;

		for (k = 0; k < sizeof(dep) / sizeof(dep[0]); k++)
		{
			if (ends_with(stem, len, dep[k].from, dep[k].from_len))
			{
				int		prefix_len = len - dep[k].from_len;
				int		new_len = prefix_len + dep[k].to_len;
				char   *candidate = malloc(new_len + 1);

				if (!candidate)
					return false;
				memcpy(candidate, stem, prefix_len);
				memcpy(candidate + prefix_len, dep[k].to, dep[k].to_len);
				candidate[new_len] = '\0';

				if (has_vowel(candidate, new_len) &&
					utf8_cplen(candidate, new_len) > 1)
				{
					free(stem);
					*p_stem = candidate;
					*p_len = new_len;
					return true;
				}
				free(candidate);
				break;
			}
		}
	}

	*p_stem = stem;
	*p_len = len;
	return true;
}

/*
 * Full inner pipeline: apply transformations, run rules, then post-processing.
 * Returns malloc'd stem and writes its byte length into *p_len.
 */
static char *
stem_word_inner(const char *word, int word_len, int *p_len)
{
	char   *transformed = apply_transforms(word, word_len);
	int		trans_len;
	int		stem_len;

	if (!transformed)
		return NULL;
	trans_len = (int) strlen(transformed);

	stem_len = strip_suffixes_inplace(transformed, trans_len);
	transformed[stem_len] = '\0';

	if (!apply_post_processing(&transformed, &stem_len))
	{
		free(transformed);
		return NULL;
	}

	*p_len = stem_len;
	return transformed;
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
/*  Public entry point                                                */
/* ------------------------------------------------------------------ */

char *
croatian_stem(const char *word)
{
	int		word_len;
	const char *canon;
	char   *result;

	if (!word || !*word)
	{
		char *empty = malloc(1);

		if (empty)
			empty[0] = '\0';
		return empty;
	}

	word_len = (int) strlen(word);

	/* 1. Lexicon fast path (canonical lemma). */
	canon = croatian_lexicon_canonical(word);
	if (canon)
	{
		int		clen = (int) strlen(canon);
		char   *out = malloc(clen + 1);

		if (!out)
			return NULL;
		memcpy(out, canon, clen);
		out[clen] = '\0';
		return out;
	}

	/* 2. naj- superlative prefix. Inner ≥ 2 codepoints, full ≥ 5. */
	if (starts_with(word, word_len, "naj", 3) && utf8_cplen(word, word_len) > 4)
	{
		const char *inner = word + 3;
		int		inner_len = word_len - 3;
		const char *inner_canon = croatian_lexicon_canonical(inner);
		char   *cand;
		int		cand_len;

		if (inner_canon)
		{
			int		clen = (int) strlen(inner_canon);
			char   *out = malloc(clen + 1);

			if (!out)
				return NULL;
			memcpy(out, inner_canon, clen);
			out[clen] = '\0';
			return out;
		}

		cand = normalize_regular_comparative_case(inner, inner_len);
		if (cand)
			return cand;

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

	/* 3. Default path. */
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

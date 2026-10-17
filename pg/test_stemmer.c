/*
 * test_stemmer.c — standalone parity test for the Croatian stemmer.
 *
 * Mirrors tests/test_stemmer.py so the C and Python implementations can
 * be cross-checked without a PostgreSQL build.
 *
 * Compile: cc -O2 -o test_stemmer test_stemmer.c croatian_stemmer.c -I.
 * Run:     ./test_stemmer
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "croatian_stemmer.h"

typedef struct
{
	const char *input;
	const char *expected;
	const char *category;
} TestCase;

static const TestCase tests[] = {
	/* Stop words and other lexicon forms: canonical lemma stems */
	{"biti", "bit", "stop"},
	{"jesam", "bit", "stop"},
	{"sam", "bit", "stop"},
	{"smo", "bit", "stop"},
	{"su", "bit", "stop"},
	{"bio", "bit", "stop"},
	{"bila", "bit", "stop"},
	{"bilo", "bit", "stop"},
	{"ću", "ht", "stop"},
	{"ćeš", "ht", "stop"},
	{"će", "ht", "stop"},
	{"ćemo", "ht", "stop"},
	{"ćete", "ht", "stop"},
	{"mogu", "moć", "stop"},
	{"možeš", "moć", "stop"},
	{"može", "moć", "stop"},
	{"možemo", "moć", "stop"},
	{"možete", "moć", "stop"},
	{"trebam", "treb", "stop"},
	{"treba", "treb", "stop"},
	{"moram", "mor", "stop"},
	{"mora", "mor", "stop"},
	{"želim", "želj", "stop"},
	{"želi", "želj", "stop"},
	{"žele", "želj", "stop"},

	/* Nouns */
	{"kuća", "kuć", "noun"},
	{"kuće", "kuć", "noun"},
	{"kući", "kuć", "noun"},
	{"kuću", "kuć", "noun"},
	{"kućom", "kuć", "noun"},
	{"grad", "grad", "noun"},
	{"grada", "grad", "noun"},
	{"gradu", "grad", "noun"},
	{"gradovi", "grad", "noun"},
	{"gradova", "grad", "noun"},
	{"šumu", "šum", "noun"},
	{"šumom", "šum", "noun"},

	/* Adjectives */
	{"lijep", "lijep", "adj"},
	{"lijepa", "lijep", "adj"},
	{"lijepo", "lijep", "adj"},
	{"lijepog", "lijep", "adj"},
	{"lijepom", "lijep", "adj"},
	{"lijepim", "lijepi", "adj"},
	{"lijepih", "lijep", "adj"},

	/* Verbs */
	{"raditi", "radit", "verb"},
	{"radimo", "radit", "verb"},
	{"radite", "radit", "verb"},
	{"radim", "radit", "verb"},
	{"radi", "radit", "verb"},

	/* Transformations */
	{"metara", "metr", "trans"},
	{"centar", "centr", "trans"},
	{"centara", "centr", "trans"},

	/* Syllabic R */
	{"trga", "trg", "syllabic"},
	{"trg", "trg", "syllabic"},
	{"krv", "krv", "syllabic"},
	{"krvi", "krv", "syllabic"},

	/* Literary cases */
	{"šumu", "šum", "lit"},
	{"šumom", "šum", "lit"},
	{"put", "put", "lit"},
	{"zašao", "zaša", "lit"},
	{"začarana", "začarn", "lit"},

	{NULL, NULL, NULL}
};

int
main(void)
{
	int	passed = 0;
	int	failed = 0;
	int	i;

	for (i = 0; tests[i].input != NULL; i++)
	{
		char *result = croatian_stem(tests[i].input);

		if (result && strcmp(result, tests[i].expected) == 0)
		{
			passed++;
		}
		else
		{
			fprintf(stderr, "FAIL [%s]: stem(\"%s\") = \"%s\", expected \"%s\"\n",
					tests[i].category, tests[i].input,
					result ? result : "(null)", tests[i].expected);
			failed++;
		}
		free(result);
	}

	if (!croatian_is_stopword("sam"))
	{
		fprintf(stderr, "FAIL: \"sam\" should be a stop word\n");
		failed++;
	}
	if (!croatian_is_stopword("biti"))
	{
		fprintf(stderr, "FAIL: \"biti\" should be a stop word\n");
		failed++;
	}
	if (croatian_is_stopword("grad"))
	{
		fprintf(stderr, "FAIL: \"grad\" should NOT be a stop word\n");
		failed++;
	}
	/* Lexicon forms that are content words must not be stop words. */
	if (croatian_is_stopword("saznali") || croatian_is_stopword("starim"))
	{
		fprintf(stderr, "FAIL: lexicon content words must not be stop words\n");
		failed++;
	}

	{
		const char *canon = croatian_lexicon_canonical("biti");

		if (!canon || strcmp(canon, "bit") != 0)
		{
			fprintf(stderr, "FAIL: lexicon_canonical(\"biti\") = \"%s\", expected \"bit\"\n",
					canon ? canon : "(null)");
			failed++;
		}
		canon = croatian_lexicon_canonical("saznali");
		if (!canon || strcmp(canon, "saznat") != 0)
		{
			fprintf(stderr, "FAIL: lexicon_canonical(\"saznali\") = \"%s\", expected \"saznat\"\n",
					canon ? canon : "(null)");
			failed++;
		}
		if (croatian_lexicon_canonical("grad") != NULL)
		{
			fprintf(stderr, "FAIL: \"grad\" should not be in the lexicon\n");
			failed++;
		}
	}

	printf("%d passed, %d failed\n", passed, failed);
	return failed > 0 ? 1 : 0;
}

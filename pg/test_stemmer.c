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
	/* Stop words: returned unchanged */
	{"biti", "biti", "stop"},
	{"jesam", "jesam", "stop"},
	{"sam", "sam", "stop"},
	{"smo", "smo", "stop"},
	{"su", "su", "stop"},
	{"bio", "bio", "stop"},
	{"bila", "bila", "stop"},
	{"bilo", "bilo", "stop"},
	{"ću", "ću", "stop"},
	{"ćeš", "ćeš", "stop"},
	{"će", "će", "stop"},
	{"ćemo", "ćemo", "stop"},
	{"ćete", "ćete", "stop"},
	{"mogu", "mogu", "stop"},
	{"možeš", "možeš", "stop"},
	{"može", "može", "stop"},
	{"možemo", "možemo", "stop"},
	{"možete", "možete", "stop"},
	{"trebam", "trebam", "stop"},
	{"treba", "treba", "stop"},
	{"moram", "moram", "stop"},
	{"mora", "mora", "stop"},
	{"želim", "želim", "stop"},
	{"želi", "želi", "stop"},
	{"žele", "žele", "stop"},

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
	{"lijepim", "lijep", "adj"},
	{"lijepih", "lijep", "adj"},

	/* Verbs */
	{"raditi", "rad", "verb"},
	{"radimo", "rad", "verb"},
	{"radite", "rad", "verb"},
	{"radim", "rad", "verb"},
	{"radi", "rad", "verb"},

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
	{"zašao", "zađ", "lit"},
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
	if (croatian_is_stopword("saznali") || croatian_is_stopword("starim"))
	{
		fprintf(stderr, "FAIL: content words must not be stop words\n");
		failed++;
	}

	printf("%d passed, %d failed\n", passed, failed);
	return failed > 0 ? 1 : 0;
}

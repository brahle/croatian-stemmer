/*
 * croatian_stemmer.h — Croatian stemmer (Ljubešić-Pandžić algorithm + autoresearch)
 *
 * Pure C implementation, no PostgreSQL dependencies.
 */
#ifndef CROATIAN_STEMMER_H
#define CROATIAN_STEMMER_H

#include <stdbool.h>

/*
 * Stem a single word. The input must be lowercase UTF-8.
 * Returns a malloc'd string containing the stem (caller must free()).
 *
 * Lexicon forms (including stop words) return their lemma's canonical
 * stem, matching stem() in the Python package.
 */
char *croatian_stem(const char *word);

/*
 * Look up the canonical lemma stem for a lexicon form.
 * Returns a static pointer (do not free) or NULL if the form is not listed.
 */
const char *croatian_lexicon_canonical(const char *word);

/*
 * Returns true iff the word is a built-in stop word (auxiliary/modal form).
 * The text search dictionary drops these; croatian_stem() still stems them.
 */
bool croatian_is_stopword(const char *word);

#endif /* CROATIAN_STEMMER_H */

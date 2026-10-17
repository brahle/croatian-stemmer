/*
 * dict_croatian_stem.c — PostgreSQL text search dictionary for Croatian
 *
 * Wraps the Ljubešić-Pandžić stemmer as a PG text search dictionary template.
 *
 * Usage:
 *   CREATE EXTENSION dict_croatian_stem;
 *   -- Then use the 'croatian_stem' dictionary in your text search config.
 */

#include "postgres.h"
#include "commands/defrem.h"
#include "tsearch/ts_public.h"
#include "tsearch/ts_locale.h"
#include "utils/formatting.h"

#include "croatian_stemmer.h"

PG_MODULE_MAGIC;

/*
 * PG 18 dropped lowerstr / lowerstr_with_len from tsearch/ts_locale.h.
 * The replacement is utils/formatting.h's str_tolower(buf, nbytes, collid).
 * readstoplist's callback signature also changed to take (const char *,
 * size_t, Oid). Provide a thin compatibility shim so the same source builds
 * cleanly on PG 15-17 and PG 18+.
 */
#if PG_VERSION_NUM >= 180000
#include "catalog/pg_collation.h"		/* DEFAULT_COLLATION_OID */
#define CS_LOWER_FN			str_tolower
#define CS_LOWER_WITH_LEN(buf, len)		\
	str_tolower((buf), (len), DEFAULT_COLLATION_OID)
#else
#define CS_LOWER_FN			lowerstr
#define CS_LOWER_WITH_LEN(buf, len)		lowerstr_with_len((buf), (len))
#endif

typedef struct
{
	StopList	stoplist;
	bool		has_stopwords;
} DictCroatianStem;

PG_FUNCTION_INFO_V1(dcroatian_stem_init);
Datum
dcroatian_stem_init(PG_FUNCTION_ARGS)
{
	List	   *dictoptions = (List *) PG_GETARG_POINTER(0);
	DictCroatianStem *d;
	ListCell   *l;

	d = (DictCroatianStem *) palloc0(sizeof(DictCroatianStem));

	foreach(l, dictoptions)
	{
		DefElem *defel = (DefElem *) lfirst(l);

		if (strcmp(defel->defname, "stopwords") == 0)
		{
			readstoplist(defGetString(defel), &d->stoplist, CS_LOWER_FN);
			d->has_stopwords = true;
		}
		else
		{
			ereport(ERROR,
					(errcode(ERRCODE_INVALID_PARAMETER_VALUE),
					 errmsg("unrecognized dictionary parameter: \"%s\"",
							defel->defname)));
		}
	}

	PG_RETURN_POINTER(d);
}

PG_FUNCTION_INFO_V1(dcroatian_stem_lexize);
Datum
dcroatian_stem_lexize(PG_FUNCTION_ARGS)
{
	DictCroatianStem *d = (DictCroatianStem *) PG_GETARG_POINTER(0);
	char	   *in = (char *) PG_GETARG_POINTER(1);
	int32		len = PG_GETARG_INT32(2);
	char	   *txt;
	char	   *stemmed;
	TSLexeme   *res;

	/* Lowercase the input (PG provides the function) */
	txt = CS_LOWER_WITH_LEN(in, len);

	/*
	 * Stop words are dropped: the built-in auxiliary/modal list, plus any
	 * user-supplied StopWords file. res[0].lexeme = NULL means "recognized
	 * stop word".
	 */
	if (croatian_is_stopword(txt) ||
		(d->has_stopwords && searchstoplist(&d->stoplist, txt)))
	{
		pfree(txt);
		res = palloc0(sizeof(TSLexeme));
		PG_RETURN_POINTER(res);
	}

	/* Stem the word */
	stemmed = croatian_stem(txt);
	pfree(txt);

	if (!stemmed)
		PG_RETURN_POINTER(NULL);

	/* Build result */
	res = palloc0(sizeof(TSLexeme) * 2);
	res[0].lexeme = pstrdup(stemmed);
	free(stemmed);	/* was malloc'd by the stemmer */

	PG_RETURN_POINTER(res);
}

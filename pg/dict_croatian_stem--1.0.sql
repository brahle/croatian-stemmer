-- dict_croatian_stem: Croatian text search dictionary
-- complain if script is sourced in psql, rather than via CREATE EXTENSION
\echo Use "CREATE EXTENSION dict_croatian_stem" to load this file. \quit

-- Init function: called once when the dictionary is created
CREATE FUNCTION dcroatian_stem_init(internal)
    RETURNS internal
    AS 'MODULE_PATHNAME'
    LANGUAGE C STRICT;

-- Lexize function: called for each token
CREATE FUNCTION dcroatian_stem_lexize(internal, internal, internal, internal)
    RETURNS internal
    AS 'MODULE_PATHNAME'
    LANGUAGE C STRICT;

-- Template: links init + lexize
CREATE TEXT SEARCH TEMPLATE croatian_stem_template (
    INIT   = dcroatian_stem_init,
    LEXIZE = dcroatian_stem_lexize
);

-- Default dictionary instance (with built-in stop words)
CREATE TEXT SEARCH DICTIONARY croatian_stem (
    TEMPLATE = croatian_stem_template
);

COMMENT ON TEXT SEARCH DICTIONARY croatian_stem IS
    'Croatian stemming dictionary (Ljubešić-Pandžić algorithm)';

-- Full text search configuration using the stemmer
CREATE TEXT SEARCH CONFIGURATION croatian (COPY = simple);
ALTER TEXT SEARCH CONFIGURATION croatian
    ALTER MAPPING FOR asciiword, asciihword, hword_asciipart,
                      word, hword, hword_part
    WITH croatian_stem;

COMMENT ON TEXT SEARCH CONFIGURATION croatian IS
    'Croatian text search configuration with stemming';

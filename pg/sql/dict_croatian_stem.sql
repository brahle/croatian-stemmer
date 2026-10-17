CREATE EXTENSION dict_croatian_stem;

-- Basic noun stemming via ts_lexize
SELECT ts_lexize('croatian_stem', 'kuća');
SELECT ts_lexize('croatian_stem', 'kuće');
SELECT ts_lexize('croatian_stem', 'kući');
SELECT ts_lexize('croatian_stem', 'grada');
-- gradovi was {gradov} pre-autoresearch; the stripper now collapses
-- plural -ov/-ev extensions, so all "grad" forms unify.
SELECT ts_lexize('croatian_stem', 'gradovi');
SELECT ts_lexize('croatian_stem', 'lijepog');
-- raditi → "rad": the .+i rule strips -ti and the thematic -i- is dropped,
-- so it meets radi/radim.
SELECT ts_lexize('croatian_stem', 'raditi');
SELECT ts_lexize('croatian_stem', 'šumom');

-- Built-in stop words (auxiliary/modal forms) are dropped.
SELECT ts_lexize('croatian_stem', 'sam');
SELECT ts_lexize('croatian_stem', 'biti');
SELECT ts_lexize('croatian_stem', 'mogu');
SELECT ts_lexize('croatian_stem', 'ću');

-- Content words are stemmed, never dropped.
SELECT ts_lexize('croatian_stem', 'saznali');
SELECT ts_lexize('croatian_stem', 'saznati');
SELECT ts_lexize('croatian_stem', 'starim');

-- naj- superlative prefix collapses with comparative/base forms.
SELECT ts_lexize('croatian_stem', 'najveći');
SELECT ts_lexize('croatian_stem', 'najljepši');

-- Morphophonological transformations
SELECT ts_lexize('croatian_stem', 'metara');
SELECT ts_lexize('croatian_stem', 'centar');

-- Syllabic R
SELECT ts_lexize('croatian_stem', 'trga');

-- Full text search configuration
SELECT to_tsvector('croatian', 'Veliki grad ima lijepe kuće');
SELECT to_tsquery('croatian', 'gradovi & kuće');

-- Search match
SELECT to_tsvector('croatian', 'Lijepe kuće u velikom gradu')
    @@ to_tsquery('croatian', 'kuća & grad');

-- "u" is not a stop word, so it stays as a lexeme.
SELECT to_tsvector('croatian', 'Idem u grad');

-- Stop words vanish from the vector; content words do not.
SELECT to_tsvector('croatian', 'Saznali smo da starim ljudima treba pomoć');

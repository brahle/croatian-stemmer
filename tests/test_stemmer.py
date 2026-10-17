"""Tests for the Croatian stemmer."""

import pytest

from croatian_stemmer import stem, stem_text


class TestStopWords:
    """Stop words map to a canonical stem per lemma so all forms collapse."""

    @pytest.mark.parametrize("word,expected", [
        ("biti", "bit"), ("jesam", "bit"), ("sam", "bit"), ("smo", "bit"),
        ("su", "bit"), ("bio", "bit"), ("bila", "bit"), ("bilo", "bit"),
        ("ću", "ht"), ("ćeš", "ht"), ("će", "ht"), ("ćemo", "ht"), ("ćete", "ht"),
        ("mogu", "moć"), ("možeš", "moć"), ("može", "moć"),
        ("možemo", "moć"), ("možete", "moć"),
        ("trebam", "treb"), ("treba", "treb"),
        ("moram", "mor"), ("mora", "mor"),
        ("želim", "želj"), ("želi", "želj"), ("žele", "želj"),
    ])
    def test_stop_words_canonicalized(self, word, expected):
        assert stem(word) == expected

    def test_stop_words_case_insensitive(self):
        assert stem("Biti") == "bit"
        assert stem("SAM") == "bit"


class TestNounStemming:
    """Test noun declension — verify consistent stems across case forms."""

    @pytest.mark.parametrize("word,expected", [
        # kuća (house) - feminine noun, most cases collapse to "kuć"
        ("kuća", "kuć"),
        ("kuće", "kuć"),
        ("kući", "kuć"),
        ("kuću", "kuć"),
        ("kućom", "kuć"),
        # grad (city) - masculine noun
        ("grad", "grad"),
        ("grada", "grad"),
        ("gradu", "grad"),
        # gradovi/gradova now correctly collapse to "grad" (same as grad/grada/gradu)
        ("gradovi", "grad"),
        ("gradova", "grad"),
        # šuma (forest)
        ("šumu", "šum"),
        ("šumom", "šum"),
    ])
    def test_noun_cases(self, word, expected):
        assert stem(word) == expected


class TestAdjectiveStemming:
    """Test adjective declension forms."""

    @pytest.mark.parametrize("word,expected", [
        # lijep (beautiful) - most forms collapse to "lijep"
        ("lijep", "lijep"),
        ("lijepa", "lijep"),
        ("lijepo", "lijep"),
        ("lijepog", "lijep"),
        ("lijepom", "lijep"),
        # -im/-ih: matched by .+(b|č|d|l|m|p|r|s|š|ž)i rule → stem "lijepi"
        ("lijepim", "lijepi"),
        ("lijepih", "lijep"),
    ])
    def test_adjective_forms(self, word, expected):
        assert stem(word) == expected


class TestVerbStemming:
    """Test verb conjugation forms."""

    @pytest.mark.parametrize("word,expected", [
        # raditi — all forms canonicalized to "radit" (separate from noun rad)
        ("raditi", "radit"),
        ("radimo", "radit"),
        ("radite", "radit"),
        ("radim", "radit"),
        ("radi", "radit"),
    ])
    def test_verb_conjugation(self, word, expected):
        assert stem(word) == expected


class TestTransformations:
    """Test morphophonological transformations."""

    @pytest.mark.parametrize("word,expected", [
        # fleeting-a: transformation applied before suffix stripping
        ("metara", "metr"),
        ("centar", "centr"),
        ("centara", "centr"),
    ])
    def test_consonant_alternations(self, word, expected):
        assert stem(word) == expected


class TestSyllabicR:
    """Test that syllabic R is treated as a vowel."""

    @pytest.mark.parametrize("word,expected", [
        ("trga", "trg"),
        ("trg", "trg"),
        ("krv", "krv"),
        ("krvi", "krv"),
    ])
    def test_syllabic_r_words(self, word, expected):
        assert stem(word) == expected


class TestStemText:
    """Test text stemming."""

    def test_basic_text(self):
        result = stem_text("Veliki grad ima lijepe kuće")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_stop_words_excluded(self):
        # "sam" and "bio" are stop words: dropped, not emitted as "bit".
        assert stem_text("Ja sam bio u gradu") == ["ja", "u", "grad"]

    def test_lexicon_content_words_kept(self):
        # Lexicon forms that are not stop words are stemmed, not dropped.
        result = stem_text("Saznali smo da starim ljudima treba pomoć")
        assert result == ["saznat", "da", "star", "ljud", "pomoć"]

    def test_every_stop_word_is_in_the_lexicon(self):
        from croatian_stemmer.rules import LEXICON, STOP_WORDS

        assert len(STOP_WORDS) == 67
        assert STOP_WORDS <= LEXICON.keys()

    def test_empty_text(self):
        assert stem_text("") == []


class TestLiteraryExamples:
    """Test cases from Šume Striborove (reference from dmarsic/StemmerHr)."""

    @pytest.mark.parametrize("word,expected", [
        ("šumu", "šum"),
        ("šumom", "šum"),
        ("put", "put"),
        ("zašao", "zaša"),
        ("začarana", "začarn"),
    ])
    def test_literary_stems(self, word, expected):
        assert stem(word) == expected

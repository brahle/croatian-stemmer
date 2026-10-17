"""Tests for the Croatian stemmer."""

import pytest

from croatian_stemmer import stem, stem_text


class TestStopWords:
    """Stop words should be returned unchanged (lowercased)."""

    @pytest.mark.parametrize("word", [
        "biti", "jesam", "sam", "smo", "su", "bio", "bila", "bilo",
        "ću", "ćeš", "će", "ćemo", "ćete",
        "mogu", "možeš", "može", "možemo", "možete",
        "trebam", "treba", "moram", "mora",
        "želim", "želi", "žele",
    ])
    def test_stop_words_unchanged(self, word):
        assert stem(word) == word

    def test_stop_words_case_insensitive(self):
        assert stem("Biti") == "biti"
        assert stem("SAM") == "sam"


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
        # -im/-ih: the thematic-vowel step drops the stem-final i → "lijep"
        ("lijepim", "lijep"),
        ("lijepih", "lijep"),
    ])
    def test_adjective_forms(self, word, expected):
        assert stem(word) == expected


class TestVerbStemming:
    """Test verb conjugation forms."""

    @pytest.mark.parametrize("word,expected", [
        # raditi (to work) - -ti/-mo/-te suffixes handled by .+i rule, thematic -i- dropped
        ("raditi", "rad"),
        ("radimo", "rad"),
        ("radite", "rad"),
        # the thematic -i- is dropped, so every form agrees with bare "radi"
        ("radim", "rad"),
        # bare 3rd person/imperative strips -i via catch-all
        ("radi", "rad"),
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

    def test_content_words_kept(self):
        # Only the auxiliary/modal stop words are dropped.
        result = stem_text("Saznali smo da starim ljudima treba pomoć")
        assert result == ["sazn", "da", "star", "ljud", "pomoć"]

    def test_stop_list_is_the_v01_list(self):
        from croatian_stemmer.rules import STOP_WORDS

        assert len(STOP_WORDS) == 67

    def test_empty_text(self):
        assert stem_text("") == []


class TestLiteraryExamples:
    """Test cases from Šume Striborove (reference from dmarsic/StemmerHr)."""

    @pytest.mark.parametrize("word,expected", [
        ("šumu", "šum"),
        ("šumom", "šum"),
        ("put", "put"),
        ("zašao", "zađ"),
        ("začarana", "začarn"),
    ])
    def test_literary_stems(self, word, expected):
        assert stem(word) == expected


class TestThematicVowel:
    """The thematic vowel (rad-i-la, gled-a-ti) is dropped, so every verb
    form meets the bare forms the catch-all rule already strips."""

    @pytest.mark.parametrize("word,expected", [
        ("radila", "rad"),
        ("radio", "rad"),
        ("radim", "rad"),
        ("radi", "rad"),
        ("raditi", "rad"),
        ("gledati", "gled"),
        ("gledala", "gled"),
        ("gleda", "gled"),
        # -je- verbs: the jat reflex is the thematic vowel (vidje-ti, vidi)
        ("vidjeti", "vid"),
        ("vidjela", "vid"),
        ("vidio", "vid"),
    ])
    def test_thematic_vowel(self, word, expected):
        assert stem(word) == expected


class TestOvatiVerbs:
    """-ovati/-ivati verbs: the infinitive -ova-/-iva- and the present -uj-
    map to one -iv stem."""

    @pytest.mark.parametrize("word,expected", [
        ("djelovati", "djeliv"),
        ("djelovala", "djeliv"),
        ("djeluje", "djeliv"),
        ("djeluju", "djeliv"),
        ("pokazivati", "pokaziv"),
        ("pokazivao", "pokaziv"),
        ("pokazuje", "pokaziv"),
    ])
    def test_ovati_uje(self, word, expected):
        assert stem(word) == expected


class TestPassiveParticiples:
    """Passive participles meet their verb: jotation is undone (objavlj-en
    -> objav-iti, korišt-en -> korist-iti) and -iran loses -an."""

    @pytest.mark.parametrize("word,expected", [
        ("objavljen", "objav"),
        ("objavljena", "objav"),
        ("objavljenih", "objav"),
        ("objaviti", "objav"),
        ("organiziran", "organizir"),
        ("organizirana", "organizir"),
        ("organizirati", "organizir"),
        ("korišten", "korist"),
        ("korištena", "korist"),
        ("koristiti", "korist"),
        ("vraćen", "vrat"),
        ("vratiti", "vrat"),
    ])
    def test_participles(self, word, expected):
        assert stem(word) == expected


class TestFleetingA:
    """Fleeting a in -ao, -ak, -ac and -tar: the nominative's a is dropped
    to meet the oblique forms (posao/posla, kupac/kupca, metar/metra)."""

    @pytest.mark.parametrize("word,expected", [
        ("posao", "pos"),
        ("posla", "pos"),
        ("poslom", "pos"),
        ("postupak", "postupk"),
        ("postupka", "postupk"),
        ("postupaka", "postupk"),
        ("odlazak", "odlask"),
        ("odlaska", "odlask"),
        ("kupac", "kupc"),
        ("kupca", "kupc"),
        ("kupci", "kupc"),
        ("kupaca", "kupc"),
        ("metar", "metr"),
        ("metra", "metr"),
        ("metara", "metr"),
    ])
    def test_fleeting_a(self, word, expected):
        assert stem(word) == expected


class TestLParticiples:
    """Masculine l-participles (-ao/-eo) meet the feminine and plural."""

    @pytest.mark.parametrize("word,expected", [
        ("rekla", "rek"),
        ("rekao", "rek"),
        ("rekli", "rek"),
        ("pomogao", "pomog"),
        ("pomogla", "pomog"),
        # -ići compounds: došao is read as the present stem (dođe), and
        # došla/došli map -šl- to -đ- to meet it; the đ is kept
        ("došao", "dođ"),
        ("došla", "dođ"),
        ("došli", "dođ"),
        ("dođe", "dođ"),
        ("počeo", "počel"),
        ("počela", "počel"),
    ])
    def test_l_participles(self, word, expected):
        assert stem(word) == expected


class TestParadigmsMeet:
    """Every form of one lemma reaches the same stem."""

    @pytest.mark.parametrize("forms", [
        # -ići compounds: l-participle -šl-/-šao and the present -đ-
        ("došao", "došla", "došli", "dođe", "dođu"),
        ("prošao", "prošla", "prošli", "prošlog", "prođe", "prođu"),
        ("našao", "našla", "našli", "nađe", "nađem"),
        ("pošao", "pošla", "pođe"),
        ("izašao", "izašla", "izađe"),
        # sl jotates to šlj in the participle (misliti -> mišljen)
        ("misliti", "mislio", "mišljen"),
        ("zamisliti", "zamišljen"),
        # verbs and pronouns with a palatal root keep it in every form
        ("tražiti", "traži", "tražio", "tražim"),
        ("održati", "održi", "održao", "održala"),
        ("pokušati", "pokušao", "pokuša"),
        ("držati", "drži", "drže"),
        ("pričati", "pričam", "priča", "pričali"),
        ("pružiti", "pruži", "pružio"),
        ("naš", "naša", "našeg", "našem", "našim"),
        # -š- comparatives after k/p still meet the positive
        ("lak", "lakši", "lakše", "najlakše"),
        # dative/locative -u of -aj nouns
        ("slučaj", "slučaja", "slučaju"),
        ("kraj", "kraja", "kraju"),
        ("uređaj", "uređaja", "uređaju"),
        ("položaj", "položaja", "položaju"),
        ("utjecaj", "utjecaja", "utjecaju"),
        ("događaj", "događaja", "događaju"),
        # a-verbs in -raju after a syllable stay verbs; traju meets trajati
        ("igrati", "igraju", "igra"),
        ("smatrati", "smatraju", "smatra"),
        ("trajati", "traju", "traje"),
        # -je-/-ije- verbs drop the jat theme; -je- roots keep it
        ("vidjeti", "vidjela", "vidio", "vidi"),
        ("voljeti", "voljela", "volio", "voli"),
        ("živjeti", "živjela", "živio", "živi"),
        ("željeti", "željela", "želio"),
        ("sjediti", "sjedio", "sjedi", "sjedila"),
        ("uspjeti", "uspjela", "uspio"),
        ("razumjeti", "razumjela", "razumije"),
        ("donijeti", "donijeli", "donio"),
        ("umrijeti", "umro", "umrla"),
        ("savjet", "savjeta", "savjeti", "savjetu"),
        ("posjetiti", "posjeti", "posjetio"),
        ("podijeliti", "podijeli", "podijelio"),
        ("podjela", "podjele", "podjelu"),
        ("dodjela", "dodjele", "dodjelu"),
        # -eg/-ega is the soft adjective genitive only after a palatal or j
        ("kolega", "kolege", "kolegu"),
        ("snijeg", "snijega", "snijegu"),
        ("brijeg", "brijega", "brijegu"),
        ("bubreg", "bubrega", "bubregu"),
        ("opseg", "opsega", "opsegu"),
        ("bolji", "boljeg", "boljem"),
        ("posljednji", "posljednjeg", "posljednja"),
        ("opći", "općeg", "opća"),
        ("koji", "kojeg", "kojem"),
        ("svoj", "svojeg", "svoja"),
        ("stariji", "starijeg", "star"),
        # a stem-final r after a consonant is not syllabic (br-oj, vr-at)
        ("broj", "broja", "broju", "brojevi"),
        ("stroj", "stroja"),
        ("zbroj", "zbroja"),
        ("vrat", "vrata"),
        ("brat", "brata"),
        # a syllabic r between consonants is a vowel (trg, krv, prst)
        ("trg", "trga"),
        ("krv", "krvi"),
        ("prst", "prsta"),
        ("srce", "srca"),
        ("crkva", "crkve"),
        ("vrh", "vrha"),
        ("cvrčak", "cvrčka"),
        ("vršak", "vrška"),
        ("mrtvac", "mrtvacu", "mrtvaca"),
        ("smrzao", "smrzla"),
        # -uj- belongs to the root when no vowel precedes it
        ("struja", "struju", "struje", "struji"),
        ("kupovati", "kupuje", "kupuju"),
        # -dak nouns alternate like -tak: pogodak/pogotka/pogoci
        ("pogodak", "pogotka", "pogoci", "pogodaka"),
        ("napredak", "napretka", "napretku"),
        ("dohodak", "dohotka"),
        ("sladak", "slatka", "slatki"),
        ("podatak", "podatka", "podaci"),
        ("vozilo", "vozila", "vozilu", "vozilom"),
    ])
    def test_paradigm_meets(self, forms):
        assert len({stem(f) for f in forms}) == 1, {f: stem(f) for f in forms}


class TestMustNotMerge:
    """Forms of unrelated lemmas keep different stems."""

    @pytest.mark.parametrize("a,b", [
        # -ići compounds keep the palatal đ of their present
        ("prošli", "prodaja"),
        ("prošla", "prodati"),
        ("došao", "dodao"),
        ("dođe", "dodati"),
        ("pošao", "podati"),
        ("našla", "nada"),
        ("našao", "naš"),
        # a palatal root is not undone to a velar or s
        ("tražiti", "trag"),
        ("traži", "traga"),
        ("pokušati", "pokus"),
        ("pružiti", "pruga"),
        ("naš", "nas"),
        ("našeg", "nas"),
        ("vaš", "vas"),
        # -aj nouns keep -aj in the dative/locative
        ("uređaju", "ured"),
        ("slučaju", "sluk"),
        ("položaju", "položiti"),
        ("kraju", "krasti"),
        # -je- after a prefix plus one consonant belongs to the root
        ("savjeti", "sav"),
        ("zavjeti", "zav"),
        ("posjeti", "pos"),
        ("podijeli", "pod"),
        ("podjela", "pod"),
        ("dodjela", "dodati"),
        ("strijela", "strah"),
        # kolega is not kolo
        ("kolega", "kolo"),
        ("kolega", "kola"),
        # br-oj and br-at are not the vowelless br- of brati
        ("broj", "brati"),
        ("brat", "brati"),
        ("broj", "brijati"),
        ("stroj", "strah"),
        ("vozilo", "voziti"),
    ])
    def test_distinct_stems(self, a, b):
        assert stem(a) != stem(b)

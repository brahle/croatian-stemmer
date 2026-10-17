"""
Stemming rules for the Ljubešić-Pandžić Croatian stemmer.

Based on: "Retrieving Information in Croatian: Building a Simple and Efficient
Rule-Based Stemmer" by Ljubešić, Boras & Kubelka (2007).

The stop list, transformations and suffix rules derive from "Simple stemmer
for Croatian v0.1", Copyright 2012 Nikola Ljubešić and Ivan Pandžić, released
under the GNU LGPL v3.0 or later. The rule additions were tuned against the
hr500k corpus (see AUTORESEARCH.md and results.tsv).
"""

import re

# Stop words: the original v0.1 list of auxiliary/modal forms (biti, htjeti,
# željeti, morati, trebati, moći). stem() returns them unchanged;
# stem_text() and the PostgreSQL dictionary drop them as function words.
STOP_WORDS: frozenset[str] = frozenset({
    "biti", "jesam", "budem", "sam", "jesi", "budeš", "si", "jesmo",
    "budemo", "smo", "jeste", "budete", "ste", "jesu", "budu", "su", "bih",
    "bijah", "bjeh", "bijaše", "bi", "bje", "bješe", "bijasmo", "bismo",
    "bjesmo", "bijaste", "biste", "bjeste", "bijahu", "biše", "bjehu", "bio",
    "bili", "budimo", "budite", "bila", "bilo", "bile",
    "ću", "ćeš", "će", "ćemo", "ćete",
    "želim", "želiš", "želi", "želimo", "želite", "žele",
    "moram", "moraš", "mora", "moramo", "morate", "moraju",
    "trebam", "trebaš", "treba", "trebamo", "trebate", "trebaju",
    "mogu", "možeš", "može", "možemo", "možete",
})

# Morphophonological suffix transformations.
# Applied before suffix stripping to normalize consonant alternations
# (palatalization, sibilarization, jotation, fleeting-a, etc.)
TRANSFORMATIONS: dict[str, str] = {
    "lozi": "loga", "lozima": "loga", "pjesi": "pjeh", "pjesima": "pjeh",
    "vojci": "vojka", "bojci": "bojka", "jaci": "jak", "jacima": "jak",
    "čajan": "čajni", "ijeran": "ijerni", "laran": "larni",
    "ijesan": "ijesni", "anjac": "anjca", "ajac": "ajca", "ajaca": "ajca",
    "ljaca": "ljca", "ljac": "ljca", "ejac": "ejca", "ejaca": "ejca",
    "ojac": "ojca", "ojaca": "ojca", "ajaka": "ajka", "ojaka": "ojka",
    "šaca": "šca", "šac": "šca", "inzima": "ing", "inzi": "ing",
    "tvenici": "tvenik", "tetici": "tetika", "teticima": "tetika",
    "nstava": "nstva", "nicima": "nik", "nici": "nik",
    "ticima": "tik", "tici": "tik", "zicima": "zik", "zici": "zik",
    "snici": "snik", "kuse": "kusi", "kusan": "kusni", "kustava": "kustva",
    "dušan": "dušni", "antan": "antni", "bilan": "bilni", "tilan": "tilni",
    "avilan": "avilni", "silan": "silni", "gilan": "gilni", "rilan": "rilni",
    "nilan": "nilni", "alan": "alni", "ozan": "ozni", "rave": "ravi",
    "stavan": "stavni", "pravan": "pravni", "tivan": "tivni",
    "sivan": "sivni", "atan": "atni", "cenata": "centa", "denata": "denta",
    "genata": "genta", "lenata": "lenta", "menata": "menta",
    "jenata": "jenta", "venata": "venta", "tetan": "tetni",
    "pletan": "pletni", "šave": "šavi", "manata": "manta",
    "tanata": "tanta", "lanata": "lanta", "sanata": "santa",
    "ačak": "ačka", "ačaka": "ačka", "ušak": "uška", "atak": "atka",
    "ataka": "atka", "atci": "atka", "atcima": "atka", "etak": "etka",
    "etaka": "etka", "itak": "itka", "itaka": "itka", "itci": "itka",
    "otak": "otka", "otaka": "otka", "utak": "utka", "utaka": "utka",
    "utci": "utka", "utcima": "utka", "eskan": "eskna", "tičan": "tični",
    "ojsci": "ojska", "esama": "esma", "metara": "metra",
    "centar": "centra", "centara": "centra", "istara": "istra",
    "istar": "istra", "ošću": "osti", "daba": "dba", "čcima": "čka",
    "čci": "čka", "mac": "mca", "maca": "mca", "naca": "nca", "nac": "nca",
    "voljan": "voljni", "anaka": "anki", "vac": "vca", "vaca": "vca",
    "saca": "sca", "sac": "sca", "raca": "rca", "rac": "rca",
    "aoca": "alca", "alaca": "alca", "alac": "alca", "elaca": "elca",
    "elac": "elca", "olaca": "olca", "olac": "olca", "olce": "olca",
    "njac": "njca", "njaca": "njca", "ekata": "ekta", "ekat": "ekta",
    "izam": "izma", "izama": "izma", "jebe": "jebi", "baci": "baci",
    "ašan": "ašni",
    # Sibilarization k -> c before -i: masculine plurals (koraci, počeci,
    # trenuci), feminine dative/locative (ruci, odluci) and -ći imperatives
    # (povuci). -icima is always a -k plural (-ica nouns take -icama);
    # bare -ici (stranici) and -eci (mjeseci) are left alone: there -c- is
    # usually part of the noun.
    "acima": "ak", "icima": "ik", "ocima": "ok",
    "ucima": "uk", "aci": "ak", "oci": "ok", "uci": "uk",
    # l -> o vocalization: masculine -eo stands for -el- (počeo/počela,
    # doveo/dovela, debeo/debela, anđeo/anđela); stem it as the feminine.
    "eo": "ela",
    # Fleeting a in the genitive plural of -stvo nouns after a consonant
    # (ministarstava, svojstava, jamstava, sredstava, bogatstava), extending
    # the v0.1 nstava/kustava entries; after a vowel -stava is usually a
    # verb or noun with a stable a (ostava, zaustava). -uštava: društava.
    "rstava": "rstva", "jstava": "jstva", "mstava": "mstva",
    "dstava": "dstva", "tstava": "tstva", "lstava": "lstva",
    "vstava": "vstva", "kstava": "kstva", "pstava": "pstva",
    "bstava": "bstva", "gstava": "gstva", "uštava": "uštva",
    # Masculine l-participle of -ići compounds (došao, prošao, otišao,
    # naišao, našao, izašao, pronašao): read as the present stem (dođe,
    # prođe, otiđe, naiđe, nađe, izađe), which došla/prošli also reach.
    # -ušao is left alone because a-verbs in -šati share it (pokušao,
    # slušao); -ašao a-verbs need a root in -aš- (ponašao, obnašao), which
    # is rare.
    "ošao": "ođe", "išao": "iđe", "ašao": "ađe",
    # Imperative plural of velar -ći verbs sibilarizes k -> c (recite,
    # recimo, povucite, izvucimo); -ecite/-ecimo/-ucite/-ucimo are only
    # verbal, unlike bare -eci (mjeseci).
    "ecite": "ek", "ecimo": "ek", "ucite": "uk", "ucimo": "uk",
}

# Suffix stripping rules: (stem_pattern, suffix_alternatives) pairs.
# Each compiles to ^(stem_pattern)(suffix1|suffix2|...)$.
# Ordered by specificity — first match wins.
# The v0.1 rule set, in its original order, plus additions found by the
# autoresearch loop (the .+ed rule, non-greedy catch-alls).
_RULES: list[tuple[str, str]] = [
    # --- Nouns ---
    ('.+(s|š)k', 'ijima|ijega|ijemu|ijem|ijim|ijih|ijoj|ijeg|iji|ije|ija|oga|ome|omu|ima|og|om|im|ih|oj|i|e|o|a|u'),
    ('.+(s|š)tv', 'ima|om|o|a|u'),
    ('.+(t|m|p|r|g)anij', 'ama|ima|om|a|u|e|i|'),
    ('.+an', 'inom|ina|inu|ine|ima|in|om|u|i|a|e|'),
    ('.+in', 'ima|ama|om|a|e|i|u|o|'),
    ('.+on', 'ovima|ova|ove|ovi|ima|om|a|e|i|u|'),
    ('.+n', 'ijima|ijega|ijemu|ijeg|ijem|ijim|ijih|ijoj|iji|ije|ija|iju|ima|ome|omu|oga|oj|om|ih|im|og|o|e|a|u|i|'),
    # --- Ć ---
    ('.+(a|e|u)ć', 'oga|ome|omu|ega|emu|ima|oj|ih|om|eg|em|og|uh|im|e|a'),
    # --- G ---
    ('.+ugov', 'ima|i|e|a'),
    ('.+ug', 'ama|om|a|e|i|u|o'),
    # Nouns in -log follow a vowel (dijalog, psiholog, prilog, nalog) or a
    # prefix ending in b/d/z (oblog, prijedlog, razlog); after -e- or another
    # consonant -log is an adjective genitive (cijel-og, topl-og, prošl-og).
    ('.*([aiou]|[bdz])log', 'ama|om|a|u|e|'),
    ('.+[^eo]g', 'ovima|ama|ovi|ove|ova|om|a|e|i|u|o|'),
    # --- I ---
    ('.+(rrar|ott|ss|ll)i', 'jem|ja|ju|o|'),
    # --- J ---
    ('.+uj', 'ući|emo|ete|mo|te|em|eš|e|u|'),
    # Dative/locative -u of -aj nouns. -čaj/-caj/-žaj/-đaj are noun
    # suffixes (slučaj, utjecaj, položaj, događaj) whose -aju outnumbers the
    # a-verb 3pl (pričaju, bacaju, pružaju) by token. Before -raj only a
    # vowelless onset marks the noun (kraj-u); a-verb 3pl -raju has a
    # syllable before it (igraju, smatraju, otvaraju).
    ('.+(c|č|ž|đ)aj', 'u'),
    ('[^aeiou]+raj', 'u'),
    ('.+(c|č|ć|đ|l|r)aj', 'evima|evi|eva|eve|ama|ima|em|a|e|i|'),
    ('.+(b|c|d|l|n|m|ž|g|f|p|r|s|t|z)ij', 'ima|ama|om|a|e|i|u|o|'),
    # --- L ---
    ('.+[^z]nal', 'ima|ama|om|a|e|i|u|o|'),
    # The Latin -ijal suffix follows -c- or vowel+r (potencijal, materijal);
    # after other consonants -ijal- is a verb's -ija- + l-participle
    # (odbijala, zagrijali, smijali).
    ('.+(c|[aeiou]r)ijal', 'ima|ama|om|a|e|i|u|o|'),
    # Neuter -ozilo nouns (vozilo, prijevozilo) take -o like the other cases.
    ('.+ozil', 'ima|om|a|e|u|i|o|'),
    ('.+olov', 'ima|i|a|e'),
    ('.+ol', 'ima|om|a|u|e|i|'),
    # --- M ---
    ('.+lem', 'ama|ima|om|a|e|i|u|o|'),
    # Masculine -ram nouns are -gram/-hram/-sram (program, kilogram, hram);
    # elsewhere -rama is a feminine -ra noun's plural (mjerama, sestrama).
    ('.*(g|h|s)ram', 'ama|om|a|e|i|u|'),
    # --- R ---
    ('.+(a|d|e|o)r', 'ama|ima|om|u|a|e|i|'),
    # --- S ---
    ('.+(e|i)s', 'ima|om|e|a|u'),
    # --- Š ---
    ('.+(t|n|j|k|j|t|b|g|v)aš', 'ama|ima|om|em|a|u|i|e'),
    ('.+(e|i)š', 'ima|ama|om|em|i|e|a|u'),
    # --- T ---
    ('.+ikat', 'ima|om|a|e|i|u|o|'),
    ('.+lat', 'ima|om|a|e|i|u|o|'),
    # Verb e-class present (provesti, jesti) — insert before noun .+et
    ('.+ed', 'ete|emo|eš|em|e|u'),
    # e-class present after a palatal (kaž-ete, piš-eš, dođ-ete), before
    # the -et noun rule would read kažete as kažet-e
    ('.+(č|ć|đ|š|ž)', 'ete|eš'),
    # no -e: -ete is far more often the 2pl present (kren-ete, uzm-ete)
    # than the accusative plural of an -et noun (uvjet-e)
    ('.+et', 'ama|ima|om|a|i|u|o|'),
    ('.+(e|i|k|o)st', 'ima|ama|om|a|e|i|u|o|'),
    ('.+išt', 'ima|em|a|e|u'),
    # --- V ---
    ('.+ova', 'smo|ste|hu|ti|še|li|la|le|lo|t|h|o'),
    ('.+(a|e|i)v', 'ijemu|ijima|ijega|ijeg|ijem|ijim|ijih|ijoj|oga|ome|omu|ima|ama|iji|ije|ija|iju|im|ih|oj|om|og|i|a|u|e|o|'),
    ('.+[^dkml]ov', 'ijemu|ijima|ijega|ijeg|ijem|ijim|ijih|ijoj|oga|ome|omu|ima|iji|ije|ija|iju|im|ih|oj|om|og|i|a|u|e|o|'),
    ('.+(m|l)ov', 'ima|om|a|u|e|i|'),
    # --- Adjectives ---
    ('.+el', 'ijemu|ijima|ijega|ijeg|ijem|ijim|ijih|ijoj|oga|ome|omu|ima|iji|ije|ija|iju|im|ih|oj|om|og|i|a|u|e|o|'),
    ('.+(a|e|š)nj', 'ijemu|ijima|ijega|ijeg|ijem|ijim|ijih|ijoj|oga|ome|omu|ima|iji|ije|ija|iju|ega|emu|eg|em|im|ih|oj|om|og|a|e|i|o|u'),
    ('.+čin', 'ama|ome|omu|oga|ima|og|om|im|ih|oj|a|u|i|o|e|'),
    ('.+roši', 'vši|smo|ste|še|mo|te|ti|li|la|lo|le|m|š|t|h|o'),
    ('.+oš', 'ijemu|ijima|ijega|ijeg|ijem|ijim|ijih|ijoj|oga|ome|omu|ima|iji|ije|ija|iju|im|ih|oj|om|og|i|a|u|e|'),
    ('.+(e|o)vit', 'ijima|ijega|ijemu|ijem|ijim|ijih|ijoj|ijeg|iji|ije|ija|oga|ome|omu|ima|og|om|im|ih|oj|i|e|o|a|u|'),
    ('.+ast', 'ijima|ijega|ijemu|ijem|ijim|ijih|ijoj|ijeg|iji|ije|ija|oga|ome|omu|ima|og|om|im|ih|oj|i|e|o|a|u|'),
    ('.+k', 'ijemu|ijima|ijega|ijeg|ijem|ijim|ijih|ijoj|oga|ome|omu|ima|iji|ije|ija|iju|im|ih|oj|om|og|i|a|u|e|o|'),
    # --- Verbs ---
    ('.+(e|a|i|u)va', 'jući|smo|ste|jmo|jte|ju|la|le|li|lo|mo|na|ne|ni|no|te|ti|še|hu|h|j|m|n|o|t|v|š|'),
    ('.+ir', 'ujemo|ujete|ujući|ajući|ivat|ujem|uješ|ujmo|ujte|avši|asmo|aste|ati|amo|ate|aju|aše|ahu|ala|alo|ali|ale|uje|uju|uj|al|an|am|aš|at|ah|ao'),
    ('.+ač', 'ismo|iste|iti|imo|ite|iše|eći|ila|ilo|ili|ile|ena|eno|eni|ene|io|im|iš|it|ih|en|i|e'),
    ('.+ača', 'vši|smo|ste|smo|ste|hu|ti|mo|te|še|la|lo|li|le|ju|na|no|ni|ne|o|m|š|t|h|n'),
    # --- Verb n-class ---
    # -nuti verbs; the passive participle -nut- takes every adjective ending
    # (spomenut-a, spomenut-ih, spomenut-og), not only -ut/-uta/-uti/-uto
    ('.+n', 'utima|uvši|usmo|uste|utih|utim|utog|utom|utoj|ući|imo|ite|emo|ete|ula|ulo|ule|uli|uto|uti|uta|ute|utu|em|eš|uo|ut|e|u|i'),
    ('.+ni', 'vši|smo|ste|ti|mo|te|mo|te|la|lo|le|li|m|š|o'),
    # --- Verb a-class ---
    ('.+((a|r|i|p|e|u)st|[^o]g|ik|uc|oj|aj|lj|ak|ck|čk|šk|uk|nj|im|ar|at|et|št|it|ot|ut|zn|zv)a', 'jući|vši|smo|ste|jmo|jte|jem|mo|te|je|ju|ti|še|hu|la|li|le|lo|na|no|ni|ne|t|h|o|j|n|m|š'),
    ('.+ur', 'ajući|asmo|aste|ajmo|ajte|amo|ate|aju|ati|aše|ahu|ala|ali|ale|alo|ana|ano|ani|ane|al|at|ah|ao|aj|an|am|aš'),
    ('.+(a|i|o)staj', 'asmo|aste|ahu|ati|emo|ete|aše|ali|ući|ala|alo|ale|mo|ao|em|eš|at|ah|te|e|u|'),
    # l-participles used as adjectives (ostali, nastali, preostali) take the
    # adjective case endings too: ostalih, ostalim, ostalog, ostaloj.
    ('.+(b|c|č|ć|d|e|f|g|j|k|n|r|t|u|v)a', 'lama|lima|loga|lome|lomu|lih|lim|log|loj|lom|lu|li|la|le|lo|l'),
    ('.+(t|č|j|ž|š)aj', 'evima|evi|eva|eve|ama|ima|em|a|e|i|'),
    ('.+([^o]m|ič|nč|uč|b|c|ć|d|đ|h|j|k|l|n|p|r|s|š|v|z|ž)a', 'jući|vši|smo|ste|jmo|jte|mo|te|ju|ti|še|hu|la|li|le|lo|na|no|ni|ne|t|h|o|j|n|m|š'),
    ('.+(a|i|o)sta', 'dosmo|doste|doše|nemo|demo|nete|dete|nimo|nite|nila|vši|nem|dem|neš|deš|doh|de|ti|ne|nu|du|la|li|lo|le|t|o'),
    ('.+ta', 'smo|ste|jmo|jte|vši|ti|mo|te|ju|še|la|lo|le|li|na|no|ni|ne|n|j|o|m|š|t|h'),
    ('.+inj', 'asmo|aste|ati|emo|ete|ali|ala|alo|ale|aše|ahu|em|eš|at|ah|ao'),
    ('.+as', 'temo|tete|timo|tite|tući|tem|teš|tao|te|li|ti|la|lo|le'),
    # --- Verb i-class ---
    ('.+(elj|ulj|tit|ac|ič|od|oj|et|av|ov)i', 'vši|eći|smo|ste|še|mo|te|ti|li|la|lo|le|m|š|t|h|o'),
    ('.+(tit|jeb|ar|ed|uš|ič)i', 'jemo|jete|jem|ješ|smo|ste|jmo|jte|vši|mo|še|te|ti|ju|je|la|lo|li|le|t|m|š|h|j|o'),
    ('.+(b|c|č|ć|d|đ|g|h|j|k|l|m|n|p|r|s|š|t|v|z|ž)i', 'jemo|jete|jem|ješ|smo|ste|jmo|jte|vši|mo|lu|še|te|ti|ju|je|la|lo|li|le|t|m|š|h|j|o'),
    ('.+luč', 'ujete|ujući|ujemo|ujem|uješ|ismo|iste|ujmo|ujte|uje|uju|iše|iti|imo|ite|ila|ilo|ili|ile|ena|eno|eni|ene|uj|io|en|im|iš|it|ih|e|i'),
    ('.+jeti', 'smo|ste|še|mo|te|ti|li|la|lo|le|m|š|t|h|o'),
    # --- L-participle ---
    ('.+e', 'lama|lima|lom|lu|li|la|le|lo|l'),
    ('.+i', 'lama|lima|lom|lu|li|la|le|lo|l'),
    # --- Adjective participle ---
    ('.+at', 'ijega|ijemu|ijima|ijeg|ijem|ijih|ijim|ima|oga|ome|omu|iji|ije|ija|iju|oj|og|om|im|ih|a|u|i|e|o|'),
    ('.+et', 'avši|ući|emo|imo|em|eš|e|u|i'),
    # --- Catch-all rules (non-greedy stems, iteration #2 improvement) ---
    ('.+?', 'ajući|alima|alom|avši|asmo|aste|ajmo|ajte|ivši|amo|ate|aju|ati|aše|ahu|ali|ala|ale|alo|ana|ano|ani|ane|am|aš|at|ah|ao|aj|an'),
    ('.+?', 'anje|enje|anja|enja|enom|enoj|enog|enim|enih|anom|anoj|anog|anim|anih|eno|ovi|ova|oga|ima|ove|enu|anu|ena|ama'),
    ('.+?', 'nijega|nijemu|nijima|nijeg|nijem|nijim|nijih|nima|niji|nije|nija|niju|noj|nom|nog|nim|nih|an|na|nu|ni|ne|no'),
    # Long pronominal dative/locative of adjectives and determiners. Soft
    # -emu follows a palatal (našemu, kojemu, nečemu); hard -ome/-omu follow
    # the adjective-forming -k-/-n-/-v- (ljudskome, glavnome, novome, svakomu).
    # Elsewhere they are a noun's -em-u/-om-e (problemu, diplome, sindromu).
    ('.+(č|ć|đ|j|š|ž)', 'emu'),
    ('.+(k|n|v)', 'ome|omu'),
    # Soft adjective/pronoun genitive -eg/-ega, the counterpart of -og/-oga,
    # follows a palatal or j (našeg, općeg, nečega, boljeg, posljednjeg,
    # kojeg, svojeg, dječjeg). -ijeg is the comparative (starijeg) only
    # with a syllable before -ij: after a vowelless onset it is a noun's jat
    # root (snijeg, bijeg, brijeg). After other consonants -eg/-ega belongs
    # to a noun (kolega, bubreg, opseg, strateg).
    ('.+(č|ć|đ|š|ž|[^i]j)', 'ega|eg'),
    ('.*[aeiou].*ij', 'ega|eg'),
    ('.+?', 'emo|ete|amo|ate|imo|ite|om|og|im|ih|em|eš|oj|an|u|o|i|e|a'),
]

# Precompiled regex patterns for suffix stripping
WORD_PATTERNS: list[re.Pattern[str]] = [
    re.compile(rf"^({stem})({suffixes})$")
    for stem, suffixes in _RULES
]

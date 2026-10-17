"""
Stemming rules for the Ljubešić-Pandžić Croatian stemmer.

Based on: "Retrieving Information in Croatian: Building a Simple and Efficient
Rule-Based Stemmer" by Ljubešić, Boras & Kubelka (2007).

The stop list, transformations and suffix rules derive from "Simple stemmer
for Croatian v0.1", Copyright 2012 Nikola Ljubešić and Ivan Pandžić, released
under the GNU LGPL v3.0 or later. LEXICON and the rule additions were tuned
against the hr500k corpus (see AUTORESEARCH.md and results.tsv).
"""

import re

# Full-form lexicon: inflected form -> canonical stem for its lemma. Covers
# irregular/suppletive paradigms (auxiliaries, modals, frequent verbs) and a
# few adjective forms the suffix rules over- or under-strip, so every form of
# a listed lemma collapses to one stem. stem() consults it before the rules.
LEXICON: dict[str, str] = {
    # biti (to be) — copula + future + conditional auxiliary
    **{w: "bit" for w in (
        "biti", "jesam", "budem", "sam", "jesi", "budeš", "si",
        "jesmo", "budemo", "smo", "jeste", "budete", "ste",
        "jesu", "budu", "su", "bih", "bijah", "bjeh", "bijaše",
        "bi", "bje", "bješe", "bijasmo", "bismo", "bjesmo",
        "bijaste", "biste", "bjeste", "bijahu", "biše", "bjehu",
        "bio", "bili", "budimo", "budite", "bila", "bilo", "bile",
    )},
    # htjeti (to want / future aux) — full irregular paradigm
    **{w: "ht" for w in (
        "ću", "ćeš", "će", "ćemo", "ćete",
        "htjeti", "hoću", "hoćeš", "hoće", "hoćemo", "hoćete",
        "htio", "htjela", "htjelo", "htjeli", "htjele",
        "htjedoh", "htjede", "htjedosmo", "htjedoste", "htjedoše",
        "htijući", "htijaše",
        "neću", "nećeš", "neće", "nećemo", "nećete",
    )},
    # željeti (to wish)
    **{w: "želj" for w in ("želim", "želiš", "želi", "želimo", "želite", "žele")},
    # morati (must)
    **{w: "mor" for w in ("moram", "moraš", "mora", "moramo", "morate", "moraju")},
    # trebati (need)
    **{w: "treb" for w in ("trebam", "trebaš", "treba", "trebamo", "trebate", "trebaju")},
    # moći (can)
    **{w: "moć" for w in ("mogu", "možeš", "može", "možemo", "možete")},
    # jesti (to eat) — skip ambiguous "jelo"/"jela" (also nouns)
    **{w: "jed" for w in (
        "jesti", "jedem", "jedeš", "jede", "jedemo", "jedete", "jedu",
        "jeo", "jedi", "jedite", "jedimo", "jedući",
    )},
    # dati (to give) — skip "da" (conjunction/affirmative)
    **{w: "dat" for w in (
        "dati", "dam", "daš", "damo", "date", "daju",
        "dao", "dala", "dalo", "dali", "dale",
        "daj", "dajte", "dajmo", "dajući", "davši",
    )},
    # Common -Ci adj with rule 62 overcapture on -im/-ima inst forms
    **{w: "star" for w in ("starim", "starima", "starimi")},
    **{w: "nov" for w in ("novim", "novima", "novimi")},
    **{w: "pun" for w in ("punim", "punima", "punimi")},
    **{w: "crn" for w in ("crnim", "crnima", "crnimi")},
    **{w: "bijel" for w in ("bijelim", "bijelima", "bijelimi")},
    **{w: "zelen" for w in ("zelenim", "zelenima", "zelenimi")},
    **{w: "slab" for w in ("slabim", "slabima", "slabimi")},
    **{w: "drag" for w in ("dragim", "dragima", "dragimi")},
    **{w: "jak" for w in ("jakim", "jakima", "jakimi")},
    # saznati (to find out)
    **{w: "saznat" for w in (
        "saznati", "saznam", "saznaš", "sazna", "saznamo", "saznate", "saznaju",
        "saznao", "saznala", "saznalo", "saznali", "saznale",
        "saznat",
    )},
    # saznavati (imperf)
    **{w: "saznavat" for w in (
        "saznavati", "saznajem", "saznaješ", "saznaje", "saznajemo",
        "saznajete", "saznaju",
        "saznavao", "saznavala", "saznavalo", "saznavali", "saznavale",
        "saznavat",
    )},
    # uključiti (to include)
    **{w: "uključit" for w in (
        "uključiti", "uključim", "uključiš", "uključi", "uključimo",
        "uključite", "uključe",
        "uključio", "uključila", "uključilo", "uključili", "uključile",
        "uključit",
    )},
    # uključivati (imperf)
    **{w: "uključivat" for w in (
        "uključivati", "uključujem", "uključuješ", "uključuje", "uključujemo",
        "uključujete", "uključuju",
        "uključivao", "uključivala", "uključivalo", "uključivali", "uključivale",
        "uključivat",
    )},
    # razviti (to develop)
    **{w: "razvit" for w in (
        "razviti", "razvijem", "razviješ", "razvije", "razvijemo",
        "razvijete", "razviju",
        "razvio", "razvila", "razvilo", "razvili", "razvile",
        "razvit",
    )},
    # razvijati (imperf)
    **{w: "razvijat" for w in (
        "razvijati", "razvijam", "razvijaš", "razvija", "razvijamo",
        "razvijate", "razvijaju",
        "razvijao", "razvijala", "razvijalo", "razvijali", "razvijale",
        "razvijat",
    )},
    # skinuti (to take off)
    **{w: "skinut" for w in (
        "skinuti", "skinem", "skineš", "skine", "skinemo", "skinete", "skinu",
        "skinuo", "skinula", "skinulo", "skinuli", "skinule",
        "skinut",
    )},
    # odbijati (imperf of odbiti)
    **{w: "odbijat" for w in (
        "odbijati", "odbijam", "odbijaš", "odbija", "odbijamo",
        "odbijate", "odbijaju",
        "odbijao", "odbijala", "odbijalo", "odbijali", "odbijale",
        "odbijat",
    )},
    # objasnjavati (imperf)
    **{w: "objašnjavat" for w in (
        "objašnjavati", "objašnjavam", "objašnjavaš", "objašnjava", "objašnjavamo",
        "objašnjavate", "objašnjavaju",
        "objašnjavao", "objašnjavala", "objašnjavalo", "objašnjavali", "objašnjavale",
        "objašnjavat",
    )},
    # posjećivati (imperf of posjetiti)
    **{w: "posjećivat" for w in (
        "posjećivati", "posjećujem", "posjećuješ", "posjećuje", "posjećujemo",
        "posjećujete", "posjećuju",
        "posjećivao", "posjećivala", "posjećivalo", "posjećivali", "posjećivale",
        "posjećivat",
    )},
    # djelovati (to act) — djelujem
    **{w: "djelovat" for w in (
        "djelovati", "djelujem", "djeluješ", "djeluje", "djelujemo",
        "djelujete", "djeluju",
        "djelovao", "djelovala", "djelovalo", "djelovali", "djelovale",
        "djelovat",
    )},
    # upravljati (to manage)
    **{w: "upravljat" for w in (
        "upravljati", "upravljam", "upravljaš", "upravlja", "upravljamo",
        "upravljate", "upravljaju",
        "upravljao", "upravljala", "upravljalo", "upravljali", "upravljale",
        "upravljat",
    )},
    # predvidjeti (to predict)
    **{w: "predvidjet" for w in (
        "predvidjeti", "predvidim", "predvidiš", "predvidi", "predvidimo",
        "predvidite", "predvide",
        "predvidio", "predvidjela", "predvidjelo", "predvidjeli", "predvidjele",
        "predvidjet",
    )},
    # predviđati (imperf)
    **{w: "predviđat" for w in (
        "predviđati", "predviđam", "predviđaš", "predviđa", "predviđamo",
        "predviđate", "predviđaju",
        "predviđao", "predviđala", "predviđalo", "predviđali", "predviđale",
        "predviđat",
    )},
    # pregledati (to look at)
    **{w: "pregledat" for w in (
        "pregledati", "pregledam", "pregledaš", "pregleda", "pregledamo",
        "pregledate", "pregledaju",
        "pregledao", "pregledala", "pregledalo", "pregledali", "pregledale",
        "pregledat",
    )},
    # natjerati (to force)
    **{w: "natjerat" for w in (
        "natjerati", "natjeram", "natjeraš", "natjera", "natjeramo",
        "natjerate", "natjeraju",
        "natjerao", "natjerala", "natjeralo", "natjerali", "natjerale",
        "natjerat",
    )},
    # osloniti se (to rely)
    **{w: "oslonit" for w in (
        "osloniti", "oslonim", "osloniš", "osloni", "oslonimo",
        "oslonite", "oslone",
        "oslonio", "oslonila", "oslonilo", "oslonili", "oslonile",
        "oslonit",
    )},
    # obećavati (imperf of obećati)
    **{w: "obećavat" for w in (
        "obećavati", "obećavam", "obećavaš", "obećava", "obećavamo",
        "obećavate", "obećavaju",
        "obećavao", "obećavala", "obećavalo", "obećavali", "obećavale",
        "obećavat",
    )},
    # financirati
    **{w: "financirat" for w in (
        "financirati", "financiram", "financiraš", "financira", "financiramo",
        "financirate", "financiraju",
        "financirao", "financirala", "financiralo", "financirali", "financirale",
        "financirat",
    )},
    # gledajući done via gledati; let me add glumiti (to act)
    **{w: "glumit" for w in (
        "glumiti", "glumim", "glumiš", "glumi", "glumimo", "glumite", "glume",
        "glumio", "glumila", "glumilo", "glumili", "glumile",
        "glumit",
    )},
    # osjetiti (to feel perf)
    **{w: "osjetit" for w in (
        "osjetiti", "osjetim", "osjetiš", "osjeti", "osjetimo", "osjetite", "osjete",
        "osjetio", "osjetila", "osjetilo", "osjetili", "osjetile",
        "osjetit",
    )},
    # razmisliti (to think perf)
    **{w: "razmislit" for w in (
        "razmisliti", "razmislim", "razmisliš", "razmisli", "razmislimo",
        "razmislite", "razmisle",
        "razmislio", "razmislila", "razmislilo", "razmislili", "razmislile",
        "razmislit",
    )},
    # sumnjati (to doubt)
    **{w: "sumnjat" for w in (
        "sumnjati", "sumnjam", "sumnjaš", "sumnja", "sumnjamo", "sumnjate", "sumnjaju",
        "sumnjao", "sumnjala", "sumnjalo", "sumnjali", "sumnjale",
        "sumnjat",
    )},
    # spremiti (to prepare)
    **{w: "spremit" for w in (
        "spremiti", "spremim", "spremiš", "spremi", "spremimo", "spremite", "spreme",
        "spremio", "spremila", "spremilo", "spremili", "spremile",
        "spremit",
    )},
    # spremati (imperf)
    **{w: "spremat" for w in (
        "spremati", "spremam", "spremaš", "sprema", "spremamo", "spremate", "spremaju",
        "spremao", "spremala", "spremalo", "spremali", "spremale",
        "spremat",
    )},
    # koštati (to cost)
    **{w: "koštat" for w in (
        "koštati", "koštam", "koštaš", "košta", "koštamo", "koštate", "koštaju",
        "koštao", "koštala", "koštalo", "koštali", "koštale",
        "koštat",
    )},
    # ponašati se (to behave)
    **{w: "ponašat" for w in (
        "ponašati", "ponašam", "ponašaš", "ponaša", "ponašamo", "ponašate", "ponašaju",
        "ponašao", "ponašala", "ponašalo", "ponašali", "ponašale",
        "ponašat",
    )},
    # proučavati (to study imperf)
    **{w: "proučavat" for w in (
        "proučavati", "proučavam", "proučavaš", "proučava", "proučavamo",
        "proučavate", "proučavaju",
        "proučavao", "proučavala", "proučavalo", "proučavali", "proučavale",
        "proučavat",
    )},
    # istražiti (to investigate)
    **{w: "istražit" for w in (
        "istražiti", "istražim", "istražiš", "istraži", "istražimo",
        "istražite", "istraže",
        "istražio", "istražila", "istražilo", "istražili", "istražile",
        "istražit",
    )},
    # istraživati (imperf)
    **{w: "istraživat" for w in (
        "istraživati", "istražujem", "istražuješ", "istražuje", "istražujemo",
        "istražujete", "istražuju",
        "istraživao", "istraživala", "istraživalo", "istraživali", "istraživale",
        "istraživat",
    )},
    # priznati (to admit)
    **{w: "priznat" for w in (
        "priznati", "priznam", "priznaš", "prizna", "priznamo", "priznate", "priznaju",
        "priznao", "priznala", "priznalo", "priznali", "priznale",
        "priznat",
    )},
    # priznavati (imperf)
    **{w: "priznavat" for w in (
        "priznavati", "priznajem", "priznaješ", "priznaje", "priznajemo",
        "priznajete", "priznaju",
        "priznavao", "priznavala", "priznavalo", "priznavali", "priznavale",
        "priznavat",
    )},
    # zaposliti (to hire)
    **{w: "zaposlit" for w in (
        "zaposliti", "zaposlim", "zaposliš", "zaposli", "zaposlimo",
        "zaposlite", "zaposle",
        "zaposlio", "zaposlila", "zaposlilo", "zaposlili", "zaposlile",
        "zaposlit",
    )},
    # pobjeći (to escape) — pobjegnem
    **{w: "pobjeć" for w in (
        "pobjeći", "pobjegnem", "pobjegneš", "pobjegne", "pobjegnemo",
        "pobjegnete", "pobjegnu",
        "pobjegao", "pobjegla", "pobjeglo", "pobjegli", "pobjegle",
        "pobjeći",
    )},
    # bježati (to flee)
    **{w: "bježat" for w in (
        "bježati", "bježim", "bježiš", "bježi", "bježimo", "bježite", "bježe",
        "bježao", "bježala", "bježalo", "bježali", "bježale",
        "bježat",
    )},
    # viknuti (to shout)
    **{w: "viknut" for w in (
        "viknuti", "viknem", "vikneš", "vikne", "viknemo", "viknete", "viknu",
        "viknuo", "viknula", "viknulo", "viknuli", "viknule",
        "viknut",
    )},
    # vikati (imperf)
    **{w: "vikat" for w in (
        "vikati", "vičem", "vičeš", "viče", "vičemo", "vičete", "viču",
        "vikao", "vikala", "vikalo", "vikali", "vikale",
        "vikat",
    )},
    # gasiti (to extinguish)
    **{w: "gasit" for w in (
        "gasiti", "gasim", "gasiš", "gasi", "gasimo", "gasite", "gase",
        "gasio", "gasila", "gasilo", "gasili", "gasile",
        "gasit",
    )},
    # natjecati (to compete)
    **{w: "natjecat" for w in (
        "natjecati", "natječem", "natječeš", "natječe", "natječemo",
        "natječete", "natječu",
        "natjecao", "natjecala", "natjecalo", "natjecali", "natjecale",
        "natjecat",
    )},
    # svjetovati (to advise) — svjetujem
    **{w: "svjetovat" for w in (
        "svjetovati", "svjetujem", "svjetuješ", "svjetuje", "svjetujemo",
        "svjetujete", "svjetuju",
        "svjetovao", "svjetovala", "svjetovalo", "svjetovali", "svjetovale",
        "svjetovat",
    )},
    # smjeti (may)
    **{w: "smjet" for w in (
        "smjeti", "smijem", "smiješ", "smije", "smijemo", "smijete", "smiju",
        "smio", "smjela", "smjelo", "smjeli", "smjele",
        "smjet",
    )},
    # piti (to drink)
    **{w: "pit" for w in (
        "piti", "pijem", "piješ", "pije", "pijemo", "pijete", "piju",
        "pio", "pila", "pilo", "pili", "pile",
        "pit",
    )},
    # roditi (to give birth)
    **{w: "rodit" for w in (
        "roditi", "rodim", "rodiš", "rodi", "rodimo", "rodite", "rode",
        "rodio", "rodila", "rodilo", "rodili", "rodile",
        "rodit",
    )},
    # rađati (imperf)
    **{w: "rađat" for w in (
        "rađati", "rađam", "rađaš", "rađa", "rađamo", "rađate", "rađaju",
        "rađao", "rađala", "rađalo", "rađali", "rađale",
        "rađat",
    )},
    # kuhati (to cook)
    **{w: "kuhat" for w in (
        "kuhati", "kuham", "kuhaš", "kuha", "kuhamo", "kuhate", "kuhaju",
        "kuhao", "kuhala", "kuhalo", "kuhali", "kuhale",
        "kuhat",
    )},
    # pjevati (to sing)
    **{w: "pjevat" for w in (
        "pjevati", "pjevam", "pjevaš", "pjeva", "pjevamo", "pjevate", "pjevaju",
        "pjevao", "pjevala", "pjevalo", "pjevali", "pjevale",
        "pjevat",
    )},
    # brojati (to count)
    **{w: "brojat" for w in (
        "brojati", "brojim", "brojiš", "broji", "brojimo", "brojite", "broje",
        "brojao", "brojala", "brojalo", "brojali", "brojale",
        "brojat",
    )},
    # smijati se (to laugh)
    **{w: "smijat" for w in (
        "smijati", "smijem", "smiješ", "smije", "smijemo", "smijete", "smiju",
        "smijao", "smijala", "smijalo", "smijali", "smijale",
        "smijat",
    )},
    # vratiti done; nastupati (to act imperf)
    **{w: "nastupat" for w in (
        "nastupati", "nastupam", "nastupaš", "nastupa", "nastupamo",
        "nastupate", "nastupaju",
        "nastupao", "nastupala", "nastupalo", "nastupali", "nastupale",
        "nastupat",
    )},
    # nastupiti (to enter perf)
    **{w: "nastupit" for w in (
        "nastupiti", "nastupim", "nastupiš", "nastupi", "nastupimo",
        "nastupite", "nastupe",
        "nastupio", "nastupila", "nastupilo", "nastupili", "nastupile",
        "nastupit",
    )},
    # predložiti (to suggest) — palatal
    **{w: "predložit" for w in (
        "predložiti", "predložim", "predložiš", "predloži", "predložimo",
        "predložite", "predlože",
        "predložio", "predložila", "predložilo", "predložili", "predložile",
        "predložit",
    )},
    # predlagati (imperf) — palatal
    **{w: "predlagat" for w in (
        "predlagati", "predlažem", "predlažeš", "predlaže", "predlažemo",
        "predlažete", "predlažu",
        "predlagao", "predlagala", "predlagalo", "predlagali", "predlagale",
        "predlagat",
    )},
    # iskoristiti (to use)
    **{w: "iskoristit" for w in (
        "iskoristiti", "iskoristim", "iskoristiš", "iskoristi", "iskoristimo",
        "iskoristite", "iskoriste",
        "iskoristio", "iskoristila", "iskoristilo", "iskoristili", "iskoristile",
        "iskoristit",
    )},
    # predstavljati (imperf)
    **{w: "predstavljat" for w in (
        "predstavljati", "predstavljam", "predstavljaš", "predstavlja", "predstavljamo",
        "predstavljate", "predstavljaju",
        "predstavljao", "predstavljala", "predstavljalo", "predstavljali", "predstavljale",
        "predstavljat",
    )},
    # potpisati (to sign)
    **{w: "potpisat" for w in (
        "potpisati", "potpišem", "potpišeš", "potpiše", "potpišemo",
        "potpišete", "potpišu",
        "potpisao", "potpisala", "potpisalo", "potpisali", "potpisale",
        "potpisat",
    )},
    # potpisivati (imperf)
    **{w: "potpisivat" for w in (
        "potpisivati", "potpisujem", "potpisuješ", "potpisuje", "potpisujemo",
        "potpisujete", "potpisuju",
        "potpisivao", "potpisivala", "potpisivalo", "potpisivali", "potpisivale",
        "potpisivat",
    )},
    # organizirati (to organize)
    **{w: "organizirat" for w in (
        "organizirati", "organiziram", "organiziraš", "organizira", "organiziramo",
        "organizirate", "organiziraju",
        "organizirao", "organizirala", "organiziralo", "organizirali", "organizirale",
        "organizirat",
    )},
    # ubiti/ubijati imperf already added
    # javiti done — now javljati (done)
    # zavoljeti (to come to love)
    **{w: "zavoljet" for w in (
        "zavoljeti", "zavolim", "zavoliš", "zavoli", "zavolimo", "zavolite", "zavole",
        "zavolio", "zavoljela", "zavoljelo", "zavoljeli", "zavoljele",
        "zavoljet",
    )},
    # pristajati (to agree) — pristanem
    **{w: "pristat" for w in (
        "pristati", "pristanem", "pristaneš", "pristane", "pristanemo",
        "pristanete", "pristanu",
        "pristao", "pristala", "pristalo", "pristali", "pristale",
        "pristat",
    )},
    # zahtijevati (to demand) — zahtijevam
    **{w: "zahtijevat" for w in (
        "zahtijevati", "zahtijevam", "zahtijevaš", "zahtijeva", "zahtijevamo",
        "zahtijevate", "zahtijevaju",
        "zahtijevao", "zahtijevala", "zahtijevalo", "zahtijevali", "zahtijevale",
        "zahtijevat",
    )},
    # riješiti (to solve)
    **{w: "riješit" for w in (
        "riješiti", "riješim", "riješiš", "riješi", "riješimo", "riješite", "riješe",
        "riješio", "riješila", "riješilo", "riješili", "riješile",
        "riješit",
    )},
    # rješavati (imperf)
    **{w: "rješavat" for w in (
        "rješavati", "rješavam", "rješavaš", "rješava", "rješavamo",
        "rješavate", "rješavaju",
        "rješavao", "rješavala", "rješavalo", "rješavali", "rješavale",
        "rješavat",
    )},
    # pogoditi (to guess)
    **{w: "pogodit" for w in (
        "pogoditi", "pogodim", "pogodiš", "pogodi", "pogodimo", "pogodite", "pogode",
        "pogodio", "pogodila", "pogodilo", "pogodili", "pogodile",
        "pogodit",
    )},
    # upoznati (to get to know)
    **{w: "upoznat" for w in (
        "upoznati", "upoznam", "upoznaš", "upozna", "upoznamo", "upoznate", "upoznaju",
        "upoznao", "upoznala", "upoznalo", "upoznali", "upoznale",
        "upoznat",
    )},
    # upoznavati (imperf)
    **{w: "upoznavat" for w in (
        "upoznavati", "upoznajem", "upoznaješ", "upoznaje", "upoznajemo",
        "upoznajete", "upoznaju",
        "upoznavao", "upoznavala", "upoznavalo", "upoznavali", "upoznavale",
        "upoznavat",
    )},
    # snimiti (to film perf)
    **{w: "snimit" for w in (
        "snimiti", "snimim", "snimiš", "snimi", "snimimo", "snimite", "snime",
        "snimio", "snimila", "snimilo", "snimili", "snimile",
        "snimit",
    )},
    # snimati (imperf)
    **{w: "snimat" for w in (
        "snimati", "snimam", "snimaš", "snima", "snimamo", "snimate", "snimaju",
        "snimao", "snimala", "snimalo", "snimali", "snimale",
        "snimat",
    )},
    # potrošiti (to spend)
    **{w: "potrošit" for w in (
        "potrošiti", "potrošim", "potrošiš", "potroši", "potrošimo",
        "potrošite", "potroše",
        "potrošio", "potrošila", "potrošilo", "potrošili", "potrošile",
        "potrošit",
    )},
    # trošiti (imperf)
    **{w: "trošit" for w in (
        "trošiti", "trošim", "trošiš", "troši", "trošimo", "trošite", "troše",
        "trošio", "trošila", "trošilo", "trošili", "trošile",
        "trošit",
    )},
    # proslaviti (to celebrate)
    **{w: "proslavit" for w in (
        "proslaviti", "proslavim", "proslaviš", "proslavi", "proslavimo",
        "proslavite", "proslave",
        "proslavio", "proslavila", "proslavilo", "proslavili", "proslavile",
        "proslavit",
    )},
    # pojaviti se (to appear)
    **{w: "pojavit" for w in (
        "pojaviti", "pojavim", "pojaviš", "pojavi", "pojavimo", "pojavite", "pojave",
        "pojavio", "pojavila", "pojavilo", "pojavili", "pojavile",
        "pojavit",
    )},
    # pojavljivati se (imperf)
    **{w: "pojavljivat" for w in (
        "pojavljivati", "pojavljujem", "pojavljuješ", "pojavljuje", "pojavljujemo",
        "pojavljujete", "pojavljuju",
        "pojavljivao", "pojavljivala", "pojavljivalo", "pojavljivali", "pojavljivale",
        "pojavljivat",
    )},
    # služiti (to serve)
    **{w: "služit" for w in (
        "služiti", "služim", "služiš", "služi", "služimo", "služite", "služe",
        "služio", "služila", "služilo", "služili", "služile",
        "služit", "služeći",
    )},
    # ući (to enter) — irregular uđem
    **{w: "uć" for w in (
        "ući", "uđem", "uđeš", "uđe", "uđemo", "uđete", "uđu",
        "ušao", "ušla", "ušlo", "ušli", "ušle",
        "ući",
    )},
    # ulaziti (imperf)
    **{w: "ulazit" for w in (
        "ulaziti", "ulazim", "ulaziš", "ulazi", "ulazimo", "ulazite", "ulaze",
        "ulazio", "ulazila", "ulazilo", "ulazili", "ulazile",
        "ulazit",
    )},
    # kazati (to say) — kažem
    **{w: "kazat" for w in (
        "kazati", "kažem", "kažeš", "kaže", "kažemo", "kažete", "kažu",
        "kazao", "kazala", "kazalo", "kazali", "kazale",
        "kazat",
    )},
    # ponuditi (to offer)
    **{w: "ponudit" for w in (
        "ponuditi", "ponudim", "ponudiš", "ponudi", "ponudimo", "ponudite", "ponude",
        "ponudio", "ponudila", "ponudilo", "ponudili", "ponudile",
        "ponudit",
    )},
    # odlučivati (imperf)
    **{w: "odlučivat" for w in (
        "odlučivati", "odlučujem", "odlučuješ", "odlučuje", "odlučujemo",
        "odlučujete", "odlučuju",
        "odlučivao", "odlučivala", "odlučivalo", "odlučivali", "odlučivale",
        "odlučivat",
    )},
    # zaustaviti (to stop)
    **{w: "zaustavit" for w in (
        "zaustaviti", "zaustavim", "zaustaviš", "zaustavi", "zaustavimo",
        "zaustavite", "zaustave",
        "zaustavio", "zaustavila", "zaustavilo", "zaustavili", "zaustavile",
        "zaustavit",
    )},
    # dosegnuti (to reach)
    **{w: "dosegnut" for w in (
        "dosegnuti", "dosegnem", "dosegneš", "dosegne", "dosegnemo",
        "dosegnete", "dosegnu",
        "dosegao", "dosegla", "doseglo", "dosegli", "dosegle",
        "dosegnut",
    )},
    # napustiti (to leave)
    **{w: "napustit" for w in (
        "napustiti", "napustim", "napustiš", "napusti", "napustimo",
        "napustite", "napuste",
        "napustio", "napustila", "napustilo", "napustili", "napustile",
        "napustit",
    )},
    # napuštati (imperf)
    **{w: "napuštat" for w in (
        "napuštati", "napuštam", "napuštaš", "napušta", "napuštamo",
        "napuštate", "napuštaju",
        "napuštao", "napuštala", "napuštalo", "napuštali", "napuštale",
        "napuštat",
    )},
    # očekivati (imperf) — očekujem
    **{w: "očekivat" for w in (
        "očekivati", "očekujem", "očekuješ", "očekuje", "očekujemo",
        "očekujete", "očekuju",
        "očekivao", "očekivala", "očekivalo", "očekivali", "očekivale",
        "očekivat",
    )},
    # sjediti (to sit)
    **{w: "sjedit" for w in (
        "sjediti", "sjedim", "sjediš", "sjedi", "sjedimo", "sjedite", "sjede",
        "sjedio", "sjedila", "sjedilo", "sjedili", "sjedile",
        "sjedit",
    )},
    # prekinuti (to interrupt)
    **{w: "prekinut" for w in (
        "prekinuti", "prekinem", "prekineš", "prekine", "prekinemo",
        "prekinete", "prekinu",
        "prekinuo", "prekinula", "prekinulo", "prekinuli", "prekinule",
        "prekinut",
    )},
    # prekidati (imperf)
    **{w: "prekidat" for w in (
        "prekidati", "prekidam", "prekidaš", "prekida", "prekidamo",
        "prekidate", "prekidaju",
        "prekidao", "prekidala", "prekidalo", "prekidali", "prekidale",
        "prekidat",
    )},
    # održavati (to hold, imperf)
    **{w: "održavat" for w in (
        "održavati", "održavam", "održavaš", "održava", "održavamo",
        "održavate", "održavaju",
        "održavao", "održavala", "održavalo", "održavali", "održavale",
        "održavat",
    )},
    # iznijeti (to bring out)
    **{w: "iznijet" for w in (
        "iznijeti", "iznesem", "izneseš", "iznese", "iznesemo", "iznesete", "iznesu",
        "iznio", "iznijela", "iznijelo", "iznijeli", "iznijele",
        "iznijet",
    )},
    # ostvariti (to realize)
    **{w: "ostvarit" for w in (
        "ostvariti", "ostvarim", "ostvariš", "ostvari", "ostvarimo",
        "ostvarite", "ostvare",
        "ostvario", "ostvarila", "ostvarilo", "ostvarili", "ostvarile",
        "ostvarit",
    )},
    # ostvarivati (imperf)
    **{w: "ostvarivat" for w in (
        "ostvarivati", "ostvarujem", "ostvaruješ", "ostvaruje", "ostvarujemo",
        "ostvarujete", "ostvaruju",
        "ostvarivao", "ostvarivala", "ostvarivalo", "ostvarivali", "ostvarivale",
        "ostvarivat",
    )},
    # odbiti (to reject)
    **{w: "odbit" for w in (
        "odbiti", "odbijem", "odbiješ", "odbije", "odbijemo", "odbijete", "odbiju",
        "odbio", "odbila", "odbilo", "odbili", "odbile",
        "odbit",
    )},
    # računati (to count)
    **{w: "računat" for w in (
        "računati", "računam", "računaš", "računa", "računamo", "računate", "računaju",
        "računao", "računala", "računalo", "računali", "računale",
        "računat",
    )},
    # paziti (to pay attention)
    **{w: "pazit" for w in (
        "paziti", "pazim", "paziš", "pazi", "pazimo", "pazite", "paze",
        "pazio", "pazila", "pazilo", "pazili", "pazile",
        "pazit",
    )},
    # disati (to breathe) — dišem
    **{w: "disat" for w in (
        "disati", "dišem", "dišeš", "diše", "dišemo", "dišete", "dišu",
        "disao", "disala", "disalo", "disali", "disale",
        "disat",
    )},
    # zamisliti (to imagine)
    **{w: "zamislit" for w in (
        "zamisliti", "zamislim", "zamisliš", "zamisli", "zamislimo", "zamislite", "zamisle",
        "zamislio", "zamislila", "zamislilo", "zamislili", "zamislile",
        "zamislit",
    )},
    # trpjeti (to endure) — irregular past -je-
    **{w: "trpjet" for w in (
        "trpjeti", "trpim", "trpiš", "trpi", "trpimo", "trpite", "trpe",
        "trpio", "trpjela", "trpjelo", "trpjeli", "trpjele",
        "trpjet",
    )},
    # lagati (to lie) — lažem
    **{w: "lagat" for w in (
        "lagati", "lažem", "lažeš", "laže", "lažemo", "lažete", "lažu",
        "lagao", "lagala", "lagalo", "lagali", "lagale",
        "lagat",
    )},
    # ljubiti (to kiss)
    **{w: "ljubit" for w in (
        "ljubiti", "ljubim", "ljubiš", "ljubi", "ljubimo", "ljubite", "ljube",
        "ljubio", "ljubila", "ljubilo", "ljubili", "ljubile",
        "ljubit",
    )},
    # skupljati (to collect)
    **{w: "skupljat" for w in (
        "skupljati", "skupljam", "skupljaš", "skuplja", "skupljamo",
        "skupljate", "skupljaju",
        "skupljao", "skupljala", "skupljalo", "skupljali", "skupljale",
        "skupljat",
    )},
    # skupiti (to gather)
    **{w: "skupit" for w in (
        "skupiti", "skupim", "skupiš", "skupi", "skupimo", "skupite", "skupe",
        "skupio", "skupila", "skupilo", "skupili", "skupile",
        "skupit",
    )},
    # doživjeti (to experience) — irregular past -je-
    **{w: "doživjet" for w in (
        "doživjeti", "doživim", "doživiš", "doživi", "doživimo",
        "doživite", "dožive",
        "doživio", "doživjela", "doživjelo", "doživjeli", "doživjele",
        "doživjet",
    )},
    # šetati (to walk)
    **{w: "šetat" for w in (
        "šetati", "šetam", "šetaš", "šeta", "šetamo", "šetate", "šetaju",
        "šetao", "šetala", "šetalo", "šetali", "šetale",
        "šetat",
    )},
    # svirati (to play an instrument)
    **{w: "svirat" for w in (
        "svirati", "sviram", "sviraš", "svira", "sviramo", "svirate", "sviraju",
        "svirao", "svirala", "sviralo", "svirali", "svirale",
        "svirat",
    )},
    # ponoviti (to repeat)
    **{w: "ponovit" for w in (
        "ponoviti", "ponovim", "ponoviš", "ponovi", "ponovimo", "ponovite", "ponove",
        "ponovio", "ponovila", "ponovilo", "ponovili", "ponovile",
        "ponovit",
    )},
    # ponavljati (imperf)
    **{w: "ponavljat" for w in (
        "ponavljati", "ponavljam", "ponavljaš", "ponavlja", "ponavljamo",
        "ponavljate", "ponavljaju",
        "ponavljao", "ponavljala", "ponavljalo", "ponavljali", "ponavljale",
        "ponavljat",
    )},
    # posjetiti (to visit)
    **{w: "posjetit" for w in (
        "posjetiti", "posjetim", "posjetiš", "posjeti", "posjetimo",
        "posjetite", "posjete",
        "posjetio", "posjetila", "posjetilo", "posjetili", "posjetile",
        "posjetit",
    )},
    # pripremiti (to prepare)
    **{w: "pripremit" for w in (
        "pripremiti", "pripremim", "pripremiš", "pripremi", "pripremimo",
        "pripremite", "pripreme",
        "pripremio", "pripremila", "pripremilo", "pripremili", "pripremile",
        "pripremit",
    )},
    # dogovoriti (to agree)
    **{w: "dogovorit" for w in (
        "dogovoriti", "dogovorim", "dogovoriš", "dogovori", "dogovorimo",
        "dogovorite", "dogovore",
        "dogovorio", "dogovorila", "dogovorilo", "dogovorili", "dogovorile",
        "dogovorit",
    )},
    # zahvaliti (to thank)
    **{w: "zahvalit" for w in (
        "zahvaliti", "zahvalim", "zahvališ", "zahvali", "zahvalimo",
        "zahvalite", "zahvale",
        "zahvalio", "zahvalila", "zahvalilo", "zahvalili", "zahvalile",
        "zahvalit",
    )},
    # razmišljati (to consider)
    **{w: "razmišljat" for w in (
        "razmišljati", "razmišljam", "razmišljaš", "razmišlja", "razmišljamo",
        "razmišljate", "razmišljaju",
        "razmišljao", "razmišljala", "razmišljalo", "razmišljali", "razmišljale",
        "razmišljat",
    )},
    # staviti (to put)
    **{w: "stavit" for w in (
        "staviti", "stavim", "staviš", "stavi", "stavimo", "stavite", "stave",
        "stavio", "stavila", "stavilo", "stavili", "stavile",
        "stavit",
    )},
    # stavljati (imperf)
    **{w: "stavljat" for w in (
        "stavljati", "stavljam", "stavljaš", "stavlja", "stavljamo",
        "stavljate", "stavljaju",
        "stavljao", "stavljala", "stavljalo", "stavljali", "stavljale",
        "stavljat",
    )},
    # vraćati (imperf of vratiti)
    **{w: "vraćat" for w in (
        "vraćati", "vraćam", "vraćaš", "vraća", "vraćamo", "vraćate", "vraćaju",
        "vraćao", "vraćala", "vraćalo", "vraćali", "vraćale",
        "vraćat",
    )},
    # kupovati (imperf) — kupujem
    **{w: "kupovat" for w in (
        "kupovati", "kupujem", "kupuješ", "kupuje", "kupujemo", "kupujete", "kupuju",
        "kupovao", "kupovala", "kupovalo", "kupovali", "kupovale",
        "kupovat",
    )},
    # prodavati (imperf) — prodajem
    **{w: "prodavat" for w in (
        "prodavati", "prodajem", "prodaješ", "prodaje", "prodajemo",
        "prodajete", "prodaju",
        "prodavao", "prodavala", "prodavalo", "prodavali", "prodavale",
        "prodavat",
    )},
    # ubiti (to kill)
    **{w: "ubit" for w in (
        "ubiti", "ubijem", "ubiješ", "ubije", "ubijemo", "ubijete", "ubiju",
        "ubio", "ubila", "ubilo", "ubili", "ubile",
        "ubit",
    )},
    # pričati (to tell)
    **{w: "pričat" for w in (
        "pričati", "pričam", "pričaš", "priča", "pričamo", "pričate", "pričaju",
        "pričao", "pričala", "pričalo", "pričali", "pričale",
        "pričat",
    )},
    # pokazivati (imperf)
    **{w: "pokazivat" for w in (
        "pokazivati", "pokazujem", "pokazuješ", "pokazuje", "pokazujemo",
        "pokazujete", "pokazuju",
        "pokazivao", "pokazivala", "pokazivalo", "pokazivali", "pokazivale",
        "pokazivat",
    )},
    # donositi (imperf of donijeti)
    **{w: "donosit" for w in (
        "donositi", "donosim", "donosiš", "donosi", "donosimo",
        "donosite", "donose",
        "donosio", "donosila", "donosilo", "donosili", "donosile",
        "donosit",
    )},
    # izlaziti (imperf of izaći)
    **{w: "izlazit" for w in (
        "izlaziti", "izlazim", "izlaziš", "izlazi", "izlazimo",
        "izlazite", "izlaze",
        "izlazio", "izlazila", "izlazilo", "izlazili", "izlazile",
        "izlazit",
    )},
    # završavati (to be finishing, imperf)
    **{w: "završavat" for w in (
        "završavati", "završavam", "završavaš", "završava", "završavamo",
        "završavate", "završavaju",
        "završavao", "završavala", "završavalo", "završavali", "završavale",
        "završavat",
    )},
    # trebati (to need, imperf) — extend the existing modal entry
    # kretati (to move, imperf) — krećem
    **{w: "kretat" for w in (
        "kretati", "krećem", "krećeš", "kreće", "krećemo", "krećete", "kreću",
        "kretao", "kretala", "kretalo", "kretali", "kretale",
        "kretat",
    )},
    # poznavati (to know, imperf) — poznajem
    **{w: "poznavat" for w in (
        "poznavati", "poznajem", "poznaješ", "poznaje", "poznajemo",
        "poznajete", "poznaju",
        "poznavao", "poznavala", "poznavalo", "poznavali", "poznavale",
        "poznavat",
    )},
    # napadati (to attack, imperf)
    **{w: "napadat" for w in (
        "napadati", "napadam", "napadaš", "napada", "napadamo",
        "napadate", "napadaju",
        "napadao", "napadala", "napadalo", "napadali", "napadale",
        "napadat",
    )},
    # slagati se (to agree, imperf) — slažem
    **{w: "slagat" for w in (
        "slagati", "slažem", "slažeš", "slaže", "slažemo", "slažete", "slažu",
        "slagao", "slagala", "slagalo", "slagali", "slagale",
        "slagat",
    )},
    # pokušavati (imperf of pokušati)
    **{w: "pokušavat" for w in (
        "pokušavati", "pokušavam", "pokušavaš", "pokušava", "pokušavamo",
        "pokušavate", "pokušavaju",
        "pokušavao", "pokušavala", "pokušavalo", "pokušavali", "pokušavale",
        "pokušavat",
    )},
    # radovati se (to be happy, imperf) — radujem
    **{w: "radovat" for w in (
        "radovati", "radujem", "raduješ", "raduje", "radujemo", "radujete", "raduju",
        "radovao", "radovala", "radovalo", "radovali", "radovale",
        "radovat",
    )},
    # nastavljati (imperf of nastaviti)
    **{w: "nastavljat" for w in (
        "nastavljati", "nastavljam", "nastavljaš", "nastavlja", "nastavljamo",
        "nastavljate", "nastavljaju",
        "nastavljao", "nastavljala", "nastavljalo", "nastavljali", "nastavljale",
        "nastavljat",
    )},
    # davati (to give, imperf) — dajem
    **{w: "davat" for w in (
        "davati", "dajem", "daješ", "daje", "dajemo", "dajete", "daju",
        "davao", "davala", "davalo", "davali", "davale",
        "davat",
    )},
    # ustati (to stand up) — irregular ustanem
    **{w: "ustat" for w in (
        "ustati", "ustanem", "ustaneš", "ustane", "ustanemo", "ustanete", "ustanu",
        "ustao", "ustala", "ustalo", "ustali", "ustale",
        "ustat",
    )},
    # izaći (to go out) — irregular izađem
    **{w: "izać" for w in (
        "izaći", "izađem", "izađeš", "izađe", "izađemo", "izađete", "izađu",
        "izašao", "izašla", "izašlo", "izašli", "izašle",
        "izaći",
    )},
    # prepoznati (to recognize)
    **{w: "prepoznat" for w in (
        "prepoznati", "prepoznam", "prepoznaš", "prepozna", "prepoznamo",
        "prepoznate", "prepoznaju",
        "prepoznao", "prepoznala", "prepoznalo", "prepoznali", "prepoznale",
        "prepoznat",
    )},
    # čuvati (to keep)
    **{w: "čuvat" for w in (
        "čuvati", "čuvam", "čuvaš", "čuva", "čuvamo", "čuvate", "čuvaju",
        "čuvao", "čuvala", "čuvalo", "čuvali", "čuvale",
        "čuvat",
    )},
    # održati (to hold)
    **{w: "održat" for w in (
        "održati", "održim", "održiš", "održi", "održimo", "održite", "održe",
        "održao", "održala", "održalo", "održali", "održale",
        "održat",
    )},
    # gubiti (to lose)
    **{w: "gubit" for w in (
        "gubiti", "gubim", "gubiš", "gubi", "gubimo", "gubite", "gube",
        "gubio", "gubila", "gubilo", "gubili", "gubile",
        "gubit",
    )},
    # vladati (to rule)
    **{w: "vladat" for w in (
        "vladati", "vladam", "vladaš", "vlada", "vladamo", "vladate", "vladaju",
        "vladao", "vladala", "vladalo", "vladali", "vladale",
        "vladat",
    )},
    # cijeniti (to value)
    **{w: "cijenit" for w in (
        "cijeniti", "cijenim", "cijeniš", "cijeni", "cijenimo", "cijenite", "cijene",
        "cijenio", "cijenila", "cijenilo", "cijenili", "cijenile",
        "cijenit",
    )},
    # pronaći (to find) — irregular pronađem
    **{w: "pronać" for w in (
        "pronaći", "pronađem", "pronađeš", "pronađe", "pronađemo", "pronađete", "pronađu",
        "pronašao", "pronašla", "pronašlo", "pronašli", "pronašle",
        "pronaći",
    )},
    # pogledati (to look at)
    **{w: "pogledat" for w in (
        "pogledati", "pogledam", "pogledaš", "pogleda", "pogledamo",
        "pogledate", "pogledaju",
        "pogledao", "pogledala", "pogledalo", "pogledali", "pogledale",
        "pogledat",
    )},
    # mjeriti (to measure)
    **{w: "mjerit" for w in (
        "mjeriti", "mjerim", "mjeriš", "mjeri", "mjerimo", "mjerite", "mjere",
        "mjerio", "mjerila", "mjerilo", "mjerili", "mjerile",
        "mjerit",
    )},
    # dolaziti (to come, imperf)
    **{w: "dolazit" for w in (
        "dolaziti", "dolazim", "dolaziš", "dolazi", "dolazimo", "dolazite", "dolaze",
        "dolazio", "dolazila", "dolazilo", "dolazili", "dolazile",
        "dolazit", "dolazeći",
    )},
    # odlaziti (to go away, imperf)
    **{w: "odlazit" for w in (
        "odlaziti", "odlazim", "odlaziš", "odlazi", "odlazimo", "odlazite", "odlaze",
        "odlazio", "odlazila", "odlazilo", "odlazili", "odlazile",
        "odlazit",
    )},
    # objaviti (to publish)
    **{w: "objavit" for w in (
        "objaviti", "objavim", "objaviš", "objavi", "objavimo", "objavite", "objave",
        "objavio", "objavila", "objavilo", "objavili", "objavile",
        "objavit",
    )},
    # obaviti (to perform)
    **{w: "obavit" for w in (
        "obaviti", "obavim", "obaviš", "obavi", "obavimo", "obavite", "obave",
        "obavio", "obavila", "obavilo", "obavili", "obavile",
        "obavit",
    )},
    # popiti (to drink up)
    **{w: "popit" for w in (
        "popiti", "popijem", "popiješ", "popije", "popijemo", "popijete", "popiju",
        "popio", "popila", "popilo", "popili", "popile",
        "popit",
    )},
    # pojesti (to eat up) — irregular pojedem
    **{w: "pojest" for w in (
        "pojesti", "pojedem", "pojedeš", "pojede", "pojedemo", "pojedete", "pojedu",
        "pojeo", "pojela", "pojelo", "pojeli", "pojele",
        "pojest",
    )},
    # dolaziti — imperf of doći, distinct lemma
    # preživjeti (to survive)
    **{w: "preživjet" for w in (
        "preživjeti", "preživim", "preživiš", "preživi", "preživimo",
        "preživite", "prežive",
        "preživio", "preživjela", "preživjelo", "preživjeli", "preživjele",
        "preživjet",
    )},
    # opisati (to describe)
    **{w: "opisat" for w in (
        "opisati", "opišem", "opišeš", "opiše", "opišemo", "opišete", "opišu",
        "opisao", "opisala", "opisalo", "opisali", "opisale",
        "opisat",
    )},
    # putovati (to travel)
    **{w: "putovat" for w in (
        "putovati", "putujem", "putuješ", "putuje", "putujemo", "putujete", "putuju",
        "putovao", "putovala", "putovalo", "putovali", "putovale",
        "putovat",
    )},
    # boriti se (to fight)
    **{w: "borit" for w in (
        "boriti", "borim", "boriš", "bori", "borimo", "borite", "bore",
        "borio", "borila", "borilo", "borili", "borile",
        "borit", "boreći",
    )},
    # poslati (to send) — irregular pošaljem
    **{w: "poslat" for w in (
        "poslati", "pošaljem", "pošalješ", "pošalje", "pošaljemo",
        "pošaljete", "pošalju",
        "poslao", "poslala", "poslalo", "poslali", "poslale",
        "poslat",
    )},
    # primiti (to receive)
    **{w: "primit" for w in (
        "primiti", "primim", "primiš", "primi", "primimo", "primite", "prime",
        "primio", "primila", "primilo", "primili", "primile",
        "primit",
    )},
    # dodati (to add) — irregular dodam
    **{w: "dodat" for w in (
        "dodati", "dodam", "dodaš", "doda", "dodamo", "dodate", "dodaju",
        "dodao", "dodala", "dodalo", "dodali", "dodale",
        "dodat",
    )},
    # graditi (to build)
    **{w: "gradit" for w in (
        "graditi", "gradim", "gradiš", "gradi", "gradimo", "gradite", "grade",
        "gradio", "gradila", "gradilo", "gradili", "gradile",
        "gradit", "gradeći",
    )},
    # pobijediti (to win)
    **{w: "pobijedit" for w in (
        "pobijediti", "pobijedim", "pobijediš", "pobijedi", "pobijedimo",
        "pobijedite", "pobijede",
        "pobijedio", "pobijedila", "pobijedilo", "pobijedili", "pobijedile",
        "pobijedit",
    )},
    # obećati (to promise)
    **{w: "obećat" for w in (
        "obećati", "obećam", "obećaš", "obeća", "obećamo", "obećate", "obećaju",
        "obećao", "obećala", "obećalo", "obećali", "obećale",
        "obećat",
    )},
    # nastati (to come about) — irregular nastanem
    **{w: "nastat" for w in (
        "nastati", "nastanem", "nastaneš", "nastane", "nastanemo",
        "nastanete", "nastanu",
        "nastao", "nastala", "nastalo", "nastali", "nastale",
        "nastat",
    )},
    # skočiti (to jump)
    **{w: "skočit" for w in (
        "skočiti", "skočim", "skočiš", "skoči", "skočimo", "skočite", "skoče",
        "skočio", "skočila", "skočilo", "skočili", "skočile",
        "skočit",
    )},
    # šutjeti (to be silent) — irregular past -je-
    **{w: "šutjet" for w in (
        "šutjeti", "šutim", "šutiš", "šuti", "šutimo", "šutite", "šute",
        "šutio", "šutjela", "šutjelo", "šutjeli", "šutjele",
        "šutjet", "šuteći",
    )},
    # plakati (to cry) — palatal plač-
    **{w: "plakat" for w in (
        "plakati", "plačem", "plačeš", "plače", "plačemo", "plačete", "plaču",
        "plakao", "plakala", "plakalo", "plakali", "plakale",
        "plakat",
    )},
    # spasiti (to save)
    **{w: "spasit" for w in (
        "spasiti", "spasim", "spasiš", "spasi", "spasimo", "spasite", "spase",
        "spasio", "spasila", "spasilo", "spasili", "spasile",
        "spasit",
    )},
    # braniti (to defend)
    **{w: "branit" for w in (
        "braniti", "branim", "braniš", "brani", "branimo", "branite", "brane",
        "branio", "branila", "branilo", "branili", "branile",
        "branit", "braneći",
    )},
    # izabrati (to choose) — irregular izaberem
    **{w: "izabrat" for w in (
        "izabrati", "izaberem", "izabereš", "izabere", "izaberemo", "izaberete",
        "izaberu",
        "izabrao", "izabrala", "izabralo", "izabrali", "izabrale",
        "izabrat",
    )},
    # birati (to choose imperf)
    **{w: "birat" for w in (
        "birati", "biram", "biraš", "bira", "biramo", "birate", "biraju",
        "birao", "birala", "biralo", "birali", "birale",
        "birat",
    )},
    # započeti (to begin, perf)
    **{w: "započet" for w in (
        "započeti", "započnem", "započneš", "započne", "započnemo",
        "započnete", "započnu",
        "započeo", "započela", "započelo", "započeli", "započele",
        "započet",
    )},
    # pokriti (to cover)
    **{w: "pokrit" for w in (
        "pokriti", "pokrijem", "pokriješ", "pokrije", "pokrijemo", "pokrijete",
        "pokriju",
        "pokrio", "pokrila", "pokrilo", "pokrili", "pokrile",
        "pokrit",
    )},
    # dopustiti (to allow)
    **{w: "dopustit" for w in (
        "dopustiti", "dopustim", "dopustiš", "dopusti", "dopustimo", "dopustite",
        "dopuste",
        "dopustio", "dopustila", "dopustilo", "dopustili", "dopustile",
        "dopustit",
    )},
    # brinuti (to worry)
    **{w: "brinut" for w in (
        "brinuti", "brinem", "brineš", "brine", "brinemo", "brinete", "brinu",
        "brinuo", "brinula", "brinulo", "brinuli", "brinule",
        "brinut",
    )},
    # nalaziti se (to be located)
    **{w: "nalazit" for w in (
        "nalaziti", "nalazim", "nalaziš", "nalazi", "nalazimo", "nalazite", "nalaze",
        "nalazio", "nalazila", "nalazilo", "nalazili", "nalazile",
        "nalazit", "nalazeći",
    )},
    # nadati se (to hope)
    **{w: "nadat" for w in (
        "nadati", "nadam", "nadaš", "nada", "nadamo", "nadate", "nadaju",
        "nadao", "nadala", "nadalo", "nadali", "nadale",
        "nadat",
    )},
    # slušati (to listen)
    **{w: "slušat" for w in (
        "slušati", "slušam", "slušaš", "sluša", "slušamo", "slušate", "slušaju",
        "slušao", "slušala", "slušalo", "slušali", "slušale",
        "slušat",
    )},
    # voziti (to drive)
    **{w: "vozit" for w in (
        "voziti", "vozim", "voziš", "vozi", "vozimo", "vozite", "voze",
        "vozio", "vozila", "vozilo", "vozili", "vozile",
        "vozit", "vozeći",
    )},
    # shvatiti (to understand)
    **{w: "shvatit" for w in (
        "shvatiti", "shvatim", "shvatiš", "shvati", "shvatimo", "shvatite", "shvate",
        "shvatio", "shvatila", "shvatilo", "shvatili", "shvatile",
        "shvatit",
    )},
    # umrijeti (to die) — irregular umrem/umro
    **{w: "umrijet" for w in (
        "umrijeti", "umrem", "umreš", "umre", "umremo", "umrete", "umru",
        "umro", "umrla", "umrlo", "umrli", "umrle",
        "umrijet",
    )},
    # sjesti (to sit down) — irregular sjednem
    **{w: "sjest" for w in (
        "sjesti", "sjednem", "sjedneš", "sjedne", "sjednemo", "sjednete", "sjednu",
        "sjeo", "sjela", "sjelo", "sjeli", "sjele",
        "sjest",
    )},
    # ostaviti (to leave)
    **{w: "ostavit" for w in (
        "ostaviti", "ostavim", "ostaviš", "ostavi", "ostavimo", "ostavite", "ostave",
        "ostavio", "ostavila", "ostavilo", "ostavili", "ostavile",
        "ostavit",
    )},
    # napisati (to write down) — perfective
    **{w: "napisat" for w in (
        "napisati", "napišem", "napišeš", "napiše", "napišemo", "napišete", "napišu",
        "napisao", "napisala", "napisalo", "napisali", "napisale",
        "napisat",
    )},
    # javljati (to announce, imperf)
    **{w: "javljat" for w in (
        "javljati", "javljam", "javljaš", "javlja", "javljamo", "javljate", "javljaju",
        "javljao", "javljala", "javljalo", "javljali", "javljale",
        "javljat",
    )},
    # pokrenuti (to launch)
    **{w: "pokrenut" for w in (
        "pokrenuti", "pokrenem", "pokreneš", "pokrene", "pokrenemo", "pokrenete",
        "pokrenu",
        "pokrenuo", "pokrenula", "pokrenulo", "pokrenuli", "pokrenule",
        "pokrenut",
    )},
    # trčati (to run)
    **{w: "trčat" for w in (
        "trčati", "trčim", "trčiš", "trči", "trčimo", "trčite", "trče",
        "trčao", "trčala", "trčalo", "trčali", "trčale",
        "trčat",
    )},
    # otići (to leave) — irregular odem/otišao
    **{w: "otić" for w in (
        "otići", "odem", "odeš", "ode", "odemo", "odete", "odu",
        "otišao", "otišla", "otišlo", "otišli", "otišle",
        "otići", "odi", "odite",
    )},
    # otvoriti (to open)
    **{w: "otvorit" for w in (
        "otvoriti", "otvorim", "otvoriš", "otvori", "otvorimo", "otvorite", "otvore",
        "otvorio", "otvorila", "otvorilo", "otvorili", "otvorile",
        "otvorit",
    )},
    # zatvoriti (to close)
    **{w: "zatvorit" for w in (
        "zatvoriti", "zatvorim", "zatvoriš", "zatvori", "zatvorimo", "zatvorite",
        "zatvore",
        "zatvorio", "zatvorila", "zatvorilo", "zatvorili", "zatvorile",
        "zatvorit",
    )},
    # odlučiti (to decide)
    **{w: "odlučit" for w in (
        "odlučiti", "odlučim", "odlučiš", "odluči", "odlučimo", "odlučite", "odluče",
        "odlučio", "odlučila", "odlučilo", "odlučili", "odlučile",
        "odlučit",
    )},
    # hodati (to walk)
    **{w: "hodat" for w in (
        "hodati", "hodam", "hodaš", "hoda", "hodamo", "hodate", "hodaju",
        "hodao", "hodala", "hodalo", "hodali", "hodale",
        "hodat",
    )},
    # spavati (to sleep)
    **{w: "spavat" for w in (
        "spavati", "spavam", "spavaš", "spava", "spavamo", "spavate", "spavaju",
        "spavao", "spavala", "spavalo", "spavali", "spavale",
        "spavat",
    )},
    # izgubiti (to lose)
    **{w: "izgubit" for w in (
        "izgubiti", "izgubim", "izgubiš", "izgubi", "izgubimo", "izgubite", "izgube",
        "izgubio", "izgubila", "izgubilo", "izgubili", "izgubile",
        "izgubit",
    )},
    # uspjeti (to succeed) — irregular uspijem
    **{w: "uspjet" for w in (
        "uspjeti", "uspijem", "uspiješ", "uspije", "uspijemo", "uspijete", "uspiju",
        "uspio", "uspjela", "uspjelo", "uspjeli", "uspjele",
        "uspjet",
    )},
    # prestati (to stop) — perfective
    **{w: "prestat" for w in (
        "prestati", "prestanem", "prestaneš", "prestane", "prestanemo", "prestanete",
        "prestanu",
        "prestao", "prestala", "prestalo", "prestali", "prestale",
        "prestat",
    )},
    # pasti (to fall) — irregular padnem
    **{w: "past" for w in (
        "pasti", "padnem", "padneš", "padne", "padnemo", "padnete", "padnu",
        "pao", "pala", "palo", "pali", "pale",
        "past",
    )},
    # donijeti (to bring) — irregular donesem/donio
    **{w: "donijet" for w in (
        "donijeti", "donesem", "doneseš", "donese", "donesemo", "donesete", "donesu",
        "donio", "donijela", "donijelo", "donijeli", "donijele",
        "donijet",
    )},
    # kupiti (to buy)
    **{w: "kupit" for w in (
        "kupiti", "kupim", "kupiš", "kupi", "kupimo", "kupite", "kupe",
        "kupio", "kupila", "kupilo", "kupili", "kupile",
        "kupit",
    )},
    # prodati (to sell)
    **{w: "prodat" for w in (
        "prodati", "prodam", "prodaš", "proda", "prodamo", "prodate", "prodaju",
        "prodao", "prodala", "prodalo", "prodali", "prodale",
        "prodat",
    )},
    # platiti (to pay)
    **{w: "platit" for w in (
        "platiti", "platim", "platiš", "plati", "platimo", "platite", "plate",
        "platio", "platila", "platilo", "platili", "platile",
        "platit",
    )},
    # stvoriti (to create)
    **{w: "stvorit" for w in (
        "stvoriti", "stvorim", "stvoriš", "stvori", "stvorimo", "stvorite", "stvore",
        "stvorio", "stvorila", "stvorilo", "stvorili", "stvorile",
        "stvorit",
    )},
    # predstaviti (to present)
    **{w: "predstavit" for w in (
        "predstaviti", "predstavim", "predstaviš", "predstavi", "predstavimo",
        "predstavite", "predstave",
        "predstavio", "predstavila", "predstavilo", "predstavili", "predstavile",
        "predstavit",
    )},
    # zaboraviti (to forget)
    **{w: "zaboravit" for w in (
        "zaboraviti", "zaboravim", "zaboraviš", "zaboravi", "zaboravimo",
        "zaboravite", "zaborave",
        "zaboravio", "zaboravila", "zaboravilo", "zaboravili", "zaboravile",
        "zaboravit",
    )},
    # proći (to pass) — irregular prođem
    **{w: "proć" for w in (
        "proći", "prođem", "prođeš", "prođe", "prođemo", "prođete", "prođu",
        "prošao", "prošla", "prošlo", "prošli", "prošle",
        "proći",
    )},
    # stići (to arrive) — irregular stignem
    **{w: "stić" for w in (
        "stići", "stignem", "stigneš", "stigne", "stignemo", "stignete", "stignu",
        "stigao", "stigla", "stiglo", "stigli", "stigle",
        "stići",
    )},
    # baciti (to throw)
    **{w: "bacit" for w in (
        "baciti", "bacim", "baciš", "baci", "bacimo", "bacite", "bace",
        "bacio", "bacila", "bacilo", "bacili", "bacile",
        "bacit",
    )},
    # vjerovati (to believe) — uje/ova alternation
    **{w: "vjerovat" for w in (
        "vjerovati", "vjerujem", "vjeruješ", "vjeruje", "vjerujemo",
        "vjerujete", "vjeruju",
        "vjerovao", "vjerovala", "vjerovalo", "vjerovali", "vjerovale",
        "vjerovat", "vjerujući",
    )},
    # razumjeti (to understand)
    **{w: "razumjet" for w in (
        "razumjeti", "razumijem", "razumiješ", "razumije", "razumijemo",
        "razumijete", "razumiju",
        "razumio", "razumjela", "razumjelo", "razumjeli", "razumjele",
        "razumjet",
    )},
    # igrati (to play)
    **{w: "igrat" for w in (
        "igrati", "igram", "igraš", "igra", "igramo", "igrate", "igraju",
        "igrao", "igrala", "igralo", "igrali", "igrale",
        "igrat", "igrajući",
    )},
    # promijeniti / mijenjati
    **{w: "promijenit" for w in (
        "promijeniti", "promijenim", "promijeniš", "promijeni", "promijenimo",
        "promijenite", "promijene",
        "promijenio", "promijenila", "promijenilo", "promijenili", "promijenile",
        "promijenit",
    )},
    **{w: "mijenjat" for w in (
        "mijenjati", "mijenjam", "mijenjaš", "mijenja", "mijenjamo",
        "mijenjate", "mijenjaju",
        "mijenjao", "mijenjala", "mijenjalo", "mijenjali", "mijenjale",
        "mijenjat", "mijenjajući",
    )},
    # odgovoriti (to answer)
    **{w: "odgovorit" for w in (
        "odgovoriti", "odgovorim", "odgovoriš", "odgovori", "odgovorimo",
        "odgovorite", "odgovore",
        "odgovorio", "odgovorila", "odgovorilo", "odgovorili", "odgovorile",
        "odgovorit",
    )},
    # odgovarati (imperf)
    **{w: "odgovarat" for w in (
        "odgovarati", "odgovaram", "odgovaraš", "odgovara", "odgovaramo",
        "odgovarate", "odgovaraju",
        "odgovarao", "odgovarala", "odgovaralo", "odgovarali", "odgovarale",
        "odgovarat",
    )},
    # sjećati se (to remember, imperf)
    **{w: "sjećat" for w in (
        "sjećati", "sjećam", "sjećaš", "sjeća", "sjećamo", "sjećate", "sjećaju",
        "sjećao", "sjećala", "sjećalo", "sjećali", "sjećale",
        "sjećat",
    )},
    # dogoditi se (to happen)
    **{w: "dogodit" for w in (
        "dogoditi", "dogodim", "dogodiš", "dogodi", "dogodimo", "dogodite",
        "dogode",
        "dogodio", "dogodila", "dogodilo", "dogodili", "dogodile",
        "dogodit",
    )},
    # krenuti (to start moving)
    **{w: "krenut" for w in (
        "krenuti", "krenem", "kreneš", "krene", "krenemo", "krenete", "krenu",
        "krenuo", "krenula", "krenulo", "krenuli", "krenule",
        "krenut",
    )},
    # stajati (to stand, imperf) — stoj- present
    **{w: "stajat" for w in (
        "stajati", "stojim", "stojiš", "stoji", "stojimo", "stojite", "stoje",
        "stajao", "stajala", "stajalo", "stajali", "stajale",
        "stajat", "stojeći",
    )},
    # čekati (to wait)
    **{w: "čekat" for w in (
        "čekati", "čekam", "čekaš", "čeka", "čekamo", "čekate", "čekaju",
        "čekao", "čekala", "čekalo", "čekali", "čekale",
        "čekat",
    )},
    # nositi (to carry)
    **{w: "nosit" for w in (
        "nositi", "nosim", "nosiš", "nosi", "nosimo", "nosite", "nose",
        "nosio", "nosila", "nosilo", "nosili", "nosile",
        "nosit", "noseći",
    )},
    # učiti (to learn)
    **{w: "učit" for w in (
        "učiti", "učim", "učiš", "uči", "učimo", "učite", "uče",
        "učio", "učila", "učilo", "učili", "učile",
        "učit", "učeći",
    )},
    # voditi (to lead)
    **{w: "vodit" for w in (
        "voditi", "vodim", "vodiš", "vodi", "vodimo", "vodite", "vode",
        "vodio", "vodila", "vodilo", "vodili", "vodile",
        "vodit", "vodeći",
    )},
    # pratiti (to follow)
    **{w: "pratit" for w in (
        "pratiti", "pratim", "pratiš", "prati", "pratimo", "pratite", "prate",
        "pratio", "pratila", "pratilo", "pratili", "pratile",
        "pratit", "prateći",
    )},
    # zvati (to call)
    **{w: "zvat" for w in (
        "zvati", "zovem", "zoveš", "zove", "zovemo", "zovete", "zovu",
        "zvao", "zvala", "zvalo", "zvali", "zvale",
        "zvat",
    )},
    # čuti (to hear)
    **{w: "čut" for w in (
        "čuti", "čujem", "čuješ", "čuje", "čujemo", "čujete", "čuju",
        "čuo", "čula", "čulo", "čuli", "čule",
        "čut", "čuvši",
    )},
    # osjećati (to feel, imperf)
    **{w: "osjećat" for w in (
        "osjećati", "osjećam", "osjećaš", "osjeća", "osjećamo",
        "osjećate", "osjećaju",
        "osjećao", "osjećala", "osjećalo", "osjećali", "osjećale",
        "osjećat",
    )},
    # pustiti (to let)
    **{w: "pustit" for w in (
        "pustiti", "pustim", "pustiš", "pusti", "pustimo", "pustite", "puste",
        "pustio", "pustila", "pustilo", "pustili", "pustile",
        "pustit",
    )},
    # živjeti (to live) — irregular past -je-
    **{w: "živjet" for w in (
        "živjeti", "živim", "živiš", "živi", "živimo", "živite", "žive",
        "živio", "živjela", "živjelo", "živjeli", "živjele",
        "živjet", "živeći",
    )},
    # koristiti (to use)
    **{w: "koristit" for w in (
        "koristiti", "koristim", "koristiš", "koristi", "koristimo", "koristite", "koriste",
        "koristio", "koristila", "koristilo", "koristili", "koristile",
        "koristit", "koristeći",
    )},
    # smatrati (to consider)
    **{w: "smatrat" for w in (
        "smatrati", "smatram", "smatraš", "smatra", "smatramo", "smatrate", "smatraju",
        "smatrao", "smatrala", "smatralo", "smatrali", "smatrale",
        "smatrat",
    )},
    # pokazati (to show) — perfective
    **{w: "pokazat" for w in (
        "pokazati", "pokažem", "pokažeš", "pokaže", "pokažemo", "pokažete", "pokažu",
        "pokazao", "pokazala", "pokazalo", "pokazali", "pokazale",
        "pokazat",
    )},
    # razgovarati (to talk)
    **{w: "razgovarat" for w in (
        "razgovarati", "razgovaram", "razgovaraš", "razgovara", "razgovaramo",
        "razgovarate", "razgovaraju",
        "razgovarao", "razgovarala", "razgovaralo", "razgovarali", "razgovarale",
        "razgovarat",
    )},
    # nastaviti (to continue) — perfective
    **{w: "nastavit" for w in (
        "nastaviti", "nastavim", "nastaviš", "nastavi", "nastavimo", "nastavite",
        "nastave",
        "nastavio", "nastavila", "nastavilo", "nastavili", "nastavile",
        "nastavit",
    )},
    # primijetiti (to notice)
    **{w: "primijetit" for w in (
        "primijetiti", "primijetim", "primijetiš", "primijeti", "primijetimo",
        "primijetite", "primijete",
        "primijetio", "primijetila", "primijetilo", "primijetili", "primijetile",
        "primijetit",
    )},
    # prihvatiti (to accept)
    **{w: "prihvatit" for w in (
        "prihvatiti", "prihvatim", "prihvatiš", "prihvati", "prihvatimo",
        "prihvatite", "prihvate",
        "prihvatio", "prihvatila", "prihvatilo", "prihvatili", "prihvatile",
        "prihvatit",
    )},
    # objasniti (to explain)
    **{w: "objasnit" for w in (
        "objasniti", "objasnim", "objasniš", "objasni", "objasnimo",
        "objasnite", "objasne",
        "objasnio", "objasnila", "objasnilo", "objasnili", "objasnile",
        "objasnit",
    )},
    # javiti (to inform)
    **{w: "javit" for w in (
        "javiti", "javim", "javiš", "javi", "javimo", "javite", "jave",
        "javio", "javila", "javilo", "javili", "javile",
        "javit",
    )},
    # postati (to become)
    **{w: "postat" for w in (
        "postati", "postanem", "postaneš", "postane", "postanemo", "postanete", "postanu",
        "postao", "postala", "postalo", "postali", "postale",
        "postat",
    )},
    # napraviti (to make)
    **{w: "napravit" for w in (
        "napraviti", "napravim", "napraviš", "napravi", "napravimo", "napravite", "naprave",
        "napravio", "napravila", "napravilo", "napravili", "napravile",
        "napravit",
    )},
    # pokušati (to try)
    **{w: "pokušat" for w in (
        "pokušati", "pokušam", "pokušaš", "pokuša", "pokušamo", "pokušate", "pokušaju",
        "pokušao", "pokušala", "pokušalo", "pokušali", "pokušale",
        "pokušat",
    )},
    # vratiti (to return)
    **{w: "vratit" for w in (
        "vratiti", "vratim", "vratiš", "vrati", "vratimo", "vratite", "vrate",
        "vratio", "vratila", "vratilo", "vratili", "vratile",
        "vratit",
    )},
    # početi (to begin) — irregular počnem present
    **{w: "počet" for w in (
        "početi", "počnem", "počneš", "počne", "počnemo", "počnete", "počnu",
        "počeo", "počela", "počelo", "počeli", "počele",
        "početi",
    )},
    # završiti (to finish)
    **{w: "završit" for w in (
        "završiti", "završim", "završiš", "završi", "završimo", "završite", "završe",
        "završio", "završila", "završilo", "završili", "završile",
        "završit",
    )},
    # pomoći (to help) — irregular pomognem present
    **{w: "pomoć" for w in (
        "pomoći", "pomognem", "pomogneš", "pomogne", "pomognemo", "pomognete", "pomognu",
        "pomogao", "pomogla", "pomoglo", "pomogli", "pomogle",
        "pomoći",
    )},
    # naći (to find) — irregular nađ-
    **{w: "nać" for w in (
        "naći", "nađem", "nađeš", "nađe", "nađemo", "nađete", "nađu",
        "našao", "našla", "našlo", "našli", "našle",
        "naći",
    )},
    # pisati (to write) — palatalization piš- / pis-
    **{w: "pisat" for w in (
        "pisati", "pišem", "pišeš", "piše", "pišemo", "pišete", "pišu",
        "pisao", "pisala", "pisalo", "pisali", "pisale",
        "pisat", "pišući",
    )},
    # dobiti (to get)
    **{w: "dobit" for w in (
        "dobiti", "dobijem", "dobiješ", "dobije", "dobijemo", "dobijete", "dobiju",
        "dobio", "dobila", "dobilo", "dobili", "dobile",
        "dobit",
    )},
    # držati (to hold)
    **{w: "držat" for w in (
        "držati", "držim", "držiš", "drži", "držimo", "držite", "drže",
        "držao", "držala", "držalo", "držali", "držale",
        "držat", "držeći",
    )},
    # ostati (to stay) — perfective
    **{w: "ostat" for w in (
        "ostati", "ostanem", "ostaneš", "ostane", "ostanemo", "ostanete", "ostanu",
        "ostao", "ostala", "ostalo", "ostali", "ostale",
        "ostat",
    )},
    # doći (to come) — irregular dođ-
    **{w: "doć" for w in (
        "doći", "dođem", "dođeš", "dođe", "dođemo", "dođete", "dođu",
        "došao", "došla", "došlo", "došli", "došle",
        "doći", "dođi", "dođite",
    )},
    # reći (to say) — irregular rek-/rec-
    **{w: "reć" for w in (
        "reći", "rečem", "rečeš", "reče", "rečemo", "rečete", "reku",
        "rekao", "rekla", "reklo", "rekli", "rekle",
        "reći", "reci", "recite",
    )},
    # činiti / učiniti (to do)
    **{w: "činit" for w in (
        "činiti", "činim", "činiš", "čini", "činimo", "činite", "čine",
        "činio", "činila", "činilo", "činili", "činile",
        "činit", "čineći",
    )},
    **{w: "učinit" for w in (
        "učiniti", "učinim", "učiniš", "učini", "učinimo", "učinite", "učine",
        "učinio", "učinila", "učinilo", "učinili", "učinile",
        "učinit",
    )},
    # pitati (to ask)
    **{w: "pitat" for w in (
        "pitati", "pitam", "pitaš", "pita", "pitamo", "pitate", "pitaju",
        "pitao", "pitala", "pitalo", "pitali", "pitale",
        "pitat", "pitajući",
    )},
    # tražiti (to look for)
    **{w: "tražit" for w in (
        "tražiti", "tražim", "tražiš", "traži", "tražimo", "tražite", "traže",
        "tražio", "tražila", "tražilo", "tražili", "tražile",
        "tražit", "tražeći",
    )},
    # uzeti (to take) — irregular uzmem/uzme present
    **{w: "uzet" for w in (
        "uzeti", "uzmem", "uzmeš", "uzme", "uzmemo", "uzmete", "uzmu",
        "uzeo", "uzela", "uzelo", "uzeli", "uzele",
        "uzet",
    )},
    # znati (to know)
    **{w: "znat" for w in (
        "znati", "znam", "znaš", "zna", "znamo", "znate", "znaju",
        "znao", "znala", "znalo", "znali", "znale",
        "znat", "znajući",
    )},
    # gledati (to watch)
    **{w: "gledat" for w in (
        "gledati", "gledam", "gledaš", "gleda", "gledamo", "gledate", "gledaju",
        "gledao", "gledala", "gledalo", "gledali", "gledale",
        "gledat", "gledajući",
    )},
    # čitati (to read)
    **{w: "čitat" for w in (
        "čitati", "čitam", "čitaš", "čita", "čitamo", "čitate", "čitaju",
        "čitao", "čitala", "čitalo", "čitali", "čitale",
        "čitat", "čitajući",
    )},
    # voljeti (to love)
    **{w: "voljet" for w in (
        "voljeti", "volim", "voliš", "voli", "volimo", "volite", "vole",
        "volio", "voljela", "voljelo", "voljeli", "voljele",
        "voljet", "voleći",
    )},
    # govoriti (to speak)
    **{w: "govorit" for w in (
        "govoriti", "govorim", "govoriš", "govori", "govorimo",
        "govorite", "govore",
        "govorio", "govorila", "govorilo", "govorili", "govorile",
        "govorit", "govoreći",
    )},
    # misliti (to think)
    **{w: "mislit" for w in (
        "misliti", "mislim", "misliš", "misli", "mislimo", "mislite",
        "misle", "mislio", "mislila", "mislilo", "mislili", "mislile",
        "mislit", "misleći",
    )},
    # vidjeti (to see) — irregular past -je- stem; unify to "vidjet"
    **{w: "vidjet" for w in (
        "vidjeti", "vidim", "vidiš", "vidi", "vidimo", "vidite", "vide",
        "vidio", "vidjela", "vidjelo", "vidjeli", "vidjele",
        "vidjet", "vidjevši", "vidjevsi", "videći",
    )},
    # postaviti (to place) — unify bare forms with -i/-la forms
    **{w: "postavit" for w in (
        "postaviti", "postavim", "postaviš", "postavi", "postavimo",
        "postavite", "postave",
        "postavio", "postavila", "postavilo", "postavili", "postavile",
        "postavit",
    )},
    # raditi (to work) — unify onto "radit" (separate from noun rad / adv rado/radije)
    **{w: "radit" for w in (
        "raditi", "radim", "radiš", "radi", "radimo", "radite", "rade",
        "radio", "radila", "radilo", "radili", "radile",
        "radit", "radeći", "radimo", "radite",
    )},
    # imati (to have) — unify all forms onto "imat" (avoid conflating with pronoun "im")
    **{w: "imat" for w in (
        "imati", "imam", "imaš", "ima", "imamo", "imate", "imaju",
        "imao", "imala", "imalo", "imali", "imale",
        "imat", "imajući", "imavši", "imaj", "imajte",
    )},
    # ime (name) — unify with imen- oblique stem (ime vs imena/imenu)
    "ime": "imen",
    # mlad (young) — fix rule 62 overcapture of mladim/mladima
    **{w: "mlad" for w in (
        "mlad", "mlada", "mlado", "mladi", "mlade", "mladu",
        "mladog", "mladoga", "mladom", "mladome", "mladomu",
        "mladoj", "mladim", "mladima", "mladih", "mladoj",
        "mlađi", "mlađa", "mlađe", "mlađu",
        "mlađeg", "mlađega", "mlađem", "mlađemu", "mlađom",
        "mlađim", "mlađima", "mlađih", "mlađoj",
    )},
    # mali (small) — suppletive comparative manj-
    **{w: "mal" for w in (
        "mali", "mala", "male",
        "malog", "maloga", "malom", "malome", "malomu",
        "maloj", "malu", "malim", "malima", "malih", "malimi",
        "manji", "manja", "manju",
        "manjeg", "manjega", "manjem", "manjemu", "manjom",
        "manjim", "manjima", "manjih", "manjoj",
    )},
    # loš (bad) — suppletive comparative gor- (skip ambiguous "gore"/"gora")
    **{w: "loš" for w in (
        "loš", "loša", "loše", "loši", "lošu",
        "lošeg", "lošega", "lošem", "lošemu", "lošom",
        "lošim", "lošima", "loših", "lošoj",
        "gori", "gorim", "gorima", "gorih", "goroj",
        "gorem", "goreg", "gorega",
    )},
    # dobar (good) — including suppletive comparative bolj-
    **{w: "dobr" for w in (
        "dobar", "dobra", "dobro", "dobri", "dobre",
        "dobrog", "dobroga", "dobrom", "dobrome", "dobromu",
        "dobroj", "dobru", "dobrim", "dobrima", "dobrih",
        "bolji", "bolja", "bolje", "bolju",
        "boljeg", "boljega", "boljem", "boljemu", "boljom",
        "boljim", "boljima", "boljih", "boljoj",
    )},
    # Fleeting-a nom sg outliers (oblique forms drop the a → consonant cluster)
    "mokar": "mokr", "mudar": "mudr", "bistar": "bistr",
    "vedar": "vedr", "modar": "modr", "oštar": "oštr",
    "mrtav": "mrtv",
    # -ak fleeting with palatalization/devoicing (oblique stem in parens)
    "težak": "tešk",      # teška/teški
    "tanak": "tank",      # tanka/tanki
    "nizak": "nisk",      # niska/niski
    "sladak": "slatk",    # slatka/slatki
    "gladak": "glatk",    # glatka/glatki
    "rijedak": "rijetk",  # rijetka/rijetki
    # Comparative forms (palatalized) unified with positive canonical stem
    **{w: "tešk" for w in (
        "teži", "teža", "teže", "težu",
        "težeg", "težega", "težem", "težemu", "težom",
        "težim", "težima", "težih", "težoj",
    )},
    **{w: "nisk" for w in (
        "niži", "niža", "niže", "nižu",
        "nižeg", "nižega", "nižem", "nižemu", "nižom",
        "nižim", "nižima", "nižih", "nižoj",
    )},
    **{w: "visok" for w in (
        "viši", "viša", "više", "višu",
        "višeg", "višega", "višem", "višemu", "višom",
        "višim", "višima", "viših", "višoj",
    )},
    "uzak": "usk", "blizak": "blisk",
    # brz (fast) — comparative brž-
    **{w: "brz" for w in (
        "brži", "brža", "brže", "bržu",
        "bržeg", "bržega", "bržem", "bržemu", "bržom",
        "bržim", "bržima", "bržih", "bržoj",
    )},
    # uzak (narrow) — comparative už-
    **{w: "usk" for w in (
        "uži", "uža", "uže", "užu",
        "užeg", "užega", "užem", "užemu", "užom",
        "užim", "užima", "užih", "užoj",
    )},
    # blizak (close) — comparative bliž-
    **{w: "blisk" for w in (
        "bliži", "bliža", "bliže", "bližu",
        "bližeg", "bližega", "bližem", "bližemu", "bližom",
        "bližim", "bližima", "bližih", "bližoj",
    )},
    # dubok (deep) — comparative dublj- (jotation)
    **{w: "dubok" for w in (
        "dublji", "dublja", "dublje", "dublju",
        "dubljeg", "dubljega", "dubljem", "dubljemu", "dubljom",
        "dubljim", "dubljima", "dubljih", "dubljoj",
    )},
    # lak (easy) — comparative lakš-
    **{w: "lak" for w in (
        "lakši", "lakša", "lakše", "lakšu",
        "lakšeg", "lakšega", "lakšem", "lakšemu", "lakšom",
        "lakšim", "lakšima", "lakših", "lakšoj",
    )},
    # suh (dry) — comparative suš- (h→š)
    **{w: "suh" for w in (
        "suši", "suša", "suše", "sušu",
        "sušeg", "sušega", "sušem", "sušemu", "sušom",
        "sušim", "sušima", "suših", "sušoj",
    )},
    # tih (quiet) — comparative tiš-
    **{w: "tih" for w in (
        "tiši", "tiša", "tiše", "tišu",
        "tišeg", "tišega", "tišem", "tišemu", "tišom",
        "tišim", "tišima", "tiših", "tišoj",
    )},
    # žut (yellow) — comparative žuć- (t→ć)
    **{w: "žut" for w in (
        "žući", "žuća", "žuće", "žuću",
        "žućeg", "žućega", "žućem", "žućemu", "žućom",
        "žućim", "žućima", "žućih", "žućoj",
    )},
    # ljut (angry) — comparative ljuć-
    **{w: "ljut" for w in (
        "ljući", "ljuća", "ljuće", "ljuću",
        "ljućeg", "ljućega", "ljućem", "ljućemu", "ljućom",
        "ljućim", "ljućima", "ljućih", "ljućoj",
    )},
    # ići (to go) — full irregular paradigm
    **{w: "id" for w in (
        "ići", "idem", "ideš", "ide", "idemo", "idete", "idu",
        "išao", "išla", "išlo", "išli", "išle",
        "idi", "idite", "idimo", "ideći", "idući",
    )},
}
# Stop words: the original v0.1 list of auxiliary/modal forms (biti, htjeti,
# željeti, morati, trebati, moći). stem() still maps them through LEXICON;
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
assert STOP_WORDS <= LEXICON.keys()

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
}

# Suffix stripping rules: (stem_pattern, suffix_alternatives) pairs.
# Each compiles to ^(stem_pattern)(suffix1|suffix2|...)$.
# Ordered by specificity — first match wins.
# The v0.1 rule set, in its original order, plus additions found by the
# autoresearch loop (the .+ed and palatal -eg rules, non-greedy catch-alls).
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
    ('.+log', 'ama|om|a|u|e|'),
    ('.+[^eo]g', 'ovima|ama|ovi|ove|ova|om|a|e|i|u|o|'),
    # --- I ---
    ('.+(rrar|ott|ss|ll)i', 'jem|ja|ju|o|'),
    # --- J ---
    ('.+uj', 'ući|emo|ete|mo|em|eš|e|u|'),
    ('.+(c|č|ć|đ|l|r)aj', 'evima|evi|eva|eve|ama|ima|em|a|e|i|u|'),
    ('.+(b|c|d|l|n|m|ž|g|f|p|r|s|t|z)ij', 'ima|ama|om|a|e|i|u|o|'),
    # --- L ---
    ('.+[^z]nal', 'ima|ama|om|a|e|i|u|o|'),
    ('.+ijal', 'ima|ama|om|a|e|i|u|o|'),
    ('.+ozil', 'ima|om|a|e|u|i|'),
    ('.+olov', 'ima|i|a|e'),
    ('.+ol', 'ima|om|a|u|e|i|'),
    # --- M ---
    ('.+lem', 'ama|ima|om|a|e|i|u|o|'),
    ('.+ram', 'ama|om|a|e|i|u|o'),
    # --- R ---
    ('.+(a|d|e|o)r', 'ama|ima|om|u|a|e|i|'),
    # --- S ---
    ('.+(e|i)s', 'ima|om|e|a|u'),
    # --- Š ---
    ('.+(t|n|j|k|j|t|b|g|v)aš', 'ama|ima|om|em|a|u|i|e|'),
    ('.+(e|i)š', 'ima|ama|om|em|i|e|a|u'),
    # --- T ---
    ('.+ikat', 'ima|om|a|e|i|u|o|'),
    ('.+lat', 'ima|om|a|e|i|u|o|'),
    # Verb e-class present (provesti, jesti) — insert before noun .+et
    ('.+ed', 'ete|emo|eš|em|e|u'),
    ('.+et', 'ama|ima|om|a|e|i|u|o|'),
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
    ('.+n', 'uvši|usmo|uste|ući|imo|ite|emo|ete|ula|ulo|ule|uli|uto|uti|uta|em|eš|uo|ut|e|u|i'),
    ('.+ni', 'vši|smo|ste|ti|mo|te|mo|te|la|lo|le|li|m|š|o'),
    # --- Verb a-class ---
    ('.+((a|r|i|p|e|u)st|[^o]g|ik|uc|oj|aj|lj|ak|ck|čk|šk|uk|nj|im|ar|at|et|št|it|ot|ut|zn|zv)a', 'jući|vši|smo|ste|jmo|jte|jem|mo|te|je|ju|ti|še|hu|la|li|le|lo|na|no|ni|ne|t|h|o|j|n|m|š'),
    ('.+ur', 'ajući|asmo|aste|ajmo|ajte|amo|ate|aju|ati|aše|ahu|ala|ali|ale|alo|ana|ano|ani|ane|al|at|ah|ao|aj|an|am|aš'),
    ('.+(a|i|o)staj', 'asmo|aste|ahu|ati|emo|ete|aše|ali|ući|ala|alo|ale|mo|ao|em|eš|at|ah|te|e|u|'),
    ('.+(b|c|č|ć|d|e|f|g|j|k|n|r|t|u|v)a', 'lama|lima|lom|lu|li|la|le|lo|l'),
    ('.+(t|č|j|ž|š)aj', 'evima|evi|eva|eve|ama|ima|em|a|e|i|u|'),
    ('.+([^o]m|ič|nč|uč|b|c|ć|d|đ|h|j|k|l|n|p|r|s|š|v|z|ž)a', 'jući|vši|smo|ste|jmo|jte|mo|te|ju|ti|še|hu|la|li|le|lo|na|no|ni|ne|t|h|o|j|n|m|š'),
    ('.+(a|i|o)sta', 'dosmo|doste|doše|nemo|demo|nete|dete|nimo|nite|nila|vši|nem|dem|neš|deš|doh|de|ti|ne|nu|du|la|li|lo|le|t|o'),
    ('.+ta', 'smo|ste|jmo|jte|vši|ti|mo|te|ju|še|la|lo|le|li|na|no|ni|ne|n|j|o|m|š|t|h'),
    ('.+inj', 'asmo|aste|ati|emo|ete|ali|ala|alo|ale|aše|ahu|em|eš|at|ah|ao'),
    ('.+as', 'temo|tete|timo|tite|tući|tem|teš|tao|te|li|ti|la|lo|le'),
    # --- Verb i-class ---
    ('.+(elj|ulj|tit|ac|ič|od|oj|et|av|ov)i', 'vši|eći|smo|ste|še|mo|te|ti|li|la|lo|le|m|š|t|h|o'),
    ('.+(tit|jeb|ar|ed|uš|ič)i', 'jemo|jete|jem|ješ|smo|ste|jmo|jte|vši|mo|še|te|ti|ju|je|la|lo|li|le|t|m|š|h|j|o'),
    ('.+(b|č|d|l|m|p|r|s|š|ž)i', 'jemo|jete|jem|ješ|smo|ste|jmo|jte|vši|mo|lu|še|te|ti|ju|je|la|lo|li|le|t|m|š|h|j|o'),
    ('.+luč', 'ujete|ujući|ujemo|ujem|uješ|ismo|iste|ujmo|ujte|uje|uju|iše|iti|imo|ite|ila|ilo|ili|ile|ena|eno|eni|ene|uj|io|en|im|iš|it|ih|e|i'),
    ('.+jeti', 'smo|ste|še|mo|te|ti|li|la|lo|le|m|š|t|h|o'),
    # --- L-participle ---
    ('.+e', 'lama|lima|lom|lu|li|la|le|lo|l'),
    ('.+i', 'lama|lima|lom|lu|li|la|le|lo|l'),
    # --- Adjective participle ---
    ('.+at', 'ijega|ijemu|ijima|ijeg|ijem|ijih|ijim|ima|oga|ome|omu|iji|ije|ija|iju|oj|og|om|im|ih|a|u|i|e|o|'),
    ('.+et', 'avši|ući|emo|imo|em|eš|e|u|i'),
    # Comparative gen sg -eg only after palatal consonants (boljeg, manjeg,
    # većeg, višeg). Keeps snijeg/brijeg nouns (stem ends in plain j) intact.
    ('.+(lj|nj|š|č|ć|ž|đ)', 'eg'),
    # --- Catch-all rules (non-greedy stems, iteration #2 improvement) ---
    ('.+?', 'ajući|alima|alom|avši|asmo|aste|ajmo|ajte|ivši|amo|ate|aju|ati|aše|ahu|ali|ala|ale|alo|ana|ano|ani|ane|am|aš|at|ah|ao|aj|an'),
    ('.+?', 'anje|enje|anja|enja|enom|enoj|enog|enim|enih|anom|anoj|anog|anim|anih|eno|ovi|ova|oga|ima|ove|enu|anu|ena|ama'),
    ('.+?', 'nijega|nijemu|nijima|nijeg|nijem|nijim|nijih|nima|niji|nije|nija|niju|noj|nom|nog|nim|nih|an|na|nu|ni|ne|no'),
    ('.+?', 'emo|ete|amo|ate|imo|ite|om|og|im|ih|em|oj|an|ju|u|o|i|e|a'),
]

# Precompiled regex patterns for suffix stripping
WORD_PATTERNS: list[re.Pattern[str]] = [
    re.compile(rf"^({stem})({suffixes})$")
    for stem, suffixes in _RULES
]

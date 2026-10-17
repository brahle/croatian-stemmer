# Smjernice za označavanje

Ove smjernice vrijede za aplikaciju za označavanje (vidi [labeling-web.md](labeling-web.md)).
Ista se verzija prikazuje sudionicima na stranici
`/static/guidelines.hr.html`; kada mijenjate jednu, promijenite i drugu.
Kratki sažetak na engleskom nalazi se u [guidelines.en.md](guidelines.en.md).

## Što radite

Za svaki primjer vidite riječ u rečenici iz jezičnog korpusa i odgovarate na jedno
pitanje. Postoje tri vrste primjera:

- **Par riječi**: pripadaju li dvije riječi, svaka u svojoj rečenici, istoj lemi?
  Odgovori: „Ista lema”, „Različite leme”, „Nisam siguran/na”.
- **Lema**: koja je rječnička lema ove riječi? Prijedlog iz korpusa je upisan;
  potvrdite ga ili ispravite pa odaberite „Potvrdi lemu”.
- **Korijen**: je li predloženi korijen prihvatljiv za ovu riječ? Odgovori:
  „Prihvati korijen”, „Odbaci korijen”, „Nisam siguran/na”.

Uvijek pročitajte cijelu rečenicu. Značenje riječi u rečenici odlučuje.

## Što je lema

Lema je oblik pod kojim bi riječ stajala u rječniku:

- **imenice**: nominativ jednine (kuće → kuća, ljudi → čovjek). Imenice koje postoje
  samo u množini ostaju u množini (škare, vrata);
- **pridjevi**: muški rod, nominativ jednine, pozitiv (lijepa → lijep). Komparativ i
  superlativ svode se na pozitiv (brži → brz, najbolji → dobar);
- **glagoli**: infinitiv (pisao → pisati). Vid je dio leme: *pisati* i *napisati*
  različite su leme. Povratnu zamjenicu *se* ne upisujte (bojim se → bojati); polje
  za lemu prima samo jednu riječ;
- **umanjenice i uvećanice** su zasebne leme (kućica nije *kuća*);
- **zamjenice, brojevi i nepromjenjive riječi**: uobičajeni rječnički oblik (njega → on).

Lemu pišite s dijakritičkim znakovima (č, ć, đ, š, ž), bez razmaka i interpunkcije;
aplikacija velika slova sama pretvara u mala.

## Parovi riječi

„Ista lema” znači da su obje riječi oblici iste rječničke riječi u istom značenju
i iste vrste riječi. Primjeri:

- *kuće* i *kućom* → ista lema (*kuća*);
- *pisati* i *napisati* → različite leme (vid);
- *lijep* i *ljepši* → ista lema (*lijep*);
- *kućica* i *kuća* → različite leme (umanjenica);
- isti zapis s različitim značenjem (*vode* u „čaša vode” i *vode* u „oni vode
  tim”) → različite leme (*voda*, *voditi*).

## Korijeni

Korijen je dio riječi koji stemer ostavlja nakon što ukloni nastavke. Prihvatite
korijen ako bi se svi uobičajeni oblici iste leme mogli svesti na njega, a ne bi se
na njega svodile riječi drugačijeg značenja. Odbacite ga ako je predug (zadržava
nastavak pa bi različiti oblici iste leme dobili različite korijene) ili prekratak
(stopio bi nepovezane riječi).

## Nepravilan oblik

Označite „Nepravilan oblik / iznimka” kada je riječ nepravilan oblik svoje leme
(na primjer *ljudi* od *čovjek*, *išao* od *ići*). Ta oznaka ne mijenja odgovor.

## Kada odabrati „Nisam siguran/na”

Odaberite „Nisam siguran/na” uvijek kada ne možete pouzdano odgovoriti, posebno:

- oblik je dvoznačan i rečenica ne razrješava značenje;
- u izvornom tekstu je tipfeler ili pogrešno rastavljena riječ;
- riječ Vam je nepoznata;
- riječ je vlastito ime, a niste sigurni kako se sklanja.

Takav odgovor nije pogreška. Pogrešan siguran odgovor šteti skupu podataka više od
iskrenog „Nisam siguran/na”.

## Prijedlozi iz korpusa

Prijedlozi lema iz korpusa dobiveni su automatski i mogu biti pogrešni. Upotrijebite
ih kao pomoć, ali odlučujte prema rečenici i ovim smjernicama.

## Provjera pouzdanosti

Među primjerima se mogu nalaziti i primjeri s poznatim odgovorom; njima se procjenjuje
pouzdanost odgovora. Odgovarajte na sve primjere jednako pažljivo.

## Prečaci

Tipke 1, 2 i 3 biraju odgovore redom kojim su prikazani (kada kursor nije u polju za
lemu).

import Keycloak from './vendor/keycloak.js';
import {version as clientVersion} from './version.js';

// All interface text, Croatian first. Nothing here is persisted: the language
// choice lives in memory only (see the storage notice).
const strings = {
  hr: {
    skipLink:'Preskoči na sadržaj', brand:'Hrvatski korijeni', title:'Označavanje jezičnih primjera', menu:'Izbornik',
    navLabel:'Označavanje', navMe:'Moji podaci', navCurator:'Kurator', logout:'Odjava', login:'Prijava', loginGoogle:'Prijava Google računom',
    paused:'Primanje odgovora je privremeno zaustavljeno. Možete pregledavati, ali odgovori se trenutačno ne spremaju.',
    landingTitle:'Pomozite izgraditi otvoreni skup podataka za hrvatski jezik',
    landingIntro:'Na ovoj stranici dobrovoljci procjenjuju pripadaju li dvije riječi istoj lemi, potvrđuju rječničke leme i procjenjuju korijene riječi. Odgovori se koriste za vrednovanje otvorenog hrvatskog stemera i objavljuju se kao otvoreni skup podataka, bez Vašeg imena.',
    landingRunBy:'Projekt vodi', landingAge:'Sudjelovati mogu osobe koje imaju najmanje 18 godina. Prije prvog odgovora tražit ćemo Vaš pristanak.',
    signInPrompt:'Prijavite se za sudjelovanje.',
    gateTitle:'Prije nego što počnete',
    gateWhat:'Spremamo Vaše odgovore, vrijeme potrebno za odgovor i Vašu adresu e-pošte iz Google računa. Odgovori se vežu uz nasumičnu oznaku, a ne uz Vaše ime. Javno objavljujemo samo zbirne oznake za svaki primjer, nikada Vaše pojedinačne odgovore.',
    gateRights:'Svoje podatke možete u svakom trenutku preuzeti ili izbrisati profil na stranici „Moji podaci”.',
    gatePrivacy:'Kako obrađujemo Vaše podatke, objašnjava', privacyNotice:'obavijest o privatnosti', gateTerms:'Prihvaćam', termsLink:'uvjete sudjelovanja',
    gateTermsLicence:', uključujući licenciju mojih odgovora.', gateParticipation:'Pristajem na bilježenje i korištenje mojih odgovora kako je opisano u',
    participationLink:'izjavi o sudjelovanju', gateAge:'Imam najmanje 18 godina.', accept:'Prihvaćam', gateErase:'Izbriši račun',
    gateMessage:'Za sudjelovanje prihvatite uvjete i izjavu o sudjelovanju te potvrdite dob.', version:'(verzija {v})',
    erasedTitle:'Profil je izbrisan',
    erasedDone:'Vaš profil je izbrisan. Račun za prijavu izbrisat ćemo u roku od 30 dana; ako se do tada ponovno prijavite, vidjet ćete ovu obavijest umjesto novog profila. Vaši odgovori ostaju u skupu podataka pod novom nasumičnom oznakom koja se ne može povezati ni s Vama ni s Vašom dosadašnjom oznakom.',
    erasurePending:'Ovaj račun je u postupku brisanja. Račun za prijavu bit će izbrisan u roku od 30 dana od zahtjeva; nakon toga se možete ponovno prijaviti kao novi sudionik.',
    erasureExpired:'Ovaj profil je izbrisan jer u roku od 30 dana od prve prijave niste prihvatili uvjete i izjavu o sudjelovanju. Račun za prijavu bit će izbrisan u roku od 30 dana; nakon toga se možete ponovno prijaviti kao novi sudionik.',
    corpus:'Korpus', chooseCorpusOption:'Odaberite korpus', kind:'Vrsta', kindPair:'Par riječi', kindLemma:'Lema', kindStem:'Korijen',
    queue:'Red', queueNext:'Novi primjeri', queueLabelled:'Moji označeni', queueUnsure:'Moji nesigurni',
    hintsTitle:'Prijedlozi iz korpusa', lemmaLabel:'Potvrđena ili ispravljena lema', stemLabel:'Predloženi korijen:',
    irregular:'Nepravilan oblik / iznimka', retry:'Ponovi spremanje istog odgovora', skip:'Preskoči', guidelines:'Smjernice za označavanje',
    pairs:'Parovi', lemmas:'Leme', stems:'Korijeni', progressLine:'{kind}: {definite} potvrđenih, {unsure} nesigurnih / {total} primjera',
    promptPair:'Pripadaju li ove riječi istoj lemi?', promptLemma:'Koja je rječnička lema ove riječi?', promptStem:'Je li predloženi korijen prihvatljiv?',
    revision:'Revizija {n}; Vaš spremljeni odgovor: {answer}.', noLabel:'Ovaj primjer još niste označili.',
    sampling:'Uzorkovanje: ', licence:'Licencija: ', corpusLemma:'Lema iz korpusa: ', source:'Izvor: ',
    same:'Ista lema', different:'Različite leme', unsure:'Nisam siguran/na', confirmed:'Potvrdi lemu', accept_:'Prihvati korijen', reject:'Odbaci korijen',
    chooseAnswer:'Odaberite odgovor (tipke 1–3). Prijedloge možete provjeriti u pojedinostima.',
    chooseCorpus:'Odaberite korpus.', noCorpora:'Trenutačno nema objavljenih korpusa.',
    emptyNext:'Trenutačno nema novih primjera ove vrste za Vas. Preskočeni primjeri vraćaju se nakon 30 minuta.',
    emptyQueue:'U ovom redu nema više primjera.', saved:'Odgovor je spremljen.',
    typeLemma:'Upišite lemu prije potvrde.', retryFirst:'Najprije ponovite prethodno spremanje ili ponovno učitajte stranicu.',
    conflict:'Odgovor je u međuvremenu izmijenjen u drugoj sesiji. Učitan je posljednji odgovor; pregledajte ga prije novog spremanja.',
    meTitle:'Moji podaci', meId:'Vaša nasumična oznaka:', meConsents:'Prihvaćeni dokumenti', meCounts:'Odgovora ukupno: {judgments}; označenih primjera: {items}.',
    consentLine:'{doc}, verzija {version}, prihvaćeno {date}', docPrivacy:'Obavijest o privatnosti', docTerms:'Uvjeti sudjelovanja', docParticipation:'Izjava o sudjelovanju',
    noConsents:'Još niste prihvatili dokumente.', download:'Preuzmi moje podatke', downloaded:'Vaši podaci su preuzeti (JSON).',
    eraseTitle:'Izbriši moj račun',
    eraseWhat:'Brisanjem se odmah uklanjaju veza s Vašim računom za prijavu, adresa e-pošte, vremena odgovora i popis prikazanih primjera. Oznaku računa za prijavu čuvamo samo dok taj račun (s imenom i prezimenom) ne izbrišemo, najdulje 30 dana.',
    eraseKeeps:'Vaši odgovori ostaju u skupu podataka pod novom nasumičnom oznakom koja se ne može povezati ni s Vama ni s Vašom dosadašnjom oznakom; od vremena odgovora čuva se samo dan. Ako je profil blokiran ili izdvojen, odgovori se brišu.',
    erasePrompt:'Za potvrdu upišite {word}', eraseWord:'IZBRIŠI', eraseButton:'Izbriši moj račun', eraseMismatch:'Za brisanje upišite točno {word}.',
    curatorTitle:'Kurator', intakeTitle:'Primanje odgovora', intakeOn:'Odgovori se primaju.', intakeOff:'Primanje odgovora je zaustavljeno.',
    intakeReadOnly:' Poslužitelj je u načinu samo za čitanje (LABELING_READ_ONLY).', pause:'Zaustavi primanje odgovora', resume:'Nastavi primanje odgovora',
    importTitle:'Uvoz prijedloga iz korpusa', importIntro:'Učitajte pripremljenu JSONL datoteku. Novi korpus je skica dok ga ne objavite. Uvoz ne mijenja postojeće odgovore.',
    importName:'Naziv korpusa', importFile:'Datoteka s prijedlozima', importSelect:'Odaberi datoteku', importButton:'Uvezi prijedloge',
    importLimits:'Najviše 20.000 primjera i 32 MiB po uvozu.', noFile:'Datoteka nije odabrana.', badJson:'Datoteka sadrži neispravan JSON.',
    importCount:'Uvoz mora sadržavati od 1 do 20.000 prijedloga.', imported:'Uvezeno {added} novih prijedloga; {present} već postoji.',
    corporaTitle:'Korpusi', colName:'Naziv', colStatus:'Status', colLicence:'Licencija izvora / oznaka', colItems:'Primjeri', colActions:'Radnje',
    statusDraft:'skica', statusPublished:'objavljen', statusArchived:'arhiviran', publish:'Objavi', unpublish:'Povuci objavu', archive:'Arhiviraj',
    exportTsv:'Izvoz TSV', exportJsonl:'Izvoz JSONL', labelsLicence:'Licencija oznaka', published:'Korpus je objavljen.', exported:'Izvoz je preuzet.',
    itemsLine:'parovi {pair}, leme {lemma}, korijeni {stem}',
    annotatorsTitle:'Označivači', colAnnotator:'Oznaka / e-pošta', colJudgments:'Odgovori', colSeen:'Zadnji put', more:'Učitaj još',
    statusActive:'aktivan', statusQuarantined:'izdvojen', statusBlocked:'blokiran', statusErased:'izbrisan', reason:'Razlog', apply:'Primijeni',
    reasonRequired:'Upišite razlog promjene statusa.', statusChanged:'Status je promijenjen.',
    erasuresTitle:'Zahtjevi za brisanje', erasuresHelp:'U konzoli za administraciju Keycloaka potražite korisnika po ID-u i izbrišite ga, zatim potvrdite ovdje. Rok je 30 dana od zahtjeva.',
    noErasures:'Nema zahtjeva koji čekaju.', erasureLine:'Keycloak ID {user} · zatraženo {date} ({days} d)', erasureExpiredReason:' · nije prihvatio/la u 30 dana', confirmErasure:'Potvrdi brisanje u Keycloaku',
    erasureCompleted:'Brisanje je potvrđeno.',
    footerPrivacy:'Privatnost', footerTerms:'Uvjeti i licencija', footerParticipation:'Sudjelovanje', footerStorage:'Kolačići i pohrana', legalMenu:'Pravne informacije',
    footerVersion:'Verzija aplikacije {v}', unavailable:'Prijava trenutačno nije dostupna. Osvježite stranicu i pokušajte ponovno.',
    genericError:'Zahtjev nije uspio. Pokušajte ponovno.', actionFailed:'Radnja nije uspjela. Pokušajte ponovno.',
    anyCorpus:'Bilo koji korpus', expertWork:'Rad za urednike', qualification:'Provjera znanja {done}/{of}',
    qualificationHelp:'Prvih {of} primjera ove vrste provjerava Vaše znanje i prikazuje se bez prijedloga. Rezultat ćete vidjeti u odjeljku „Pouzdanost”.',
    corpusLocked:'Korpus ćete moći odabrati kad položite provjeru znanja za ovu vrstu. Do tada dobivate primjere iz bilo kojeg korpusa.',
    blindNote:'Ovaj primjer prikazan je bez prijedloga iz korpusa.', footerTrust:'Pouzdanost',
    trustTitle:'Pouzdanost', trustHow:'Kako radi pouzdanost', trustNone:'Pouzdanost još nije izračunata.',
    trustLine:'{kind}: razina {tier}, procjena {band}; provjera s poznatim odgovorom oko {checks}{agreement}.',
    trustAgreement:'; slaganje s riješenim primjerima oko {value} %', trustQualified:' (provjera znanja položena)',
    trustBlocked:'Vaš profil je blokiran. Razlog: {reason}', trustAnchor:'Na popisu ste pouzdanih stručnjaka.',
    trustRunAt:'Izračunato {date}.',
    tier_new:'nova', tier_qualified:'kvalificirana', tier_established:'etablirana', tier_anchor:'stručnjak', tier_quarantined:'izdvojena',
    band_visoka:'visoka', band_dobra:'dobra', band_treba_paznje:'treba pažnje', band_nedovoljno_podataka:'nedovoljno podataka',
    tabOverview:'Pregled', tabPeople:'Suradnici', tabQuarantine:'Karantena', tabGold:'Zlatni primjeri', tabDisputes:'Sporni primjeri',
    tabTrusted:'Pouzdane adrese', tabScoring:'Bodovanje',
    scoringTitle:'Bodovanje pouzdanosti', scoringOn:'Bodovanje je uključeno; izračun se pokreće svakih {minutes} min.',
    scoringOff:'Bodovanje je isključeno: nitko se ne profilira.', scoringEnable:'Uključi bodovanje', scoringDisable:'Isključi bodovanje',
    lastRun:'Zadnji izračun: {date} ({status}).', noRun:'Još nema izračuna.', alertsTitle:'Upozorenja', noAlerts:'Nema upozorenja.',
    readinessTitle:'Spremnost po vrsti', readinessLine:'{kind}: provjera znanja {q}, skrivene provjere {a}, napredovanje {p}; skupovi {pools}',
    yes:'da', no:'ne', statesTitle:'Stanja primjera', colStates:'Stanja', colTiers:'Razine', colItem:'Primjer', colAnswer:'Odgovor',
    colRun:'Izračun', colCounts:'Odgovori / primjeri / osobe', anchorBadge:'stručnjak',
    state_open:'otvoreno', state_reserve:'provjere u pričuvi', state_provisional:'privremeno', state_resolved:'riješeno', state_needs_expert:'traži stručnjaka',
    state_contested:'sporno', state_ambiguous:'dvosmisleno', stateContested:'sporno', stateNeedsExpert:'traži stručnjaka', stateProvisional:'privremeno',
    quarantineHelp:'Automatska karantena traje najdulje 14 dana; ako u tom roku ne odlučite, izračun je sam ukida. Osoba ne vidi obavijest.',
    quarantineEmpty:'Nitko nije u karanteni.', quarantineLine:'{who} · {days} d · signali: {flags}', release:'Vrati u rad', keep:'Zadrži', block:'Blokiraj',
    decisionDone:'Odluka je zapisana.',
    goldFile:'Datoteka sa zlatnim primjerima (JSONL)', goldRetireFile:'Datoteka s oznakama primjera za povlačenje (jedna po retku)', goldRetireButton:'Povuci sve s popisa', anyCorpus:'svi korpusi', badIds:'Svaki redak datoteke mora biti oznaka primjera (UUID).', goldRetired:'Povučeno {retired}; već povučeno {already}; izvan uporabe {inactive}; nepoznato {unknown}.', goldImportButton:'Uvezi zlatne primjere', goldPool:'Skup', all:'svi',
    poolQualification:'provjera znanja', poolAudit:'skrivene provjere', goldImported:'Prihvaćeno {accepted}; izdvojeno za kalibraciju {held}; nepromijenjeno {same}.',
    goldPools:'Aktivni skupovi: {pools}', retire:'Povuci', reactivate:'Vrati', retract:'Poništi', disclose:'Označi kao otkriven',
    goldDone:'Promjena je zapisana.', noItems:'Nema primjera.',
    adjudicate:'Presudi', markAmbiguous:'Dvosmisleno', reopen:'Ponovno otvori', discard:'odbaci ranije glasove', votesLine:'Glasovi: {votes}',
    trustedEmail:'Adresa e-pošte', trustedLabel:'Bilješka (najviše ime)', trustedAdd:'Dodaj na popis', trustedRemove:'Ukloni',
    trustedAdded:'Adresa je dodana.', trustedLine:'{label} · {email}{who}', trustedAnchor:' · stručnjak {id}', noTrusted:'Popis je prazan.',
    runNow:'Pokreni izračun', runDone:'Izračun je završen ({status}).', calibrationTitle:'Kalibracija', runsTitle:'Izračuni',
    calibrationLine:'{cell}: {correct}/{n} točno, Wilsonova granica {lb}; {state}{pending}', passed:'prošla', notPassed:'nije prošla',
    pendingRefs:'; čeka {n} referentnih odgovora', redraw:'Novo izvlačenje', redrawDone:'Novo izvlačenje zatraženo.',
    pin:'Prikvači', unpin:'Otkvači', bundle:'Paket za ponavljanje', stale:' · zastario', pinned:' · prikvačen',
    iaaTitle:'Slaganje (Krippendorffova alfa)', iaaLine:'{kind}: alfa {alpha}, opaženo slaganje {observed}', paramsTitle:'Parametri',
    paramsJson:'Parametri (JSON)', paramsSave:'Spremi parametre', paramsSaved:'Parametri su spremljeni.',
    annotatorsExport:'Suradnici (JSONL)', exportResolved:'Razriješeno (TSV)', exportRunExport:'Izračun za izdanje (JSONL)', recordRelease:'Zabilježi izdanje',
    releaseRecorded:'Izdanje je zabilježeno; otkriveno zlatnih primjera: {n}.',
    exportedRestricted:'Preuzeto. Datoteka sadrži pseudonimizirane podatke: čuvajte je samo lokalno, izbrišite je najkasnije za 30 dana i odmah kada se dovrši brisanje osobe čiji su odgovori u njoj.',
  },
  en: {
    skipLink:'Skip to content', brand:'Croatian stems', title:'Labeling language examples', menu:'Menu',
    navLabel:'Labeling', navMe:'My data', navCurator:'Curator', logout:'Sign out', login:'Sign in', loginGoogle:'Sign in with Google',
    paused:'Collection of answers is paused for now. You can browse, but answers are not being saved.',
    landingTitle:'Help build an open dataset for the Croatian language',
    landingIntro:'On this site volunteers judge whether two words share a lemma, confirm dictionary lemmas and judge word stems. The answers are used to evaluate an open Croatian stemmer and are published as an open dataset, without your name.',
    landingRunBy:'The project is run by', landingAge:'You must be at least 18 to take part. We will ask for your consent before your first answer.',
    signInPrompt:'Sign in to take part.',
    gateTitle:'Before you start',
    gateWhat:'We store your answers, the time you take to answer and the email address of your Google account. Answers are linked to a random identifier, not to your name. We publish only aggregated labels for each item, never your individual answers.',
    gateRights:'You can download your data or erase your profile at any time on the "My data" page.',
    gatePrivacy:'How we process your data is explained in the', privacyNotice:'privacy notice', gateTerms:'I accept the', termsLink:'terms of participation',
    gateTermsLicence:', including the licence of my answers.', gateParticipation:'I agree that my answers are recorded and used as described in the',
    participationLink:'participation statement', gateAge:'I am at least 18 years old.', accept:'I accept', gateErase:'Erase account',
    gateMessage:'To take part, accept the terms and the participation statement and confirm your age.', version:'(version {v})',
    erasedTitle:'Profile erased',
    erasedDone:'Your profile has been erased. We will delete your sign-in account within 30 days; if you sign in again before then, you will see this notice instead of a new profile. Your answers remain in the dataset under a new random identifier that can be linked neither to you nor to your previous identifier.',
    erasurePending:'This account is being erased. The sign-in account will be deleted within 30 days of the request; after that you can sign in again as a new participant.',
    erasureExpired:'This profile was erased because the terms and the participation statement were not accepted within 30 days of the first sign-in. The sign-in account will be deleted within 30 days; after that you can sign in again as a new participant.',
    corpus:'Corpus', chooseCorpusOption:'Choose a corpus', kind:'Kind', kindPair:'Word pair', kindLemma:'Lemma', kindStem:'Stem',
    queue:'Queue', queueNext:'New items', queueLabelled:'My labelled', queueUnsure:'My unsure',
    hintsTitle:'Corpus suggestions', lemmaLabel:'Confirmed or corrected lemma', stemLabel:'Proposed stem:',
    irregular:'Irregular form / exception', retry:'Retry saving the same answer', skip:'Skip', guidelines:'Labeling guidelines',
    pairs:'Pairs', lemmas:'Lemmas', stems:'Stems', progressLine:'{kind}: {definite} confirmed, {unsure} unsure / {total} items',
    promptPair:'Do these words share a lemma?', promptLemma:'What is the dictionary lemma of this word?', promptStem:'Is the proposed stem acceptable?',
    revision:'Revision {n}; your saved answer: {answer}.', noLabel:'You have not labelled this item yet.',
    sampling:'Sampling: ', licence:'Licence: ', corpusLemma:'Corpus lemma: ', source:'Source: ',
    same:'Same lemma', different:'Different lemmas', unsure:'Not sure', confirmed:'Confirm lemma', accept_:'Accept stem', reject:'Reject stem',
    chooseAnswer:'Choose an answer (keys 1–3). You can check the suggestions in the details.',
    chooseCorpus:'Choose a corpus.', noCorpora:'There are no published corpora at the moment.',
    emptyNext:'There are no new items of this kind for you right now. Skipped items come back after 30 minutes.',
    emptyQueue:'There are no more items in this queue.', saved:'Answer saved.',
    typeLemma:'Type the lemma before confirming.', retryFirst:'Retry the previous save first, or reload the page.',
    conflict:'This answer was changed in another session meanwhile. The latest answer has been loaded; review it before saving again.',
    meTitle:'My data', meId:'Your random identifier:', meConsents:'Accepted documents', meCounts:'Answers in total: {judgments}; items labelled: {items}.',
    consentLine:'{doc}, version {version}, accepted {date}', docPrivacy:'Privacy notice', docTerms:'Terms of participation', docParticipation:'Participation statement',
    noConsents:'You have not accepted the documents yet.', download:'Download my data', downloaded:'Your data has been downloaded (JSON).',
    eraseTitle:'Erase my account',
    eraseWhat:'Erasing immediately removes the link to your sign-in account, your email address, answer times and the list of items shown to you. We keep the identifier of the sign-in account only until we delete that account (with your first and last name), at most 30 days.',
    eraseKeeps:'Your answers remain in the dataset under a new random identifier that can be linked neither to you nor to your previous identifier; of each answer\'s time only the day is kept. If the profile is blocked or set aside, the answers are deleted.',
    erasePrompt:'To confirm, type {word}', eraseWord:'DELETE', eraseButton:'Erase my account', eraseMismatch:'To erase, type exactly {word}.',
    curatorTitle:'Curator', intakeTitle:'Collecting answers', intakeOn:'Answers are being collected.', intakeOff:'Collection of answers is paused.',
    intakeReadOnly:' The server is in read-only mode (LABELING_READ_ONLY).', pause:'Pause collecting answers', resume:'Resume collecting answers',
    importTitle:'Import corpus candidates', importIntro:'Upload a prepared JSONL file. A new corpus is a draft until you publish it. Importing never changes existing answers.',
    importName:'Corpus name', importFile:'Candidate file', importSelect:'Choose file', importButton:'Import candidates',
    importLimits:'At most 20,000 items and 32 MiB per import.', noFile:'No file chosen.', badJson:'The file contains invalid JSON.',
    importCount:'An import must contain 1 to 20,000 candidates.', imported:'Imported {added} new candidates; {present} already present.',
    corporaTitle:'Corpora', colName:'Name', colStatus:'Status', colLicence:'Source / labels licence', colItems:'Items', colActions:'Actions',
    statusDraft:'draft', statusPublished:'published', statusArchived:'archived', publish:'Publish', unpublish:'Unpublish', archive:'Archive',
    exportTsv:'Export TSV', exportJsonl:'Export JSONL', labelsLicence:'Labels licence', published:'The corpus is published.', exported:'Export downloaded.',
    itemsLine:'pairs {pair}, lemmas {lemma}, stems {stem}',
    annotatorsTitle:'Annotators', colAnnotator:'Identifier / email', colJudgments:'Answers', colSeen:'Last seen', more:'Load more',
    statusActive:'active', statusQuarantined:'set aside', statusBlocked:'blocked', statusErased:'erased', reason:'Reason', apply:'Apply',
    reasonRequired:'Type a reason for the status change.', statusChanged:'Status changed.',
    erasuresTitle:'Erasure requests', erasuresHelp:'Find the user by ID in the Keycloak admin console and delete it, then confirm here. The limit is 30 days from the request.',
    noErasures:'No requests are waiting.', erasureLine:'Keycloak ID {user} · requested {date} ({days} d)', erasureExpiredReason:' · not accepted within 30 days', confirmErasure:'Confirm deletion in Keycloak',
    erasureCompleted:'Deletion confirmed.',
    footerPrivacy:'Privacy', footerTerms:'Terms and licence', footerParticipation:'Participation', footerStorage:'Cookies and storage', legalMenu:'Legal information',
    footerVersion:'Application version {v}', unavailable:'Sign-in is unavailable right now. Reload the page and try again.',
    genericError:'The request failed. Please try again.', actionFailed:'The action failed. Please try again.',
    anyCorpus:'Any corpus', expertWork:'Expert work', qualification:'Knowledge check {done}/{of}',
    qualificationHelp:'The first {of} items of this kind check your knowledge and are shown without a suggestion. You will see the result under "Reliability".',
    corpusLocked:'You can choose a corpus once you pass the knowledge check for this kind. Until then you get items from any corpus.',
    blindNote:'This item is shown without the corpus suggestion.', footerTrust:'Reliability',
    trustTitle:'Reliability', trustHow:'How reliability works', trustNone:'Reliability has not been computed yet.',
    trustLine:'{kind}: level {tier}, estimate {band}; known-answer checks about {checks}{agreement}.',
    trustAgreement:'; agreement with resolved items about {value} %', trustQualified:' (knowledge check passed)',
    trustBlocked:'Your profile is blocked. Reason: {reason}', trustAnchor:'You are on the list of trusted experts.',
    trustRunAt:'Computed {date}.',
    tier_new:'new', tier_qualified:'qualified', tier_established:'established', tier_anchor:'expert', tier_quarantined:'set aside',
    band_visoka:'high', band_dobra:'good', band_treba_paznje:'needs attention', band_nedovoljno_podataka:'not enough data',
    tabOverview:'Overview', tabPeople:'Contributors', tabQuarantine:'Quarantine', tabGold:'Gold items', tabDisputes:'Disputed items',
    tabTrusted:'Trusted addresses', tabScoring:'Scoring',
    scoringTitle:'Reliability scoring', scoringOn:'Scoring is on; a run starts every {minutes} min.',
    scoringOff:'Scoring is off: nobody is profiled.', scoringEnable:'Turn scoring on', scoringDisable:'Turn scoring off',
    lastRun:'Last run: {date} ({status}).', noRun:'No run yet.', alertsTitle:'Alerts', noAlerts:'No alerts.',
    readinessTitle:'Readiness per kind', readinessLine:'{kind}: knowledge check {q}, hidden checks {a}, promotion {p}; pools {pools}',
    yes:'yes', no:'no', statesTitle:'Item states', colStates:'States', colTiers:'Levels', colItem:'Item', colAnswer:'Answer',
    colRun:'Run', colCounts:'Answers / items / people', anchorBadge:'expert',
    state_open:'open', state_reserve:'checks in reserve', state_provisional:'provisional', state_resolved:'resolved', state_needs_expert:'needs an expert',
    state_contested:'contested', state_ambiguous:'ambiguous', stateContested:'contested', stateNeedsExpert:'needs an expert', stateProvisional:'provisional',
    quarantineHelp:'An automatic quarantine lasts at most 14 days; if you do not decide by then, the run lifts it. The person sees no notice.',
    quarantineEmpty:'Nobody is in quarantine.', quarantineLine:'{who} · {days} d · signals: {flags}', release:'Release', keep:'Keep', block:'Block',
    decisionDone:'The decision is recorded.',
    goldFile:'Gold items file (JSONL)', goldRetireFile:'File of item ids to retire (one per line)', goldRetireButton:'Retire everything listed', anyCorpus:'any corpus', badIds:'Every line of the file must be an item id (UUID).', goldRetired:'Retired {retired}; already retired {already}; out of use {inactive}; unknown {unknown}.', goldImportButton:'Import gold items', goldPool:'Pool', all:'all',
    poolQualification:'knowledge check', poolAudit:'hidden checks', goldImported:'Accepted {accepted}; held out for calibration {held}; unchanged {same}.',
    goldPools:'Active pools: {pools}', retire:'Retire', reactivate:'Reactivate', retract:'Retract', disclose:'Mark disclosed',
    goldDone:'The change is recorded.', noItems:'No items.',
    adjudicate:'Adjudicate', markAmbiguous:'Ambiguous', reopen:'Reopen', discard:'discard earlier votes', votesLine:'Votes: {votes}',
    trustedEmail:'Email address', trustedLabel:'Note (a first name at most)', trustedAdd:'Add to the list', trustedRemove:'Remove',
    trustedAdded:'The address is added.', trustedLine:'{label} · {email}{who}', trustedAnchor:' · expert {id}', noTrusted:'The list is empty.',
    runNow:'Run now', runDone:'The run finished ({status}).', calibrationTitle:'Calibration', runsTitle:'Runs',
    calibrationLine:'{cell}: {correct}/{n} correct, Wilson bound {lb}; {state}{pending}', passed:'passed', notPassed:'not passed',
    pendingRefs:'; waiting for {n} reference answers', redraw:'Draw again', redrawDone:'A new draw is requested.',
    pin:'Pin', unpin:'Unpin', bundle:'Replay bundle', stale:' · stale', pinned:' · pinned',
    iaaTitle:'Agreement (Krippendorff’s alpha)', iaaLine:'{kind}: alpha {alpha}, observed agreement {observed}', paramsTitle:'Parameters',
    paramsJson:'Parameters (JSON)', paramsSave:'Save parameters', paramsSaved:'The parameters are saved.',
    annotatorsExport:'Contributors (JSONL)', exportResolved:'Resolved (TSV)', exportRunExport:'Run export for a release (JSONL)', recordRelease:'Record the release',
    releaseRecorded:'The release is recorded; gold items disclosed: {n}.',
    exportedRestricted:'Downloaded. The file holds pseudonymous data: keep it local only, delete it within 30 days and at once when the erasure of a person whose answers it holds is completed.',
  },
};
const errors = {
  hr: {invalid_token:'Prijava je istekla. Ponovno se prijavite.', annotator_role_required:'Nemate ovlast za označavanje.', identity_unavailable:'Provjera prijave trenutačno nije dostupna.',
    invalid_candidates:'Datoteka ne odgovara formatu prijedloga za uvoz.', body_too_large:'Datoteka ili zahtjev prelazi dopuštenu veličinu.', corpus_provenance_conflict:'Podrijetlo korpusa razlikuje se od već uvezenog korpusa.',
    immutable_item_conflict:'Postojeći primjer ima drukčiji sadržaj. Uvoz je odbijen.', invalid_judgment:'Odgovor ne odgovara ovom primjeru. Provjerite lemu: jedna riječ, samo slova.', request_id_conflict:'Ovaj pokušaj spremanja već je upotrijebljen za drugi odgovor.',
    not_found:'Primjer ili korpus nije dostupan.', database_unavailable:'Baza podataka trenutačno nije dostupna.', consent_required:'Prije sudjelovanja prihvatite trenutačne verzije uvjeta i izjave o sudjelovanju.',
    consent_version_mismatch:'Dokumenti su u međuvremenu ažurirani. Osvježite stranicu i pročitajte nove verzije.', account_blocked:'Vaš profil je blokiran. Svoje podatke i dalje možete preuzeti ili izbrisati na stranici „Moji podaci”.',
    erasure_pending:'Ovaj račun je u postupku brisanja.', judgments_paused:'Primanje odgovora je privremeno zaustavljeno. Pokušajte kasnije.', rate_limited:'Previše zahtjeva u kratkom vremenu. Pričekajte trenutak pa pokušajte ponovno.',
    daily_cap_reached:'Dosegnut je dnevni broj odgovora. Hvala! Nastavite sutra.', curator_required:'Za ovu radnju potrebna je uloga kuratora.', item_retired:'Ovaj primjer je povučen i više se ne označava.',
    license_not_publishable:'Licencija izvornog korpusa ne dopušta objavu oznaka pod odabranom licencijom.', corpus_not_published:'Korpus nije objavljen.', corpus_already_published:'Korpus je već objavljen pod drugom licencijom oznaka.',
    invalid_corpus_status:'Ta promjena statusa korpusa nije moguća.', own_status_change:'Ne možete mijenjati status vlastitog profila.', annotator_erased:'Profil je izbrisan; status se više ne može mijenjati.',
    erasure_not_pending:'Brisanje je već potvrđeno.', gold_conflict:'Primjer već ima drukčiji zlatni odgovor. Uvoz je odbijen.',
    unknown_item:'Primjer ne postoji u pohranjenom korpusu.', invalid_gold:'Redak ne odgovara formatu zlatnih primjera.', invalid_release:'Popis primjera izdanja nije ispravan.', already_trusted:'Adresa je već na popisu.',
    invalid_email:'Upišite ispravnu adresu e-pošte.', scoring_busy:'Izračun je već u tijeku. Pokušajte za koji trenutak.', params_invalid:'Parametri nisu ispravni.',
    not_assigned:'Ovaj primjer Vam nije dodijeljen. Učitajte sljedeći primjer.', run_stale:'Nakon izračuna je bilo moderacije; pokrenite novi izračun.',
    run_not_done:'Izračun nije završen.', not_adjudicable:'Presuditi se može samo spornom, privremenom ili primjeru koji traži stručnjaka.',
    gold_disclosed:'Odgovor ovog primjera je otkriven; ne može se ponovno koristiti za provjere.', calibration_item:'Primjer je u kalibracijskom uzorku i ne može biti zlatni.', several_corpora:'Oznake pripadaju različitim korpusima. Odaberite korpus.', reserve_item:'Primjer iz pričuve zlatnih provjera nikad se ne objavljuje.',
    corpus_choice_locked:'Korpus ćete moći odabrati kad položite provjeru znanja. Do tada odaberite „Bilo koji korpus”.'},
  en: {invalid_token:'Your sign-in has expired. Please sign in again.', annotator_role_required:'You are not allowed to label.', identity_unavailable:'Sign-in verification is unavailable right now.',
    invalid_candidates:'The file does not match the candidate import format.', body_too_large:'The file or request is too large.', corpus_provenance_conflict:'The corpus provenance differs from the corpus already imported.',
    immutable_item_conflict:'An existing item has different content. The import was refused.', invalid_judgment:'The answer does not fit this item. Check the lemma: one word, letters only.', request_id_conflict:'This save attempt was already used for a different answer.',
    not_found:'The item or corpus is not available.', database_unavailable:'The database is unavailable right now.', consent_required:'Before taking part, accept the current terms and participation statement.',
    consent_version_mismatch:'The documents have been updated meanwhile. Reload the page and read the new versions.', account_blocked:'Your profile is blocked. You can still download or erase your data on the "My data" page.',
    erasure_pending:'This account is being erased.', judgments_paused:'Collection of answers is paused. Please try later.', rate_limited:'Too many requests in a short time. Wait a moment and try again.',
    daily_cap_reached:'You have reached the daily number of answers. Thank you! Continue tomorrow.', curator_required:'This action needs the curator role.', item_retired:'This item has been retired and is no longer labelled.',
    license_not_publishable:'The source corpus licence does not allow publishing labels under the chosen licence.', corpus_not_published:'The corpus is not published.', corpus_already_published:'The corpus is already published under a different labels licence.',
    invalid_corpus_status:'That corpus status change is not possible.', own_status_change:'You cannot change the status of your own profile.', annotator_erased:'The profile is erased; its status can no longer change.',
    erasure_not_pending:'The deletion has already been confirmed.', gold_conflict:'The item already has a different gold answer. The import was refused.',
    unknown_item:'The item does not exist in the stored corpus.', invalid_gold:'A line does not match the gold item format.', invalid_release:'The release item list is not valid.', already_trusted:'The address is already on the list.',
    invalid_email:'Type a valid email address.', scoring_busy:'A run is already in progress. Try again in a moment.', params_invalid:'The parameters are not valid.',
    not_assigned:'This item was not served to you. Load the next item.', run_stale:'There was moderation after this run; start a new run.',
    run_not_done:'The run has not finished.', not_adjudicable:'Only a contested, provisional or needs-expert item can be adjudicated.',
    gold_disclosed:'This item\'s answer has been disclosed; it cannot be used for checks again.', calibration_item:'The item is in the calibration sample and cannot be gold.', several_corpora:'The ids belong to several corpora. Choose a corpus.', reserve_item:'An item from the known-answer reserve is never released.',
    corpus_choice_locked:'You can choose a corpus once you pass the knowledge check. Until then, choose "Any corpus".'},
};
const LABEL_LICENCES = ['CC BY-SA 4.0', 'CC BY 4.0', 'CC0 1.0'];
const CHOICES = {pair:['same','different','unsure'], lemma:['confirmed','unsure'], stem:['accept','reject','unsure']};

class UserError extends Error {}
const $ = id => document.getElementById(id);
let lang = initialLanguage();
let config = null, keycloak = null, me = null;
let current = null, cursor = '', pending = null, busy = false, generation = 0, shownAt = 0, lastProgress = null;
let annotatorOffset = 0, trustCard = null, qualifying = null, curatorTab = 'overview';
const ANY = '*';

// Croatian unless the address asks for English (?lang=en); the language switch keeps the address in step.
function initialLanguage(){
  return new URLSearchParams(location.search).get('lang') === 'en' ? 'en' : 'hr';
}
function rememberLanguage(){
  const url = new URL(location.href);
  if (lang === 'en') url.searchParams.set('lang', 'en'); else url.searchParams.delete('lang');
  history.replaceState(history.state, '', url);
}
// A tab-scoped flag (no token) so a reload asks Keycloak for the existing session instead of signing out.
// It is the only thing this page stores; storage.*.html and the browser test list it.
const SIGNED_IN = 'labeling-signed-in';
function signedInFlag(value){
  try {
    if (value === undefined) return sessionStorage.getItem(SIGNED_IN) === '1';
    if (value) sessionStorage.setItem(SIGNED_IN, '1'); else sessionStorage.removeItem(SIGNED_IN);
  } catch {}
  return false;
}
function t(key, values = {}){
  return (strings[lang][key] ?? strings.hr[key] ?? key).replace(/\{(\w+)\}/g, (_, name) => String(values[name] ?? ''));
}
function errorText(error){
  if (error instanceof UserError && error.code) return errors[lang][error.code] || t('genericError');
  return error instanceof UserError ? error.message : t('actionFailed');
}
function message(text, error = false){ $('message').textContent = text; $('message').dataset.error = String(error); }
function element(tag, text, attributes = {}){
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  return node;
}
function button(text, onclick, attributes = {}){ const node = element('button', text, {type:'button', ...attributes}); node.onclick = onclick; return node; }
function date(value){ return value ? new Date(value).toLocaleString(lang === 'hr' ? 'hr-HR' : 'en-GB') : '—'; }

function applyLanguage(){
  document.documentElement.lang = lang;
  for (const node of document.querySelectorAll('[data-i18n]')) node.textContent = t(node.dataset.i18n);
  for (const node of document.querySelectorAll('[data-i18n-aria]')) node.setAttribute('aria-label', t(node.dataset.i18nAria));
  for (const node of document.querySelectorAll('a[data-doc]')) node.href = `/legal/${node.dataset.doc}.${lang}`;
  for (const node of document.querySelectorAll('a[data-guidelines]')) node.href = `/static/guidelines.${lang}.html`;
  $('language').textContent = lang === 'hr' ? 'English' : 'Hrvatski';
  $('language').lang = lang === 'hr' ? 'en' : 'hr';
  $('login').textContent = config?.idpHint === 'google' ? t('loginGoogle') : t('login');
  $('footer-version').textContent = t('footerVersion', {v: clientVersion});
  if (config) for (const node of document.querySelectorAll('[data-version]')) node.textContent = t('version', {v: config.legal[node.dataset.version]});
  $('erase-prompt').textContent = t('erasePrompt', {word: t('eraseWord')});
  const first = $('corpus').options[0];
  if (first && !first.value) first.textContent = t('chooseCorpusOption');
  if (!$('file').files[0]) $('file-name').textContent = t('noFile');
  if (current) paint();
  if (lastProgress) paintProgress();
  paintQualification();
  if (me && !$('me').hidden) paintMe();
}

const SECTIONS = ['landing', 'gate', 'erased', 'workspace', 'me', 'curator'];
// The privacy notice is information (linked above these); each consent has its own unticked box.
const GATE = ['accept-terms', 'accept-participation', 'accept-age'];
function show(section){ for (const id of SECTIONS) $(id).hidden = id !== section; }
function lock(value){
  busy = value;
  for (const node of document.querySelectorAll('main button, main select, main input, header nav button:not(#language)')) {
    const blockedByPending = !!pending && !!node.closest('#workspace') && node.id !== 'retry';
    node.disabled = value || blockedByPending || node.dataset.off === '1';
  }
  if (!value) gateReady();
}
async function run(action){
  if (busy) return;
  lock(true);
  try { await action(); } catch (error) { message(errorText(error), true); } finally { lock(false); }
}
async function api(path, options = {}){
  try { await keycloak.updateToken(30); } catch { throw Object.assign(new UserError(), {code:'invalid_token'}); }
  const response = await fetch('/api/' + path, {...options, headers:{Authorization:'Bearer ' + keycloak.token, ...options.headers}});
  if (!response.ok) {
    let data = {};
    try { data = await response.json(); } catch {}
    throw Object.assign(new UserError(t('genericError')), {code:data.detail?.code, status:response.status, detail:data.detail});
  }
  return response;
}
const json = async (path, options) => (await api(path, options)).json();
const post = (path, body, method = 'POST') => json(path, {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
async function download(path, filename){
  const response = await api(path), url = URL.createObjectURL(await response.blob()), link = element('a', null, {href:url, download:filename});
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

// ---- account, gate, erasure -------------------------------------------------

async function loadMe(){
  try { me = await json('me'); }
  catch (error) {
    if (error.code === 'erasure_pending') { showErased(t(error.detail?.reason === 'unconsented_expiry' ? 'erasureExpired' : 'erasurePending')); return; }
    throw error;
  }
  for (const id of ['nav-label', 'nav-me', 'logout']) $(id).hidden = false;
  $('nav-curator').hidden = !me.curator;
  $('expert-field').hidden = !me.anchor;
  if (!me.consented) { show('gate'); message(t('gateMessage')); return; }
  await openWorkspace();
}
function gateReady(){
  const ready = GATE.every(id => $(id).checked);
  $('accept').disabled = busy || !ready;
}
function showErased(text){
  me = null; current = null;
  for (const id of ['nav-label', 'nav-me', 'nav-curator']) $(id).hidden = true;
  $('logout').hidden = false;
  show('erased');
  $('erased-text').textContent = text;
  message(text);
}
async function openMe(){
  show('me');
  me = await json('me');
  trustCard = await json('me/trust?lang=' + lang);
  paintMe();
  message(t('meTitle'));
}
function paintMe(){
  $('me-id').textContent = me.annotator_id;
  $('me-counts').textContent = t('meCounts', {judgments: me.counts.judgments, items: me.counts.items_labelled});
  const docs = {privacy: t('docPrivacy'), terms: t('docTerms'), participation: t('docParticipation')};
  $('me-consents').replaceChildren(...(me.consents.length ? me.consents.map(c => element('li', t('consentLine', {doc: docs[c.document], version: c.version, date: date(c.accepted_at)})))
                                                         : [element('li', t('noConsents'))]));
  paintTrust();
}
// The reliability card: a band and rounded counts; the complete data are in the download.
function paintTrust(){
  const card = trustCard, lines = [];
  if (!card) { $('trust').replaceChildren(); return; }
  if (card.status === 'blocked') lines.push(element('p', t('trustBlocked', {reason: card.status_reason || '—'})));
  if (card.anchor) lines.push(element('p', t('trustAnchor')));
  if (!card.run) lines.push(element('p', t('trustNone')));
  else {
    lines.push(element('p', t('trustRunAt', {date: date(card.run_at)}), {class:'muted'}));
    const names = {pair: t('pairs'), lemma: t('lemmas'), stem: t('stems')};
    const list = element('ul');
    for (const [kind, k] of Object.entries(card.kinds || {})) {
      const agreement = k.agreement_approx === null ? '' : t('trustAgreement', {value: Math.round(k.agreement_approx * 100)});
      list.append(element('li', t('trustLine', {kind: names[kind], tier: t('tier_' + k.tier), band: t('band_' + k.band),
                                                 checks: k.checks_approx, agreement}) + (k.qualified ? t('trustQualified') : '')));
    }
    lines.push(list);
  }
  $('trust').replaceChildren(...lines);
}

// ---- labeling ------------------------------------------------------------------

async function openWorkspace(){
  show('workspace');
  await loadCorpora($('corpus').value);
}
async function allCorpora(){
  const rows = [];
  let offset = 0;
  do { const page = await json('corpora?offset=' + offset); rows.push(...page.items); offset = page.next_offset; } while (offset !== null);
  return rows;
}
async function loadCorpora(selected = ''){
  const rows = (await allCorpora()).filter(row => row.status === 'published');
  const locked = Object.values(me?.corpus_choice || {}).includes('locked');
  const any = rows.length > 1 || (rows.length && locked) ? [new Option(t('anyCorpus'), ANY)] : [];
  $('corpus').replaceChildren(new Option(t('chooseCorpusOption'), ''), ...any, ...rows.map(row => new Option(row.name, row.id)));
  // "Any corpus" is the default once there is more than one (the least-resolved one is served first).
  $('corpus').value = rows.some(row => row.id === selected) ? selected : rows.length === 1 ? rows[0].id : any.length ? ANY : '';
  if (!rows.length) { message(t('noCorpora')); }
  paintCorpusLock();
  await chooseCorpus();
}
// Below the qualified level, while a kind's knowledge check runs, new work comes from "any corpus"
// (the server refuses a chosen one); the person's own items stay reachable by corpus.
function corpusLocked(){ return $('queue').value === 'next' && me?.corpus_choice?.[$('kind').value] === 'locked'; }
function paintCorpusLock(){
  const locked = corpusLocked() && [...$('corpus').options].some(option => option.value === ANY);
  if (locked) $('corpus').value = ANY;
  $('corpus').dataset.off = locked ? '1' : '';
  $('corpus').disabled = busy || locked;
  $('corpus-lock').hidden = !locked;
}
function resetQuestion(){
  generation++; cursor = ''; current = null; pending = null; lastProgress = null; qualifying = null; paintQualification();
  $('retry').hidden = true; $('question').hidden = true; $('skip').hidden = true; $('empty').hidden = true;
  $('progress').replaceChildren();
}
async function chooseCorpus(){
  resetQuestion();
  if (!$('corpus').value) { if ($('corpus').options.length > 1) message(t('chooseCorpus')); return; }
  await progress();
  await load();
}
async function progress(){
  if (!$('corpus').value || $('corpus').value === ANY) { $('progress').replaceChildren(); return; }
  lastProgress = await json(`corpora/${$('corpus').value}/progress`);
  paintProgress();
}
function paintProgress(){
  const names = {pair: t('pairs'), lemma: t('lemmas'), stem: t('stems')};
  $('progress').replaceChildren(...Object.entries(lastProgress.kinds).map(([kind, count]) =>
    element('p', t('progressLine', {kind: names[kind], definite: count.definite, unsure: count.unsure, total: count.total}))));
}
async function load(){
  const seq = ++generation, corpus = $('corpus').value, kind = $('kind').value, queue = $('queue').value;
  const expert = $('expert-field').hidden || $('expert').checked;
  let item, served = null;
  if (queue === 'next') {
    try { served = await json(corpus === ANY ? `next?kind=${kind}&expert=${expert}` : `corpora/${corpus}/next?kind=${kind}&expert=${expert}`); }
    catch (error) {
      // The level changed since the page loaded: refresh it and follow the lock.
      if (error.code !== 'corpus_choice_locked' || corpusLocked()) throw error;
      me = await json('me');
      if (!corpusLocked()) throw error;
      return loadCorpora(corpus);
    }
    item = served.item;
  } else if (corpus === ANY) { message(t('chooseCorpus')); return; }
  else item = (await json(`corpora/${corpus}/items?kind=${kind}&state=${queue}&after=${encodeURIComponent(cursor)}`)).items[0] || null;
  if (seq !== generation) return;
  current = item; pending = null; qualifying = served ? served.qualification : null;
  paintQualification();
  $('retry').hidden = true; $('question').hidden = !current; $('skip').hidden = !current; $('empty').hidden = !!current;
  if (current) {
    if (queue !== 'next') cursor = current.cursor;
    render();
    message(t('chooseAnswer'));
  } else {
    $('empty').textContent = queue === 'next' ? t('emptyNext') : t('emptyQueue');
    message($('empty').textContent);
  }
}
function answerText(answer){ return t(answer === 'accept' ? 'accept_' : answer); }
function paintQualification(){
  // Announced: the first items of a kind check the person's knowledge (shown without a suggestion).
  $('qualification').hidden = !qualifying;
  if (qualifying) $('qualification').textContent = t('qualification', {done: qualifying.done, of: qualifying.of}) + ' ' + t('qualificationHelp', {of: qualifying.of});
}
function render(){
  const c = current.candidate, j = current.judgment;
  shownAt = performance.now();
  paint();
  // A blind showing has no suggestion: the lemma field starts empty.
  $('lemma').value = j?.lemma || (current.presentation === 'blind' ? '' : c.proposed_lemma);
  $('irregular').checked = j?.irregular || false;
}
function paint(){
  const c = current.candidate, j = current.judgment;
  $('revision').textContent = j ? t('revision', {n: current.assignment.current_revision, answer: answerText(j.answer)}) : t('noLabel');
  $('prompt').textContent = t({pair:'promptPair', lemma:'promptLemma', stem:'promptStem'}[c.kind]);
  const blind = current.presentation === 'blind';
  const texts = {word:c.word, context:c.context, 'other-word':c.other_word, 'other-context':c.other_context,
                 stem:c.proposed_stem, license:t('licence') + c.license,
                 hints:blind ? '' : t('corpusLemma') + c.proposed_lemma + (c.other_proposed_lemma ? ' / ' + c.other_proposed_lemma : '')};
  for (const [id, value] of Object.entries(texts)) $(id).textContent = value;
  $('blind').hidden = !blind; $('hints').hidden = blind;
  $('second').hidden = c.kind !== 'pair'; $('lemma-field').hidden = c.kind !== 'lemma'; $('stem-field').hidden = c.kind !== 'stem';
  $('source').replaceChildren(document.createTextNode(t('source')));
  let url;
  try { url = new URL(c.source_uri); } catch {}
  if (url && ['https:', 'http:'].includes(url.protocol)) $('source').append(element('a', c.source_uri, {href:url.href, target:'_blank', rel:'noopener noreferrer'}));
  else $('source').append(document.createTextNode(c.source_uri));
  $('choices').replaceChildren(...CHOICES[c.kind].map((answer, index) => {
    const node = button(answerText(answer), () => run(() => save(answer)), {'aria-keyshortcuts': String(index + 1)});
    node.prepend(element('kbd', String(index + 1), {'aria-hidden':'true'}));
    return node;
  }));
}
async function save(answer){
  if (pending) { message(t('retryFirst'), true); return; }
  const lemma = current.candidate.kind === 'lemma' && answer === 'confirmed' ? $('lemma').value.trim() : '';
  if (answer === 'confirmed' && !lemma) { message(t('typeLemma'), true); return; }
  const elapsed = Math.round(performance.now() - shownAt);
  pending = {path:`corpora/${current.candidate.corpus_id}/items/${current.candidate.item_id}/answer`,
             body:{request_id:crypto.randomUUID(), base_revision:current.assignment.current_revision, answer, lemma,
                   irregular:$('irregular').checked, client_version:clientVersion,
                   elapsed_ms:elapsed >= 0 && elapsed <= 3600000 ? elapsed : null}};
  await submitPending();
}
async function submitPending(){
  try { await post(pending.path, pending.body); }
  catch (error) {
    if (error.code === 'revision_conflict') {
      const path = pending.path.replace(/\/answer$/, '');
      pending = null; $('retry').hidden = true;
      current = await json(path); render(); await progress();
      message(t('conflict'), true);
      return;
    }
    // A field the server's schema refuses (e.g. a lemma that is not one word) is a 422 without a code.
    if (error.status === 422 && !error.code) error.code = 'invalid_judgment';
    if (error.code === 'judgments_paused') $('paused').hidden = false;
    // Keep the same request id for a retry when the outcome is unknown or temporary.
    const retryable = !error.status || error.status >= 500 || error.status === 429;
    if (retryable) $('retry').hidden = false; else { pending = null; $('retry').hidden = true; }
    throw error;
  }
  pending = null; $('retry').hidden = true;
  $('paused').hidden = true;
  await progress();
  await load();
}
document.addEventListener('keydown', event => {
  if (event.altKey || event.ctrlKey || event.metaKey || event.repeat || busy || !current || $('workspace').hidden) return;
  const target = event.target;
  if (target.isContentEditable || target.tagName === 'SELECT' || target.tagName === 'TEXTAREA' || (target.tagName === 'INPUT' && target.type !== 'checkbox')) return;
  const choice = /^[1-9]$/.test(event.key) ? $('choices').children[Number(event.key) - 1] : null;
  if (choice && !choice.disabled) { event.preventDefault(); choice.click(); }
});

// ---- curator ---------------------------------------------------------------------

const CURATOR_TABS = {
  overview: async () => { await curatorSettings(); await curatorOverview(); await curatorCorpora(); await curatorErasures(); },
  people: () => curatorAnnotators(true), quarantine: () => curatorQuarantine(), gold: () => curatorGold(),
  disputes: () => curatorDisputes(), trusted: () => curatorTrusted(), scoring: () => curatorScoring(),
};
async function openCurator(){
  show('curator');
  await showTab(curatorTab);
  message(t('curatorTitle'));
}
async function showTab(name){
  curatorTab = name;
  for (const node of document.querySelectorAll('#curator-tabs [role=tab]')) node.setAttribute('aria-selected', String(node.dataset.tab === name));
  for (const key of Object.keys(CURATOR_TABS)) $('tab-' + key).hidden = key !== name;
  await CURATOR_TABS[name]();
}
// A table cell that keeps its column name, so a table can collapse to cards on a phone.
function cell(label, ...content){
  const td = element('td', null, {'data-label': label});
  td.append(...content.map(c => typeof c === 'string' ? document.createTextNode(c) : c));
  return td;
}
function reasonInput(){ return element('input', null, {'aria-label': t('reason'), placeholder: t('reason'), maxlength:'500'}); }
function needReason(input){ const value = input.value.trim(); if (!value) throw new UserError(t('reasonRequired')); return value; }
function yesNo(value){ return value ? t('yes') : t('no'); }
async function curatorOverview(){
  const [data, alerts, settings] = await Promise.all([json('admin/overview'), json('admin/alerts'), json('admin/scoring/settings')]);
  $('scoring-state').textContent = data.scoring_enabled ? t('scoringOn', {minutes: Math.round(settings.interval_s / 60)}) : t('scoringOff');
  $('scoring-toggle').textContent = data.scoring_enabled ? t('scoringDisable') : t('scoringEnable');
  $('scoring-toggle').onclick = () => run(async () => {
    await post('admin/scoring/settings', {scoring_enabled: !data.scoring_enabled}, 'PUT'); await curatorOverview();
  });
  $('last-run').textContent = data.last_run ? t('lastRun', {date: date(data.last_run.finished_at), status: data.last_run.status}) : t('noRun');
  $('alerts').replaceChildren(...(alerts.items.length ? alerts.items.map(a => element('li', [a.code, a.kind, a.count ?? a.audit_pool, (a.missing || []).join(', ')]
                                                                                       .filter(v => v !== undefined && v !== null && v !== '').join(' · ')))
                                                       : [element('li', t('noAlerts'))]));
  const names = {pair: t('pairs'), lemma: t('lemmas'), stem: t('stems')};
  $('readiness').replaceChildren(...Object.entries(data.readiness).map(([kind, r]) => element('li', t('readinessLine', {
    kind: names[kind], q: yesNo(r.qualification), a: yesNo(r.audit), p: yesNo(r.promotion),
    pools: `${Object.values(r.pools.qualification).reduce((a, b) => a + b, 0)} / ${Object.values(r.pools.audit).reduce((a, b) => a + b, 0)}` +
           (r.pools.wrong_suggestion !== undefined && kind !== 'stem' ? ` / ${r.pools.wrong_suggestion}` : '')}))));
  const rows = [];
  for (const corpus of data.corpora) for (const [kind, states] of Object.entries(corpus.kinds)) {
    const tr = element('tr');
    tr.append(cell(t('colName'), corpus.name), cell(t('kind'), names[kind]),
              cell(t('colStates'), Object.entries(states).map(([state, n]) => `${t('state_' + state)} ${n}`).join(', ')));
    rows.push(tr);
  }
  $('states').replaceChildren(...rows);
}
async function curatorQuarantine(){
  const items = (await json('admin/annotators?quarantine=open')).items;
  $('quarantine').replaceChildren(...(items.length ? items.map(row => {
    const flags = Object.values(row.kinds).flatMap(k => k.flags);
    const li = element('li', t('quarantineLine', {who: row.email || row.id, days: row.quarantine_age_days ?? '—',
                                                  flags: [...new Set(flags)].join(', ') || '—'}), {'data-annotator': row.id});
    const details = element('pre', JSON.stringify(Object.fromEntries(Object.entries(row.kinds).map(([k, v]) => [k, {gold: v.gold, signals: v.signals}])), null, 1));
    const reason = reasonInput();
    const decide = to => () => run(async () => {
      await post(`admin/annotators/${row.id}/status`, {status: to, reason: needReason(reason)}, 'PUT');
      await curatorQuarantine(); message(t('decisionDone'));
    });
    li.append(details, reason, button(t('release'), decide('active')), button(t('keep'), decide('quarantined')),
              button(t('block'), decide('blocked'), {class:'danger'}));
    return li;
  }) : [element('li', t('quarantineEmpty'))]));
}
async function curatorGold(){
  const pool = $('gold-pool').value;
  const selected = $('gold-retire-corpus').value;
  $('gold-retire-corpus').replaceChildren(new Option(t('anyCorpus'), ''), ...(await allCorpora()).map(c => new Option(c.name, c.id)));
  $('gold-retire-corpus').value = selected;
  const data = await json('admin/gold' + (pool ? '?pool=' + pool : ''));
  $('gold-pools').textContent = t('goldPools', {pools: data.pools.filter(p => p.status === 'active')
    .map(p => `${p.kind}/${p.pool}${p.suggestion_agrees === false ? '*' : ''}: ${p.n}`).join(', ') || '—'});
  $('gold').replaceChildren(...(data.items.length ? data.items.map(g => {
    const tr = element('tr', null, {'data-gold': g.item_id});
    const reason = reasonInput();
    const act = action => () => run(async () => {
      await post(`admin/gold/${g.corpus_id}/${g.item_id}`, {action, reason: needReason(reason)}, 'PUT');
      await curatorGold(); message(t('goldDone'));
    });
    const actions = cell(t('colActions'), reason);
    for (const action of g.status === 'active' ? ['retire', 'retract', 'disclose'] : ['reactivate', 'retract'])
      actions.append(button(t(action), act(action)));
    tr.append(cell(t('colItem'), `${g.word || ''}${g.other_word ? ' / ' + g.other_word : ''}`),
              cell(t('kind'), g.kind), cell(t('goldPool'), t(g.pool === 'audit' ? 'poolAudit' : 'poolQualification')),
              cell(t('colAnswer'), g.answer + (g.lemma ? ' ' + g.lemma : '')), cell(t('colStatus'), `${g.status} (${g.served_count})`), actions);
    return tr;
  }) : [element('tr', null)]));
}
async function curatorDisputes(){
  const state = $('dispute-state').value;
  const data = await json('admin/items/queue?state=' + state);
  $('disputes').replaceChildren(...(data.items.length ? data.items.map(item => {
    const li = element('li', null, {'data-item': item.item_id});
    li.append(element('strong', `${item.word}${item.other_word ? ' / ' + item.other_word : ''}`),
              element('p', item.context || '', {class:'muted'}),
              element('p', item.classes.map(c => `${c.answer}${c.lemma ? ' ' + c.lemma : ''}: ${Math.round(c.prob * 1000) / 10} %`).join(' · ')),
              element('p', t('votesLine', {votes: item.votes.map(v => `${v.answer}${v.lemma ? ' ' + v.lemma : ''} (${t('tier_' + v.tier)})`).join(', ')}), {class:'muted'}));
    const answer = element('select', null, {'aria-label': t('colAnswer')});
    answer.append(...CHOICES[item.kind].filter(a => a !== 'unsure').map(a => new Option(answerText(a), a)));
    const lemma = element('input', null, {'aria-label': t('lemmaLabel'), placeholder: t('lemmaLabel'), maxlength:'128'});
    lemma.value = item.kind === 'lemma' ? item.proposed_lemma || '' : '';
    if (item.kind !== 'lemma') lemma.hidden = true;
    const reason = reasonInput();
    const discard = element('input', null, {type:'checkbox', 'aria-label': t('discard')});
    const path = `admin/items/${item.corpus_id}/${item.item_id}/`;
    const done = async () => { await curatorDisputes(); message(t('decisionDone')); };
    const discardLabel = element('label', null, {class:'check'});
    discardLabel.append(discard, element('span', t('discard')));
    li.append(answer, lemma, reason,
              button(t('adjudicate'), () => run(async () => { await post(path + 'adjudicate', {answer: answer.value, lemma: item.kind === 'lemma' ? lemma.value.trim() : '', reason: needReason(reason)}); await done(); })),
              button(t('markAmbiguous'), () => run(async () => { await post(path + 'ambiguous', {reason: needReason(reason)}); await done(); })),
              discardLabel,
              button(t('reopen'), () => run(async () => { await post(path + 'reopen', {reason: needReason(reason), discard_previous: discard.checked}); await done(); })));
    return li;
  }) : [element('li', t('noItems'))]));
}
async function curatorTrusted(){
  const data = await json('admin/trusted');
  $('trusted').replaceChildren(...(data.items.length ? data.items.map(entry => {
    const li = element('li', t('trustedLine', {label: entry.label, email: entry.email,
                                               who: entry.annotator_id ? t('trustedAnchor', {id: entry.annotator_id}) : ''}), {'data-trusted': String(entry.id)});
    const reason = reasonInput();
    li.append(element('br'), reason, button(t('trustedRemove'), () => run(async () => {
      await json(`admin/trusted/${entry.id}`, {method:'DELETE', headers:{'Content-Type':'application/json'}, body:JSON.stringify({reason: needReason(reason)})});
      await curatorTrusted();
    }), {class:'danger'}));
    return li;
  }) : [element('li', t('noTrusted'))]));
}
async function curatorScoring(){
  const [runs, params, corpora] = await Promise.all([json('admin/scoring/runs'), json('admin/scoring/params'), allCorpora()]);
  const latest = runs.items.find(r => r.status === 'done');
  const detail = latest ? await json('admin/scoring/runs/' + latest.id) : null;
  $('calibration').replaceChildren(...(detail ? Object.values(detail.calibration).map(c => {
    const li = element('li', t('calibrationLine', {cell: `${c.kind}/${c.cell}`, correct: c.correct, n: c.n, lb: c.wilson_lb.toFixed(3),
                                                   state: c.passed ? t('passed') : t('notPassed'),
                                                   pending: c.pending.length ? t('pendingRefs', {n: c.pending.length}) : ''}));
    li.append(' ', button(t('redraw'), () => run(async () => { await post('admin/scoring/calibration/redraw', {kind: c.kind, cell: c.cell}); message(t('redrawDone')); })));
    return li;
  }) : [element('li', t('noRun'))]));
  $('runs').replaceChildren(...runs.items.map(r => {
    const tr = element('tr', null, {'data-run': r.id});
    const actions = cell(t('colActions'));
    if (r.status === 'done') {
      actions.append(button(r.pinned ? t('unpin') : t('pin'), () => run(async () => { await post(`admin/scoring/runs/${r.id}/${r.pinned ? 'unpin' : 'pin'}`, {}); await curatorScoring(); })),
                     button(t('bundle'), () => run(async () => { await download(`admin/scoring/runs/${r.id}/bundle`, `run-${r.id}.json`); message(t('exportedRestricted')); })),
                     button(t('annotatorsExport'), () => run(async () => { await download(`admin/annotators/export.jsonl?run_id=${r.id}`, `annotators-${r.id}.jsonl`); message(t('exportedRestricted')); })));
      if (r.pinned) actions.append(button(t('recordRelease'), () => run(async () => {
        const data = await post(`admin/scoring/runs/${r.id}/release`, {}); message(t('releaseRecorded', {n: data.disclosed}));
      })));
    }
    tr.append(cell(t('colRun'), `${date(r.finished_at || r.started_at)} · ${r.id.slice(0, 8)}`),
              cell(t('colStatus'), r.status + (r.stale ? t('stale') : '') + (r.pinned ? t('pinned') : '')),
              cell(t('colCounts'), `${r.n_judgments ?? '—'} / ${r.n_items ?? '—'} / ${r.n_annotators ?? '—'}`), actions);
    return tr;
  }));
  $('params').value = JSON.stringify(params.params, null, 1);
  const selected = $('iaa-corpus').value;
  $('iaa-corpus').replaceChildren(...corpora.map(c => new Option(c.name, c.id)));
  if (corpora.some(c => c.id === selected)) $('iaa-corpus').value = selected;
  await curatorAgreement();
}
async function curatorAgreement(){
  if (!$('iaa-corpus').value) { $('iaa').replaceChildren(); return; }
  const data = await json('admin/scoring/iaa?corpus=' + $('iaa-corpus').value);
  const format = value => value === null || value === undefined ? '—' : value.toFixed(3);
  $('iaa').replaceChildren(...Object.entries(data.kinds).map(([kind, k]) => element('li', t('iaaLine', {kind, alpha: format(k.alpha), observed: format(k.observed_agreement)}))));
}
async function curatorSettings(){
  const data = await json('admin/settings');
  config.acceptingJudgments = data.accepting_judgments && !data.read_only;
  $('paused').hidden = config.acceptingJudgments;
  $('intake-state').textContent = (data.accepting_judgments ? t('intakeOn') : t('intakeOff')) + (data.read_only ? t('intakeReadOnly') : '');
  $('intake-toggle').textContent = data.accepting_judgments ? t('pause') : t('resume');
  $('intake-toggle').onclick = () => run(async () => { await post('admin/settings', {accepting_judgments: !data.accepting_judgments}, 'PUT'); await curatorSettings(); });
}
async function curatorCorpora(){
  const statusNames = {draft:t('statusDraft'), published:t('statusPublished'), archived:t('statusArchived')};
  $('corpora').replaceChildren(...(await allCorpora()).map(row => {
    const actions = cell(t('colActions'));
    if (row.status !== 'published') {
      const licence = element('select', null, {'aria-label': t('labelsLicence')});
      licence.append(...LABEL_LICENCES.map(name => new Option(name, name)));
      actions.append(licence, button(t('publish'), () => run(async () => {
        await post(`corpora/${row.id}/publish`, {labels_license: licence.value}); await curatorCorpora(); message(t('published'));
      })));
    } else {
      actions.append(button(t('unpublish'), () => run(async () => { await post(`corpora/${row.id}/unpublish`, {}); await curatorCorpora(); })));
    }
    if (row.status !== 'archived') actions.append(button(t('archive'), () => run(async () => { await post(`corpora/${row.id}/archive`, {}); await curatorCorpora(); })));
    actions.append(button(t('exportTsv'), () => run(async () => { await download(`corpora/${row.id}/export.tsv`, `oznake-${row.id}.tsv`); message(t('exported')); })),
                   button(t('exportJsonl'), () => run(async () => { await download(`corpora/${row.id}/export.jsonl`, `odgovori-${row.id}.jsonl`); message(t('exported')); })),
                   button(t('exportResolved'), () => run(async () => { await download(`corpora/${row.id}/resolved.tsv`, `razrijeseno-${row.id}.tsv`); message(t('exportedRestricted')); })),
                   button(t('exportRunExport'), () => run(async () => { await download(`corpora/${row.id}/resolved.jsonl`, `izracun-${row.id}.jsonl`); message(t('exportedRestricted')); })));
    const tr = element('tr', null, {'data-corpus': row.id});
    tr.append(cell(t('colName'), row.name), cell(t('colStatus'), statusNames[row.status] || row.status),
              cell(t('colLicence'), `${row.license} / ${row.labels_license || '—'}`), cell(t('colItems'), t('itemsLine', row.items)), actions);
    return tr;
  }));
}
async function curatorAnnotators(reset){
  if (reset) { annotatorOffset = 0; $('annotators').replaceChildren(); }
  const page = await json('admin/annotators?offset=' + annotatorOffset);
  const statusNames = {active:t('statusActive'), quarantined:t('statusQuarantined'), blocked:t('statusBlocked'), erased:t('statusErased')};
  for (const row of page.items) {
    const tr = element('tr', null, {'data-annotator': row.id});
    const who = cell(t('colAnnotator'), element('span', row.email || '—'), element('br'), element('small', row.id));
    if (row.anchor) who.append(' ', element('strong', t('anchorBadge')));
    const status = cell(t('colStatus'), element('span', statusNames[row.status] || row.status));
    if (row.status_reason) status.append(element('br'), element('small', row.status_reason, {class:'reason'}));
    const tiers = cell(t('colTiers'), Object.entries(row.kinds || {}).map(([kind, k]) =>
      `${kind}: ${t('tier_' + k.tier)} θ ${k.theta.toFixed(2)}${k.flags.length ? ' [' + k.flags.join(', ') + ']' : ''}`).join('; ') || '—');
    const actions = cell(t('colActions'));
    const off = row.status === 'erased' || row.id === me?.annotator_id;
    const choice = element('select', null, {'aria-label': t('colStatus')});
    choice.append(...['active', 'quarantined', 'blocked'].map(value => new Option(statusNames[value], value)));
    choice.value = row.status === 'erased' ? 'active' : row.status;
    const reason = element('input', null, {'aria-label': t('reason'), placeholder: t('reason'), maxlength:'500'});
    const apply = button(t('apply'), () => run(async () => {
      if (!reason.value.trim()) throw new UserError(t('reasonRequired'));
      await post(`admin/annotators/${row.id}/status`, {status: choice.value, reason: reason.value.trim()}, 'PUT');
      await curatorAnnotators(true); message(t('statusChanged'));
    }));
    for (const node of [choice, reason, apply]) { if (off) { node.dataset.off = '1'; node.disabled = true; } }
    actions.append(choice, reason, apply);
    tr.append(who, status, tiers, cell(t('colJudgments'), String(row.counts.judgments)), cell(t('colSeen'), date(row.last_seen_at)), actions);
    $('annotators').append(tr);
  }
  annotatorOffset = page.next_offset ?? annotatorOffset;
  $('annotators-more').hidden = page.next_offset === null;
}
async function curatorErasures(){
  const items = (await json('admin/erasures')).items;
  $('erasures').replaceChildren(...(items.length ? items.map(item => {
    const reason = item.reason === 'unconsented_expiry' ? t('erasureExpiredReason') : '';
    const li = element('li', t('erasureLine', {user: item.keycloak_user_id || item.annotator_id, date: date(item.requested_at),
                                               days: item.age_days}) + reason + ' ', {'data-erasure': String(item.id)});
    li.append(button(t('confirmErasure'), () => run(async () => { await post(`admin/erasures/${item.id}/complete`, {}); await curatorErasures(); message(t('erasureCompleted')); })));
    return li;
  }) : [element('li', t('noErasures'))]));
}

// ---- wiring ------------------------------------------------------------------------

$('language').onclick = () => { lang = lang === 'hr' ? 'en' : 'hr'; rememberLanguage(); applyLanguage(); };
$('login').onclick = () => keycloak.login({idpHint: config.idpHint || undefined, locale: lang});
for (const id of ['logout', 'gate-logout', 'erased-logout']) $(id).onclick = () => { signedInFlag(false); keycloak.logout({redirectUri: location.origin + '/'}); };
$('nav-label').onclick = () => run(async () => { me = await json('me'); if (me.consented) await openWorkspace(); else { show('gate'); message(t('gateMessage')); } });
$('nav-me').onclick = $('gate-erase').onclick = () => run(openMe);
$('nav-curator').onclick = () => run(openCurator);
for (const node of document.querySelectorAll('#curator-tabs [role=tab]')) node.onclick = () => run(() => showTab(node.dataset.tab));
$('gold-pool').onchange = () => run(curatorGold);
$('dispute-state').onchange = () => run(curatorDisputes);
$('iaa-corpus').onchange = () => run(curatorAgreement);
$('run-now').onclick = () => run(async () => {
  const result = await post('admin/scoring/run', {});
  await curatorScoring(); message(t('runDone', {status: result.runs.map(r => r.status).join(', ')}));
});
$('params-save').onclick = () => run(async () => {
  let params;
  try { params = JSON.parse($('params').value); } catch { throw Object.assign(new UserError(), {code:'params_invalid'}); }
  await post('admin/scoring/params', {params}, 'PUT'); message(t('paramsSaved'));
});
$('trusted-form').onsubmit = event => { event.preventDefault(); run(async () => {
  await post('admin/trusted', {email: $('trusted-email').value.trim(), label: $('trusted-label').value.trim()});
  $('trusted-email').value = ''; $('trusted-label').value = '';
  await curatorTrusted(); message(t('trustedAdded'));
}); };
$('gold-import').onsubmit = event => { event.preventDefault(); run(async () => {
  const file = $('gold-file').files[0];
  if (!file || file.size > 32 * 1024 * 1024) throw Object.assign(new UserError(), {code:'body_too_large'});
  let rows;
  try { rows = (await file.text()).split(/\r?\n/).filter(line => line.trim()).map(line => JSON.parse(line)); }
  catch { throw new UserError(t('badJson')); }
  const data = await post('admin/gold/import', {rows});
  const accepted = Object.entries(data.accepted).map(([kind, pools]) => `${kind} ${pools.qualification}/${pools.audit}`).join(', ') || '0';
  await curatorGold(); message(t('goldImported', {accepted, held: data.held_out, same: data.unchanged}));
}); };
$('gold-retire').onsubmit = event => { event.preventDefault(); run(async () => {
  const file = $('gold-retire-file').files[0];
  if (!file) throw new UserError(t('badIds'));
  if (file.size > 2 * 1024 * 1024) throw Object.assign(new UserError(), {code:'body_too_large'});
  const ids = (await file.text()).split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  if (!ids.length || !ids.every(id => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id))) throw new UserError(t('badIds'));
  const reason = needReason($('gold-retire-reason'));
  const corpus = $('gold-retire-corpus').value;
  const data = await post('admin/gold/retire', {item_ids: ids, reason, ...(corpus ? {corpus_id: corpus} : {})});
  $('gold-retire-reason').value = '';
  await curatorGold(); message(t('goldRetired', {retired: data.retired, already: data.already_retired, inactive: data.not_active, unknown: data.unknown}));
}); };
for (const id of GATE) $(id).onchange = gateReady;
$('consent').onsubmit = event => { event.preventDefault(); run(async () => {
  await post('me/consent', {privacy_version: config.legal.privacy, terms_version: config.legal.terms,
                            participation_version: config.legal.participation, age_confirmed: $('accept-age').checked,
                            age_threshold: config.minimumAge, locale: lang, ui_version: clientVersion});
  await loadMe();
}); };
$('download').onclick = () => run(async () => { await download('me/export.json', 'moji-podaci.json'); message(t('downloaded')); });
$('erase').onsubmit = event => { event.preventDefault(); run(async () => {
  const word = t('eraseWord');
  if ($('erase-confirm').value.trim().normalize('NFC').toLocaleUpperCase(lang) !== word) throw new UserError(t('eraseMismatch', {word}));
  await post('me/erase', {confirm: word});
  $('erase-confirm').value = '';
  showErased(t('erasedDone'));
}); };
$('corpus').onchange = () => run(chooseCorpus);
for (const id of ['kind', 'queue']) $(id).onchange = () => run(async () => {
  const corpus = $('corpus').value;
  paintCorpusLock();
  if ($('corpus').value !== corpus) await chooseCorpus(); else { cursor = ''; await load(); }
});
$('skip').onclick = () => run(load);
$('retry').onclick = () => run(submitPending);
$('answer').onsubmit = event => event.preventDefault();
$('select-file').onclick = () => $('file').click();
$('file').onchange = () => { $('file-name').textContent = $('file').files[0]?.name || t('noFile'); };
$('annotators-more').onclick = () => run(() => curatorAnnotators(false));
$('import').onsubmit = event => { event.preventDefault(); run(async () => {
  const file = $('file').files[0];
  if (!file || file.size > 32 * 1024 * 1024) throw Object.assign(new UserError(), {code:'body_too_large'});
  let candidates;
  try { candidates = (await file.text()).split(/\r?\n/).filter(line => line.trim()).map(line => JSON.parse(line)); }
  catch { throw new UserError(t('badJson')); }
  if (!candidates.length || candidates.length > 20000) throw new UserError(t('importCount'));
  const body = JSON.stringify({name: $('name').value.trim(), candidates});
  if (new Blob([body]).size > 32 * 1024 * 1024) throw Object.assign(new UserError(), {code:'body_too_large'});
  const data = await json('import', {method:'POST', headers:{'Content-Type':'application/json'}, body});
  await curatorCorpora();
  message(t('imported', {added: data.added, present: data.already_present}));
}); };

try {
  config = await (await fetch('/api/config')).json();
  applyLanguage();
  $('controller').textContent = config.controller.name;
  $('paused').hidden = config.acceptingJudgments;
  keycloak = new Keycloak({url: config.url, realm: config.realm, clientId: config.clientId});
  // The identity server is contacted only by someone who signed in from this tab: a reload then
  // redirects once with prompt=none and comes straight back, signed in or not.
  const authenticated = await keycloak.init({pkceMethod:'S256', checkLoginIframe:false, flow:'standard', responseMode:'query',
                                             ...(signedInFlag() ? {onLoad:'check-sso'} : {})});
  signedInFlag(authenticated);
  $('login').disabled = false;
  if (authenticated) await run(loadMe);
  else { show('landing'); message(t('signInPrompt')); }
} catch {
  show('landing');
  message(t('unavailable'), true);
}

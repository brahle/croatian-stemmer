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
    landingRunBy:'Projekt vodi', landingAge:'Sudjelovati mogu osobe koje imaju najmanje 16 godina. Prije prvog odgovora tražit ćemo Vaš pristanak.',
    signInPrompt:'Prijavite se za sudjelovanje.',
    gateTitle:'Prije nego što počnete',
    gateWhat:'Spremamo Vaše odgovore, vrijeme potrebno za odgovor i Vašu adresu e-pošte iz Google računa. Odgovori se vežu uz nasumičnu oznaku, a ne uz Vaše ime, i objavljuju se kao otvoreni skup podataka pod licencijom CC BY-SA 4.0.',
    gateRights:'Svoje podatke možete u svakom trenutku preuzeti ili izbrisati profil na stranici „Moji podaci”.',
    gatePrivacy:'Pročitao/la sam', privacyNotice:'obavijest o privatnosti', gateTerms:'Prihvaćam', termsLink:'uvjete sudjelovanja',
    gateTermsLicence:', uključujući licenciju mojih odgovora.', gateAge:'Imam najmanje 16 godina.', accept:'Prihvaćam', gateErase:'Izbriši račun',
    gateMessage:'Za sudjelovanje prihvatite obavijest o privatnosti i uvjete te potvrdite dob.', version:'(verzija {v})',
    erasedTitle:'Profil je izbrisan',
    erasedDone:'Vaš profil je izbrisan. Račun za prijavu izbrisat ćemo u roku od 30 dana; ako se do tada ponovno prijavite, vidjet ćete ovu obavijest umjesto novog profila. Vaši odgovori ostaju u skupu podataka pod nasumičnom oznakom koja se više ne može povezati s Vama.',
    erasurePending:'Ovaj račun je u postupku brisanja. Račun za prijavu bit će izbrisan u roku od 30 dana od zahtjeva; nakon toga se možete ponovno prijaviti kao novi sudionik.',
    corpus:'Korpus', chooseCorpusOption:'Odaberite korpus', kind:'Vrsta', kindPair:'Par riječi', kindLemma:'Lema', kindStem:'Korijen',
    queue:'Red', queueNext:'Novi primjeri', queueLabelled:'Moji označeni', queueUnsure:'Moji nesigurni',
    hintsTitle:'Prijedlozi iz korpusa i način uzorkovanja', lemmaLabel:'Potvrđena ili ispravljena lema', stemLabel:'Predloženi korijen:',
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
    consentLine:'{doc}, verzija {version}, prihvaćeno {date}', docPrivacy:'Obavijest o privatnosti', docTerms:'Uvjeti sudjelovanja',
    noConsents:'Još niste prihvatili dokumente.', download:'Preuzmi moje podatke', downloaded:'Vaši podaci su preuzeti (JSON).',
    eraseTitle:'Izbriši moj račun',
    eraseWhat:'Brisanjem se odmah uklanjaju veza s Vašim računom za prijavu, adresa e-pošte, vremena odgovora i popis prikazanih primjera. Račun za prijavu (s imenom i prezimenom) brišemo u roku od 30 dana.',
    eraseKeeps:'Vaši odgovori ostaju u skupu podataka pod nasumičnom oznakom koja se više ne može povezati s Vama.',
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
    erasuresTitle:'Zahtjevi za brisanje', erasuresHelp:'Izbrišite korisnika u konzoli za administraciju Keycloaka, zatim potvrdite ovdje. Rok je 30 dana od zahtjeva.',
    noErasures:'Nema zahtjeva koji čekaju.', erasureLine:'{user} · zatraženo {date} ({days} d)', confirmErasure:'Potvrdi brisanje u Keycloaku',
    erasureCompleted:'Brisanje je potvrđeno.',
    footerPrivacy:'Privatnost', footerTerms:'Uvjeti i licencija', footerStorage:'Kolačići i pohrana', legalMenu:'Pravne informacije',
    footerVersion:'Verzija aplikacije {v}', unavailable:'Prijava trenutačno nije dostupna. Osvježite stranicu i pokušajte ponovno.',
    genericError:'Zahtjev nije uspio. Pokušajte ponovno.', actionFailed:'Radnja nije uspjela. Pokušajte ponovno.',
  },
  en: {
    skipLink:'Skip to content', brand:'Croatian stems', title:'Labeling language examples', menu:'Menu',
    navLabel:'Labeling', navMe:'My data', navCurator:'Curator', logout:'Sign out', login:'Sign in', loginGoogle:'Sign in with Google',
    paused:'Collection of answers is paused for now. You can browse, but answers are not being saved.',
    landingTitle:'Help build an open dataset for the Croatian language',
    landingIntro:'On this site volunteers judge whether two words share a lemma, confirm dictionary lemmas and judge word stems. The answers are used to evaluate an open Croatian stemmer and are published as an open dataset, without your name.',
    landingRunBy:'The project is run by', landingAge:'You must be at least 16 to take part. We will ask for your consent before your first answer.',
    signInPrompt:'Sign in to take part.',
    gateTitle:'Before you start',
    gateWhat:'We store your answers, the time you take to answer and the email address of your Google account. Answers are linked to a random identifier, not to your name, and are published as an open dataset under the CC BY-SA 4.0 licence.',
    gateRights:'You can download your data or erase your profile at any time on the "My data" page.',
    gatePrivacy:'I have read the', privacyNotice:'privacy notice', gateTerms:'I accept the', termsLink:'terms of participation',
    gateTermsLicence:', including the licence of my answers.', gateAge:'I am at least 16 years old.', accept:'I accept', gateErase:'Erase account',
    gateMessage:'To take part, accept the privacy notice and the terms and confirm your age.', version:'(version {v})',
    erasedTitle:'Profile erased',
    erasedDone:'Your profile has been erased. We will delete your sign-in account within 30 days; if you sign in again before then, you will see this notice instead of a new profile. Your answers remain in the dataset under a random identifier that can no longer be linked to you.',
    erasurePending:'This account is being erased. The sign-in account will be deleted within 30 days of the request; after that you can sign in again as a new participant.',
    corpus:'Corpus', chooseCorpusOption:'Choose a corpus', kind:'Kind', kindPair:'Word pair', kindLemma:'Lemma', kindStem:'Stem',
    queue:'Queue', queueNext:'New items', queueLabelled:'My labelled', queueUnsure:'My unsure',
    hintsTitle:'Corpus suggestions and sampling', lemmaLabel:'Confirmed or corrected lemma', stemLabel:'Proposed stem:',
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
    consentLine:'{doc}, version {version}, accepted {date}', docPrivacy:'Privacy notice', docTerms:'Terms of participation',
    noConsents:'You have not accepted the documents yet.', download:'Download my data', downloaded:'Your data has been downloaded (JSON).',
    eraseTitle:'Erase my account',
    eraseWhat:'Erasing immediately removes the link to your sign-in account, your email address, answer times and the list of items shown to you. We delete the sign-in account (with your first and last name) within 30 days.',
    eraseKeeps:'Your answers remain in the dataset under a random identifier that can no longer be linked to you.',
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
    erasuresTitle:'Erasure requests', erasuresHelp:'Delete the user in the Keycloak admin console, then confirm here. The limit is 30 days from the request.',
    noErasures:'No requests are waiting.', erasureLine:'{user} · requested {date} ({days} d)', confirmErasure:'Confirm deletion in Keycloak',
    erasureCompleted:'Deletion confirmed.',
    footerPrivacy:'Privacy', footerTerms:'Terms and licence', footerStorage:'Cookies and storage', legalMenu:'Legal information',
    footerVersion:'Application version {v}', unavailable:'Sign-in is unavailable right now. Reload the page and try again.',
    genericError:'The request failed. Please try again.', actionFailed:'The action failed. Please try again.',
  },
};
const errors = {
  hr: {invalid_token:'Prijava je istekla. Ponovno se prijavite.', annotator_role_required:'Nemate ovlast za označavanje.', identity_unavailable:'Provjera prijave trenutačno nije dostupna.',
    invalid_candidates:'Datoteka ne odgovara formatu prijedloga za uvoz.', body_too_large:'Datoteka ili zahtjev prelazi dopuštenu veličinu.', corpus_provenance_conflict:'Podrijetlo korpusa razlikuje se od već uvezenog korpusa.',
    immutable_item_conflict:'Postojeći primjer ima drukčiji sadržaj. Uvoz je odbijen.', invalid_judgment:'Odgovor ne odgovara ovom primjeru. Provjerite lemu: jedna riječ, samo slova.', request_id_conflict:'Ovaj pokušaj spremanja već je upotrijebljen za drugi odgovor.',
    not_found:'Primjer ili korpus nije dostupan.', database_unavailable:'Baza podataka trenutačno nije dostupna.', consent_required:'Prije sudjelovanja prihvatite trenutačne verzije obavijesti o privatnosti i uvjeta.',
    consent_version_mismatch:'Dokumenti su u međuvremenu ažurirani. Osvježite stranicu i pročitajte nove verzije.', account_blocked:'Vaš profil je blokiran. Svoje podatke i dalje možete preuzeti ili izbrisati na stranici „Moji podaci”.',
    erasure_pending:'Ovaj račun je u postupku brisanja.', judgments_paused:'Primanje odgovora je privremeno zaustavljeno. Pokušajte kasnije.', rate_limited:'Previše zahtjeva u kratkom vremenu. Pričekajte trenutak pa pokušajte ponovno.',
    daily_cap_reached:'Dosegnut je dnevni broj odgovora. Hvala! Nastavite sutra.', curator_required:'Za ovu radnju potrebna je uloga kuratora.', item_retired:'Ovaj primjer je povučen i više se ne označava.',
    license_not_publishable:'Licencija izvornog korpusa ne dopušta objavu oznaka pod odabranom licencijom.', corpus_not_published:'Korpus nije objavljen.', corpus_already_published:'Korpus je već objavljen pod drugom licencijom oznaka.',
    invalid_corpus_status:'Ta promjena statusa korpusa nije moguća.', own_status_change:'Ne možete mijenjati status vlastitog profila.', annotator_erased:'Profil je izbrisan; status se više ne može mijenjati.',
    erasure_not_pending:'Brisanje je već potvrđeno.'},
  en: {invalid_token:'Your sign-in has expired. Please sign in again.', annotator_role_required:'You are not allowed to label.', identity_unavailable:'Sign-in verification is unavailable right now.',
    invalid_candidates:'The file does not match the candidate import format.', body_too_large:'The file or request is too large.', corpus_provenance_conflict:'The corpus provenance differs from the corpus already imported.',
    immutable_item_conflict:'An existing item has different content. The import was refused.', invalid_judgment:'The answer does not fit this item. Check the lemma: one word, letters only.', request_id_conflict:'This save attempt was already used for a different answer.',
    not_found:'The item or corpus is not available.', database_unavailable:'The database is unavailable right now.', consent_required:'Before taking part, accept the current privacy notice and terms.',
    consent_version_mismatch:'The documents have been updated meanwhile. Reload the page and read the new versions.', account_blocked:'Your profile is blocked. You can still download or erase your data on the "My data" page.',
    erasure_pending:'This account is being erased.', judgments_paused:'Collection of answers is paused. Please try later.', rate_limited:'Too many requests in a short time. Wait a moment and try again.',
    daily_cap_reached:'You have reached the daily number of answers. Thank you! Continue tomorrow.', curator_required:'This action needs the curator role.', item_retired:'This item has been retired and is no longer labelled.',
    license_not_publishable:'The source corpus licence does not allow publishing labels under the chosen licence.', corpus_not_published:'The corpus is not published.', corpus_already_published:'The corpus is already published under a different labels licence.',
    invalid_corpus_status:'That corpus status change is not possible.', own_status_change:'You cannot change the status of your own profile.', annotator_erased:'The profile is erased; its status can no longer change.',
    erasure_not_pending:'The deletion has already been confirmed.'},
};
const LABEL_LICENCES = ['CC BY-SA 4.0', 'CC BY 4.0', 'CC0 1.0'];
const CHOICES = {pair:['same','different','unsure'], lemma:['confirmed','unsure'], stem:['accept','reject','unsure']};

class UserError extends Error {}
const $ = id => document.getElementById(id);
let lang = initialLanguage();
let config = null, keycloak = null, me = null;
let current = null, cursor = -1, pending = null, busy = false, generation = 0, shownAt = 0, lastProgress = null;
let annotatorOffset = 0;

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
  if (me && !$('me').hidden) paintMe();
}

const SECTIONS = ['landing', 'gate', 'erased', 'workspace', 'me', 'curator'];
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
  catch (error) { if (error.code === 'erasure_pending') { showErased(t('erasurePending')); return; } throw error; }
  for (const id of ['nav-label', 'nav-me', 'logout']) $(id).hidden = false;
  $('nav-curator').hidden = !me.curator;
  if (!me.consented) { show('gate'); message(t('gateMessage')); return; }
  await openWorkspace();
}
function gateReady(){
  const ready = ['accept-privacy', 'accept-terms', 'accept-age'].every(id => $(id).checked);
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
  paintMe();
  message(t('meTitle'));
}
function paintMe(){
  $('me-id').textContent = me.annotator_id;
  $('me-counts').textContent = t('meCounts', {judgments: me.counts.judgments, items: me.counts.items_labelled});
  const docs = {privacy: t('docPrivacy'), terms: t('docTerms')};
  $('me-consents').replaceChildren(...(me.consents.length ? me.consents.map(c => element('li', t('consentLine', {doc: docs[c.document], version: c.version, date: date(c.accepted_at)})))
                                                         : [element('li', t('noConsents'))]));
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
  $('corpus').replaceChildren(new Option(t('chooseCorpusOption'), ''), ...rows.map(row => new Option(row.name, row.id)));
  $('corpus').value = rows.some(row => row.id === selected) ? selected : rows.length === 1 ? rows[0].id : '';
  if (!rows.length) { message(t('noCorpora')); }
  await chooseCorpus();
}
function resetQuestion(){
  generation++; cursor = -1; current = null; pending = null; lastProgress = null;
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
  if (!$('corpus').value) return;
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
  let item;
  if (queue === 'next') item = (await json(`corpora/${corpus}/next?kind=${kind}`)).item;
  else item = (await json(`corpora/${corpus}/items?kind=${kind}&state=${queue}&after=${cursor}`)).items[0] || null;
  if (seq !== generation) return;
  current = item; pending = null;
  $('retry').hidden = true; $('question').hidden = !current; $('skip').hidden = !current; $('empty').hidden = !!current;
  if (current) {
    if (queue !== 'next') cursor = current.ordinal;
    render();
    message(t('chooseAnswer'));
  } else {
    $('empty').textContent = queue === 'next' ? t('emptyNext') : t('emptyQueue');
    message($('empty').textContent);
  }
}
function answerText(answer){ return t(answer === 'accept' ? 'accept_' : answer); }
function render(){
  const c = current.candidate, j = current.judgment;
  shownAt = performance.now();
  paint();
  $('lemma').value = j?.lemma || c.proposed_lemma;
  $('irregular').checked = j?.irregular || false;
}
function paint(){
  const c = current.candidate, j = current.judgment;
  $('revision').textContent = j ? t('revision', {n: current.assignment.current_revision, answer: answerText(j.answer)}) : t('noLabel');
  $('prompt').textContent = t({pair:'promptPair', lemma:'promptLemma', stem:'promptStem'}[c.kind]);
  const texts = {word:c.word, context:c.context, 'word-ref':c.word_ref, 'other-word':c.other_word, 'other-context':c.other_context,
                 'other-ref':c.other_word_ref, stem:c.proposed_stem, stratum:t('sampling') + c.sampling_stratum, license:t('licence') + c.license,
                 hints:t('corpusLemma') + c.proposed_lemma + (c.other_proposed_lemma ? ' / ' + c.other_proposed_lemma : '')};
  for (const [id, value] of Object.entries(texts)) $(id).textContent = value;
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
  pending = {path:`corpora/${$('corpus').value}/items/${current.candidate.item_id}/answer`,
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

async function openCurator(){
  show('curator');
  await curatorSettings();
  await curatorCorpora();
  await curatorAnnotators(true);
  await curatorErasures();
  message(t('curatorTitle'));
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
    const actions = element('td');
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
                   button(t('exportJsonl'), () => run(async () => { await download(`corpora/${row.id}/export.jsonl`, `odgovori-${row.id}.jsonl`); message(t('exported')); })));
    const tr = element('tr', null, {'data-corpus': row.id});
    tr.append(element('td', row.name), element('td', statusNames[row.status] || row.status),
              element('td', `${row.license} / ${row.labels_license || '—'}`), element('td', t('itemsLine', row.items)), actions);
    return tr;
  }));
}
async function curatorAnnotators(reset){
  if (reset) { annotatorOffset = 0; $('annotators').replaceChildren(); }
  const page = await json('admin/annotators?offset=' + annotatorOffset);
  const statusNames = {active:t('statusActive'), quarantined:t('statusQuarantined'), blocked:t('statusBlocked'), erased:t('statusErased')};
  for (const row of page.items) {
    const tr = element('tr', null, {'data-annotator': row.id});
    const who = element('td');
    who.append(element('span', row.email || '—'), element('br'), element('small', row.id));
    const status = element('td');
    status.append(element('span', statusNames[row.status] || row.status));
    if (row.status_reason) status.append(element('br'), element('small', row.status_reason, {class:'reason'}));
    const actions = element('td');
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
    tr.append(who, status, element('td', String(row.counts.judgments)), element('td', date(row.last_seen_at)), actions);
    $('annotators').append(tr);
  }
  annotatorOffset = page.next_offset ?? annotatorOffset;
  $('annotators-more').hidden = page.next_offset === null;
}
async function curatorErasures(){
  const items = (await json('admin/erasures')).items;
  $('erasures').replaceChildren(...(items.length ? items.map(item => {
    const li = element('li', t('erasureLine', {user: [item.preferred_username, item.email].filter(Boolean).join(' · ') || item.annotator_id,
                                               date: date(item.requested_at), days: item.age_days}) + ' ', {'data-erasure': String(item.id)});
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
for (const id of ['accept-privacy', 'accept-terms', 'accept-age']) $(id).onchange = gateReady;
$('consent').onsubmit = event => { event.preventDefault(); run(async () => {
  await post('me/consent', {privacy_version: config.legal.privacy, terms_version: config.legal.terms,
                            age_confirmed: $('accept-age').checked, locale: lang, ui_version: clientVersion});
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
for (const id of ['kind', 'queue']) $(id).onchange = () => run(async () => { cursor = -1; await load(); });
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

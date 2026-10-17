import Keycloak from './vendor/keycloak.js';

class UserError extends Error {}
const $ = id => document.getElementById(id);
const labels = {pair:'Parovi', lemma:'Leme', stem:'Korijeni'};
const errors = {invalid_token:'Prijava je istekla. Ponovno se prijavite.', annotator_role_required:'Nemate ovlast za označavanje. Zatražite ulogu označivača.', identity_unavailable:'Provjera prijave trenutačno nije dostupna.', invalid_candidates:'Datoteka ne odgovara formatu prijedloga za uvoz.', body_too_large:'Datoteka ili zahtjev prelazi dopuštenu veličinu.', corpus_provenance_conflict:'Podrijetlo korpusa razlikuje se od već uvezenog korpusa.', immutable_item_conflict:'Postojeći primjer ima drukčiji sadržaj. Uvoz je odbijen.', invalid_judgment:'Odgovor ne odgovara ovom primjeru. Provjerite lemu.', request_id_conflict:'Ovaj pokušaj spremanja već je upotrijebljen za drugi odgovor.', not_found:'Primjer ili korpus nije dostupan.', database_unavailable:'Baza podataka trenutačno nije dostupna.'};
let keycloak, current = null, cursor = -1, pending = null, busy = false, generation = 0;
function message(text, error=false){$('message').textContent=text;$('message').dataset.error=String(error);}
function lock(value){busy=value;for(const el of document.querySelectorAll('#workspace button, #workspace select, #workspace input'))el.disabled=value||(!!pending&&el.id!=='retry'&&el.id!=='export');$('export').disabled=value||!$('corpus').value;}
async function api(path, options={}){
  try{await keycloak.updateToken(30);}catch{$('login').hidden=false;throw new UserError(errors.invalid_token);}
  const response=await fetch('/api/'+path,{...options,headers:{Authorization:'Bearer '+keycloak.token,...options.headers}});
  if(!response.ok){let data;try{data=await response.json();}catch{data={};}const e=new UserError(errors[data.detail?.code]||'Zahtjev nije uspio. Pokušajte ponovno.');e.code=data.detail?.code;e.status=response.status;throw e;}
  return response;
}
const json=async(path,options)=> (await api(path,options)).json();
async function run(action){if(busy)return;lock(true);try{await action();}catch(e){message(e instanceof UserError?e.message:'Radnja nije uspjela. Pokušajte ponovno.',true);}finally{lock(false);}}
async function corpora(selected=''){
  const rows=[];let offset=0;
  do{const page=await json('corpora?offset='+offset);rows.push(...page.items);offset=page.next_offset;}while(offset!==null);
  $('corpus').replaceChildren(new Option('Odaberite korpus',''),...rows.map(row=>new Option(row.name,row.id)));
  $('corpus').value=selected;
  await chooseCorpus();
}
async function progress(){
  if(!$('corpus').value)return;
  const data=await json(`corpora/${$('corpus').value}/progress`);
  $('progress').replaceChildren(...Object.entries(data.kinds).map(([kind,count])=>{const p=document.createElement('p');p.textContent=`${labels[kind]}: ${count.definite} potvrđenih, ${count.unsure} nesigurnih / ${count.total} prijedloga`;return p;}));
}
async function chooseCorpus(){generation++;cursor=-1;current=null;pending=null;$('retry').hidden=true;$('labeling').hidden=!$('corpus').value;$('question').hidden=true;$('skip').hidden=true;if($('corpus').value){await progress();await next();}else message('Odaberite korpus ili uvezite prijedloge.');}
async function next(){
  const seq=++generation;
  const path=`corpora/${$('corpus').value}/items?kind=${$('kind').value}&state=${$('queue').value}&after=${cursor}`;
  const data=await json(path);if(seq!==generation)return;
  current=data.items[0]||null;pending=null;$('retry').hidden=true;$('question').hidden=!current;$('empty').hidden=!!current;$('skip').hidden=!current;
  if(current){cursor=current.ordinal;render();message('Odaberite odgovor. Prijedloge možete provjeriti u pojedinostima.');}else message('Pregled reda je završen. Možete promijeniti vrstu ili red.');
}
function render(){
  const c=current.candidate,j=current.judgment;
  $('revision').textContent=j?`Revizija ${current.current_revision}; spremljeni odgovor: ${answerText(j.answer)}.`:'Primjer još nema ljudsku oznaku.';
  $('prompt').textContent={pair:'Pripadaju li ove riječi istoj lemi?',lemma:'Koja je rječnička lema ove riječi?',stem:'Je li predloženi korijen prihvatljiv?'}[c.kind];
  for(const [id,value] of Object.entries({word:c.word,context:c.context,'word-ref':c.word_ref,'other-word':c.other_word,'other-context':c.other_context,'other-ref':c.other_word_ref,stem:c.proposed_stem,stratum:'Uzorkovanje: '+c.sampling_stratum,license:'Licencija: '+c.license,hints:'Lema iz korpusa: '+c.proposed_lemma+(c.other_proposed_lemma?' / '+c.other_proposed_lemma:'')}))$(id).textContent=value;
  $('second').hidden=c.kind!=='pair';$('lemma-field').hidden=c.kind!=='lemma';$('stem-field').hidden=c.kind!=='stem';$('lemma').value=j?.lemma||c.proposed_lemma;$('irregular').checked=j?.irregular||false;
  $('source').replaceChildren(document.createTextNode('Izvor: '));
  let url;try{url=new URL(c.source_uri);}catch{}
  if(url&&['https:','http:'].includes(url.protocol)){const a=document.createElement('a');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';a.textContent=c.source_uri;$('source').append(a);}else $('source').append(document.createTextNode(c.source_uri));
  const choices={pair:['same','different','unsure'],lemma:['confirmed','unsure'],stem:['accept','reject','unsure']}[c.kind];
  $('choices').replaceChildren(...choices.map(answer=>{const button=document.createElement('button');button.type='button';button.textContent=answerText(answer);button.onclick=()=>run(()=>save(answer));return button;}));
}
function answerText(answer){return {same:'Ista lema',different:'Različite leme',unsure:'Nisam siguran/na',confirmed:'Potvrdi lemu',accept:'Prihvati korijen',reject:'Odbaci korijen'}[answer]||answer;}
async function save(answer){
  if(pending){message('Najprije ponovite prethodno spremanje ili ponovno učitajte red.',true);return;}
  const lemma=current.candidate.kind==='lemma'&&answer==='confirmed'?$('lemma').value.trim():'';
  if(answer==='confirmed'&&!lemma){message('Upišite lemu prije potvrde.',true);return;}
  pending={path:`corpora/${$('corpus').value}/items/${current.candidate.item_id}/answer`,body:{request_id:crypto.randomUUID(),base_revision:current.current_revision,answer,lemma,irregular:$('irregular').checked}};
  await submitPending();
}
async function submitPending(){
  try{await json(pending.path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pending.body)});}
  catch(e){
    if(e.code==='revision_conflict'){
      const path=pending.path.replace(/\/answer$/,'');pending=null;$('retry').hidden=true;
      current=await json(path);cursor=current.ordinal;render();await progress();
      message('Odgovor je u međuvremenu izmijenjen u drugoj sesiji. Učitan je posljednji odgovor; pregledajte ga prije novog spremanja.',true);return;
    }
    if(e.status&&e.status<500){pending=null;$('retry').hidden=true;}else $('retry').hidden=false;
    throw e;
  }
  pending=null;$('retry').hidden=true;await progress();await next();
}
$('select-file').onclick=()=>$('file').click();
$('file').onchange=()=>{$('file-name').textContent=$('file').files[0]?.name||'Datoteka nije odabrana.';};
$('import').onsubmit=event=>{event.preventDefault();run(async()=>{
  const file=$('file').files[0];if(!file||file.size>32*1024*1024)throw new UserError(errors.body_too_large);
  let candidates;try{candidates=(await file.text()).split(/\r?\n/).filter(line=>line.trim()).map(line=>JSON.parse(line));}catch{throw new UserError('Datoteka sadrži neispravan JSON.');}
  if(!candidates.length||candidates.length>20000)throw new UserError('Uvoz mora sadržavati od 1 do 20.000 prijedloga.');
  const body=JSON.stringify({name:$('name').value.trim(),candidates});if(new Blob([body]).size>32*1024*1024)throw new UserError(errors.body_too_large);
  const data=await json('import',{method:'POST',headers:{'Content-Type':'application/json'},body});await corpora(data.corpus.id);message(`Uvezeno ${data.added} novih prijedloga; ${data.already_present} već postoji. Ljudske oznake ostaju sačuvane.`);
});};
$('corpus').onchange=()=>run(chooseCorpus);
for(const id of ['kind','queue','restart'])$(id)[id==='restart'?'onclick':'onchange']=()=>run(async()=>{cursor=-1;await next();});
$('skip').onclick=()=>run(next);$('retry').onclick=()=>run(submitPending);
$('answer').onsubmit=e=>e.preventDefault();
$('export').onclick=()=>run(async()=>{const response=await api(`corpora/${$('corpus').value}/export.tsv`),url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download=`oznake-${$('corpus').value}.tsv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);message('TSV je preuzet. Izvoz sadrži povijest revizija; evaluator razrješava posljednje odgovore.');});
$('login').onclick=()=>keycloak.login();$('logout').onclick=()=>keycloak.logout({redirectUri:location.origin+'/'});
try{
  const config=await (await fetch('/api/config')).json();keycloak=new Keycloak(config);
  const authenticated=await keycloak.init({onLoad:'check-sso',pkceMethod:'S256',checkLoginIframe:false,flow:'standard',responseMode:'query'});
  $('login').disabled=false;
  if(authenticated){$('identity').textContent=keycloak.tokenParsed?.preferred_username||'Prijavljeni korisnik';$('login').hidden=true;$('logout').hidden=false;$('workspace').hidden=false;await run(()=>corpora());}
}catch{message('Prijava trenutačno nije dostupna. Osvježite stranicu i pokušajte ponovno.',true);}

import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';

// Deliberately synthetic data. These answers never count toward human gold.
const FIXTURE = 'http://127.0.0.1:55485';
const RUN = randomUUID().slice(0, 8);
const CURATOR = `curator-${RUN}`, ANA = `ana-${RUN}`;
test.describe.configure({mode: 'serial'});

function candidates(){
  const base = {candidate_schema_version:1, corpus_id:randomUUID(), corpus_sha256:'a'.repeat(64), source_uri:'urn:test:browser-synthetic-only',
    license:'CC BY-SA 4.0', item_id:randomUUID(), kind:'pair', word:'kuće', other_word:'kuća', proposed_lemma:'kuća', other_proposed_lemma:'kuća',
    proposed_stem:'', upos:'NOUN', context:'Sintetički primjer <img src=x onerror=alert(1)> kuće.', other_context:'Sintetički primjer kuća.',
    word_ref:'test:1', other_word_ref:'test:2', sampling_stratum:'synthetic-browser', algorithm_sha256:'b'.repeat(64)};
  const second = {...base, item_id:randomUUID(), word_ref:'test:3'};
  const lemma = {...base, item_id:randomUUID(), kind:'lemma', other_word:'', other_proposed_lemma:'', other_context:'', other_word_ref:''};
  return [base, second, lemma, {...lemma, item_id:randomUUID(), kind:'stem', proposed_stem:'kuć'}];
}
function watch(page){ const faults = []; page.on('pageerror', e => faults.push(e.message)); page.on('dialog', d => { faults.push('dialog ' + d.message()); d.dismiss(); }); return faults; }
async function signIn(page, name, curator = false){
  await page.request.get(`${FIXTURE}/fixture/persona?name=${name}&curator=${curator ? 1 : 0}`);
  await page.goto('/');
  await page.getByRole('button', {name:'Prijava Google računom', exact:true}).click();
}
async function acceptGate(page){
  await expect(page.locator('#gate')).toBeVisible();
  const accept = page.getByRole('button', {name:'Prihvaćam', exact:true});
  await page.locator('#accept-privacy').check(); await page.locator('#accept-terms').check();
  await expect(accept).toBeDisabled();
  await page.locator('#accept-age').check();
  await expect(accept).toBeEnabled();
  await accept.click();
  await expect(page.locator('#workspace')).toBeVisible();
}
async function storage(page){
  return page.evaluate(() => ({cookie: document.cookie, local: Object.keys(localStorage), session: Object.keys(sessionStorage)}));
}

test('landing, legal notices and language switch work without signing in', async ({page, context, browser}) => {
  const faults = watch(page), identity = [];
  page.on('request', r => { if (r.url().startsWith(FIXTURE)) identity.push(r.url()); });
  await page.goto('/');
  await expect(page.locator('#landing')).toBeVisible();
  await expect(page.locator('#controller')).toHaveText('Synthetic Test Controller');
  await expect(page.getByRole('button', {name:'Prijava Google računom', exact:true})).toBeEnabled();
  // Nothing is sent to the identity server until the person chooses to sign in.
  expect(identity).toEqual([]);
  await page.getByRole('link', {name:'Privatnost', exact:true}).click();
  await expect(page.locator('h1')).toHaveText('Obavijest o privatnosti');
  await expect(page.locator('body')).toContainText('Voditelj obrade je Synthetic Test Controller.');
  await expect(page.locator('body')).toContainText('Example Hosting Ltd, Germany (synthetic)');
  expect(await page.content()).not.toContain('{{');
  await page.goto('/legal/storage.en');
  await expect(page.locator('body')).toContainText('kc-callback-');
  await page.goto('/legal/terms.hr');
  await expect(page.locator('body')).toContainText('CC BY-SA 4.0');
  await page.goto('/');
  await page.getByRole('button', {name:'English', exact:true}).click();
  await expect(page.getByRole('button', {name:'Sign in with Google', exact:true})).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.getByRole('link', {name:'Privacy', exact:true})).toHaveAttribute('href', '/legal/privacy.en');
  // The choice lives in the address, so a reload keeps it.
  expect(new URL(page.url()).searchParams.get('lang')).toBe('en');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await page.getByRole('button', {name:'Hrvatski', exact:true}).click();
  expect(new URL(page.url()).searchParams.has('lang')).toBe(false);
  await expect(page.locator('#landing h2')).toContainText('otvoreni skup podataka');
  expect(await context.cookies()).toEqual([]);
  expect(await storage(page)).toEqual({cookie:'', local:[], session:[]});
  expect(faults).toEqual([]);
  // Croatian is the default even for a browser that prefers English.
  const english = await browser.newContext({locale:'en-US'}), visitor = await english.newPage();
  await visitor.goto('/');
  await expect(visitor.locator('html')).toHaveAttribute('lang', 'hr');
  await expect(visitor.getByRole('button', {name:'Prijava Google računom', exact:true})).toBeVisible();
  await english.close();
});

test('curator publishes; annotator gate, labeling, data rights and erasure', async ({browser}) => {
  const rows = candidates(), corpus = rows[0].corpus_id;
  const curatorContext = await browser.newContext(), annotatorContext = await browser.newContext();
  const cur = await curatorContext.newPage(), ana = await annotatorContext.newPage();
  const faults = [...[cur, ana].map(watch)];

  // Curator: sign in through the Google hint, accept, import and publish.
  await signIn(cur, CURATOR, true);
  const authorize = await (await cur.request.get(`${FIXTURE}/fixture/last-authorize`)).json();
  expect(authorize.kc_idp_hint).toBe('google');
  expect(authorize.ui_locales).toBe('hr');
  await acceptGate(cur);
  // A reload keeps the person signed in: only the token-free tab marker is stored.
  await cur.reload();
  await expect(cur.locator('#workspace')).toBeVisible();
  expect(await storage(cur)).toEqual({cookie:'', local:[], session:['labeling-signed-in']});
  await expect(cur.locator('#nav-curator')).toBeVisible();
  await cur.locator('#nav-curator').click();
  await expect(cur.locator('#curator')).toBeVisible();
  await cur.getByText('Uvoz prijedloga iz korpusa', {exact:true}).click();
  await cur.locator('#name').fill('Sintetički pregled u pregledniku');
  await cur.locator('#file').setInputFiles({name:'synthetic.jsonl', mimeType:'application/jsonl', buffer:Buffer.from(rows.map(r => JSON.stringify(r)).join('\n'))});
  await cur.getByRole('button', {name:'Uvezi prijedloge', exact:true}).click();
  await expect(cur.locator('#message')).toContainText('Uvezeno 4 novih prijedloga');
  const corpusRow = cur.locator(`tr[data-corpus="${corpus}"]`);
  await expect(corpusRow).toContainText('skica');
  await corpusRow.getByRole('button', {name:'Objavi', exact:true}).click();
  await expect(corpusRow).toContainText('objavljen');
  await expect(corpusRow).toContainText('CC BY-SA 4.0 / CC BY-SA 4.0');

  // Annotator: gate first, no curator panel.
  await signIn(ana, ANA);
  await expect(ana.locator('#gate')).toBeVisible();
  await expect(ana.locator('#nav-curator')).toBeHidden();
  await expect(ana.locator('#curator')).toBeHidden();
  await acceptGate(ana);
  await ana.locator('#corpus').selectOption(corpus);
  await expect(ana.locator('#word')).toHaveText('kuće');
  await expect(ana.locator('#context')).toContainText('<img src=x onerror=alert(1)>');
  expect(await ana.locator('#context img').count()).toBe(0);
  // Skip: the next new item comes; the skipped one returns only after 30 minutes.
  const skipped = await ana.locator('#word-ref').textContent();
  await ana.getByRole('button', {name:'Preskoči', exact:true}).click();
  await expect(ana.locator('#word-ref')).not.toHaveText(skipped);
  // Keyboard shortcut 1 = "Ista lema".
  await expect(ana.getByRole('button', {name:'Ista lema', exact:true})).toHaveAttribute('aria-keyshortcuts', '1');
  await ana.locator('#prompt').click();
  await ana.keyboard.press('1');
  await expect(ana.locator('#progress')).toContainText('Parovi: 1 potvrđenih');
  await expect(ana.locator('#empty')).toBeVisible();

  // Lemma: markup in the lemma field is refused and never rendered; a lost response is retried idempotently.
  await ana.locator('#kind').selectOption('lemma');
  await expect(ana.locator('#lemma-field')).toBeVisible();
  await ana.locator('#lemma').fill('<img src=x onerror=alert(1)>');
  await ana.getByRole('button', {name:'Potvrdi lemu', exact:true}).click();
  await expect(ana.locator('#message')).toContainText('Provjerite lemu');
  expect(await ana.locator('img').count()).toBe(0);
  const attempts = []; let loseFirst = true;
  await ana.route('**/api/corpora/*/items/*/answer', async route => {
    attempts.push(JSON.parse(route.request().postData()));
    if (loseFirst) { loseFirst = false; await route.fetch(); await route.abort('failed'); } else await route.continue();
  });
  await ana.locator('#lemma').fill('KUĆA'); await ana.locator('#irregular').check();
  await ana.getByRole('button', {name:'Potvrdi lemu', exact:true}).click();
  await expect(ana.locator('#retry')).toBeVisible();
  await expect(ana.locator('#kind')).toBeDisabled();
  await ana.locator('#retry').click();
  await expect(ana.locator('#progress')).toContainText('Leme: 1 potvrđenih');
  await ana.unroute('**/api/corpora/*/items/*/answer');
  expect(attempts[0].request_id).toBe(attempts[1].request_id);
  expect(attempts[0].client_version).toMatch(/^\d+\.\d+\.\d+$/);
  expect(attempts[0].elapsed_ms).toBeGreaterThanOrEqual(0);

  await ana.locator('#kind').selectOption('stem');
  await expect(ana.locator('#stem')).toHaveText('kuć');
  await ana.getByRole('button', {name:'Prihvati korijen', exact:true}).click();
  await expect(ana.locator('#progress')).toContainText('Korijeni: 1 potvrđenih');

  // Own review queue and a stale edit from a second tab.
  await ana.locator('#kind').selectOption('pair');
  await ana.locator('#queue').selectOption('mine_labelled');
  await expect(ana.locator('#revision')).toContainText('Revizija 1');
  const tab = await annotatorContext.newPage(); faults.push(watch(tab));
  await signIn(tab, ANA);
  await tab.locator('#corpus').selectOption(corpus);
  await tab.locator('#queue').selectOption('mine_labelled');
  await expect(tab.locator('#revision')).toContainText('Revizija 1');
  await ana.getByRole('button', {name:'Nisam siguran/na', exact:true}).click();
  await expect(ana.locator('#progress')).toContainText('Parovi: 0 potvrđenih, 1 nesigurnih');
  await tab.getByRole('button', {name:'Različite leme', exact:true}).click();
  await expect(tab.locator('#message')).toContainText('drugoj sesiji');
  await expect(tab.locator('#revision')).toContainText('Revizija 2');
  await tab.close();
  await ana.locator('#queue').selectOption('mine_unsure');
  await expect(ana.locator('#question')).toBeVisible();

  // Kill switch: the curator pauses intake; the answer is kept for a retry.
  await cur.getByRole('button', {name:'Zaustavi primanje odgovora', exact:true}).click();
  await expect(cur.locator('#intake-state')).toContainText('zaustavljeno');
  await ana.getByRole('button', {name:'Ista lema', exact:true}).click();
  await expect(ana.locator('#message')).toContainText('privremeno zaustavljeno');
  await expect(ana.locator('#paused')).toBeVisible();
  await cur.getByRole('button', {name:'Nastavi primanje odgovora', exact:true}).click();
  await expect(cur.locator('#intake-state')).toContainText('Odgovori se primaju');
  await ana.locator('#retry').click();
  await expect(ana.locator('#progress')).toContainText('Parovi: 1 potvrđenih, 0 nesigurnih');
  await expect(ana.locator('#paused')).toBeHidden();
  await ana.locator('#queue').selectOption('mine_labelled');
  await expect(ana.locator('#question')).toBeVisible();
  await ana.screenshot({path: 'test-results/labeling-question.png', fullPage: true});

  // Curator: the status reason is shown as text, never as markup.
  await cur.locator('#nav-curator').click();
  const annotatorRow = cur.locator('#annotators tr', {hasText:`${ANA}@example.org`});
  await annotatorRow.locator('select').selectOption('quarantined');
  await annotatorRow.getByRole('textbox').fill('<img src=x onerror=alert(1)> provjera');
  await annotatorRow.getByRole('button', {name:'Primijeni', exact:true}).click();
  await expect(cur.locator('#annotators tr', {hasText:`${ANA}@example.org`}).locator('.reason')).toHaveText('<img src=x onerror=alert(1)> provjera');
  expect(await cur.locator('#annotators img').count()).toBe(0);
  await cur.screenshot({path: 'test-results/labeling-curator.png'});

  // My data: consents, counts and the JSON export.
  await ana.locator('#nav-me').click();
  await expect(ana.locator('#me-consents li')).toHaveCount(2);
  await expect(ana.locator('#me-counts')).toContainText('Odgovora ukupno: 5');
  const pending = ana.waitForEvent('download');
  await ana.getByRole('button', {name:'Preuzmi moje podatke', exact:true}).click();
  let exported = '';
  for await (const chunk of await (await pending).createReadStream()) exported += chunk.toString();
  const data = JSON.parse(exported);
  expect(data.annotator.email).toBe(`${ANA}@example.org`);
  expect(data.judgments).toHaveLength(5);
  expect(data.judgments.every(j => j.client_version && j.elapsed_ms !== undefined)).toBe(true);
  // No cookie and no persistent storage on the app origin, signed in or not.
  expect(await annotatorContext.cookies()).toEqual([]);
  const stored = await storage(ana);
  expect(stored.cookie).toBe(''); expect(stored.local).toEqual([]);
  expect(stored.session.some(k => /token/i.test(k))).toBe(false);

  await ana.screenshot({path: process.env.LABELING_SCREENSHOT || 'test-results/labeling-desktop.png', fullPage: true});
  await ana.setViewportSize({width: 390, height: 844});
  expect(await ana.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await ana.screenshot({path: 'test-results/labeling-mobile.png', fullPage: true});

  // Erasure with the typed confirmation; signing in again shows the pending notice.
  await ana.locator('#erase-confirm').fill('obriši');
  await ana.getByRole('button', {name:'Izbriši moj račun', exact:true}).click();
  await expect(ana.locator('#message')).toContainText('upišite točno IZBRIŠI');
  await ana.locator('#erase-confirm').fill('izbriši');
  await ana.getByRole('button', {name:'Izbriši moj račun', exact:true}).click();
  await expect(ana.locator('#erased')).toBeVisible();
  await expect(ana.locator('#erased-text')).toContainText('u roku od 30 dana');
  await ana.locator('#erased').getByRole('button', {name:'Odjava', exact:true}).click();
  await expect(ana.getByRole('button', {name:'Prijava Google računom', exact:true})).toBeVisible();
  await signIn(ana, ANA);
  await expect(ana.locator('#erased-text')).toContainText('u postupku brisanja');

  // Curator completes the Keycloak side.
  await cur.locator('#nav-curator').click();
  const erasure = cur.locator('#erasures li', {hasText:`${ANA}@example.org`});
  await expect(erasure).toBeVisible();
  await erasure.getByRole('button', {name:'Potvrdi brisanje u Keycloaku', exact:true}).click();
  await expect(cur.locator('#erasures li', {hasText:`${ANA}@example.org`})).toHaveCount(0);

  // After logout nothing is left behind on the app origin.
  for (const page of [ana, cur]) {
    await page.getByRole('button', {name:'Odjava', exact:true}).first().click();
    await expect(page.getByRole('button', {name:'Prijava Google računom', exact:true})).toBeVisible();
    expect(await storage(page)).toEqual({cookie:'', local:[], session:[]});
  }
  expect(await annotatorContext.cookies()).toEqual([]);
  expect(await curatorContext.cookies()).toEqual([]);
  expect(faults.flat()).toEqual([]);
  await curatorContext.close(); await annotatorContext.close();
});

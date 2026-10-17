import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';

// Deliberately synthetic data. These answers never count toward human gold.
function candidates(){
  const base={candidate_schema_version:1,corpus_id:randomUUID(),corpus_sha256:'a'.repeat(64),source_uri:'urn:test:browser-synthetic-only',license:'synthetic fixture',item_id:randomUUID(),kind:'pair',word:'kuće',other_word:'kuća',proposed_lemma:'kuća',other_proposed_lemma:'kuća',proposed_stem:'',upos:'NOUN',context:'Sintetički primjer <img src=x onerror=alert(1)> kuće.',other_context:'Sintetički primjer kuća.',word_ref:'test:1',other_word_ref:'test:2',sampling_stratum:'synthetic-browser',algorithm_sha256:'b'.repeat(64)};
  const lemma={...base,item_id:randomUUID(),kind:'lemma',other_word:'',other_proposed_lemma:'',other_context:'',other_word_ref:''};
  return [base,lemma,{...lemma,item_id:randomUUID(),kind:'stem',proposed_stem:'kuć'}];
}
async function login(page){await page.goto('/');await page.getByRole('button',{name:'Prijava',exact:true}).click();await expect(page.locator('#workspace')).toBeVisible();}

test('PKCE login, candidate import, all judgment kinds, stale edit, revision export and logout',async({page,context})=>{
  const faults=[];page.on('pageerror',e=>faults.push(e.message));
  const rows=candidates();await login(page);
  await page.getByText('Uvoz prijedloga iz korpusa',{exact:true}).click();
  await page.locator('#name').fill('Sintetički pregled u pregledniku');
  await page.locator('#file').setInputFiles({name:'synthetic.jsonl',mimeType:'application/jsonl',buffer:Buffer.from(rows.map(r=>JSON.stringify(r)).join('\n'))});
  await page.getByRole('button',{name:'Uvezi prijedloge',exact:true}).click();
  await expect(page.locator('#progress')).toContainText('Parovi: 0 potvrđenih');
  await expect(page.locator('#context')).toContainText('<img src=x onerror=alert(1)>');
  expect(await page.locator('#context img').count()).toBe(0);
  const second=await context.newPage();await login(second);await second.locator('#corpus').selectOption(rows[0].corpus_id);
  await expect(second.locator('#word')).toHaveText('kuće');
  const attempts=[];let loseFirst=true;
  await page.route('**/api/corpora/*/items/*/answer',async route=>{
    attempts.push(JSON.parse(route.request().postData()));
    if(loseFirst){loseFirst=false;await route.fetch();await route.abort('failed');}else await route.continue();
  });
  await page.getByRole('button',{name:'Ista lema',exact:true}).click();
  await expect(page.locator('#retry')).toBeVisible();
  await expect(page.locator('#kind')).toBeDisabled();
  await page.locator('#retry').click();
  expect(attempts[0].request_id).toBe(attempts[1].request_id);
  await page.unroute('**/api/corpora/*/items/*/answer');
  await expect(page.locator('#progress')).toContainText('Parovi: 1 potvrđenih');
  await second.getByRole('button',{name:'Različite leme',exact:true}).click();
  await expect(second.locator('#message')).toContainText('drugoj sesiji');
  await expect(second.locator('#revision')).toContainText('Revizija 1');
  await second.getByRole('button',{name:'Različite leme',exact:true}).click();
  await expect(second.locator('#empty')).toBeVisible();await second.close();
  await page.locator('#kind').selectOption('lemma');await expect(page.locator('#lemma-field')).toBeVisible();
  await page.locator('#lemma').fill('KUĆA');await page.locator('#irregular').check();
  await page.getByRole('button',{name:'Potvrdi lemu',exact:true}).click();await expect(page.locator('#progress')).toContainText('Leme: 1 potvrđenih');
  await page.locator('#kind').selectOption('stem');await expect(page.locator('#stem')).toHaveText('kuć');
  await page.getByRole('button',{name:'Prihvati korijen',exact:true}).click();await expect(page.locator('#progress')).toContainText('Korijeni: 1 potvrđenih');
  await page.locator('#kind').selectOption('pair');await page.locator('#queue').selectOption('labelled');
  await expect(page.locator('#revision')).toContainText('Revizija 2');
  await page.getByRole('button',{name:'Nisam siguran/na',exact:true}).click();await expect(page.locator('#progress')).toContainText('Parovi: 0 potvrđenih, 1 nesigurnih');
  const download=page.waitForEvent('download');await page.locator('#export').click();
  const file=await download;const stream=await file.createReadStream();let tsv='';for await(const chunk of stream)tsv+=chunk.toString();
  expect(tsv.trim().split('\n')).toHaveLength(6);expect(tsv).toContain('\tunsure\t');expect(tsv).toContain('urn:test:browser-synthetic-only');
  const storage=await page.evaluate(()=>({local:Object.keys(localStorage),session:Object.keys(sessionStorage)}));
  expect(storage.local.some(k=>/token/i.test(k))).toBe(false);expect(storage.session.some(k=>/token/i.test(k))).toBe(false);
  await page.locator('#queue').selectOption('unsure');await expect(page.locator('#question')).toBeVisible();
  await page.screenshot({path:process.env.LABELING_SCREENSHOT||'test-results/labeling-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:'test-results/labeling-mobile.png',fullPage:true});
  await page.getByRole('button',{name:'Odjava',exact:true}).click();await expect(page.getByRole('button',{name:'Prijava',exact:true})).toBeVisible();
  expect(faults).toEqual([]);
});

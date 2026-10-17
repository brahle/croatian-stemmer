"""Real PostgreSQL acceptance; fixtures are synthetic, never dataset gold."""
import asyncio
import io
import os
import time
from uuid import uuid4

import pytest
import pytest_asyncio
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from croatian_stemmer.labeling.schema import read_tsv
from croatian_stemmer.labeling.web.api import create_app
from croatian_stemmer.labeling.web.config import Settings

@pytest_asyncio.fixture
async def api():
    dsn=os.getenv("LABELING_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set LABELING_TEST_DATABASE_URL to a migrated, isolated PostgreSQL test database")
    if not dsn.rsplit('/',1)[-1].endswith('_test'):
        raise ValueError("Use a dedicated *_test database; do not run against human labels")
    settings=Settings(dsn,"https://identity.example/realms/test")
    app=create_app(settings)
    private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    app.state.auth.keys={"test":private.public_key()};app.state.auth.loaded_at=time.monotonic()
    owners={name:str(uuid4()) for name in ("alice","bob")}
    def headers(name="alice"):
        claims={"sub":owners[name],"iss":settings.issuer,"aud":settings.audience,
                "azp":settings.client_id,"typ":"Bearer","iat":int(time.time()),"exp":int(time.time())+300,
                "resource_access":{settings.audience:{"roles":[settings.role]}}}
        return {"Authorization":"Bearer "+jwt.encode(claims,private,algorithm="RS256",headers={"kid":"test"})}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://app.test") as client:
        yield client,headers,owners
    await app.state.engine.dispose()


def candidates():
    corpus=str(uuid4())
    base={"candidate_schema_version":1,"corpus_id":corpus,"corpus_sha256":"a"*64,
          "source_uri":"urn:test:synthetic-only","license":"test fixture, not human gold",
          "item_id":str(uuid4()),"kind":"pair","word":"kuće","other_word":"kuća",
          "proposed_lemma":"kuća","other_proposed_lemma":"kuća","proposed_stem":"",
          "upos":"NOUN","context":"Sintetički primjer kuće.","other_context":"Sintetički primjer kuća.",
          "word_ref":"test:1","other_word_ref":"test:2","sampling_stratum":"test",
          "algorithm_sha256":"b"*64}
    lemma={**base,"item_id":str(uuid4()),"kind":"lemma","other_word":"","other_context":"",
           "other_word_ref":"","other_proposed_lemma":""}
    stem={**lemma,"item_id":str(uuid4()),"kind":"stem","proposed_stem":"kuć"}
    return [base,lemma,stem]

async def imported(api,rows=None):
    client,headers,_=api
    rows=rows or candidates()
    r=await client.post('/api/import',headers=headers(),json={"name":"Sintetički test","candidates":rows})
    assert r.status_code==200,r.text
    return rows,r.json()

def answer(revision=0,value="same",**extra):
    return {"request_id":str(uuid4()),"base_revision":revision,"answer":value,**extra}

def path(row):
    return f'/api/corpora/{row["corpus_id"]}/items/{row["item_id"]}/answer'


@pytest.mark.parametrize("parameter", ["offset", "after"])
@pytest.mark.asyncio
async def test_pagination_rejects_postgres_integer_overflow(api, parameter):
    client, headers, _ = api
    rows, _ = await imported(api)
    route = '/api/corpora' if parameter == 'offset' else f'/api/corpora/{rows[0]["corpus_id"]}/items'
    maximum = 2**31 - 1
    response = await client.get(route, headers=headers(), params={parameter: maximum})
    assert response.status_code == 200
    for value in (maximum + 1, 10**20):
        response = await client.get(route, headers=headers(), params={parameter: value})
        assert response.status_code == 422
        assert response.json()['detail'][0]['loc'] == ['query', parameter]

@pytest.mark.asyncio
async def test_import_suggestions_are_not_labels_and_repeat_preserves(api):
    client,headers,_=api
    rows,data=await imported(api)
    assert data['added']==3
    progress=(await client.get(f'/api/corpora/{rows[0]["corpus_id"]}/progress',headers=headers())).json()
    assert progress['revision_events']==0
    assert all(v['definite']==0 and v['reviewed']==0 for v in progress['kinds'].values())
    export=await client.get(f'/api/corpora/{rows[0]["corpus_id"]}/export.tsv',headers=headers())
    assert len(list(read_tsv(io.StringIO(export.text))))==0
    changed=[{**r,"algorithm_sha256":"c"*64} for r in rows]
    _,data=await imported(api,changed)
    assert data['added']==0 and data['already_present']==3
    q=(await client.get(f'/api/corpora/{rows[0]["corpus_id"]}/items',headers=headers())).json()
    assert q['items'][0]['candidate']['algorithm_sha256']=='b'*64
    await imported(api,rows+[dict(rows[0],item_id=str(uuid4()),word_ref="test:3")])
    assert (await client.get(f'/api/corpora/{rows[0]["corpus_id"]}/progress',headers=headers())).json()['kinds']['pair']['total']==2

@pytest.mark.asyncio
async def test_tenant_isolation_all_routes_and_same_corpus_ids(api):
    client,headers,owners=api
    rows,_=await imported(api)
    row=rows[0];root=f'/api/corpora/{row["corpus_id"]}'
    assert (await client.get('/api/corpora',headers=headers('bob'))).json()['items']==[]
    for tail in ('progress','items','export.tsv','items/'+row['item_id']):
        assert (await client.get(root+'/'+tail,headers=headers('bob'))).status_code==404
    assert (await client.post(path(row),headers=headers('bob'),json=answer())).status_code==404
    assert (await client.post('/api/import',headers=headers('bob'),json={"name":"Bob","candidates":rows})).status_code==200
    assert (await client.post(path(row),headers=headers('alice'),json=answer())).status_code==200
    assert (await client.get(root+'/progress',headers=headers('bob'))).json()['revision_events']==0
    assert list(read_tsv(io.StringIO((await client.get(root+'/export.tsv',headers=headers('bob'))).text)))==[]
    for method,url,body in [('GET','/api/corpora',None),('GET',root+'/items',None),('POST','/api/import',{}),('POST',path(row),answer())]:
        assert (await client.request(method,url,json=body)).status_code==401

@pytest.mark.asyncio
async def test_revisions_retry_race_and_export_roundtrip(api):
    client,headers,owners=api
    rows,_=await imported(api);row=rows[0]
    payload=answer()
    first=await client.post(path(row),headers=headers(),json=payload)
    assert first.status_code==200 and first.json()['revision']==1
    retry=await client.post(path(row),headers=headers(),json=payload)
    assert retry.json()==first.json()
    assert (await client.post(path(row),headers=headers(),json=dict(payload,answer="different"))).status_code==409
    results=await asyncio.gather(*(client.post(path(row),headers=headers(),json=answer(1,value)) for value in ('different','unsure')))
    assert sorted(r.status_code for r in results)==[200,409]
    assert (await client.post(path(row),headers=headers(),json=answer(2,"unsure"))).status_code==200
    assert (await client.post(path(rows[1]),headers=headers(),json=answer(0,"confirmed",lemma=" KUĆA ",irregular=True))).status_code==200
    assert (await client.post(path(rows[2]),headers=headers(),json=answer(0,"accept"))).status_code==200
    root=f'/api/corpora/{row["corpus_id"]}'
    state=(await client.get(root+'/progress',headers=headers())).json()
    assert state['revision_events']==5
    assert state['kinds']['pair']=={'total':1,'reviewed':1,'unsure':1,'definite':0}
    r=await client.get(root+'/export.tsv',headers=headers())
    exported=list(read_tsv(io.StringIO(r.text)))
    assert len(exported)==5
    assert all(x.annotator_id==owners['alice'] and x.provenance=='human' for x in exported)
    assert sorted(x.revision for x in exported if x.kind=='pair')==[1,2,3]
    assert next(x for x in exported if x.kind=='lemma').lemma=='kuća'
    assert r.headers['cache-control']=='no-store'

@pytest.mark.asyncio
async def test_invalid_answers_and_immutable_source_do_not_write(api):
    client,headers,_=api
    rows,_=await imported(api);row=rows[0]
    for payload in (answer(value="confirmed",lemma="kuća"),answer(owner_id="spoof"),answer(irregular="false"),answer(revision=True)):
        assert (await client.post(path(row),headers=headers(),json=payload)).status_code==422
    for key,value in (('word','dom'),('source_uri','urn:other')):
        altered=[dict(row,**{key:value})]
        assert (await client.post('/api/import',headers=headers(),json={'name':'Changed','candidates':altered})).status_code==409
    for changed in (dict(row,answer="same"),dict(row,word="x"*129),dict(row,candidate_schema_version=True)):
        assert (await client.post('/api/import',headers=headers(),json={'name':'Invalid','candidates':[changed]})).status_code==422
    assert (await client.get(f'/api/corpora/{row["corpus_id"]}/progress',headers=headers())).json()['revision_events']==0

@pytest.mark.asyncio
async def test_body_limits(api):
    client,headers,_=api
    r=await client.post('/api/import',headers={**headers(),'Content-Length':str(32*1024*1024+1)},content=b'')
    assert r.status_code==413
    async def chunks():
        for _ in range(5):
            yield b'x'*4096
    r=await client.post('/api/corpora/'+str(uuid4())+'/items/'+str(uuid4())+'/answer',headers={**headers(),'Content-Type':'application/json'},content=chunks())
    assert r.status_code==413,r.text

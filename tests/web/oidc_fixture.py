"""Synthetic OIDC browser fixture, bound to loopback; never a deployment auth mode.

Checks authorization-code PKCE and nonce using real RS256 tokens. Tests label
only urn:test candidates. This is not a substitute for production Keycloak SSO
acceptance or evidence of actual human annotations.
"""
import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlencode
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

ISSUER = 'http://127.0.0.1:55485/realms/test'
CLIENT = 'croatian-stemmer-labeling-web'
AUDIENCE = 'croatian-stemmer-labeling-api'
REDIRECT = 'http://127.0.0.1:55484/'
PRIVATE = rsa.generate_private_key(public_exponent=65537,key_size=2048)
SUBJECT = str(uuid4())
app = FastAPI()
app.add_middleware(CORSMiddleware,allow_origins=['http://127.0.0.1:55484'],allow_credentials=True,allow_methods=['GET','POST'],allow_headers=['Content-Type'])
codes = {}

@app.get('/realms/test/protocol/openid-connect/certs')
async def certs():
    key=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(PRIVATE.public_key()))
    return {'keys':[{**key,'kid':'fixture','use':'sig','alg':'RS256'}]}

@app.get('/realms/test/protocol/openid-connect/auth')
async def authorize(request: Request):
    p=request.query_params
    if (p.get('client_id')!=CLIENT or p.get('redirect_uri')!=REDIRECT or p.get('response_type')!='code'
        or p.get('code_challenge_method')!='S256' or not p.get('code_challenge') or not p.get('nonce')):
        raise HTTPException(400,'invalid fixture authorization')
    if p.get('prompt')=='none':
        return RedirectResponse(REDIRECT+'?'+urlencode({'error':'login_required','state':p['state']}))
    code=str(uuid4());codes[code]=dict(p)
    return RedirectResponse(REDIRECT+'?'+urlencode({'code':code,'state':p['state'],'session_state':'synthetic-fixture','iss':ISSUER}))

@app.post('/realms/test/protocol/openid-connect/token')
async def token(request: Request):
    p={k:v[0] for k,v in parse_qs((await request.body()).decode()).items()}
    issued=codes.pop(p.get('code'),None)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(p.get('code_verifier','').encode()).digest()).decode().rstrip('=')
    if (not issued or p.get('grant_type')!='authorization_code' or p.get('client_id')!=CLIENT
        or p.get('redirect_uri')!=REDIRECT or challenge!=issued['code_challenge']):
        raise HTTPException(400,'invalid fixture PKCE')
    now=int(time.time())
    common={'sub':SUBJECT,'iss':ISSUER,'iat':now,'exp':now+600,'session_state':'synthetic-fixture','preferred_username':'sintetički-test'}
    access={**common,'aud':AUDIENCE,'azp':CLIENT,'typ':'Bearer','resource_access':{AUDIENCE:{'roles':['annotator']}}}
    identity={**common,'aud':CLIENT,'nonce':issued['nonce']}
    sign=lambda payload:jwt.encode(payload,PRIVATE,algorithm='RS256',headers={'kid':'fixture'})
    return {'access_token':sign(access),'id_token':sign(identity),'refresh_token':sign({**common,'typ':'Refresh'}),'token_type':'Bearer','expires_in':600}

@app.get('/realms/test/protocol/openid-connect/logout')
async def logout(request: Request):
    if request.query_params.get('post_logout_redirect_uri')!=REDIRECT:
        raise HTTPException(400,'invalid redirect')
    return RedirectResponse(REDIRECT)

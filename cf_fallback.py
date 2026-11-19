"""Cloudflare free-allocation fallback with a shared, durable neuron budget."""
import base64
import json
import math
import os
import time
from datetime import datetime, timedelta, timezone

TEXT_MODEL='@cf/openai/gpt-oss-120b'
VISION_MODEL='@cf/meta/llama-4-scout-17b-16e-instruct'

def enabled(cfg):
    return cfg.get('cloudflare_fallback',{}).get('enabled') is True

def available(cfg):
    return enabled(cfg) and bool(os.environ.get('CF_ACCOUNT_ID') and os.environ.get('CF_API_TOKEN'))

def neuron_budget(store,cfg,cost,*,commit=False,receipt=None):
    from providers import Held,Deferred
    settings=cfg.get('cloudflare_fallback',{})
    limit=settings.get('daily_neuron_limit',9000)
    if not cfg.get('free_only') or not 1<=limit<=10000 or cost<=0:
        raise Held('Invalid Cloudflare free-allocation guard')
    day=datetime.now(timezone.utc).date().isoformat()
    with store.db:
        store.db.execute('CREATE TABLE IF NOT EXISTS cf_neurons(day TEXT PRIMARY KEY,reserved INTEGER NOT NULL)')
        store.db.execute('CREATE TABLE IF NOT EXISTS cf_receipts(id TEXT PRIMARY KEY,day TEXT NOT NULL,estimated INTEGER NOT NULL,settled INTEGER NOT NULL DEFAULT 0,actual INTEGER)')
        # Preserve pre-fallback image usage when first installing this ledger.
        old=store.db.execute("SELECT images FROM usage WHERE day=? AND provider='cloudflare'",(day,)).fetchone()
        store.db.execute('INSERT OR IGNORE INTO cf_neurons VALUES(?,?)',(day,(old[0] if old else 0)*128))
        used=store.db.execute('SELECT reserved FROM cf_neurons WHERE day=?',(day,)).fetchone()[0]
        if used+cost>limit:
            now=datetime.now(timezone.utc)
            reset=(now+timedelta(days=1)).replace(hour=0,minute=0,second=5,microsecond=0)
            raise Deferred('Cloudflare shared free-allocation budget reached',reset.timestamp())
        if commit:
            store.db.execute('UPDATE cf_neurons SET reserved=reserved+? WHERE day=?',(cost,day))
            if receipt is not None:
                store.db.execute('INSERT INTO cf_receipts(id,day,estimated,settled) VALUES(?,?,?,0)',(receipt,day,cost))

def chat(pool,system,prompt,cap,*,image=None):
    from providers import Held
    if not available(pool.cfg):
        raise Held('Cloudflare fallback requires this project account/token and explicit configuration')
    model=pool.cfg['cloudflare_fallback']['vision_model' if image is not None else 'text_model']
    if model!=(VISION_MODEL if image is not None else TEXT_MODEL):
        raise Held('Cloudflare fallback model outside verified free-allocation allowlist')
    input_bound=len((system+prompt).encode('utf-8'))+300+(16384 if image is not None else 0)
    completion_bound=cap+(512 if image is None else 0)
    reservation=input_bound+completion_bound
    provider='cloudflare_vision' if image is not None else 'cloudflare_text'
    if reservation>pool.cfg['limits'][provider]['max_request_tokens']:
        raise Held(provider+': request exceeds bounded input')
    # Official 2026-11-17 neuron/M-token rates, conservative UTF-8 upper bound.
    in_rate,out_rate=(24545,77273) if image is not None else (31818,68182)
    neurons=math.ceil((input_bound*in_rate+completion_bound*out_rate)/1_000_000)+8
    content=prompt
    if image is not None:
        content=[{'type':'text','text':prompt},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(image).decode('ascii')}}]
    payload={'model':model,'messages':[{'role':'system','content':system},{'role':'user','content':content}],
             'max_tokens':completion_bound,'temperature':0.1,'response_format':{'type':'json_object'},'stream':False}
    if image is None:payload['reasoning_effort']='low'
    response=pool.request(provider,'https://api.cloudflare.com/client/v4/accounts/'+os.environ['CF_ACCOUNT_ID']+'/ai/v1/chat/completions',
                          tokens=reservation,neurons=neurons,
                          headers={'Authorization':'Bearer '+os.environ['CF_API_TOKEN']},json=payload)
    obj=response.json()
    if not isinstance(obj,dict):raise Held('Malformed Cloudflare response')
    settle(pool.store,response,obj,in_rate,out_rate)
    if obj.get('success') is False:
        codes=[str(e.get('code')) for e in obj.get('errors',[])[:3]]
        raise Held('Cloudflare inference rejected; error codes '+','.join(codes))
    result=obj.get('result',obj)
    if 'choices' in result:
        choice=result['choices'][0]
        if choice.get('finish_reason')!='stop':
            from core import digest
            from providers import Deferred
            key='cf_incomplete:'+digest(model+system+prompt+(base64.b64encode(image).decode('ascii') if image is not None else ''))
            record=pool.store.get(key,{})
            day=datetime.now(timezone.utc).date().isoformat()
            attempts=(record.get('attempts',0) if record.get('day')==day else 0)+1
            pool.store.put(key,{'day':day,'attempts':attempts})
            if attempts>=3:
                raise Held('Cloudflare output incomplete after three bounded attempts')
            raise Deferred('Cloudflare output incomplete; bounded retry',pool.store.cooldown(provider))
        value=choice['message']['content']
    else:
        value=result.get('response')
    result=pool.parse(value)
    if image is None:pool.store.put('last_text_provider','cloudflare_text')
    return result

def settle(store,response,obj,in_rate,out_rate):
    """Settle only this receipted call from complete provider usage; never reset history."""
    receipt=getattr(response,'_mah_cf_receipt',None)
    if not isinstance(receipt,str):
        return False
    usage=obj.get('usage',obj.get('result',{}).get('usage',{}))
    a,b=usage.get('prompt_tokens'),usage.get('completion_tokens')
    if type(a) is not int or type(b) is not int or a<0 or b<0 or a+b==0:
        return False
    actual=math.ceil((a*in_rate+b*out_rate)/1_000_000)+8
    with store.db:
        row=store.db.execute('SELECT day,estimated,settled FROM cf_receipts WHERE id=?',(receipt,)).fetchone()
        if row is None or row[2]:
            return False
        day,estimated,_=row
        if actual>estimated:
            # Unexpected metering violates our conservative bound: stop further
            # calls instead of trusting an undercount or refunding unknown usage.
            store.db.execute('UPDATE cf_neurons SET reserved=MAX(reserved,10000) WHERE day=?',(day,))
            store.db.execute('UPDATE cf_receipts SET settled=1,actual=? WHERE id=?',(actual,receipt))
            return False
        store.db.execute('UPDATE cf_neurons SET reserved=reserved-?+? WHERE day=?',(estimated,actual,day))
        store.db.execute('UPDATE cf_receipts SET settled=1,actual=? WHERE id=?',(actual,receipt))
    return True

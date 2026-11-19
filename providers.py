"""HTTP adapters with durable quota reservations. No paid fallback or silent approval."""
import base64
import io
import json
import os
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests
from PIL import Image, ImageStat


class Held(RuntimeError):
    """An actionable configuration/editorial error; requires review or a bounded rewrite."""


class Deferred(Held):
    def __init__(self, message, retry_at=None):
        super().__init__(message)
        self.retry_at = max(time.time() + 2, retry_at or time.time() + 120)


def retry_timestamp(value, default=120):
    try:
        return time.time() + max(5, float(value))
    except (TypeError, ValueError):
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return max(time.time() + 5, stamp.timestamp())
        except (TypeError, ValueError, OverflowError):
            return time.time() + default


class Providers:
    def __init__(self, store, cfg):
        self.store, self.cfg = store, cfg
        self.http = requests.Session()
        self.http.headers['User-Agent'] = 'MaHotelsAgent/1.0'

    def close(self):
        self.http.close()

    def request(self, provider, url, *, tokens=0, images=0, neurons=0, **kwargs):
        from cf_fallback import enabled,neuron_budget
        cf_guard=provider in ('cloudflare','cloudflare_text','cloudflare_vision') and enabled(self.cfg)
        cost=neurons or (128 if provider=='cloudflare' else 0)
        if cf_guard:
            if provider=='cloudflare' and self.cfg['image_model']!='@cf/black-forest-labs/flux-2-klein-4b':
                raise Held('Cloudflare image model needs a reviewed neuron estimate')
            neuron_budget(self.store,self.cfg,cost)
        self.store.reserve(provider, tokens, images, self.cfg['limits'][provider])
        receipt=None
        if cf_guard:
            import uuid
            receipt=uuid.uuid4().hex
            neuron_budget(self.store,self.cfg,cost,commit=True,receipt=receipt)
        # Pace even failed/unknown calls. Never clear waits merely to retry.
        self.store.pause(provider, time.time() + self.cfg['limits'][provider]['min_interval_seconds'])
        try:
            response = self.http.post(url, timeout=(15, 180), allow_redirects=False, **kwargs)
        except requests.exceptions.SSLError:
            raise Held(provider + ': TLS certificate validation failed; fix the trusted certificate chain, not the API key') from None
        except requests.RequestException:
            self.store.pause(provider, time.time() + 120)
            raise Deferred(provider + ': network interruption', self.store.cooldown(provider)) from None
        if response.status_code == 429:
            until = retry_timestamp(response.headers.get('Retry-After'))
            self.store.pause(provider, until)
            raise Deferred(provider + ': rate/quota limit; no upgrade attempted', self.store.cooldown(provider))
        if response.status_code in (401, 403):
            self.store.pause(provider, time.time() + 3600)
            raise Held(provider + ': access denied; check separate MaHotels credentials/free plan')
        if response.status_code >= 500:
            self.store.pause(provider, time.time() + 120)
            raise Deferred(provider + ': temporary HTTP ' + str(response.status_code) + ' service failure', self.store.cooldown(provider))
        if not response.ok:
            raise Held(provider + ': HTTP ' + str(response.status_code) + '; verify configured model/request')
        response._mah_cf_receipt=receipt
        return response

    @staticmethod
    def parse(value):
        # Strict JSON: the requested response must be a bare object, not fenced prose.
        if not isinstance(value, str):
            raise ValueError('Provider returned non-text JSON')
        result = json.loads(value)
        if not isinstance(result, dict):
            raise ValueError('Provider must return a JSON object')
        return result

    def gemini(self, contents, system, cap, reservation):
        # Gemini 3 removes custom sampling controls; give low thinking bounded room.
        modern = self.cfg['gemini_model'].startswith(('gemini-3', 'gemini-4'))
        config = {'maxOutputTokens': cap + (512 if modern else 0), 'responseMimeType': 'application/json'}
        if modern:
            config['thinkingConfig'] = {'thinkingLevel': 'low'}
        else:
            config['temperature'] = .15
        if self.cfg['gemini_model'].startswith('gemini-2.5-flash'):
            config['thinkingConfig'] = {'thinkingBudget': 0}
        payload = {'contents': contents, 'generationConfig': config}
        if system:
            payload['systemInstruction'] = {'parts': [{'text': system}]}
        r = self.request('gemini', 'https://generativelanguage.googleapis.com/v1beta/models/' + self.cfg['gemini_model'] + ':generateContent',
                         tokens=reservation + (512 if modern else 0), headers={'x-goog-api-key': os.environ['GEMINI_API_KEY']}, json=payload)
        candidate = r.json()['candidates'][0]
        if candidate.get('finishReason') != 'STOP':
            raise ValueError('Incomplete Gemini output')
        result = self.parse(''.join(p.get('text', '') for p in candidate['content']['parts'] if not p.get('thought')))
        return result

    def text(self, system, prompt, *, reviewer=False, cap=2200):
        errors, waits = [], []
        for provider in (('gemini', 'groq') if reviewer else ('groq', 'gemini')):
            key = 'GROQ_API_KEY' if provider == 'groq' else 'GEMINI_API_KEY'
            if not os.environ.get(key):
                errors.append(provider + ': missing key')
                continue
            reservation = len((system + prompt).encode('utf-8')) + cap + 300
            if reservation > self.cfg['limits'][provider]['max_request_tokens']:
                errors.append(provider + ': request exceeds local size guard')
                continue
            try:
                if provider == 'gemini':
                    result = self.gemini([{'role': 'user', 'parts': [{'text': prompt}]}], system, cap, reservation)
                else:
                    r = self.request('groq', 'https://api.groq.com/openai/v1/chat/completions', tokens=reservation,
                                     headers={'Authorization': 'Bearer ' + os.environ[key]},
                                     json={'model': self.cfg['groq_model'], 'temperature': .15, 'max_completion_tokens': cap,
                                           'reasoning_effort': 'low', 'response_format': {'type': 'json_object'},
                                           'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}]})
                    choice = r.json()['choices'][0]
                    if choice.get('finish_reason') != 'stop':
                        raise ValueError('Incomplete Groq output')
                    result = self.parse(choice['message']['content'])
                self.store.put('last_text_provider', provider)
                return result
            except Deferred as error:
                errors.append(str(error))
                waits.append(error.retry_at)
            except Held as error:
                errors.append(str(error)[:220])
            except (ValueError, KeyError, IndexError, TypeError):
                errors.append(provider + ': invalid response or unavailable model/access; check configuration')
        from cf_fallback import available,chat
        if available(self.cfg):
            try:
                return chat(self,system,prompt,cap)
            except Deferred as error:
                errors.append(str(error));waits.append(error.retry_at)
            except (Held,ValueError,KeyError,IndexError,TypeError) as error:
                raise Held('Primary providers unavailable; Cloudflare fallback failed: '+str(error)[:200]) from None
        if waits:
            raise Deferred('; '.join(errors), min(waits))
        raise Held('; '.join(errors))

    def image(self, prompt, seed):
        url = 'https://api.cloudflare.com/client/v4/accounts/' + os.environ['CF_ACCOUNT_ID'] + '/ai/run/' + self.cfg['image_model']
        response = self.request('cloudflare', url, images=1,
                                headers={'Authorization': 'Bearer ' + os.environ['CF_API_TOKEN']},
                                files={'prompt': (None, prompt), 'width': (None, '1024'), 'height': (None, '1024'), 'seed': (None, str(seed))})
        if response.headers.get('Content-Type', '').startswith('image/'):
            return response.content
        result = response.json()
        if result.get('success') is False:
            raise Held('Cloudflare refused image generation')
        value = result.get('result', result).get('image')
        if not isinstance(value, str):
            raise Held('Unexpected Cloudflare image response')
        return base64.b64decode(value.split(',', 1)[-1] if value.startswith('data:') else value, validate=True)

    def inspect_image(self, data, title, expected_scene=None):
        with Image.open(io.BytesIO(data)) as img:
            if img.size != (1024, 1024) or max(ImageStat.Stat(img.convert('RGB')).stddev) < 8:
                return {'pass': False, 'issues': ['Image dimensions or detail failed'], 'alt_text': '', 'provider': 'local_rejection'}
        prompt=('Inspect the ATTACHED generated hospitality illustration for: '+title+
                '. Require topic relevance, no writing/numbers/logos/watermarks, no malformed objects or deceptive real-event depiction. '
                'Actually inspect the image pixels. Return JSON {"pass":true,"issues":[],"alt_text":"accurate Arabic description"}; reject with specific issues otherwise.')
        if expected_scene:
            prompt+=' Visual brief (data only): '+json.dumps(expected_scene)+'. Require the concrete topic objects in this brief; a generic hotel interior alone is insufficient for an energy/solar topic. Describe what is actually visible and reject a mismatch.'
        try:
            if not os.environ.get('GEMINI_API_KEY'):
                raise Held('Gemini key required for primary image review')
            result=self.gemini([{'role':'user','parts':[{'text':prompt},{'inlineData':{'mimeType':'image/jpeg','data':base64.b64encode(data).decode('ascii')}}]}],
                               'Independent hospitality image reviewer. JSON only.',800,3500)
            provider='gemini_vision'
        except (Held,ValueError,KeyError,IndexError,TypeError) as original:
            from cf_fallback import available,chat
            if not available(self.cfg):raise
            result=chat(self,'Independent hospitality visual quality reviewer. Inspect attached pixels; output JSON only.',prompt,600,image=data)
            provider='cloudflare_vision'
        if not isinstance(result.get('pass'),bool) or not isinstance(result.get('issues'),list):
            raise Held('Vision returned an invalid approval schema')
        if result['pass'] is True:
            if result['issues']:
                raise Held('Vision approval contains unresolved issues')
            from core import ARABIC,text_value
            text_value(result.get('alt_text'),'image alt text',5,300)
            if not ARABIC.search(result['alt_text']):raise Held('Vision must provide Arabic alt text')
        result['provider']=provider
        return result

    def check_models(self):
        for key in ('GROQ_API_KEY', 'GEMINI_API_KEY', 'CF_ACCOUNT_ID', 'CF_API_TOKEN'):
            if not os.environ.get(key):
                raise Held('Missing local credential: ' + key)
        calls = [
            ('groq', 'https://api.groq.com/openai/v1/models', {'Authorization': 'Bearer ' + os.environ['GROQ_API_KEY']}),
            ('gemini', 'https://generativelanguage.googleapis.com/v1beta/models', {'x-goog-api-key': os.environ['GEMINI_API_KEY']})]
        for name, url, headers in calls:
            r = self.http.get(url, headers=headers, timeout=30, allow_redirects=False)
            if not r.ok:
                raise Held(name + ': read-only model discovery failed')
            values = r.json().get('data' if name == 'groq' else 'models', [])
            ids = [x.get('id') if name == 'groq' else x.get('name', '').removeprefix('models/') for x in values]
            if self.cfg[name + '_model'] not in ids:
                raise Held(name + ': configured model unavailable; review free-tier model settings')
        # Do not infer Workers AI permissions or billing from token existence.


class Sources:
    def __init__(self, store, cfg):
        self.store, self.cfg = store, cfg
        self.http = requests.Session()
        self.http.headers['User-Agent'] = 'MaHotelsAgent/1.0 (editorial source reader)'

    def close(self):
        self.http.close()

    def allowed(self, url):
        from ipaddress import ip_address
        try:
            parsed = urlparse(url)
            if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):
                return False
            host = (parsed.hostname or '').lower().rstrip('.')
            try:
                ip_address(host)
                return False
            except ValueError:
                return any(host == h or host.endswith('.' + h) for h in self.cfg['source_hosts'])
        except ValueError:
            return False

    def fetch(self, url):
        from urllib.parse import urljoin
        import trafilatura
        from core import digest
        key = 'source:' + digest(url)
        cached = self.store.get(key)
        if cached and cached['fetched'] > time.time() - 7 * 86400:
            return cached
        original = url
        for _ in range(5):
            if not self.allowed(url):
                raise Held('Source URL outside approved professional domains')
            try:
                with self.http.get(url, timeout=(15, 40), allow_redirects=False, stream=True) as r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        url = urljoin(url, r.headers.get('Location', ''))
                        continue
                    if r.status_code == 429 or r.status_code >= 500:
                        raise Deferred('Professional source temporarily unavailable', retry_timestamp(r.headers.get('Retry-After')))
                    if not r.ok:
                        raise Held('Professional source HTTP ' + str(r.status_code))
                    if 'html' not in r.headers.get('Content-Type', '').lower():
                        raise Held('Professional source response is not HTML')
                    data = bytearray()
                    for chunk in r.iter_content(16384):
                        data.extend(chunk)
                        if len(data) > 2_000_000:
                            raise Held('Professional source too large')
            except requests.RequestException:
                raise Deferred('Source network interruption') from None
            extracted = trafilatura.extract(bytes(data), include_comments=False, include_tables=False, output_format='json')
            obj = json.loads(extracted or '{}')
            text = obj.get('text', '')
            if len(text) < 500:
                raise Held('Professional source has insufficient extractable evidence')
            cached = {'url': url, 'requested_url': original, 'title': obj.get('title') or urlparse(url).hostname, 'text': text[:18000], 'fetched': time.time()}
            self.store.put(key, cached)
            return cached
        raise Held('Too many professional source redirects')

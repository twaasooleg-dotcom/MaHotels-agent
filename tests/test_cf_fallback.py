import io
import json
import os
import time
from unittest.mock import Mock,patch
from PIL import Image
from cf_fallback import chat,neuron_budget,TEXT_MODEL,VISION_MODEL
from providers import Providers,Held,Deferred
from test_agent import StoreCase,config

class CloudflareFallbackTests(StoreCase):
    def pool(self):
        p=Providers(self.store,config());self.addCleanup(p.close);return p

    def test_exhausted_primary_providers_use_real_fallback_without_resetting_them(self):
        p=self.pool()
        for provider in ('groq','gemini'):
            self.store.reserve(provider,config()['limits'][provider]['tokens'],0,config()['limits'][provider])
        before=[tuple(r) for r in self.store.db.execute("SELECT * FROM usage WHERE provider IN ('groq','gemini')")]
        response=Mock(status_code=200,ok=True,headers={})
        response.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':'{"pass":false,"issues":["unsupported claim"]}'}}]}
        p.http.post=Mock(return_value=response)
        with patch.dict(os.environ,{'GROQ_API_KEY':'test','GEMINI_API_KEY':'test','CF_ACCOUNT_ID':'test','CF_API_TOKEN':'test'}):
            result=p.text('Reviewer','Review claim',reviewer=True,cap=300)
        self.assertFalse(result['pass'])
        self.assertEqual(p.http.post.call_count,1)
        self.assertEqual(self.store.get('last_text_provider'),'cloudflare_text')
        self.assertEqual(before,[tuple(r) for r in self.store.db.execute("SELECT * FROM usage WHERE provider IN ('groq','gemini')")])
        self.assertGreater(self.store.db.execute('SELECT reserved FROM cf_neurons').fetchone()[0],0)

    def test_shared_budget_blocks_network_and_cannot_be_cleared_by_retry(self):
        p=self.pool()
        neuron_budget(self.store,p.cfg,p.cfg['cloudflare_fallback']['daily_neuron_limit'],commit=True)
        p.http.post=Mock()
        with patch.dict(os.environ,{'CF_ACCOUNT_ID':'test','CF_API_TOKEN':'test'}):
            for _ in range(2):
                with self.assertRaises(Deferred):chat(p,'System','Prompt',300)
        p.http.post.assert_not_called()
        self.assertEqual(self.store.db.execute('SELECT reserved FROM cf_neurons').fetchone()[0],p.cfg['cloudflare_fallback']['daily_neuron_limit'])

    def test_network_failure_keeps_neuron_and_request_reservations(self):
        import requests
        p=self.pool();p.http.post=Mock(side_effect=requests.ConnectionError())
        with patch.dict(os.environ,{'CF_ACCOUNT_ID':'test','CF_API_TOKEN':'test'}):
            with self.assertRaises(Deferred):chat(p,'System','Prompt',300)
        self.assertGreater(self.store.db.execute('SELECT reserved FROM cf_neurons').fetchone()[0],0)
        self.assertEqual(self.store.db.execute("SELECT requests FROM usage WHERE provider='cloudflare_text'").fetchone()[0],1)

    def test_actual_vision_payload_contains_pixels_and_rejects_bad_alt(self):
        p=self.pool();p.gemini=Mock(side_effect=Deferred('Gemini quota'))
        out=io.BytesIO();Image.effect_noise((1024,1024),50).convert('RGB').save(out,format='JPEG')
        p.request=Mock()
        p.request.return_value.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':'{"pass":true,"issues":[],"alt_text":"صورة توضيحية لاستقبال فندقي"}'}}]}
        with patch.dict(os.environ,{'CF_ACCOUNT_ID':'test','CF_API_TOKEN':'test','GEMINI_API_KEY':'test'}):
            result=p.inspect_image(out.getvalue(),'Hotel reception')
        self.assertEqual(result['provider'],'cloudflare_vision')
        payload=p.request.call_args.kwargs['json']
        self.assertEqual(payload['model'],VISION_MODEL)
        self.assertTrue(payload['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,'))
        self.assertGreater(p.request.call_args.kwargs['neurons'],0)

    def test_truncated_json_never_becomes_approval(self):
        p=self.pool();p.request=Mock()
        p.request.return_value.json.return_value={'choices':[{'finish_reason':'length','message':{'content':'{"pass":true}'}}]}
        with patch.dict(os.environ,{'CF_ACCOUNT_ID':'test','CF_API_TOKEN':'test'}):
            with self.assertRaises(Held):chat(p,'System','Prompt',300)

    def test_only_verified_free_models_allowed(self):
        p=self.pool();p.cfg['cloudflare_fallback']['text_model']='@cf/unknown/paid-model';p.http.post=Mock()
        with patch.dict(os.environ,{'CF_ACCOUNT_ID':'test','CF_API_TOKEN':'test'}):
            with self.assertRaises(Held):chat(p,'System','Prompt',300)
        p.http.post.assert_not_called()

    def test_vision_failure_never_uses_local_approval(self):
        p=self.pool();p.gemini=Mock(side_effect=Deferred('Gemini quota'))
        p.request=Mock(side_effect=Deferred('Cloudflare quota'))
        out=io.BytesIO();Image.effect_noise((1024,1024),50).convert('RGB').save(out,format='JPEG')
        with patch.dict(os.environ,{'CF_ACCOUNT_ID':'test','CF_API_TOKEN':'test','GEMINI_API_KEY':'test'}):
            with self.assertRaises(Deferred):p.inspect_image(out.getvalue(),'Hotel')

    def test_images_share_the_same_neuron_cap(self):
        p=self.pool();neuron_budget(self.store,p.cfg,p.cfg['cloudflare_fallback']['daily_neuron_limit']-10,commit=True);p.http.post=Mock()
        with patch.dict(os.environ,{'CF_ACCOUNT_ID':'test','CF_API_TOKEN':'test'}):
            with self.assertRaises(Deferred):p.image('hotel',123)
        p.http.post.assert_not_called()

    def test_incomplete_output_retry_is_bounded_and_never_approved(self):
        p=self.pool();p.request=Mock()
        p.request.return_value.json.return_value={'choices':[{'finish_reason':'length','message':{'content':'{}'}}]}
        with patch.dict(os.environ,{'CF_ACCOUNT_ID':'test','CF_API_TOKEN':'test'}):
            for _ in range(2):
                with self.assertRaises(Deferred):chat(p,'System','incomplete unique prompt',300)
            with self.assertRaises(Held) as caught:chat(p,'System','incomplete unique prompt',300)
            self.assertNotIsInstance(caught.exception,Deferred)

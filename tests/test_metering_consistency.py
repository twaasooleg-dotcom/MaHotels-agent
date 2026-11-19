from types import SimpleNamespace
from unittest.mock import Mock
from cf_fallback import neuron_budget,settle
from article_parts import validate_part
from test_agent import StoreCase,config,article

class MeteringSettlementTests(StoreCase):
    def reserve(self,key='r1',cost=200):
        neuron_budget(self.store,config(),cost,commit=True,receipt=key)
        return SimpleNamespace(_mah_cf_receipt=key)

    def test_only_current_completed_request_is_settled(self):
        neuron_budget(self.store,config(),6000,commit=True)
        response=self.reserve()
        self.assertTrue(settle(self.store,response,{'usage':{'prompt_tokens':100,'completion_tokens':10}},31818,68182))
        self.assertEqual(self.store.db.execute('SELECT reserved FROM cf_neurons').fetchone()[0],6012)

    def test_duplicate_settlement_cannot_refund_twice(self):
        response=self.reserve()
        body={'usage':{'prompt_tokens':100,'completion_tokens':10}}
        self.assertTrue(settle(self.store,response,body,31818,68182))
        used=self.store.db.execute('SELECT reserved FROM cf_neurons').fetchone()[0]
        self.assertFalse(settle(self.store,response,body,31818,68182))
        self.assertEqual(self.store.db.execute('SELECT reserved FROM cf_neurons').fetchone()[0],used)

    def test_missing_negative_or_unreceipted_usage_never_refunds(self):
        response=self.reserve()
        for usage in ({},{'prompt_tokens':-1,'completion_tokens':5},{'prompt_tokens':0,'completion_tokens':0}):
            self.assertFalse(settle(self.store,response,{'usage':usage},31818,68182))
        self.assertFalse(settle(self.store,SimpleNamespace(),{'usage':{'prompt_tokens':1,'completion_tokens':1}},31818,68182))
        self.assertEqual(self.store.db.execute('SELECT reserved FROM cf_neurons').fetchone()[0],200)

    def test_unexpected_over_bound_usage_stops_further_calls(self):
        response=self.reserve(cost=20)
        self.assertFalse(settle(self.store,response,{'usage':{'prompt_tokens':10000,'completion_tokens':10000}},31818,68182))
        self.assertEqual(self.store.db.execute('SELECT reserved FROM cf_neurons').fetchone()[0],10000)

    def test_failed_request_keeps_full_reservation(self):
        self.reserve()
        self.assertEqual(self.store.db.execute('SELECT settled FROM cf_receipts').fetchone()[0],0)
        self.assertEqual(self.store.db.execute('SELECT reserved FROM cf_neurons').fetchone()[0],200)

class PartConsistencyTests(StoreCase):
    def test_shorter_section_is_valid_when_final_article_rules_hold(self):
        section=article()['sections'][0]
        for p in section['paragraphs']:p['text']='خدمة '*60
        validate_part('section',section,[{'id':1}])

    def test_appended_paragraph_must_have_valid_length_and_evidence(self):
        p={'heading':'تفصيل عملي','text':'خدمة '*85,'source_ids':[1]}
        validate_part('append_paragraph',p,[{'id':1}])
        p['source_ids']=[999]
        with self.assertRaises(ValueError):validate_part('append_paragraph',p,[{'id':1}])

    def test_malformed_part_is_rejected_without_attribute_error(self):
        for value in (None, [], 'not an object'):
            with self.assertRaises(ValueError):validate_part('section',value,[{'id':1}])

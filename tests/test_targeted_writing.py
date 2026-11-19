import copy
import json
from unittest.mock import Mock
from article_parts import validate_part, structural_targets, apply_part
from providers import Deferred, Held
from core import words, validate_article
from test_agent import StoreCase, article

class TargetedWritingTests(StoreCase):
    def test_editorial_repair_keeps_valid_article_and_review_cache(self):
        job,data=self.job(state='reviewing')
        a=self.agent()
        data['review_cache']={'unchanged':{'pass':True}}
        original=copy.deepcopy(data['article'])
        a.revise(job,data,['Correct only the opening grammar'],targets=[{'kind':'opening','index':0}])
        saved=json.loads(self.store.jobs()[0]['data'])
        self.assertEqual(saved['article'],original)
        self.assertIn('unchanged',saved['review_cache'])
        self.assertEqual(saved['repair_queue'][0]['kind'],'opening')
        self.assertFalse(saved.get('text_reviewed',False))

    def test_invalid_replacement_never_overwrites_saved_section_and_holds_after_three(self):
        job,data=self.job(state='writing')
        a=self.agent()
        original=copy.deepcopy(data['article'])
        data['repair_queue']=[{'kind':'section','index':1,'attempts':0}]
        bad=copy.deepcopy(original['sections'][1])
        for p in bad['paragraphs']:p['text']='خدمة '*43
        a.pool.text.return_value=bad
        a.write_step(job,data)
        a.write_step(job,data)
        with self.assertRaises(Held):
            a.write_step(job,data)
        self.assertEqual(data['article'],original)
        self.assertEqual(data['repair_queue'][0]['attempts'],3)
        self.assertFalse(data.get('text_reviewed',False))

    def test_deferred_repair_retains_queue_and_part_attempt_budget(self):
        job,data=self.job(state='writing')
        a=self.agent()
        data['repair_queue']=[{'kind':'opening','index':0,'attempts':0}]
        data.pop('text_reviewed',None)
        data.pop('image_checked',None)
        original=copy.deepcopy(data)
        a.pool.text.side_effect=Deferred('quota')
        with self.assertRaises(Deferred):a.write_step(job,data)
        self.assertEqual(data,original)

    def test_successful_opening_repair_changes_no_sections_and_requires_review(self):
        job,data=self.job(state='writing')
        a=self.agent()
        before=copy.deepcopy(data['article']['sections'])
        data['repair_queue']=[{'kind':'opening','index':0,'attempts':0}]
        a.pool.text.return_value={'intro':'ضيافة '*50,'excerpt':'ملخص مهني','source_ids':[1],'image_prompt':'hotel illustration'}
        a.write_step(job,data)
        self.assertEqual(data['article']['sections'],before)
        self.assertEqual(data['repair_queue'],[])
        self.assertFalse(data.get('text_reviewed',False))
        self.assertEqual(self.store.jobs()[0]['state'],'writing')

    def test_short_article_plans_only_needed_sections_without_mutation(self):
        job,data=self.job(state='writing')
        a=self.agent()
        for s in data['article']['sections']:
            for p in s['paragraphs']:p['text']='ضيافة '*55
        before=copy.deepcopy(data['article'])
        plan=structural_targets(before,data['evidence'],a.cfg)
        self.assertTrue(plan)
        self.assertLessEqual(len(plan),8)
        self.assertTrue(all(t['kind']=='append_paragraph' for t in plan))
        self.assertEqual(before,data['article'])
        for t in plan:
            apply_part(before,'append_paragraph',t['index'],article()['sections'][t['index']]['paragraphs'][0])
        self.assertGreaterEqual(words(before),a.cfg['min_article_words'])

    def test_new_part_word_count_and_evidence_are_checked_before_commit(self):
        data=article(); section=data['sections'][0]
        validate_part('section',section,[{'id':1}])
        bad=copy.deepcopy(section)
        bad['paragraphs'][0]['source_ids']=[999]
        with self.assertRaises(ValueError):validate_part('section',bad,[{'id':1}])
        bad=copy.deepcopy(section)
        for p in bad['paragraphs']:p['text']='كلمة '*60
        validate_part('section',bad,[{'id':1}])
        short=article()
        for sec in short['sections']:
            for p in sec['paragraphs']:p['text']='ضيافة '*60
        with self.assertRaisesRegex(ValueError,'Article has'):
            validate_article(short,[{'id':1}],self.agent().cfg)

    def test_review_allows_translated_evidence_without_inventing_statistics(self):
        job,data=self.job(state='reviewing')
        a=self.agent()
        a.pool.text.return_value={'pass':False,'issues':['Unsupported guarantee']}
        original=copy.deepcopy(data['article'])
        a.review_step(job,data)
        system,prompt=a.pool.text.call_args.args
        self.assertIn('English',prompt)
        self.assertIn('source_ids',prompt)
        self.assertEqual(data['article'],original)
        self.assertEqual(data['repair_queue'][0]['kind'],'opening')
        self.assertFalse(data.get('text_reviewed',False))

    def test_manual_retry_preserves_article_and_audits_old_revision_budget(self):
        job,data=self.job(state='held')
        a=self.agent()
        data['revisions']=3
        data['held_from']='reviewing'
        data['last_error']='Editorial validation failed'
        self.store.save_job(job['id'],data,state='held')
        self.store.db.execute("UPDATE jobs SET slot=NULL WHERE id=?",(job['id'],))
        self.store.db.commit()
        before=copy.deepcopy(data['article'])
        a.retry_held()
        saved=json.loads(self.store.jobs()[0]['data'])
        self.assertEqual(saved['article'],before)
        self.assertEqual(saved['manual_retries'][-1]['revisions'],3)
        self.assertEqual(saved['revisions'],0)
        self.assertEqual(self.store.jobs()[0]['state'],'reviewing')


class FaqConsistencyTests(StoreCase):
    def test_valid_final_article_faq_is_not_rejected_by_part_validator(self):
        draft=article()
        for entry in draft['faq']:
            entry['answer']='خدمة '*60
        validate_part('faq',{'faq':draft['faq']},[{'id':1}])
        for entry in draft['faq']:
            entry['answer']='خدمة '*101
        with self.assertRaises(ValueError):
            validate_part('faq',{'faq':draft['faq']},[{'id':1}])


class LengthCompletionTests(StoreCase):
    def test_word_completion_does_not_consume_an_extra_semantic_revision(self):
        job,data=self.job(state='writing')
        a=self.agent()
        for section in data['article']['sections']:
            for p in section['paragraphs']:p['text']='ضيافة '*60
        data['revisions']=3
        a.write_step(job,data)
        self.assertEqual(data['revisions'],3)
        self.assertTrue(data['repair_queue'])
        self.assertTrue(all(p['kind']=='append_paragraph' for p in data['repair_queue']))
        a.pool.text.assert_not_called()
        self.assertFalse(data.get('text_reviewed',False))

    def test_append_work_stops_when_length_is_already_sufficient(self):
        job,data=self.job(state='writing')
        a=self.agent()
        data['repair_queue']=[{'kind':'append_paragraph','index':0,'attempts':0}]
        data['revisions']=3
        a.write_step(job,data)
        self.assertEqual(data['repair_queue'],[])
        self.assertEqual(data['revisions'],3)
        self.assertEqual(self.store.jobs()[0]['state'],'reviewing')
        self.assertFalse(data.get('text_reviewed',False))
        a.pool.text.assert_not_called()

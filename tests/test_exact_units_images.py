import copy
import io
import json
from pathlib import Path
from unittest.mock import Mock
from PIL import Image
from agent import SECTION_PURPOSES
from article_parts import apply_part,validate_part,review_targets
from core import digest
from providers import Held
from test_agent import StoreCase,article

class ExactRepairTests(StoreCase):
    def test_reviewer_paragraph_location_maps_only_the_failed_paragraph(self):
        packet={'paragraphs':[{'heading':'أول'},{'heading':'ثان'}]}
        result=review_targets([{'kind':'paragraph','index':2,'paragraph':2}],packet,[{'path':'paragraphs[1].text','problem':'unsupported'}])
        self.assertEqual(result,[{'kind':'paragraph','index':2,'paragraph':3}])

    def test_unlocated_issue_repairs_only_visible_packet_not_whole_section(self):
        packet={'paragraphs':[{'heading':'أول'},{'heading':'ثان'}]}
        result=review_targets([{'kind':'paragraph','index':2,'paragraph':0}],packet,['Unsupported claim'])
        self.assertEqual(len(result),2)
        self.assertTrue(all(t['kind']=='paragraph' for t in result))

    def test_faq_packet_offset_maps_to_original_answer(self):
        result=review_targets([{'kind':'faq_item','index':2}],{'faq':[{'question':'سؤال أ'},{'question':'سؤال ب'}]},[{'path':'faq[0].answer','problem':'unsupported'}])
        self.assertEqual(result,[{'kind':'faq_item','index':2}])

    def test_three_attempt_budget_applies_to_each_part_without_resetting_totals(self):
        job,data=self.job(state='reviewing')
        a=self.agent();data['revision_counts']={};data['revisions']=0
        for i in range(4):
            a.revise(job,data,['Correct this paragraph'],targets=[{'kind':'paragraph','index':0,'paragraph':i}])
        self.assertEqual(data['revisions'],4)
        self.assertTrue(all(n==1 for n in data['revision_counts'].values()))
        for _ in range(2):a.revise(job,data,['Still wrong'],targets=[{'kind':'paragraph','index':0,'paragraph':0}])
        with self.assertRaises(Held):a.revise(job,data,['Still wrong'],targets=[{'kind':'paragraph','index':0,'paragraph':0}])
        self.assertFalse(data.get('text_reviewed',False))

    def test_single_paragraph_and_faq_edits_preserve_other_text(self):
        a=article();before=copy.deepcopy(a)
        p={'heading':'تفصيل مصحح','text':'ضيافة '*70,'source_ids':[1]}
        validate_part('paragraph',p,[{'id':1}]);apply_part(a,'paragraph',1,p,2)
        self.assertEqual(a['sections'][0],before['sections'][0])
        self.assertEqual(a['sections'][1]['paragraphs'][0],before['sections'][1]['paragraphs'][0])
        self.assertEqual(a['sections'][1]['paragraphs'][2],p)
        f={'question':'سؤال مصحح؟','answer':'خدمة '*35,'source_ids':[1]}
        validate_part('faq_item',f,[{'id':1}]);apply_part(a,'faq_item',2,f)
        self.assertEqual(a['faq'][0],before['faq'][0]);self.assertEqual(a['faq'][2],f)

class ImageProvenanceTests(StoreCase):
    def test_stale_image_approval_cannot_publish(self):
        job,data=self.job()
        data['image_prompt_hash']='old prompt'
        a=self.agent()
        with self.assertRaises(Held):a.publish(job,data)
        a.wp.call.assert_not_called()

    def test_changed_scene_regenerates_image_and_passes_scene_to_actual_vision(self):
        job,data=self.job(state='image')
        data['image_prompt_hash']='old prompt'
        a=self.agent()
        path=self.root/(job['slug']+'.jpg');path.write_bytes(b'old image')
        out=io.BytesIO();Image.effect_noise((1024,1024),40).convert('RGB').save(out,format='JPEG')
        a.pool.image.return_value=out.getvalue()
        a.pool.inspect_image.return_value={'pass':True,'issues':[],'alt_text':'صورة توضيحية لفندق','provider':'gemini_vision'}
        a.image_step(job,data)
        self.assertEqual(a.pool.image.call_count,1)
        self.assertEqual(a.pool.inspect_image.call_args.args[2],data['article']['image_prompt'])
        self.assertEqual(data['image_prompt_hash'],digest(job['title']+'|'+data['article']['image_prompt']))
        self.assertEqual(self.store.jobs()[0]['state'],'ready')
        self.assertTrue(list((self.root/'superseded-images').glob('*.jpg')))


class ReadyImageFlowTests(StoreCase):
    def test_ready_job_with_stale_visual_is_not_skipped_waiting_for_slot(self):
        job,data=self.job(state='ready')
        self.store.db.execute('UPDATE jobs SET slot=NULL WHERE id=?',(job['id'],))
        self.store.db.commit()
        data['image_prompt_hash']='old'
        self.store.save_job(job['id'],data)
        a=self.agent()
        a.cfg['topics_per_cycle']=1
        a.connect=Mock()
        a.prepare_slots=Mock()
        a.cycle=Mock(side_effect=[self.store.db.execute('SELECT * FROM cycles').fetchone(),None])
        a.run()
        self.assertEqual(self.store.jobs()[0]['state'],'image')
        self.assertIsNone(self.store.jobs()[0]['post'])
        a.wp.call.assert_not_called()

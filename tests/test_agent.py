import copy
import io
import json
import sqlite3
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import requests
from PIL import Image

from agent import Agent, WordPress, ROOT
from core import (BYLINE, UTC, Store, canonical, render_article, slots, utcnow,
                  validate_article, validate_config, validate_topic, words, digest)
from providers import Deferred, Held, Providers, Sources, retry_timestamp


def config():
    return json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))


def article():
    vocab = ['تشغيل', 'إيرادات', 'حجوزات', 'تدريب']
    sections = []
    for word in vocab:
        sections.append({'heading': 'إدارة ' + word, 'paragraphs': [
            {'heading': f'إجراء {word} {i}', 'text': ' '.join([word] * 85), 'source_ids': [1]}
            for i in range(4)]})
    return {'title': 'دليل مهني لتحسين التشغيل الفندقي', 'approved_title': 'دليل مهني لتحسين التشغيل الفندقي',
            'intro': ' '.join(['ضيافة'] * 50), 'source_ids': [1], 'excerpt': 'ملخص مهني',
            'image_prompt': 'Hotel front desk, conceptual hospitality illustration', 'sections': sections,
            'faq': [{'question': 'كيف نقيس جودة الأداء الفندقي؟', 'answer': ' '.join(['خدمة'] * 40), 'source_ids': [1]} for _ in range(5)]}


def topic():
    return {'title': 'إدارة التدبير الفندقي.. خطوات عملية لقياس الأداء', 'category': 'التدبير الفندقي', 'subcategory': 'الجودة',
            'keyword': 'قياس أداء التدبير الفندقي', 'related_keywords': ['الجودة', 'الغرف', 'التشغيل'], 'intent': 'قياس أداء تنظيف الغرف',
            'audience': 'مديرو الإدارات', 'angle': 'إجراءات عملية', 'questions': ['كيف نقيس؟', 'متى نفحص؟', 'كيف نصحح؟'],
            'content_type': 'دليل', 'priority': 'مرتفعة', 'scores': [18] * 5, 'score': 90, 'cluster': 'التدبير', 'level': 'متوسط',
            'related_article_url': None, 'source_urls': ['https://ehl.edu/a', 'https://hftp.org/b']}


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'jobs.sqlite')
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.store.close)

    def job(self, state='ready', post=None, data=None):
        slot = (utcnow() + timedelta(days=2)).replace(microsecond=0).isoformat()
        data = data or {'article': article(), 'evidence': [{'id': 1, 'text': 'Professional hospitality source'}],
                        'sources': [{'url': 'https://ehl.edu/a', 'title': 'EHL'}], 'topic': topic(), 'text_reviewed': True,
                        'image_checked': True, 'image_review': {'pass': True, 'issues': [], 'alt_text': 'مكتب استقبال فندقي', 'provider': 'gemini_vision'}}
        data.setdefault('image_prompt_hash',digest(data['article']['title']+'|'+data['article']['image_prompt']))
        self.store.db.execute("INSERT INTO cycles(id,created,start,state,data) VALUES(1,?,NULL,'building','{}')", (utcnow().isoformat(),))
        self.store.db.execute('INSERT INTO jobs(id,cycle,title,keyword,intent,slot,slug,post,state,data) VALUES(?,?,?,?,?,?,?,?,?,?)',
                              ('job', 1, data['article']['title'], 'مفتاح', 'نية', slot, 'mah-job', post, state, json.dumps(data)))
        self.store.db.commit()
        return self.store.jobs()[0], data

    def agent(self):
        a = Agent.__new__(Agent)
        a.root = self.root
        a.state = self.root
        a.cfg = config()
        a.store = self.store
        a.pool = Mock()
        a.wp = Mock()
        a.wp.author = 99
        a.wp.archive_statuses = 'publish,future,draft,pending'
        a.resume_at = a.last_error = None
        return a


class SchedulingTests(unittest.TestCase):
    def test_exactly_thirty_slots_and_three_per_day_through_dst(self):
        cfg = config()
        cfg['cycle_days'] = 10  # Exercise the generic slot helper across a DST transition.
        for first in ('2026-04-20', '2026-10-25', '2026-11-12'):
            values = [datetime.fromisoformat(s).astimezone(ZoneInfo('Africa/Cairo')) for s in slots(first, cfg)]
            self.assertEqual(len(values), 30)
            self.assertEqual(len({v.date() for v in values}), 10)
            for i in range(0, 30, 3):
                self.assertEqual([v.hour for v in values[i:i + 3]], [12, 14, 18])
            self.assertEqual(len(set(v.astimezone(UTC) for v in values)), 30)

    def test_confirmed_category_is_not_used_as_tag(self):
        cfg = config()
        validate_config(cfg)
        self.assertIsNone(cfg['tag_id'])
        self.assertEqual(cfg['category_ids'], [7])
        self.assertEqual(cfg['image_size'], [1024, 1024])

    def test_cannot_point_config_at_arabiatrend(self):
        cfg = config()
        cfg['site_url'] = 'https://arabiatrend.com'
        with self.assertRaises(ValueError):
            validate_config(cfg)


class EditorialTests(unittest.TestCase):
    def test_valid_long_arabic_schema(self):
        count = validate_article(article(), [{'id': 1}], config())
        self.assertGreaterEqual(count, 1500)
        self.assertLessEqual(count, 2000)

    def test_short_article_never_accepted(self):
        a = article()
        for section in a['sections']:
            section['paragraphs'] = section['paragraphs'][:3]
        with self.assertRaisesRegex(ValueError, '1500-2000'):
            validate_article(a, [{'id': 1}], config())

    def test_intro_must_answer_in_40_to_60_words(self):
        a = article()
        a['intro'] = 'إجابة قصيرة'
        with self.assertRaisesRegex(ValueError, '40-60'):
            validate_article(a, [{'id': 1}], config())

    def test_fake_evidence_reference_rejected(self):
        a = article()
        a['sections'][1]['paragraphs'][0]['source_ids'] = [999]
        with self.assertRaisesRegex(ValueError, 'evidence'):
            validate_article(a, [{'id': 1}], config())

    def test_markdown_and_conclusion_rejected(self):
        for field, value in [('heading', 'الخلاصة'), ('heading', '**عنوان**')]:
            a = article()
            a['sections'][0][field] = value
            with self.assertRaises(ValueError):
                validate_article(a, [{'id': 1}], config())

    def test_heading_and_faq_rendering_no_rules_and_no_title_duplication(self):
        a = article()
        output = render_article(a, [{'url': 'https://ehl.edu/a', 'title': 'مصدر'}])
        self.assertTrue(output.startswith('<p><strong>' + BYLINE + '</strong></p><p>'))
        self.assertIn('<h2><strong>الأسئلة الشائعة</strong></h2>', output)
        self.assertTrue(output.endswith('</p>'))
        self.assertNotIn('<hr', output)
        self.assertNotIn(a['title'], output)
        self.assertLess(output.index('مصادر مهنية'), output.index('الأسئلة الشائعة'))

    def test_renderer_escapes_injected_html(self):
        a = article()
        a['intro'] = '<script>alert(1)</script>'
        result = render_article(a, [{'url': 'https://ehl.edu/?q="', 'title': '<img src=x>'}])
        self.assertNotIn('<script>', result)
        self.assertNotIn('<img', result)
        self.assertIn('&lt;script&gt;', result)

    def test_topic_metadata_and_scores(self):
        self.assertIs(validate_topic(topic())['score'], 90)
        t = topic()
        t['scores'] = [15] * 5
        t['score'] = 75
        with self.assertRaises(ValueError):
            validate_topic(t)

    def test_strict_json_rejects_fenced_or_surrounded_output(self):
        for value in ('```json\n{}\n```', 'result: {}', '[]'):
            with self.assertRaises(ValueError):
                Providers.parse(value)


class PersistenceTests(StoreCase):
    def test_budget_reservation_survives_restart(self):
        limit = {'requests': 1, 'tokens': 100, 'images': 0}
        self.store.reserve('groq', 50, 0, limit)
        self.store.close()
        self.store = Store(self.root / 'jobs.sqlite')
        # Replace cleanup bound to the old connection with a fresh close too.
        self.addCleanup(self.store.close)
        with self.assertRaises(Deferred):
            self.store.reserve('groq', 50, 0, limit)

    def test_cooldown_cannot_be_shortened_and_wait_does_not_spend_budget(self):
        future = time.time() + 3600
        self.store.pause('gemini', future)
        self.store.pause('gemini', time.time() + 1)
        self.assertEqual(self.store.cooldown('gemini'), future)
        with self.assertRaises(Deferred):
            self.store.reserve('gemini', 1, 0, config()['limits']['gemini'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM usage').fetchone()[0], 0)

    def test_archive_and_intent_ledger_prevent_rewording_duplicates(self):
        t = topic()
        self.store.db.execute('INSERT INTO archive VALUES(1,?,?,?,NULL,NULL)', (t['title'], 'https://mahotels.net/a', 'publish'))
        self.store.db.commit()
        t['title'] = t['title'].replace('إدارة', 'ادارة')
        self.assertTrue(self.store.is_duplicate(t))

    def test_duplicate_slot_is_enforced_by_database(self):
        job, _ = self.job()
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute("INSERT INTO jobs(id,cycle,slot,slug,state,data) VALUES('other',1,?,'other','ready','{}')", (job['slot'],))

    def test_third_revision_editorial_rejection_is_not_bypassed(self):
        job, data = self.job(state='reviewing')
        data.pop('text_reviewed')
        data['revisions'] = 3
        a = self.agent()
        a.pool.text.return_value = {'pass': False, 'issues': ['Unsupported claim']}
        with self.assertRaises(Held):
            a.review_step(job, data)
        self.assertFalse(data.get('text_reviewed', False))
        a.wp.call.assert_not_called()

    def test_review_packet_success_saved_before_next_provider_call(self):
        job, data = self.job(state='reviewing')
        data.pop('text_reviewed')
        a = self.agent()
        a.pool.text.return_value = {'pass': True, 'issues': []}
        a.review_step(job, data)
        first = json.loads(self.store.jobs()[0]['data'])
        self.assertEqual(len(first['review_cache']), 1)
        a.pool.text.side_effect = Deferred('quota', time.time() + 120)
        with self.assertRaises(Deferred):
            a.review_step(job, first)
        self.assertEqual(len(json.loads(self.store.jobs()[0]['data'])['review_cache']), 1)
        self.assertFalse(first.get('text_reviewed', False))

    def test_archive_import_failure_prevents_cycle_creation(self):
        a = self.agent()
        a.wp.call.side_effect = Held('Archive unavailable')
        with self.assertRaises(Held):
            a.cycle()
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM cycles').fetchone()[0], 0)

    def test_planner_checkpoint_replay_does_not_approve_topic_twice(self):
        data = {'round': 1, 'pending': [topic()]}
        self.store.db.execute("INSERT INTO cycles(id,created,state,data) VALUES(1,?,'planning',?)", (utcnow().isoformat(), json.dumps(data)))
        self.store.db.commit()
        a = self.agent()
        a.sources = Mock()
        a.sources.allowed.return_value = True
        a.pool.text.return_value = {'pass': True, 'issues': []}
        cycle = self.store.db.execute('SELECT * FROM cycles').fetchone()
        a.plan_step(cycle)
        self.assertEqual(len(self.store.jobs()), 1)
        # Crash window: approval is durable but the pending-candidate checkpoint is old.
        a.save_cycle(cycle, data)
        a.plan_step(self.store.db.execute('SELECT * FROM cycles').fetchone())
        self.assertEqual(len(self.store.jobs()), 1)
        self.assertEqual(a.pool.text.call_count, 1)

    def test_new_cycle_not_created_before_next_day(self):
        self.store.db.execute("INSERT INTO cycles(id,created,start,state,data) VALUES(1,?,?,'scheduled','{}')",
                              (utcnow().isoformat(), date.today().isoformat()))
        self.store.db.commit()
        a = self.agent()
        a.archive_sync = Mock()
        self.assertIsNone(a.cycle())
        a.archive_sync.assert_not_called()

    def test_partial_batch_does_not_reserve_publication_slots(self):
        self.job()
        a = self.agent()
        cycle = self.store.db.execute('SELECT * FROM cycles').fetchone()
        a.prepare_slots(cycle)
        a.wp.call.assert_not_called()
        self.assertIsNone(self.store.db.execute('SELECT start FROM cycles').fetchone()[0])

    def test_publish_requires_actual_vision_not_local_heuristics(self):
        job, data = self.job()
        data['image_review']['provider'] = 'local_rejection'
        a = self.agent()
        with self.assertRaises(Held):
            a.publish(job, data)
        a.wp.call.assert_not_called()

    def test_publish_refuses_elapsed_slot(self):
        job, data = self.job()
        j = dict(job)
        j['slot'] = (utcnow() - timedelta(minutes=1)).isoformat()
        a = self.agent()
        with self.assertRaisesRegex(Held, 'elapsed'):
            a.publish(j, data)
        a.wp.call.assert_not_called()

    def test_recovered_foreign_post_is_never_modified(self):
        job, data = self.job(post=44)
        a = self.agent()
        wp = WordPress.__new__(WordPress)
        wp.author = 99
        wp.call = Mock(return_value={'author': 55, 'slug': 'mah-job', 'status': 'draft'})
        a.wp = wp
        with self.assertRaisesRegex(Held, 'owner/slug'):
            a.publish(job, data)
        self.assertEqual(wp.call.call_count, 1)
        self.assertEqual(wp.call.call_args.args, ('posts/44?context=edit',))

    def test_lost_schedule_response_reconciles_without_duplicate_creation(self):
        job, data = self.job()
        a = self.agent()
        a.wp.call.return_value = [{'id': 44}]
        a.wp.owned_post.return_value = {'author': 99, 'slug': 'mah-job', 'status': 'future', 'featured_media': 45,
                                       'date_gmt': datetime.fromisoformat(job['slot']).strftime('%Y-%m-%dT%H:%M:%S'), 'tags': [], 'categories': [7]}
        a.publish(job, data)
        self.assertEqual(self.store.jobs()[0]['state'], 'scheduled')
        self.assertEqual(self.store.jobs()[0]['post'], 44)
        self.assertTrue(all(not call.kwargs and len(call.args) == 1 for call in a.wp.call.call_args_list))


class ProviderTests(StoreCase):
    def test_modern_gemini_uses_supported_thinking_and_no_sampling_override(self):
        pool = Providers(self.store, config())
        self.addCleanup(pool.close)
        response = Mock()
        response.json.return_value = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': '{"pass":true,"issues":[]}'}]}}]}
        pool.request = Mock(return_value=response)
        with patch.dict('os.environ', {'GEMINI_API_KEY': 'test'}):
            self.assertTrue(pool.gemini([{'role': 'user', 'parts': [{'text': 'Check'}]}], 'Review', 900, 2000)['pass'])
        generation = pool.request.call_args.kwargs['json']['generationConfig']
        self.assertNotIn('temperature', generation)
        self.assertEqual(generation['thinkingConfig'], {'thinkingLevel': 'low'})

    def test_network_error_reserves_budget_before_call(self):
        pool = Providers(self.store, config())
        self.addCleanup(pool.close)
        pool.http.post = Mock(side_effect=requests.ConnectionError('secret must not leak'))
        with self.assertRaises(Deferred) as result:
            pool.request('groq', 'https://example.com', tokens=20)
        self.assertNotIn('secret', str(result.exception))
        self.assertEqual(self.store.db.execute('SELECT requests,tokens FROM usage').fetchone()[:], (1, 20))

    def test_429_preserves_full_retry_after_and_no_second_call(self):
        pool = Providers(self.store, config())
        self.addCleanup(pool.close)
        pool.http.post = Mock(return_value=Mock(status_code=429, headers={'Retry-After': '7200'}))
        with self.assertRaises(Deferred):
            pool.request('gemini', 'https://example.com')
        self.assertGreater(self.store.cooldown('gemini'), time.time() + 7100)
        with self.assertRaises(Deferred):
            pool.request('gemini', 'https://example.com')
        self.assertEqual(pool.http.post.call_count, 1)

    def test_http_date_retry_after_supported(self):
        self.assertGreater(retry_timestamp('Wed, 11 Nov 2037 10:00:00 GMT'), time.time())

    def test_square_image_request_is_multipart_and_budgeted(self):
        pool = Providers(self.store, config())
        self.addCleanup(pool.close)
        pool.request = Mock(return_value=Mock(headers={'Content-Type': 'image/jpeg'}, content=b'image'))
        with patch.dict('os.environ', {'CF_ACCOUNT_ID': 'test', 'CF_API_TOKEN': 'test'}):
            self.assertEqual(pool.image('Hotel lobby', 12), b'image')
        fields = pool.request.call_args.kwargs['files']
        self.assertEqual(fields['width'], (None, '1024'))
        self.assertEqual(fields['height'], (None, '1024'))
        self.assertEqual(pool.request.call_args.kwargs['images'], 1)

    def test_unavailable_vision_does_not_approve_locally(self):
        image = Image.effect_noise((1024, 1024), 50).convert('RGB')
        out = io.BytesIO()
        image.save(out, format='JPEG')
        pool = Providers(self.store, config())
        self.addCleanup(pool.close)
        pool.gemini = Mock(side_effect=Deferred('vision quota'))
        with patch.dict('os.environ', {'GEMINI_API_KEY': 'test'}):
            with self.assertRaises(Deferred):
                pool.inspect_image(out.getvalue(), 'عنوان فندقي')

    def test_approved_source_hosts_do_not_allow_lookalikes_or_private_ips(self):
        source = Sources(self.store, config())
        self.addCleanup(source.close)
        self.assertTrue(source.allowed('https://hospitalityinsights.ehl.edu/a'))
        for url in ('https://ehl.edu.evil.example/a', 'http://ehl.edu/a', 'https://127.0.0.1/a', 'https://ehl.edu:444/a', 'https://user:pass@ehl.edu/a'):
            self.assertFalse(source.allowed(url))


class BatchIntegrationTests(StoreCase):
    def test_three_articles_schedule_only_after_all_ready_and_replay_is_idempotent(self):
        a = self.agent()
        a.connect = Mock()
        a.pool.text.return_value = {'pass': True, 'issues': []}
        a.pool.inspect_image.return_value = {'pass': True, 'issues': [], 'alt_text': 'صورة توضيحية لاستقبال فندقي', 'provider': 'gemini_vision'}
        out = io.BytesIO()
        Image.effect_noise((1024, 1024), 40).convert('RGB').save(out, format='PNG')
        a.pool.image.return_value = out.getvalue()
        self.store.db.execute("INSERT INTO cycles(id,created,start,state,data) VALUES(1,?,NULL,'building','{}')", (utcnow().isoformat(),))
        for index in range(3):
            item = article()
            item['title'] = item['approved_title'] = f'دليل التشغيل الفندقي المتخصص {index}'
            data = {'topic': topic(), 'article': item, 'evidence': [{'id': 1, 'text': 'Professional hospitality guidance'}],
                    'sources': [{'url': 'https://ehl.edu/a', 'title': 'EHL'}], 'revisions': 0}
            self.store.db.execute('INSERT INTO jobs(id,cycle,title,keyword,intent,slug,state,data) VALUES(?,1,?,?,?,?,?,?)',
                                  (str(index), item['title'], str(index), str(index), 'mah-' + str(index), 'writing', json.dumps(data)))
        self.store.db.commit()
        posts, media, scheduled, calls = {}, {}, [], []
        queue = Mock(headers={'X-WP-TotalPages': '0'})
        queue.json.return_value = []

        def call(path, body=None, raw=None, headers=None, response=False):
            calls.append(path)
            if response:
                return queue
            if path.startswith('posts?') or path.startswith('media?'):
                return []
            if path == 'posts':
                if not posts:
                    self.assertEqual(sum(j['state'] == 'ready' for j in self.store.jobs()), 3)
                post_id = len(posts) + 100
                posts[post_id] = dict(body, id=post_id, author=99)
                return posts[post_id]
            if path == 'media':
                with Image.open(io.BytesIO(raw)) as image:
                    self.assertEqual(image.size, (1024, 1024))
                media_id = len(media) + 500
                slug = headers['Content-Disposition'].split('filename="')[1].removesuffix('.jpg"')
                media[media_id] = {'id': media_id, 'author': 99, 'slug': slug}
                return media[media_id]
            if path.startswith('media/'):
                media_id = int(path.split('/')[1].split('?')[0])
                return media[media_id]
            if path.startswith('posts/'):
                post_id = int(path.split('/')[1])
                self.assertNotIn('tags', body)
                hour = datetime.fromisoformat(body['date_gmt']).replace(tzinfo=UTC).astimezone(ZoneInfo('Africa/Cairo')).hour
                self.assertEqual(body['categories'], [7,1710] if hour == 14 else [7])
                self.assertEqual(body['status'], 'future')
                self.assertIn('featured_media', body)
                self.assertTrue(body['content'].startswith('<p><strong>' + BYLINE))
                scheduled.append(body['date_gmt'])
                posts[post_id].update(body)
                return posts[post_id]
            raise AssertionError(path)

        a.wp.call = call
        a.wp.owned_post.side_effect = lambda pid, slug: posts[pid]
        a.run()
        self.assertEqual(len(posts), 3)
        self.assertEqual(len(media), 3)
        self.assertEqual(len(scheduled), 3)
        local = [datetime.fromisoformat(v).replace(tzinfo=UTC).astimezone(ZoneInfo('Africa/Cairo')) for v in scheduled]
        self.assertEqual(len({v.date() for v in local}), 1)
        self.assertEqual([v.hour for v in local], [12, 14, 18])
        self.assertTrue(all(j['state'] == 'scheduled' for j in self.store.jobs()))
        self.assertEqual(self.store.db.execute('SELECT state FROM cycles').fetchone()[0], 'scheduled')
        self.assertLessEqual(len(calls), 19)  # Six calls/article plus one queue read.
        initial_calls = len(calls)
        a.run()
        self.assertEqual(len(posts), 3)
        self.assertEqual(len(media), 3)
        self.assertEqual(len(calls), initial_calls)


if __name__ == '__main__':
    unittest.main()

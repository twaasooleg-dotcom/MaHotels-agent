import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from agent import Agent, ROOT, REVIEW_SYSTEM
from core import CATEGORIES, Store, utcnow
from providers import Deferred, Held, Providers
from topic_prompts import topic_request
from test_agent import topic


def config():
    return json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))


class TopicRequestTests(unittest.TestCase):
    def test_manual_resume_preserves_the_original_interval_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'db.sqlite')
            try:
                marker = '2026-11-11T13:59:35+00:00'
                store.put('last_run_started', marker)
                store.db.execute("INSERT INTO cycles(id,created,state,data) VALUES(1,?,'planning','{}')", (marker,))
                store.db.commit()
                a = Agent.__new__(Agent)
                a.root, a.store, a.cfg = Path(folder), store, config()
                a.connect, a.cycle = Mock(), Mock(return_value=None)
                a.run(resume_existing=True)
                a.connect.assert_called_once()
                self.assertEqual(store.get('last_run_started'), marker)
                self.assertEqual(store.db.execute('SELECT COUNT(*) FROM cycles').fetchone()[0], 1)
            finally:
                store.close()

    def test_manual_resume_cannot_start_a_new_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'db.sqlite')
            try:
                a = Agent.__new__(Agent)
                a.root, a.store, a.cfg = Path(folder), store, config()
                a.connect = Mock()
                with self.assertRaisesRegex(Held, 'No unfinished batch'):
                    a.run(resume_existing=True)
                a.connect.assert_not_called()
                self.assertIsNone(store.get('last_run_started'))
            finally:
                store.close()

    def test_request_fits_groq_guard_with_long_arabic_history(self):
        approved = []
        for i in range(30):
            t = topic()
            t.update(title='التشغيل الفندقي المتخصص ' * 30, category=CATEGORIES[i % 20])
            approved.append(t)
        system, prompt, cap = topic_request(1, approved, ['العنوان الفندقي الطويل ' * 50] * 8, config()['source_hosts'])
        self.assertLessEqual(len((system + prompt).encode()) + cap + 300, 7600)
        self.assertIn('exactly ONE', prompt)
        self.assertTrue(all(category in prompt for category in CATEGORIES))

    def test_preview_has_no_wordpress_calls_and_preserves_production_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'db.sqlite')
            try:
                store.put('last_run_started', '2026-11-11T13:59:35+00:00')
                a = Agent.__new__(Agent)
                a.store, a.state, a.cfg = store, Path(folder), config()
                a.pool, a.wp, a.sources = Mock(), Mock(), Mock()
                a.pool.text.return_value = {'topics': [topic()]}
                a.sources.allowed.return_value = True
                with patch.dict(os.environ, {'MAH_FREE_CONFIRMED': '1'}):
                    report = a.test_topic()
                self.assertFalse(report['approved'])
                self.assertEqual(report['wordpress_requests'], 0)
                a.wp.assert_not_called()
                a.wp.call.assert_not_called()
                self.assertEqual(store.jobs(), [])
                self.assertEqual(store.db.execute('SELECT COUNT(*) FROM cycles').fetchone()[0], 0)
                self.assertEqual(store.get('last_run_started'), '2026-11-11T13:59:35+00:00')
                self.assertTrue((Path(folder) / 'topic-test.json').is_file())
            finally:
                store.close()

    def test_semantic_review_splits_history_and_caches_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'db.sqlite')
            try:
                data = {'round': 1, 'pending': [topic()]}
                store.db.execute("INSERT INTO cycles(id,created,state,data) VALUES(1,?,'planning',?)", (utcnow().isoformat(), json.dumps(data)))
                store.db.commit()
                a = Agent.__new__(Agent)
                a.store, a.cfg, a.pool, a.sources = store, config(), Mock(), Mock()
                a.sources.allowed.return_value = True
                store.is_duplicate = Mock(return_value=False)
                store.closest = Mock(return_value=[{'title': 'تفاصيل إدارة جودة الفنادق وتدريب العاملين ' * 30 + str(i), 'status': 'publish', 'link': 'https://mahotels.net/' + 'a' * 900} for i in range(12)])
                a.pool.text.side_effect = [{'pass': True, 'issues': []}, Deferred('provider wait')]
                with self.assertRaises(Deferred):
                    a.plan_step(store.db.execute('SELECT * FROM cycles').fetchone())
                saved = json.loads(store.db.execute('SELECT data FROM cycles').fetchone()[0])
                self.assertEqual(len(saved['candidate_review_cache']), 1)
                self.assertEqual(len(saved['pending']), 1)
                a.pool.text.reset_mock()
                a.pool.text.side_effect = None
                a.pool.text.return_value = {'pass': True, 'issues': []}
                a.plan_step(store.db.execute('SELECT * FROM cycles').fetchone())
                self.assertEqual(len(store.jobs()), 1)
                self.assertGreater(a.pool.text.call_count, 1)
                for call in a.pool.text.call_args_list:
                    system, prompt = call.args
                    self.assertLessEqual(len((system + prompt).encode()) + call.kwargs['cap'] + 300, 7600)
                    self.assertNotIn('a' * 900, prompt)
            finally:
                store.close()


class ProviderFailureTests(unittest.TestCase):
    def test_gemini_503_can_fall_back_to_fitting_groq_request(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'db.sqlite')
            pool = Providers(store, config())
            try:
                gemini = Mock(status_code=503, headers={})
                groq = Mock(status_code=200, ok=True)
                groq.json.return_value = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"pass":true,"issues":[]}'}}]}
                pool.http.post = Mock(side_effect=[gemini, groq])
                with patch.dict(os.environ, {'GEMINI_API_KEY': 'test', 'GROQ_API_KEY': 'test'}):
                    self.assertTrue(pool.text('Editor', 'Check facts', reviewer=True, cap=900)['pass'])
                self.assertEqual(pool.http.post.call_count, 2)
                self.assertGreater(store.cooldown('gemini'), 0)
            finally:
                pool.close()
                store.close()

    def test_tls_error_is_not_misreported_as_an_api_key_error(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'db.sqlite')
            pool = Providers(store, config())
            try:
                pool.http.post = Mock(side_effect=requests.exceptions.SSLError('sensitive raw failure'))
                with self.assertRaises(Held) as caught:
                    pool.request('groq', 'https://api.groq.com/test')
                self.assertIn('TLS certificate', str(caught.exception))
                self.assertNotIn('sensitive raw failure', str(caught.exception))
                self.assertNotIsInstance(caught.exception, Deferred)
            finally:
                pool.close()
                store.close()


if __name__ == '__main__':
    unittest.main()

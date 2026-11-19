import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from agent import Agent, ROOT
from core import Store, UTC
from providers import Sources, Held, Deferred
from repair_sources import repair


class SourceRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'jobs.sqlite')
        self.addCleanup(self.store.close)
        with self.store.db:
            self.store.db.execute("INSERT INTO cycles(id,created,state,data) VALUES(1,'2026-11-11T10:00:00+00:00','writing','{}')")
        self.cfg = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
        self.reader = Mock()
        self.reader.allowed.return_value = True
        self.reader.fetch.side_effect = lambda url: {'url': url, 'text': 'verified evidence ' * 50}
        self.urls = ['https://ehl.edu/real-one', 'https://ehl.edu/real-two']

    def add_job(self, name='a', **fields):
        data = {'topic': {'source_urls': ['https://ehl.edu/guessed-one', 'https://ehl.edu/guessed-two']},
                'held_from': 'approved', 'last_error': 'Need two accessible professional sources; HTTP 404'}
        data.update(fields)
        with self.store.db:
            self.store.db.execute('INSERT INTO jobs(id,cycle,title,keyword,intent,slug,state,data) VALUES(?,1,?,?,?,?,?,?)',
                                  (name, name, name, name, name, 'held', json.dumps(data)))

    def test_verified_repair_preserves_identity_budgets_marker_and_is_idempotent(self):
        self.add_job()
        self.store.put('last_run_started', '2026-11-11T10:00:00+00:00')
        self.store.reserve('groq', 100, 0, self.cfg['limits']['groq'])
        usage = [tuple(row) for row in self.store.db.execute('SELECT * FROM usage')]
        result = repair(self.store, self.reader, {'a': self.urls}, self.root)
        self.assertTrue(Path(result['backup']).exists())
        job = self.store.jobs()[0]
        self.assertEqual(job['state'], 'approved')
        self.assertEqual((job['id'], job['slug']), ('a', 'a'))
        self.assertEqual(json.loads(job['data'])['topic']['source_urls'], self.urls)
        self.assertEqual(self.store.get('last_run_started'), '2026-11-11T10:00:00+00:00')
        self.assertEqual(usage, [tuple(row) for row in self.store.db.execute('SELECT * FROM usage')])
        self.assertEqual(repair(self.store, self.reader, {'a': self.urls}, self.root)['updated'], 0)

    def test_one_bad_page_aborts_all_job_changes(self):
        self.add_job('a')
        self.add_job('b')
        before = [dict(row) for row in self.store.jobs()]
        self.reader.fetch.side_effect = [{'url': self.urls[0]}, {'url': self.urls[1]}, Held('Professional source HTTP 404')]
        with self.assertRaises(Held):
            repair(self.store, self.reader, {'a': self.urls, 'b': self.urls}, self.root)
        self.assertEqual(before, [dict(row) for row in self.store.jobs()])

    def test_duplicate_redirect_targets_and_unapproved_domains_are_rejected(self):
        self.add_job()
        self.reader.fetch.return_value = {'url': self.urls[0]}
        self.reader.fetch.side_effect = None
        with self.assertRaisesRegex(ValueError, 'two distinct'):
            repair(self.store, self.reader, {'a': self.urls}, self.root)
        self.reader.allowed.return_value = False
        with self.assertRaisesRegex(ValueError, 'outside approved'):
            repair(self.store, self.reader, {'a': self.urls}, self.root)

    def test_live_drafted_or_unrelated_holds_are_never_reset(self):
        for fields in ({'article': {'intro': 'started'}}, {'last_error': 'Editorial validation failed'},
                       {'held_from': 'image'}):
            with self.store.db:
                self.store.db.execute('DELETE FROM jobs')
            self.add_job(**fields)
            with self.assertRaises(ValueError):
                repair(self.store, self.reader, {'a': self.urls}, self.root)
        self.reader.fetch.assert_not_called()

    def test_status_reports_future_daily_window_without_resetting_old_marker(self):
        a = Agent.__new__(Agent)
        a.root, a.state, a.cfg, a.store = self.root, self.root, self.cfg, self.store
        a.wp, a.last_error, a.deferred_until = None, None, None
        marker = '2026-11-11T13:59:35+00:00'
        self.store.put('last_run_started', marker)
        for instant, expected in ((datetime(2026, 11, 15, 10, tzinfo=UTC), '2026-11-16T06:00:00+02:00'),
                                  (datetime(2026, 11, 15, 2, tzinfo=UTC), '2026-11-15T06:00:00+02:00')):
            with patch('agent.utcnow', return_value=instant):
                self.assertEqual(a.status()['next_run_window'], expected)
        self.assertEqual(self.store.get('last_run_started'), marker)

    def test_http_failures_explain_404_without_exposing_response_body(self):
        reader = Sources(self.store, self.cfg)
        self.addCleanup(reader.close)
        response = Mock(status_code=404, ok=False, headers={'Content-Type': 'text/html'})
        reader.http.get = Mock()
        reader.http.get.return_value.__enter__ = Mock(return_value=response)
        reader.http.get.return_value.__exit__ = Mock(return_value=False)
        with self.assertRaisesRegex(Held, 'HTTP 404'):
            reader.fetch('https://ehl.edu/bad')
        response.status_code = 503
        with self.assertRaises(Deferred):
            reader.fetch('https://ehl.edu/bad')


if __name__ == '__main__':
    unittest.main()

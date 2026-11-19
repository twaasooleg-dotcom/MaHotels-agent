import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from agent import Agent, ROOT, WordPress
from core import Store, UTC
from providers import Deferred


def config():
    return json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))


class DailyRunTests(unittest.TestCase):
    def test_second_run_is_blocked_before_connection_and_next_window_is_allowed(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'db.sqlite')
            try:
                a = Agent.__new__(Agent)
                a.root, a.cfg, a.store = Path(folder), config(), store
                a.connect, a.cycle = Mock(), Mock(return_value=None)
                started = datetime(2026, 11, 11, 10, tzinfo=UTC)
                with patch('agent.utcnow', return_value=started):
                    a.run()
                a.connect.assert_called_once()
                a.connect.reset_mock()
                with patch('agent.utcnow', return_value=started + timedelta(hours=3)):
                    a.run()
                a.connect.assert_not_called()
                with patch('agent.utcnow', return_value=started + timedelta(days=1)):
                    a.run()
                a.connect.assert_called_once()
            finally:
                store.close()

    def test_long_quota_wait_has_no_automatic_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'db.sqlite')
            try:
                a = Agent.__new__(Agent)
                a.root, a.cfg, a.store = Path(folder), config(), store
                a.connect = Mock()
                a.resume_at = None
                a.cycle = Mock(side_effect=Deferred('daily quota', time.time() + 3600))
                a.run()
                self.assertIsNone(a.resume_at)
                self.assertGreater(a.deferred_until, time.time())
            finally:
                store.close()


class WordPressLoadTests(unittest.TestCase):
    def client(self):
        wp = WordPress.__new__(WordPress)
        wp.cfg = config()
        wp.http = Mock()
        response = Mock(status_code=200, ok=True)
        response.json.return_value = {'id': 1}
        wp.http.request.return_value = response
        wp.request_count, wp.next_request_at = 0, 0
        return wp

    def test_calls_are_paced_and_responses_use_minimal_fields(self):
        wp = self.client()
        with patch('agent.time.monotonic', return_value=100), patch('agent.time.sleep') as sleep:
            wp.call('posts/1?context=edit')
            wp.call('media/2?context=edit')
        sleep.assert_called_once_with(3)
        urls = [c.args[1] for c in wp.http.request.call_args_list]
        self.assertTrue(all('_fields=' in u for u in urls))
        self.assertTrue(all('content' not in u and 'excerpt' not in u for u in urls))

    def test_wordpress_request_cap_stops_further_http_calls(self):
        wp = self.client()
        wp.request_count = wp.cfg['wp_max_requests_per_run']
        with self.assertRaises(Deferred):
            wp.call('posts/1')
        wp.http.request.assert_not_called()

    def test_single_recurring_task_and_no_resume_registration_in_wrapper(self):
        script = (ROOT / 'setup.ps1').read_text(encoding='utf-8-sig')
        controls = (ROOT / 'task-control.ps1').read_text(encoding='utf-8-sig')
        self.assertEqual((script + controls).count('New-ScheduledTaskTrigger'), 1)
        self.assertIn('-DaysInterval 1 ', controls)
        self.assertIn('Register-MaDailyTask', script)
        wrapper = (ROOT / 'run.ps1').read_text(encoding='utf-8-sig')
        self.assertNotIn('Set-MaResumeTask', wrapper)
        self.assertNotIn('Register-ScheduledTask', wrapper)
        controls = (ROOT / 'task-control.ps1').read_text(encoding='utf-8-sig')
        self.assertNotIn('Set-MaResumeTask', controls)


if __name__ == '__main__':
    unittest.main()

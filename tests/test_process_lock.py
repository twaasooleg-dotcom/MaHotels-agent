import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import agent
from core import Store, ProcessBusy, LockAccessError, process_lock


class LockTests(unittest.TestCase):
    def test_child_lock_excludes_second_process_and_releases_after_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'run.lock'
            script = ("import sys; from core import process_lock; "
                      "guard=process_lock(sys.argv[1]); guard.__enter__(); "
                      "print('locked',flush=True); sys.stdin.read(1); guard.__exit__(None,None,None)")
            child = subprocess.Popen([sys.executable, '-B', '-c', script, str(path)],
                                     cwd=agent.ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'locked')
                with self.assertRaises(ProcessBusy):
                    with process_lock(path):
                        self.fail('Overlapping writers must be excluded')
            finally:
                child.communicate('x', timeout=10)
            self.assertEqual(child.returncode, 0)
            with process_lock(path):
                pass
            self.assertEqual(path.read_bytes(), b'0')

    def test_exception_releases_lock_and_old_marker_is_reusable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'run.lock'
            path.write_bytes(b'0')
            with self.assertRaisesRegex(ValueError, 'step failed'):
                with process_lock(path):
                    raise ValueError('step failed')
            with process_lock(path):
                pass
            self.assertTrue(path.exists())

    def test_access_denial_is_distinct_from_busy(self):
        with patch('builtins.open', side_effect=PermissionError('private details')):
            with self.assertRaises(LockAccessError) as caught:
                with process_lock('unused'):
                    pass
            self.assertNotIn('private details', str(caught.exception))

    def test_busy_run_returns_clear_message_without_constructing_agent(self):
        with patch.object(agent, '_main', side_effect=ProcessBusy('Another MaHotels instance is running')), \
             patch.object(agent, 'Agent') as constructor, patch('sys.argv', ['agent.py', 'run']), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(agent.main(), 3)
        constructor.assert_not_called()
        self.assertIn('Another MaHotels', out.getvalue())
        self.assertNotIn('Traceback', out.getvalue())

    def test_live_status_preserves_database_and_does_not_contact_providers(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'state').mkdir()
            store = Store(root / 'state/jobs.sqlite')
            store.put('last_run_started', '2026-11-15T10:00:00+00:00')
            store.close()
            before = (root / 'state/jobs.sqlite').read_bytes()
            with patch.object(agent, '_main', side_effect=ProcessBusy()), \
                 patch.object(agent, 'ROOT', root), patch.object(agent, 'Agent') as constructor, \
                 patch('sys.argv', ['agent.py', 'status']), redirect_stdout(io.StringIO()) as out:
                self.assertEqual(agent.main(), 0)
            result = json.loads(out.getvalue())
            self.assertTrue(result['running'])
            self.assertEqual(result['counts'], {})
            constructor.assert_not_called()
            self.assertEqual((root / 'state/jobs.sqlite').read_bytes(), before)
            self.assertFalse((root / 'state/status.json').exists())


class WritingRequestSizeTests(unittest.TestCase):
    def test_intro_with_evidence_and_corrections_fits_groq_without_dropping_context(self):
        from unittest.mock import Mock
        from test_agent import topic
        a = agent.Agent.__new__(agent.Agent)
        a.store, a.pool = Mock(), Mock()
        a.article_system = (agent.ROOT / 'prompts/article-system-ar.txt').read_text(encoding='utf-8')
        a.pool.text.return_value = {'intro': 'draft', 'excerpt': 'summary', 'source_ids': [1], 'image_prompt': 'hotel'}
        corrections = ['Correct unsupported claims and preserve source attribution. ' * 4 for _ in range(4)]
        evidence = [{'id': i, 'text': ('hotel evidence ' * 30)[:450]} for i in range(1, 7)]
        data = {'topic': topic(), 'evidence': evidence, 'corrections': corrections}
        a.write_step({'id': 'preview', 'title': data['topic']['title']}, data)
        args, kwargs = a.pool.text.call_args
        reservation = len((args[0] + args[1]).encode('utf-8')) + kwargs['cap'] + 300
        limit = json.loads((agent.ROOT / 'config.json').read_text(encoding='utf-8'))['limits']['groq']['max_request_tokens']
        self.assertLessEqual(reservation, limit)
        for correction in corrections:
            self.assertIn(correction, args[1])
        for block in evidence:
            self.assertIn(block['text'], args[1])
        self.assertIn('1500-2000', args[0])
        self.assertIn('40-60', args[0])


if __name__ == '__main__':
    unittest.main()

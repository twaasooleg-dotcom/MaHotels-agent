import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from agent import Agent
from core import CATEGORIES, Store, utcnow
from daily_migration import migrate_daily, promote_backlog
from test_agent import config, topic


class DailyMigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / 'db.sqlite')
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.store.close)
        self.store.db.execute("INSERT INTO cycles(id,created,state,data) VALUES(1,?,'planning',?)", (utcnow().isoformat(), json.dumps({'round': 5, 'pending': []})))
        self.store.db.commit()

    def add_job(self, number, category=None, level=None, post=None):
        t = topic()
        t.update(category=category or CATEGORIES[number % 20], level=level or ('تمهيدي', 'متوسط', 'متقدم')[number % 3])
        self.store.db.execute('INSERT INTO jobs(id,cycle,title,keyword,intent,slug,post,state,data) VALUES(?,1,?,?,?,?,?,?,?)',
                              (str(number), t['title'] + str(number), str(number), str(number), 'mah-' + str(number), post, 'approved', json.dumps({'topic': t})))
        self.store.db.commit()

    def test_daily_config_and_slots_target_three(self):
        cfg = config()
        self.assertEqual((cfg['cycle_days'], cfg['topics_per_cycle']), (1, 3))
        self.assertEqual(cfg['run_hour'], 6)
        self.assertEqual(cfg['wp_max_requests_per_run'], 100)

    def test_migration_preserves_excess_topics_cache_budgets_and_run_marker(self):
        for n in range(7):
            self.add_job(n)
        marker = '2026-11-11T13:59:35+00:00'
        self.store.put('last_run_started', marker)
        self.store.reserve('groq', 100, 0, config()['limits']['groq'])
        self.store.db.execute("INSERT INTO archive VALUES(1,'cached title','https://mahotels.net/a','publish','date','')")
        self.store.db.commit()
        before = {r['id'] for r in self.store.jobs()}
        summary = migrate_daily(self.store, target=2)
        self.assertEqual(summary['retained'], 2)
        self.assertEqual(summary['backlog'], 5)
        self.assertEqual({r['id'] for r in self.store.jobs()}, before)
        self.assertEqual(len(self.store.jobs(1)), 2)
        self.assertEqual(self.store.get('last_run_started'), marker)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM archive').fetchone()[0], 1)
        self.assertEqual(self.store.db.execute('SELECT tokens FROM usage').fetchone()[0], 100)
        self.assertEqual(migrate_daily(self.store, target=2), summary)

    def test_backlog_promotion_never_exceeds_two_or_reuses_ids(self):
        for n in range(8):
            self.add_job(n)
        migrate_daily(self.store, target=2)
        self.store.db.execute("UPDATE cycles SET state='scheduled' WHERE id=1")
        cursor = self.store.db.execute("INSERT INTO cycles(created,state,data) VALUES(?,'planning','{}')", (utcnow().isoformat(),))
        new_id = cursor.lastrowid
        self.store.db.commit()
        count = promote_backlog(self.store, new_id, target=2)
        self.assertEqual(count, 2)
        self.assertEqual(len(self.store.jobs(new_id)), 2)
        self.assertEqual(len(self.store.jobs()), 8)
        self.assertEqual(len({r['id'] for r in self.store.jobs()}), 8)

    def test_ambiguous_partial_wordpress_commit_is_not_reassigned(self):
        for n in range(4):
            self.add_job(n, post=100 if n == 0 else None)
        with self.assertRaisesRegex(ValueError, 'live IDs'):
            migrate_daily(self.store, target=2)
        self.assertEqual(len(self.store.jobs(1)), 4)
        self.assertIsNone(self.store.get('daily_migration_v1'))

    def test_planner_stops_at_two_without_a_third_model_request(self):
        for n in range(2):
            self.add_job(n)
        a = Agent.__new__(Agent)
        a.store, a.cfg, a.pool = self.store, dict(config(), topics_per_cycle=2), Mock()
        a.plan_step(self.store.db.execute('SELECT * FROM cycles WHERE id=1').fetchone())
        self.assertEqual(self.store.db.execute('SELECT state FROM cycles WHERE id=1').fetchone()[0], 'building')
        self.assertEqual(len(self.store.jobs(1)), 2)
        a.pool.text.assert_not_called()


    def test_prior_three_topic_marker_does_not_skip_two_topic_migration(self):
        for n in range(3):
            self.add_job(n)
        self.store.put('daily_migration_v1', {'target': 3})
        before = {r['id']: r['data'] for r in self.store.jobs()}
        summary = migrate_daily(self.store, target=2)
        self.assertEqual(summary['target'], 2)
        self.assertEqual(len(self.store.jobs(1)), 2)
        self.assertEqual(len(self.store.jobs()), 3)
        self.assertEqual({r['id']: r['data'] for r in self.store.jobs()}, before)
        self.assertEqual(migrate_daily(self.store, target=2), summary)

    def test_completed_three_post_batch_is_preserved(self):
        for n in range(3):
            self.add_job(n, post=100+n)
        self.store.db.execute("UPDATE cycles SET state='scheduled' WHERE id=1")
        self.store.db.commit()
        migrate_daily(self.store, target=2)
        self.assertEqual(len(self.store.jobs(1)), 3)
        self.assertEqual([r['post'] for r in self.store.jobs(1)], [100,101,102])

    def test_configuration_rejects_previous_three_publication_hours(self):
        from core import validate_config
        cfg = config()
        cfg['publish_hours'] = [10,14,18]
        with self.assertRaises(ValueError):
            validate_config(cfg)


    def test_backlog_is_separate_from_active_status_counts(self):
        for n in range(3):
            self.add_job(n)
        migrate_daily(self.store, target=2)
        a = Agent.__new__(Agent)
        a.store, a.cfg = self.store, config()
        a.root = a.state = Path(self.directory.name)
        a.wp = a.last_error = a.deferred_until = None
        report = a.status()
        self.assertEqual(report['counts'], {'approved': 2})
        self.assertEqual(report['backlog_counts'], {'approved': 1})


if __name__ == '__main__':
    unittest.main()

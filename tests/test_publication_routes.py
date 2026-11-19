import copy
import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from agent import WordPress
from core import UTC, digest, utcnow, validate_config
from daily_migration import migrate_daily
from providers import Held, Deferred
from publication_policy import configured_routes, reserved_route
from test_agent import StoreCase, config


class PublicationRouteTests(StoreCase):
    def batch(self, count=3):
        first, data=self.job()
        self.store.db.execute('UPDATE jobs SET slot=NULL WHERE id=?',(first['id'],))
        for i in range(1,count):
            extra=copy.deepcopy(data)
            title=first['title']+str(i)
            extra['article']['title']=extra['article']['approved_title']=title
            extra['image_prompt_hash']=digest(title+'|'+extra['article']['image_prompt'])
            self.store.db.execute('INSERT INTO jobs(id,cycle,title,keyword,intent,slug,state,data) VALUES(?,1,?,?,?,?,?,?)',
                                  (str(i),title,str(i),str(i),'mah-'+str(i),'ready',json.dumps(extra)))
        self.store.db.commit()
        a=self.agent()
        response=Mock(headers={'X-WP-TotalPages':'1'})
        response.json.return_value=[]
        a.wp.call.return_value=response
        return a, response

    def news_job(self, post=44):
        job,data=self.job(post=post)
        job=dict(job)
        # Use an explicit Cairo date/hour rather than the host timezone or current season.
        from zoneinfo import ZoneInfo
        local=(utcnow().astimezone(ZoneInfo('Africa/Cairo'))+timedelta(days=2)).replace(hour=14,minute=0,second=0,microsecond=0)
        job['slot']=local.astimezone(UTC).isoformat()
        data['publication']={'hour':14,'category_ids':[7,1710],'tag_ids':[]}
        return job,data

    def test_three_routes_validate_and_news_is_category_not_tag(self):
        cfg=config()
        validate_config(cfg)
        self.assertEqual(configured_routes(cfg),[
            {'hour':12,'category_ids':[7],'tag_ids':[]},
            {'hour':14,'category_ids':[7,1710],'tag_ids':[]},
            {'hour':18,'category_ids':[7],'tag_ids':[]}])
        for mutate in ('tag','missing','wrong','duplicate'):
            bad=copy.deepcopy(cfg)
            if mutate=='tag':bad['tag_id']=1710
            if mutate=='missing':bad['publication_routes'].pop(1)
            if mutate=='wrong':bad['publication_routes'][0]['category_ids']=[7,1710]
            if mutate=='duplicate':bad['publication_routes'][1]['category_ids']=[7,1710,1710]
            with self.assertRaises(ValueError):validate_config(bad)

    def test_identity_checks_each_configured_category_once_without_tag_request(self):
        wp=WordPress.__new__(WordPress)
        wp.cfg,wp.store=config(),self.store
        me={'id':99,'username':'ma_news_agent','capabilities':dict(edit_posts=True,publish_posts=True,upload_files=True)}
        def call(path):
            if path.startswith('users/me'):return me
            return {'id':int(path.split('/')[1]),'name':'Existing category'}
        wp.call=Mock(side_effect=call)
        result=wp.identity()
        self.assertEqual(result['author'],99)
        self.assertEqual([c.args[0] for c in wp.call.call_args_list],['users/me?context=edit','categories/7','categories/1710'])

    def test_partial_two_job_batch_cannot_reserve_new_three_slot_day(self):
        a,_=self.batch(2)
        a.prepare_slots(self.store.db.execute('SELECT * FROM cycles').fetchone())
        a.wp.call.assert_not_called()
        self.assertIsNone(self.store.db.execute('SELECT start FROM cycles').fetchone()[0])

    def test_conflicting_news_slot_moves_whole_batch_and_pins_routes(self):
        a,response=self.batch()
        response.json.return_value=[{'date_gmt':'2026-11-18T12:00:00'}] # 14 Cairo
        with patch('agent.utcnow',return_value=datetime(2026,11,17,8,tzinfo=UTC)):
            a.prepare_slots(self.store.db.execute('SELECT * FROM cycles').fetchone())
        self.assertEqual(self.store.db.execute('SELECT start FROM cycles').fetchone()[0],'2026-11-19')
        from zoneinfo import ZoneInfo
        jobs=self.store.jobs()
        self.assertEqual([datetime.fromisoformat(j['slot']).astimezone(ZoneInfo('Africa/Cairo')).hour for j in jobs],[12,14,18])
        for job,route in zip(jobs,configured_routes(a.cfg)):
            self.assertEqual(json.loads(job['data'])['publication'],route)

    def test_recovery_uses_pinned_taxonomy_after_configuration_change(self):
        job,data=self.news_job()
        a=self.agent()
        a.cfg['publication_routes'][1]['category_ids']=[7] # Later setting cannot change this reservation.
        a.wp.owned_post.return_value={'author':99,'slug':job['slug'],'status':'future','featured_media':45,
            'date_gmt':datetime.fromisoformat(job['slot']).strftime('%Y-%m-%dT%H:%M:%S'),'tags':[],'categories':[7,1710]}
        a.publish(job,data)
        self.assertEqual(self.store.jobs()[0]['state'],'scheduled')
        a.wp.call.assert_not_called()
        self.assertEqual(data['publication']['category_ids'],[7,1710])

    def test_recovered_news_post_without_news_category_is_not_overwritten(self):
        job,data=self.news_job()
        a=self.agent()
        a.wp.owned_post.return_value={'author':99,'slug':job['slug'],'status':'future','featured_media':45,
            'date_gmt':datetime.fromisoformat(job['slot']).strftime('%Y-%m-%dT%H:%M:%S'),'tags':[],'categories':[7]}
        with self.assertRaisesRegex(Held,'differs'):a.publish(job,data)
        a.wp.call.assert_not_called()

    def test_schedule_confirmation_requires_news_category(self):
        job,data=self.news_job()
        job['media']=45
        a=self.agent()
        a.wp.owned_post.return_value={'author':99,'slug':job['slug'],'status':'draft'}
        def call(path,body=None):
            if path.startswith('media/'):return {'id':45,'author':99,'slug':job['slug']+'-image'}
            result=dict(body)
            result['categories']=[7] # Simulate WP/filter dropping the requested news category.
            return result
        a.wp.call.side_effect=call
        with self.assertRaisesRegex(Deferred,'confirmation'):a.publish(job,data)
        self.assertNotEqual(self.store.jobs()[0]['state'],'scheduled')

    def test_mismatched_reserved_hour_stops_before_wordpress(self):
        job,data=self.news_job()
        data['publication']['hour']=18
        a=self.agent()
        with self.assertRaisesRegex(ValueError,'Cairo slot'):a.publish(job,data)
        a.wp.call.assert_not_called()
        a.wp.owned_post.assert_not_called()

    def test_legacy_reserved_taxonomy_retained_without_adding_news(self):
        job,data=self.news_job()
        del data['publication']
        self.assertEqual(reserved_route(config(),data,job['slot'])['category_ids'],[7])

    def test_completed_two_post_batch_and_primary_budgets_survive_three_job_migration(self):
        self.batch(2)
        with self.store.db:
            self.store.db.execute("UPDATE cycles SET state='scheduled',start='2026-11-18'")
            self.store.db.execute("UPDATE jobs SET state='scheduled',post=rowid+100,media=rowid+500")
        self.store.put('last_run_started','2026-11-17T08:00:00+00:00')
        self.store.reserve('groq',100,0,config()['limits']['groq'])
        before=[dict(j) for j in self.store.jobs()]
        result=migrate_daily(self.store,target=3)
        self.assertEqual(result['target'],3)
        self.assertEqual(before,[dict(j) for j in self.store.jobs()])
        self.assertEqual(self.store.get('last_run_started'),'2026-11-17T08:00:00+00:00')
        self.assertEqual(self.store.db.execute('SELECT tokens FROM usage').fetchone()[0],100)

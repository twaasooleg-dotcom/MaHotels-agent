"""Apply editor-selected source URLs after fetching all pages; never contacts WP/AI."""
import truststore
truststore.inject_into_ssl()

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from core import Store, process_lock
from providers import Sources, Held


def repair(store, reader, replacements, backup_dir):
    if not isinstance(replacements, dict) or not replacements:
        raise ValueError('Supply a nonempty object mapping job IDs to two or more source URLs')
    changes = []
    for job_id, urls in replacements.items():
        job = store.db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not job:
            raise ValueError('Unknown job: ' + job_id)
        data = json.loads(job['data'])
        if data['topic']['source_urls'] == urls and job['state'] != 'held':
            continue  # Reapplying this manifest cannot restart writing or alter live posts.
        if (job['state'] not in ('approved', 'held') or job['post'] or job['media'] or job['slot']
                or any(data.get(k) for k in ('article', 'evidence', 'text_reviewed'))):
            raise ValueError('Source replacement requires an unpublished job with no drafted article: ' + job_id)
        if job['state'] == 'held' and (data.get('held_from') != 'approved'
                or not data.get('last_error', '').startswith('Need two accessible professional sources;')):
            raise ValueError('This job is held for a different reason: ' + job_id)
        if not isinstance(urls, list) or not 2 <= len(urls) <= 5 or len(set(urls)) != len(urls):
            raise ValueError('Provide 2-5 distinct source URLs for ' + job_id)
        if any(not isinstance(url, str) or not reader.allowed(url) for url in urls):
            raise ValueError('Source URL outside approved professional domains')
        verified = [reader.fetch(url) for url in urls]
        if len({page['url'] for page in verified}) < 2:
            raise ValueError('Source URLs resolve to fewer than two distinct pages')
        changes.append((job, data, urls))

    if not changes:
        return {'updated': 0, 'wordpress_requests': 0, 'generation_requests': 0}
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    backup_path = backup_dir / ('jobs-before-source-repair-' + stamp + '.sqlite')
    with closing(sqlite3.connect(backup_path)) as backup:
        store.db.backup(backup)
    # All page validation completes before any job is changed. Source cache writes
    # are harmless if validation aborts; IDs, run markers and provider budgets stay intact.
    with store.db:
        for job, data, urls in changes:
            data.setdefault('source_repair_history', []).append({
                'at': datetime.now(timezone.utc).isoformat(),
                'previous_urls': data['topic']['source_urls'], 'verified_urls': urls})
            data['topic']['source_urls'] = urls
            data.pop('last_error', None)
            data.pop('retry_at', None)
            data.pop('held_from', None)
            store.db.execute('UPDATE jobs SET data=?,state=? WHERE id=?',
                             (json.dumps(data, ensure_ascii=False), 'approved', job['id']))
    return {'updated': len(changes), 'backup': str(backup_path),
            'wordpress_requests': 0, 'generation_requests': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    state = root / 'state'
    replacements = json.loads(args.manifest.read_text(encoding='utf-8-sig'))
    with process_lock(state / 'run.lock'):
        store = Store(state / 'jobs.sqlite')
        reader = Sources(store, json.loads((root / 'config.json').read_text(encoding='utf-8-sig')))
        try:
            print(json.dumps(repair(store, reader, replacements, state), ensure_ascii=False, indent=2))
        finally:
            reader.close()
            store.close()


if __name__ == '__main__':
    main()

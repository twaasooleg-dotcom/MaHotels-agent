"""Preserve legacy topic history while limiting active daily work to the configured number of jobs."""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from core import Store


def select_daily_jobs(rows, target):
    selected, categories, levels = [], set(), set()
    for row in rows:
        topic = json.loads(row['data'])['topic']
        if topic['category'] in categories:
            continue
        if len(selected) == target - 1 and len(levels) < min(2, target) and topic['level'] in levels:
            continue
        selected.append(row)
        categories.add(topic['category'])
        levels.add(topic['level'])
        if len(selected) == target:
            break
    return selected


def promote_backlog(store, cycle_id, target=3):
    if store.jobs(cycle_id):
        raise ValueError('Backlog promotion requires an empty new daily cycle')
    rows = list(store.db.execute("SELECT j.* FROM jobs j JOIN cycles c ON c.id=j.cycle WHERE c.state='backlog' ORDER BY CASE j.state WHEN 'ready' THEN 0 WHEN 'writing' THEN 1 ELSE 2 END,j.rowid"))
    chosen = select_daily_jobs(rows, target)
    with store.db:
        for row in chosen:
            store.db.execute('UPDATE jobs SET cycle=? WHERE id=?', (cycle_id, row['id']))
    return len(chosen)


def migrate_daily(store, target=3):
    previous = store.get('daily_migration_v1')
    if previous and previous.get('target') == target:
        return previous
    cycles = list(store.db.execute("SELECT * FROM cycles WHERE state NOT IN ('scheduled','backlog') ORDER BY id"))
    # Refuse ambiguous partially committed legacy batches rather than alter live IDs/slots.
    for cycle in cycles:
        rows = store.jobs(cycle['id'])
        if len(rows) > target and any(r['post'] or r['media'] or r['slot'] for r in rows):
            raise ValueError('Legacy batch exceeds the requested target with live IDs/reserved slots; inspect before daily migration')
    summary = {'migrated_at': datetime.now(timezone.utc).isoformat(), 'target': target, 'retained': 0, 'backlog': 0}
    with store.db:
        for index, cycle in enumerate(cycles):
            rows = store.jobs(cycle['id'])
            if index > 0:
                store.db.execute("UPDATE cycles SET state='backlog' WHERE id=?", (cycle['id'],))
                summary['backlog'] += len(rows)
                continue
            if len(rows) <= target:
                chosen = rows
            else:
                ranked = sorted(rows, key=lambda r: (r['state'] == 'ready', len(json.loads(r['data']).get('article', {}).get('sections', []))), reverse=True)
                chosen = select_daily_jobs(ranked, target)
            keep = {r['id'] for r in chosen}
            excess = [r for r in rows if r['id'] not in keep]
            if excess:
                cursor = store.db.execute("INSERT INTO cycles(created,start,state,data) VALUES(?,NULL,'backlog',?)", (
                    cycle['created'], json.dumps({'origin': cycle['id'], 'purpose': 'preserved legacy topics for future daily batches'})))
                backlog_id = cursor.lastrowid
                for row in excess:
                    store.db.execute('UPDATE jobs SET cycle=? WHERE id=?', (backlog_id, row['id']))
            data = json.loads(cycle['data'])
            data.update(target=target, cycle_days=1, round=0)
            state = 'planning' if len(chosen) < target else ('building' if cycle['state'] == 'planning' else cycle['state'])
            store.db.execute('UPDATE cycles SET state=?,data=? WHERE id=?', (state, json.dumps(data, ensure_ascii=False), cycle['id']))
            summary['retained'] += len(chosen)
            summary['backlog'] += len(excess)
        store.db.execute('INSERT OR REPLACE INTO kv VALUES(?,?)', ('daily_migration_v1', json.dumps(summary)))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--pending', action='store_true', help='Read-only check for unfinished active work')
    args = parser.parse_args()
    path = args.database.resolve(strict=True)
    if args.pending:
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as read_only:
            count = read_only.execute("SELECT COUNT(*) FROM cycles WHERE state NOT IN ('scheduled','backlog')").fetchone()[0]
        print(int(count > 0))
        return
    target = json.loads(Path(__file__).with_name('config.json').read_text(encoding='utf-8-sig'))['topics_per_cycle']
    store = Store(path)
    try:
        if not store.get('daily_migration_v1') or store.get('daily_migration_v1').get('target') != target:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
            backup = path.with_name('jobs-before-daily-' + stamp + '.sqlite')
            with sqlite3.connect(backup) as snapshot:
                store.db.backup(snapshot)
            print('SQLite snapshot saved: ' + str(backup))
        print(json.dumps(migrate_daily(store, target=target), ensure_ascii=False))
    finally:
        store.close()


if __name__ == '__main__':
    main()

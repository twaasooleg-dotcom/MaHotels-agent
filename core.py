"""Durable state, Cairo slots and fail-closed editorial validation."""
import hashlib
import html
import json
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from zoneinfo import ZoneInfo

UTC = timezone.utc
BYLINE = 'إم إيه هوتيلز - خاص'
ARABIC = re.compile(r'[\u0600-\u06ff]')
CATEGORIES = ('إدارة الفنادق', 'الإيرادات والتسعير', 'التسويق والتوزيع', 'تجربة النزيل', 'المكاتب الأمامية',
              'التدبير الفندقي', 'الأغذية والمشروبات', 'الموارد البشرية', 'الاستثمار الفندقي', 'التصميم والتجهيزات',
              'التكنولوجيا الفندقية', 'الذكاء الاصطناعي', 'الاستدامة', 'الأمن والسلامة', 'الجودة والمعايير',
              'الضيافة الفاخرة', 'المؤتمرات والفعاليات', 'الطلب والأسواق', 'العلاقات العامة', 'الأدلة المهنية')


def utcnow():
    return datetime.now(UTC)


def canonical(value):
    text = unicodedata.normalize('NFKC', html.unescape(str(value))).lower()
    text = re.sub(r'<[^>]*>', ' ', text)
    text = re.sub(r'[\u064b-\u065f\u0670\u0640]', '', text)
    text = text.translate(str.maketrans('أإآىة', 'ااايه'))
    return ' '.join(re.findall(r'[\w]+', text))


def similarity(a, b):
    a, b = canonical(a), canonical(b)
    if not a or not b:
        return 0
    aa, bb = set(a.split()), set(b.split())
    return max(SequenceMatcher(None, a, b).ratio(), len(aa & bb) / max(1, len(aa | bb)))


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def slots(start, cfg):
    """Calendar-day iteration preserves Cairo clock times through DST changes."""
    first = date.fromisoformat(start) if isinstance(start, str) else start
    zone = ZoneInfo(cfg['timezone'])
    return [datetime.combine(first + timedelta(days=d), datetime.min.time(), zone)
            .replace(hour=h).astimezone(UTC).isoformat()
            for d in range(cfg['cycle_days']) for h in cfg['publish_hours']]


def validate_config(cfg):
    if cfg['site_url'] != 'https://mahotels.net' or cfg['wp_username'] != 'ma_news_agent':
        raise ValueError('Unexpected site or WordPress username')
    if cfg['timezone'] != 'Africa/Cairo' or cfg['publish_hours'] != [12, 14, 18]:
        raise ValueError('Expected 12:00, 14:00 and 18:00 Africa/Cairo')
    if cfg['topics_per_cycle'] != 3 or cfg['cycle_days'] != 1 or cfg['image_size'] != [1024, 1024]:
        raise ValueError('Expected 3 topics / 1 day / 1024x1024 images')
    if not cfg['free_only']:
        raise ValueError('Expected free-only operation')
    if cfg.get('tag_id') is not None and (type(cfg['tag_id']) is not int or cfg['tag_id'] <= 0):
        raise ValueError('tag_id must be a positive existing tag ID or null')
    if not isinstance(cfg['category_ids'], list) or any(type(c) is not int or c <= 0 for c in cfg['category_ids']):
        raise ValueError('category_ids must contain positive existing category IDs')
    from publication_policy import configured_routes
    expected = [{'hour':12,'category_ids':[7],'tag_ids':[]}, {'hour':14,'category_ids':[7,1710],'tag_ids':[]}, {'hour':18,'category_ids':[7],'tag_ids':[]}]
    if configured_routes(cfg) != expected or cfg.get('tag_id') is not None or cfg['category_ids'] != [7]:
        raise ValueError('Expected blog at noon/18:00 and blog + news category 1710 at 14:00; 1710 is not a tag')
    if cfg.get('automatic_resumes') is not False:
        raise ValueError('Automatic resumes must be disabled: one run daily')
    if cfg.get('wp_min_interval_seconds', 0) < 3 or not 1 <= cfg.get('wp_max_requests_per_run', 0) <= 400:
        raise ValueError('WordPress calls must be paced and capped')
    if cfg.get('first_publish_date'):
        date.fromisoformat(cfg['first_publish_date'])
    fallback=cfg.get('cloudflare_fallback',{})
    if fallback.get('enabled'):
        if fallback.get('text_model')!='@cf/openai/gpt-oss-120b' or fallback.get('vision_model')!='@cf/meta/llama-4-scout-17b-16e-instruct':
            raise ValueError('Unreviewed Cloudflare fallback model')
        if type(fallback.get('daily_neuron_limit')) is not int or not 1<=fallback['daily_neuron_limit']<=10000:
            raise ValueError('Cloudflare fallback must remain inside its shared free-allocation guard')
        for name in ('cloudflare_text','cloudflare_vision'):
            for key in ('requests','tokens','images','min_interval_seconds','max_request_tokens'):
                if type(cfg['limits'][name].get(key)) is not int or cfg['limits'][name][key]<0:
                    raise ValueError('Invalid Cloudflare fallback limit')
    for p in ('groq', 'gemini', 'cloudflare'):
        limit = cfg['limits'][p]
        if any(type(limit[k]) is not int or limit[k] < 0 for k in ('requests', 'tokens', 'images')):
            raise ValueError('Invalid provider budgets')


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS usage(day TEXT, provider TEXT, requests INTEGER, tokens INTEGER, images INTEGER, PRIMARY KEY(day,provider));
          CREATE TABLE IF NOT EXISTS cooldown(provider TEXT PRIMARY KEY, until REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS archive(id INTEGER PRIMARY KEY, title TEXT, link TEXT, status TEXT, modified TEXT, excerpt TEXT);
          CREATE TABLE IF NOT EXISTS cycles(id INTEGER PRIMARY KEY, created TEXT NOT NULL, start TEXT, state TEXT NOT NULL, data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, cycle INTEGER REFERENCES cycles(id), title TEXT, keyword TEXT, intent TEXT, slot TEXT UNIQUE, slug TEXT UNIQUE, post INTEGER, media INTEGER, state TEXT, data TEXT NOT NULL);
        ''')
        self.db.commit()

    def close(self):
        self.db.close()

    def get(self, key, default=None):
        row = self.db.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO kv VALUES(?,?)', (key, json.dumps(value, ensure_ascii=False)))

    def cooldown(self, provider):
        row = self.db.execute('SELECT until FROM cooldown WHERE provider=?', (provider,)).fetchone()
        return row[0] if row else 0

    def pause(self, provider, until):
        with self.db:
            self.db.execute('INSERT INTO cooldown VALUES(?,?) ON CONFLICT(provider) DO UPDATE SET until=MAX(until,excluded.until)', (provider, until))

    def reserve(self, provider, tokens, images, limits, stamp=None):
        from providers import Deferred
        stamp = stamp or utcnow()
        if self.cooldown(provider) > stamp.timestamp():
            raise Deferred(provider + ' waiting', self.cooldown(provider))
        day = stamp.date().isoformat()
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO usage VALUES(?,?,0,0,0)', (day, provider))
            row = self.db.execute('SELECT requests,tokens,images FROM usage WHERE day=? AND provider=?', (day, provider)).fetchone()
            if any(a + b > limits[k] for a, b, k in zip(row, (1, tokens, images), ('requests', 'tokens', 'images'))):
                midnight = stamp.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                raise Deferred(provider + ' daily local budget reached', midnight.timestamp() + 5)
            self.db.execute('UPDATE usage SET requests=requests+1,tokens=tokens+?,images=images+? WHERE day=? AND provider=?', (tokens, images, day, provider))

    def jobs(self, cycle=None):
        query = 'SELECT * FROM jobs' + (' WHERE cycle=?' if cycle is not None else '') + ' ORDER BY rowid'
        return list(self.db.execute(query, (cycle,) if cycle is not None else ()))

    def save_job(self, job_id, data, **fields):
        if not set(fields) <= {'post', 'media', 'slot', 'state'}:
            raise ValueError('Unexpected job fields')
        fields['data'] = json.dumps(data, ensure_ascii=False)
        with self.db:
            self.db.execute('UPDATE jobs SET ' + ','.join(k + '=?' for k in fields) + ' WHERE id=?', (*fields.values(), job_id))

    def closest(self, title, limit=12, exclude=None):
        items = [dict(r) for r in self.db.execute('SELECT title,link,status FROM archive')]
        items += [{'title': r['title'], 'link': '', 'status': r['state']} for r in self.jobs() if r['id'] != exclude]
        unique = {}
        for item in items:
            unique.setdefault(canonical(item['title']), item)
        return sorted(unique.values(), key=lambda x: similarity(title, x['title']), reverse=True)[:limit]

    def is_duplicate(self, topic):
        if any(similarity(topic['title'], r['title']) >= .82 for r in self.closest(topic['title'])):
            return True
        return any(canonical(r['keyword']) == canonical(topic['keyword']) and canonical(r['intent']) == canonical(topic['intent']) for r in self.jobs())


def text_value(value, name, minimum=1, maximum=2000):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise ValueError('Invalid ' + name)
    if re.search(r'<[^>]+>|```|\*\*|^\s*(?:---|___|\*\*\*)\s*$', value, re.M):
        raise ValueError('HTML/Markdown is forbidden in ' + name)
    return value.strip()


def validate_topic(t):
    for k in ('title', 'category', 'subcategory', 'keyword', 'intent', 'audience', 'angle', 'content_type', 'priority', 'cluster', 'level'):
        text_value(t.get(k), k, maximum=500)
    if ':' in t['title'] or '：' in t['title'] or not ARABIC.search(t['title']):
        raise ValueError('Use Arabic topic titles and .. instead of :')
    category = next((c for c in CATEGORIES if canonical(c) == canonical(t['category'])), None)
    if not category:
        raise ValueError('Topic must use one of the 20 configured hospitality domains')
    t['category'] = category
    for k, lo, hi in (('related_keywords', 3, 5), ('questions', 3, 3), ('source_urls', 2, 5)):
        values = t.get(k)
        if not isinstance(values, list) or not lo <= len(values) <= hi:
            raise ValueError('Invalid topic ' + k)
        for value in values:
            text_value(value, k, maximum=700)
    scores = t.get('scores')
    if not isinstance(scores, list) or len(scores) != 5 or any(type(s) is not int or not 0 <= s <= 20 for s in scores) or sum(scores) < 80:
        raise ValueError('Topic must score >=80 with five 0-20 scores')
    if t.get('score') != sum(scores):
        raise ValueError('Topic score mismatch')
    if t['priority'] not in ('مرتفعة', 'متوسطة', 'منخفضة') or t['level'] not in ('تمهيدي', 'متوسط', 'متقدم'):
        raise ValueError('Invalid topic priority or level')
    return t


def words(article):
    items = [article.get('intro', '')]
    for section in article.get('sections', []):
        items.append(section.get('heading', ''))
        for paragraph in section.get('paragraphs', []):
            items += [paragraph.get('heading', ''), paragraph.get('text', '')]
    for faq in article.get('faq', []):
        items += [faq.get('question', ''), faq.get('answer', '')]
    return sum(len(str(s).split()) for s in items)


def validate_article(a, evidence, cfg):
    text_value(a.get('title'), 'title', 10, 180)
    intro = text_value(a.get('intro'), 'intro', maximum=2000)
    if not 40 <= len(intro.split()) <= 60:
        raise ValueError('Introduction must be 40-60 words without a heading')
    text_value(a.get('excerpt'), 'excerpt', maximum=350)
    text_value(a.get('image_prompt'), 'image_prompt', maximum=1500)
    if a.get('title') != a.get('approved_title'):
        raise ValueError('Writer changed the approved topic title')
    ids = {b['id'] for b in evidence}

    def refs(item):
        if not isinstance(item.get('source_ids'), list) or not item['source_ids'] or any(type(i) is not int or i not in ids for i in item['source_ids']):
            raise ValueError('Missing or unknown evidence IDs')

    refs(a)
    sections = a.get('sections')
    if not isinstance(sections, list) or len(sections) != 4:
        raise ValueError('Expected four body sections: causes, steps, mistakes, practical tips')
    all_text = [intro]
    for section in sections:
        heading = text_value(section.get('heading'), 'section heading', maximum=150)
        if 'الخلاصة' in heading:
            raise ValueError('Conclusion section is forbidden')
        paragraphs = section.get('paragraphs')
        if not isinstance(paragraphs, list) or not 3 <= len(paragraphs) <= 6:
            raise ValueError('Expected 3-6 short paragraphs in each body section')
        all_text.append(heading)
        for p in paragraphs:
            ph = text_value(p.get('heading'), 'paragraph heading', maximum=150)
            text = text_value(p.get('text'), 'paragraph', maximum=3500)
            if not 45 <= len(text.split()) <= 120 or 'الخلاصة' in ph:
                raise ValueError('Each practical paragraph needs 45-120 words and an allowed heading')
            refs(p)
            all_text += [ph, text]
    faq = a.get('faq')
    if not isinstance(faq, list) or not 4 <= len(faq) <= 7:
        raise ValueError('Expected 4-7 final FAQ questions and answers')
    for f in faq:
        text_value(f.get('question'), 'FAQ question', maximum=250)
        text_value(f.get('answer'), 'FAQ answer', maximum=2500)
        if not 20 <= len(f['answer'].split()) <= 100:
            raise ValueError('FAQ answers must be 20-100 words')
        refs(f)
        all_text += [f['question'], f['answer']]
    count = words(a)
    if not cfg['min_article_words'] <= count <= cfg['max_article_words']:
        raise ValueError(f'Article has {count} words; required 1500-2000')
    joined = ' '.join(all_text)
    if len(ARABIC.findall(joined)) < len(joined) * .35:
        raise ValueError('Article must be predominantly Arabic')
    if any(similarity(p['text'], q['text']) > .92 for si, s in enumerate(sections) for p in s['paragraphs'] for tj, t in enumerate(sections) for q in t['paragraphs'] if si < tj):
        raise ValueError('Repeated paragraphs across sections')
    return count


def render_article(a, sources, related=None):
    esc = html.escape
    body = '<p><strong>' + BYLINE + '</strong></p><p>' + esc(a['intro']) + '</p>'
    for section in a['sections']:
        body += '<h2><strong>' + esc(section['heading']) + '</strong></h2>'
        for p in section['paragraphs']:
            body += '<p><strong>' + esc(p['heading']) + '</strong><br>' + esc(p['text']) + '</p>'
    if related:
        body += '<p>للمزيد: <a href="' + esc(related['link'], quote=True) + '">' + esc(related['title']) + '</a></p>'
    body += '<h2><strong>مصادر مهنية</strong></h2><ul>'
    for source in sources:
        body += '<li><a rel="noopener" href="' + esc(source['url'], quote=True) + '">' + esc(source['title']) + '</a></li>'
    body += '</ul><h2><strong>الأسئلة الشائعة</strong></h2>'
    for f in a['faq']:
        body += '<p><strong>' + esc(f['question']) + '</strong></p><p>' + esc(f['answer']) + '</p>'
    return body


class ProcessBusy(RuntimeError):
    """Another process owns the advisory/Windows byte lock."""


class LockAccessError(RuntimeError):
    """The lock path itself cannot be opened or initialized."""


@contextmanager
def process_lock(path):
    try:
        handle = open(path, 'a+b', buffering=0)
    except OSError:
        raise LockAccessError('Cannot open state/run.lock; check folder permissions and file attributes') from None
    try:
        # Windows permits locking beyond EOF. Acquire before touching byte zero:
        # another process's mandatory byte lock forbids even reading that byte.
        handle.seek(0)
        try:
            if __import__('os').name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            import errno
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK) or getattr(error, 'winerror', None) in (32, 33, 36):
                raise ProcessBusy('Another MaHotels instance is running. No second run started; use status or wait for it to finish.') from None
            raise LockAccessError('Could not acquire state/run.lock; check filesystem access') from None
        if __import__('os').fstat(handle.fileno()).st_size == 0:
            handle.write(b'0')
        yield
    finally:
        # Closing releases the OS lock, including after exceptions. Never unlink
        # a live lock file: that could let a second process use a different inode.
        handle.close()

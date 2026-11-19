"""Bounded article parts and targeted repairs; no publication or approval bypass."""
import copy
import json
from core import text_value, words

def refs(value, evidence):
    ids = {b['id'] for b in evidence}
    if not isinstance(value.get('source_ids'), list) or not value['source_ids'] or any(type(i) is not int or i not in ids for i in value['source_ids']):
        raise ValueError('Missing or unknown evidence IDs')

def validate_part(kind, value, evidence):
    if not isinstance(value,dict):raise ValueError('Article part must be an object')
    if kind == 'opening':
        text = text_value(value.get('intro'), 'intro', maximum=2000)
        if not 40 <= len(text.split()) <= 60:
            raise ValueError('Opening needs 40-60 actual space-separated words')
        text_value(value.get('excerpt'), 'excerpt', maximum=350)
        text_value(value.get('image_prompt'), 'image prompt', maximum=1500)
        refs(value, evidence)
    elif kind == 'section':
        title = text_value(value.get('heading'), 'section heading', maximum=150)
        if 'الخلاصة' in title:
            raise ValueError('Conclusion is forbidden')
        ps = value.get('paragraphs')
        if not isinstance(ps, list) or not 3 <= len(ps) <= 6:
            raise ValueError('A section needs 3-6 paragraphs, matching final validation')
        total = 0
        for p in ps:
            if not isinstance(p,dict):raise ValueError('Paragraph must be an object')
            title = text_value(p.get('heading'), 'paragraph heading', maximum=150)
            text = text_value(p.get('text'), 'paragraph', maximum=3500)
            if 'الخلاصة' in title or not 45 <= len(text.split()) <= 120:
                raise ValueError('Paragraph needs 45-120 actual words and an allowed heading')
            total += len(text.split())
            refs(p, evidence)
    elif kind in ('append_paragraph','paragraph'):
        heading=text_value(value.get('heading'),'paragraph heading',maximum=150)
        text=text_value(value.get('text'),'paragraph',maximum=3500)
        if 'الخلاصة' in heading or not 45<=len(text.split())<=120:
            raise ValueError('Paragraph needs 45-120 words and an allowed heading')
        refs(value,evidence)
    elif kind == 'faq_item':
        text_value(value.get('question'),'FAQ question',maximum=250)
        answer=text_value(value.get('answer'),'FAQ answer',maximum=2500)
        if not 20<=len(answer.split())<=100:raise ValueError('FAQ answer needs 20-100 words')
        refs(value,evidence)
    elif kind == 'faq':
        fs = value.get('faq')
        if not isinstance(fs, list) or len(fs) != 5:
            raise ValueError('Generate exactly five FAQ entries')
        for f in fs:
            if not isinstance(f,dict):raise ValueError('FAQ must be an object')
            text_value(f.get('question'), 'FAQ question', maximum=250)
            answer = text_value(f.get('answer'), 'FAQ answer', maximum=2500)
            if not 20 <= len(answer.split()) <= 100:
                raise ValueError('Each FAQ answer needs 20-100 words, matching final article validation')
            refs(f, evidence)
    else:
        raise ValueError('Unknown article part')

def apply_part(article, kind, index, value, paragraph_index=None):
    if kind == 'opening':
        for k in ('intro', 'excerpt', 'image_prompt', 'source_ids'):
            article[k] = value[k]
    elif kind == 'paragraph':
        article['sections'][index]['paragraphs'][paragraph_index]=value
    elif kind == 'faq_item':
        article['faq'][index]=value
    elif kind == 'append_paragraph':
        if len(article['sections'][index]['paragraphs'])>=6:
            raise ValueError('Cannot exceed six paragraphs per section')
        article['sections'][index]['paragraphs'].append(value)
    elif kind == 'section':
        if index == len(article['sections']):
            article['sections'].append(value)
        else:
            article['sections'][index] = value
    else:
        article['faq'] = value['faq']

def structural_targets(a, evidence, cfg):
    targets=[]
    try:
        validate_part('opening',a,evidence)
    except (ValueError,KeyError,TypeError):
        targets.append({'kind':'opening','index':0,'attempts':0})
    for i,s in enumerate(a.get('sections',[])):
        try:
            title=text_value(s.get('heading'),'section heading',maximum=150)
            if 'الخلاصة' in title or not 3<=len(s['paragraphs'])<=6:raise ValueError('Invalid section')
            for p in s['paragraphs']:
                heading=text_value(p.get('heading'),'paragraph heading',maximum=150)
                text=text_value(p.get('text'),'paragraph',maximum=3500)
                if not 45<=len(text.split())<=120 or 'الخلاصة' in heading:raise ValueError('Invalid paragraph')
                refs(p,evidence)
        except (ValueError,KeyError,TypeError):
            targets.append({'kind':'section','index':i,'attempts':0})
    for f in a.get('faq',[]):
        try:
            if not 20<=len(f.get('answer','').split())<=100:raise ValueError('FAQ length')
            refs(f,evidence)
        except (ValueError,KeyError,TypeError):
            targets.append({'kind':'faq','index':0,'attempts':0})
            break
    if targets:
        return targets
    if words(a)<cfg['min_article_words']:
        import math
        needed=math.ceil((cfg['min_article_words']+50-words(a))/45)
        for i,s in sorted(enumerate(a['sections']),key=lambda item:sum(len(p['text'].split()) for p in item[1]['paragraphs'])):
            for _ in range(6-len(s['paragraphs'])):
                targets.append({'kind':'append_paragraph','index':i,'attempts':0})
                needed-=1
                if needed<=0:return targets
    elif words(a)>cfg['max_article_words']:
        i=max(range(len(a['sections'])),key=lambda n:sum(len(p['text'].split()) for p in a['sections'][n]['paragraphs']))
        targets.append({'kind':'section','index':i,'attempts':0})
    return targets

def request_part(pool, system, data, kind, index, purposes, paragraph_index=None):
    a=data.get('article', {})
    evidence=[{'id':b['id'],'text':b['text']} for b in data['evidence']]
    base={'topic':data['topic']['title'], 'keyword':data['topic']['keyword'],
          'angle':data['topic']['angle'][:200], 'evidence':evidence,
          'corrections':data.get('corrections', [])}
    rules=('Write natural professional Arabic. Do not copy schema placeholders. Evidence may be English; translate supported meaning faithfully. '
           'Do not invent figures, savings, guarantees or firsthand experience. Do not assert that research or data proves a claim unless the supplied excerpt explicitly says so. Write operational recommendations as conditional proposals, not alleged observations or guarantees. '
           'Count actual space-separated words before returning; do not add word counts to JSON. ')
    if kind=='opening':
        rules+='Repair/write ONLY opening metadata. Intro 40-60 words, no heading/byline. Correct Arabic grammar. '
        if a.get('intro'):
            base['previous_intro']=a['intro']
        rules+='Return {"intro":"...","excerpt":"<=300 characters","source_ids":[1],"image_prompt":"A detailed topic-specific visible scene in English, no text or graphs"}. '
        cap=1100
    elif kind=='section':
        rules+=('Write ONLY body section '+str(index+1)+'/4: '+purposes[index]+
                '. Exactly four paragraphs, 85-95 actual words EACH, total 340-390 text words. '
                'Each paragraph needs a specific Arabic heading. Add useful supported analysis, never padding. '
                'Return {"heading":"...","paragraphs":[{"heading":"...","text":"...","source_ids":[1]}]}. ')
        base['other_headings']=[s['heading'] for i,s in enumerate(a.get('sections',[])) if i!=index]
        cap=2400
    elif kind in ('paragraph','append_paragraph'):
        rules+='Write ONLY ONE additional practical paragraph, 80-100 words, adding a new supported action or explanation. Return {"heading":"specific heading","text":"...","source_ids":[1]}. '
        base['existing_headings']=[p['heading'] for part in a.get('sections',[]) for p in part['paragraphs']]
        base['section_heading']=a['sections'][index]['heading']
        cap=1100
        if kind=='paragraph':
            base['previous_paragraph']=a['sections'][index]['paragraphs'][paragraph_index]
            rules+='Correct ONLY the previous paragraph, addressing the given issues; retain valid details and heading where possible. '
    elif kind=='faq_item':
        base['previous_faq']=a['faq'][index]
        rules+='Correct ONLY this FAQ answer using the evidence. Return {"question":"same question","answer":"35-45 Arabic words","source_ids":[1]}. '
        cap=900
    else:
        rules+='Write ONLY five final FAQs; each answer 35-45 words. Return {"faq":[{"question":"...","answer":"...","source_ids":[1]}]}. '
        cap=1900
    return pool.text(system, rules+json.dumps(base,ensure_ascii=False,separators=(',',':')), cap=cap)

def article_progress(data):
    from core import words
    a=data.get('article',{})
    return {'words':words(a),'body_sections':len(a.get('sections',[])),
            'faq_complete':bool(a.get('faq')),'review_packets_passed':len(data.get('review_cache',{})),
            'repairs_left':len(data.get('repair_queue',[])),
            'text_reviewed':bool(data.get('text_reviewed')),
            'image_reviewed':bool(data.get('image_checked'))}

def review_targets(seeds,packet,issues):
    """Resolve reviewer-local locations to exact persistent article units."""
    import re
    from core import canonical
    if len(seeds)!=1:return seeds
    seed=seeds[0]
    raw=json.dumps(issues,ensure_ascii=False)
    normalized=canonical(raw)
    if seed['kind']=='paragraph':
        values=packet.get('paragraphs',[])
        found={int(v) for v in re.findall(r'paragraphs\[(\d+)\]',raw) if int(v)<len(values)}
        found.update(i for i,p in enumerate(values) if canonical(p['heading']) in normalized)
        if not found:found=set(range(len(values)))
        return [{'kind':'paragraph','index':seed['index'],'paragraph':seed['paragraph']+i} for i in sorted(found)]
    if seed['kind']=='faq_item':
        values=packet.get('faq',[])
        found={int(v) for v in re.findall(r'faq\[(\d+)\]',raw) if int(v)<len(values)}
        found.update(i for i,f in enumerate(values) if canonical(f['question']) in normalized)
        if not found:found=set(range(len(values)))
        return [{'kind':'faq_item','index':seed['index']+i} for i in sorted(found)]
    return seeds

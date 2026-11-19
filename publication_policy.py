"""Persist each slot's WordPress taxonomy independently of later config edits."""
from datetime import datetime
from zoneinfo import ZoneInfo


def validate_route(route):
    if not isinstance(route, dict) or type(route.get('hour')) is not int or not 0 <= route['hour'] <= 23:
        raise ValueError('Publication route needs an integer Cairo hour')
    for key in ('category_ids', 'tag_ids'):
        values = route.get(key)
        if not isinstance(values, list) or any(type(v) is not int or v <= 0 for v in values) or len(set(values)) != len(values):
            raise ValueError('Publication route needs unique positive category/tag IDs')
    if not route['category_ids']:
        raise ValueError('Publication route needs an existing category')
    return {k: list(route[k]) if k != 'hour' else route[k] for k in ('hour','category_ids','tag_ids')}


def legacy_route(cfg, hour):
    """Old reserved jobs retain the original global taxonomy."""
    return validate_route({'hour':hour, 'category_ids':cfg['category_ids'],
                           'tag_ids':[cfg['tag_id']] if cfg.get('tag_id') is not None else []})


def configured_routes(cfg):
    if 'publication_routes' not in cfg:
        return [legacy_route(cfg, hour) for hour in cfg['publish_hours']]
    routes = [validate_route(r) for r in cfg['publication_routes']]
    if [r['hour'] for r in routes] != cfg['publish_hours']:
        raise ValueError('Publication routes must match the ordered publication hours exactly')
    return routes


def reserved_route(cfg, data, slot):
    hour=datetime.fromisoformat(slot).astimezone(ZoneInfo(cfg['timezone'])).hour
    route=validate_route(data['publication']) if 'publication' in data else legacy_route(cfg,hour)
    if route['hour'] != hour:
        raise ValueError('Reserved publication route differs from its Cairo slot; inspect without reassigning')
    return route


def taxonomy_matches(post, route):
    return all(c in post.get('categories',[]) for c in route['category_ids']) and all(t in post.get('tags',[]) for t in route['tag_ids'])

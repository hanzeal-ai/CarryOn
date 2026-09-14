"""Expose only selectable model metadata from the native Codex catalog cache."""
import json
from pathlib import Path


def catalog(home):
    try:
        raw = json.loads((Path(home) / 'models_cache.json').read_text())
        models = []
        for item in raw.get('models', []):
            if item.get('visibility') != 'list' or not isinstance(item.get('slug'), str):
                continue
            efforts = [level['effort'] for level in item.get('supported_reasoning_levels', [])
                       if isinstance(level, dict) and isinstance(level.get('effort'), str) and level['effort']]
            if efforts:
                models.append({'id': item['slug'], 'name': item.get('display_name') or item['slug'],
                               'efforts': efforts, 'defaultEffort': item.get('default_reasoning_level')})
        return {'models': models, 'source': 'native-cache', 'fetchedAt': raw.get('fetched_at')}
    except (OSError, ValueError, TypeError, AttributeError):
        return {'models': [], 'source': 'native-cache'}

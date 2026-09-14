import json
import tempfile
import unittest
from pathlib import Path
from carryon.models import catalog


class ModelCatalogTests(unittest.TestCase):
    def test_only_native_visible_choices_and_efforts_are_exposed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'models_cache.json'
            self.assertEqual(catalog(folder)['models'], [])
            path.write_text(json.dumps({'fetched_at': 'today', 'models': [
                {'slug': 'visible', 'visibility': 'list', 'supported_reasoning_levels': [{'effort': 'low'}, {'effort': 'high'}], 'instructions': 'private'},
                {'slug': 'hidden', 'visibility': 'hide', 'supported_reasoning_levels': [{'effort': 'high'}]}]}))
            result = catalog(folder)
            self.assertEqual([m['id'] for m in result['models']], ['visible'])
            self.assertEqual(result['models'][0]['efforts'], ['low', 'high'])
            self.assertNotIn('private', json.dumps(result))
            path.write_text('invalid')
            self.assertEqual(catalog(folder)['models'], [])

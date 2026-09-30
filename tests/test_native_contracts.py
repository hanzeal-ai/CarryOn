"""Independent wire fixture plus optional installed-app compatibility gate."""
import json
from pathlib import Path
import tempfile
import shutil
import unittest

from scripts.check_native_contracts import compare, implemented_versions, installed_contract

FIXTURE = Path(__file__).parent / 'fixtures/desktop-ipc-contract.json'
APP = Path('/Applications/ChatGPT.app')


class NativeContractTests(unittest.TestCase):
    def test_implementation_matches_independently_captured_wire_table(self):
        native = json.loads(FIXTURE.read_text())
        compare(implemented_versions(), native['versions'])
        # Literal expectations prevent silently changing fixture and code to the
        # known broken versions without revisiting the native contract evidence.
        self.assertEqual(native['versions']['thread-follower-update-thread-settings'], 2)
        self.assertEqual(native['versions']['thread-read-state-changed'], 3)
        self.assertEqual(native['versions']['thread-queued-followups-changed'], 2)

    def test_drift_and_missing_methods_fail_closed(self):
        baseline = json.loads(FIXTURE.read_text())['versions']
        changed = {**baseline, 'thread-follower-update-thread-settings': 1}
        with self.assertRaisesRegex(ValueError, 'thread-follower-update-thread-settings'):
            compare(implemented_versions(), changed)
        changed = dict(baseline)
        changed.pop('thread-read-state-changed')
        with self.assertRaisesRegex(ValueError, 'thread-read-state-changed'):
            compare(implemented_versions(), changed)

    @unittest.skipUnless((APP / 'Contents/Resources/app.asar').is_file(), 'requires installed desktop app')
    def test_installed_app_still_accepts_implemented_wire_versions(self):
        compare(implemented_versions(), installed_contract(APP)['versions'])

    def test_unrecognized_bundle_cannot_claim_compatibility(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(OSError):
                installed_contract(Path(temporary))

    @unittest.skipUnless((APP / 'Contents/Resources/codex').is_file() or shutil.which('codex'), 'requires installed Codex schema exporter')
    def test_pinned_public_schemas_match_native_export(self):
        import subprocess
        from carryon.contracts import SCHEMAS
        from carryon.usage import executable
        with tempfile.TemporaryDirectory() as temporary:
            subprocess.run([executable(), 'app-server',
                'generate-json-schema', '--experimental', '--out', temporary],
                check=True, capture_output=True, timeout=30)
            for name, schema in SCHEMAS.items():
                with self.subTest(schema=name):
                    candidates = list(Path(temporary).rglob(schema['title'] + '.json'))
                    self.assertEqual(len(candidates), 1)
                    expected = json.loads(candidates[0].read_text())
                    pinned = json.loads(json.dumps(schema))
                    if name == 'settings':
                        # Desktop-only profile metadata is not a public app-server field.
                        pinned['properties'].pop('activePermissionProfile')
                    self.assertEqual(pinned, expected)

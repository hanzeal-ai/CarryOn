import json
import tempfile
import unittest
from pathlib import Path
from scripts.build_app_updates import manifest, ios_releases


class AppUpdatePublishingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.ios = self.root/'ios.json'
        self.ios.write_text('[]')
        self.dmg = self.root/'CarryOn-0.3.0-macos-arm64.dmg'
        self.dmg.write_bytes(b'fixture archive')

    def tearDown(self):
        self.temporary.cleanup()

    def test_only_publishes_existing_architecture_and_leaves_ios_unpublished(self):
        data = manifest([self.dmg], self.ios)
        self.assertEqual(data['schemaVersion'], 1)
        self.assertEqual(len(data['releases']), 1)
        self.assertEqual(data['releases'][0]['architecture'], 'arm64')
        self.assertTrue(data['releases'][0]['url'].endswith('/v0.3.0/'+self.dmg.name))
        with self.assertRaises(ValueError): manifest([self.dmg, self.dmg], self.ios)
        with self.assertRaises(ValueError): manifest([self.root/'CarryOn-0.3.0-macos-x86_64.dmg'], self.ios)

    def test_ios_requires_real_apple_link_and_preserves_channel_build(self):
        entry = {'platform': 'ios', 'channel': 'testflight', 'bundleIdentifier': 'com.hanzeal.carryon',
                 'version': '1.0', 'build': '4', 'minimumSystemVersion': '17.0',
                 'url': 'https://testflight.apple.com/join/AbCd1234', 'notes': '修复会话加载'}
        self.ios.write_text(json.dumps([entry]))
        self.assertEqual(manifest([self.dmg], self.ios)['releases'][0], entry)
        for url in ['http://testflight.apple.com/join/AbCd1234', 'https://evil.test/join/AbCd1234',
                    'https://testflight.apple.com/join/AbCd1234?redirect=bad']:
            self.ios.write_text(json.dumps([{**entry, 'url': url}]))
            with self.assertRaises(ValueError): ios_releases(self.ios)
        self.ios.write_text(json.dumps([entry, entry]))
        with self.assertRaises(ValueError): ios_releases(self.ios)

    def test_empty_release_is_unpublished_not_current(self):
        self.assertEqual(manifest([], self.ios), {'schemaVersion': 1, 'releases': []})

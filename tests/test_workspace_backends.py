import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from carryon.services import workspace_backend, workspace_codex_home
from carryon.services import register, records
from carryon.workspace_seed import seed
from carryon.app_server import AppServer
from carryon.ipc import IPCError
from carryon.operations import controls


class WorkspaceBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.env = patch.dict(os.environ, {'CARRYON_REGISTRY_DIR': str(self.root/'registry'),
            'CARRYON_HOME': str(self.root/'default'), 'CODEX_HOME': str(self.root/'desktop-codex')})
        self.env.start()
    def tearDown(self):
        self.env.stop(); self.temp.cleanup()

    def test_default_identity_and_independent_homes_survive_restart(self):
        default, a, b = (self.root/n for n in ('default','a','b'))
        self.assertEqual(workspace_backend(default), 'desktop-ipc')
        self.assertEqual(workspace_codex_home(default), self.root/'desktop-codex')
        for directory in (a,b):
            entry = register(directory, codex_home=self.root/'desktop-codex')
            self.assertEqual(entry['backend'], 'app-server')
            self.assertEqual(Path(entry['codexHome']), directory/'codex-home')
            self.assertEqual(workspace_codex_home(directory, entry['codexHome']), directory/'codex-home')
        with patch.dict(os.environ, {'CARRYON_HOME':str(a)}):
            self.assertEqual(workspace_backend(a), 'app-server')
        self.assertNotEqual(records()[str(a)]['codexHome'], records()[str(b)]['codexHome'])

    def test_duplicate_real_home_and_default_symlink_are_rejected(self):
        shared = self.root/'shared'; shared.mkdir()
        register(self.root/'a', codex_home=shared)
        alias = self.root/'alias'; alias.symlink_to(shared, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, '其他工作区'):
            register(self.root/'b', codex_home=alias)
        target = self.root/'desktop-codex'; target.mkdir()
        b=self.root/'b'; b.mkdir(); (b/'codex-home').symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, '不能链接'):
            workspace_codex_home(b)

    def test_seed_copies_only_login_and_model_configuration_once(self):
        source=self.root/'desktop-codex'; source.mkdir()
        (source/'auth.json').write_text('{"test_token":"synthetic"}')
        (source/'config.toml').write_text('model="test-model"\napproval_policy="never"\nnotify=["external"]\n[model_providers.test]\nbase_url="http://example.invalid"\n[projects."/private"]\ntrust_level="trusted"\n')
        (source/'state_5.sqlite').write_text('must not copy')
        (source/'sessions').mkdir()
        home=self.root/'a/codex-home'; seed(home)
        import tomllib
        copied=tomllib.loads((home/'config.toml').read_text())
        self.assertEqual(set(copied), {'model','model_providers'})
        self.assertEqual(json.loads((home/'auth.json').read_text()), {'test_token':'synthetic'})
        self.assertFalse((home/'sessions').exists()); self.assertFalse((home/'state_5.sqlite').exists())
        self.assertEqual((home/'auth.json').stat().st_mode&0o777, 0o600)
        (source/'auth.json').write_text('{"test_token":"changed"}')
        (home/'config.toml').write_text('model="workspace"')
        seed(home)
        self.assertEqual((home/'config.toml').read_text(),'model="workspace"')
        self.assertEqual(json.loads((home/'auth.json').read_text())['test_token'],'synthetic')

    def test_existing_credentials_are_preserved_and_bad_source_is_not_partially_published(self):
        source=self.root/'desktop-codex';source.mkdir()
        (source/'config.toml').write_text('model="inherited"')
        (source/'auth.json').write_text('{broken')
        home=self.root/'new'
        with self.assertRaises(ValueError):seed(home)
        self.assertFalse((home/'config.toml').exists())
        (home/'auth.json').write_text('{"owned":true}')
        seed(home)
        self.assertEqual(json.loads((home/'auth.json').read_text()),{'owned':True})

    def test_shared_configuration_links_are_rejected_even_after_initialization(self):
        source=self.root/'desktop-codex';source.mkdir()
        (source/'auth.json').write_text('{"token":"fixture"}')
        for hardlink in (False, True):
            home=self.root/str(hardlink);seed(home)
            (home/'auth.json').unlink()
            if hardlink: os.link(source/'auth.json',home/'auth.json')
            else: (home/'auth.json').symlink_to(source/'auth.json')
            with self.assertRaisesRegex(ValueError, '不能使用链接'):seed(home)

    def test_stream_preserves_old_snapshots_and_pending_requests(self):
        app=AppServer(self.root/'a')
        tid='00000000-0000-0000-0000-000000000001';turn='turn-a'
        app._event({'method':'thread/started','params':{'thread':{'id':tid,'cwd':str(self.root),'status':{'type':'idle'}}}})
        app._event({'method':'turn/started','params':{'threadId':tid,'turn':{'id':turn,'status':'inProgress','items':[]}}})
        app._event({'method':'item/started','params':{'threadId':tid,'turnId':turn,'item':{'id':'answer','type':'agentMessage','text':''}}})
        old=app.current(tid)
        app._event({'method':'item/agentMessage/delta','params':{'threadId':tid,'turnId':turn,'itemId':'answer','delta':'hello'}})
        self.assertEqual(old['turns'][0]['items'][0]['text'],'')
        self.assertEqual(app.current(tid)['turns'][0]['items'][0]['text'],'hello')
        request={'id':7,'method':'item/commandExecution/requestApproval','params':{'threadId':tid,'turnId':turn,'itemId':'cmd'}}
        app._event(request)
        self.assertEqual(controls(app.current(tid))['requests'][0]['id'],7)
        app._event({'method':'serverRequest/resolved','params':{'threadId':tid,'requestId':7}})
        self.assertEqual(app.current(tid)['requests'],[])
        app._event({'method':'turn/completed','params':{'threadId':tid,'turn':{'id':turn,'status':'completed','items':[]}}})
        self.assertEqual(app.current(tid)['turns'][0]['items'][0]['text'],'hello')
        self.assertNotIn('settings',controls(app.current(tid))['supportedOperations'])

    def test_refused_rpc_is_definite_and_disconnect_after_write_is_uncertain(self):
        app=AppServer(self.root/'a')
        def refused(value):
            waiter=app.pending[value['id']]
            waiter['response']={'error':{'message':'refused'}};waiter['event'].set()
        with patch.object(app,'_write',side_effect=refused):
            with self.assertRaises(IPCError) as error: app.rpc('turn/start',{})
        self.assertFalse(error.exception.uncertain)
        with patch.object(app,'_write',side_effect=lambda _:app.close()):
            with self.assertRaises(IPCError) as error: app.rpc('turn/start',{})
        self.assertTrue(error.exception.uncertain)


if __name__=='__main__':unittest.main()

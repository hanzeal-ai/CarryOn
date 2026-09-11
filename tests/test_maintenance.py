import hashlib
import io
import json
import os
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from connectnow import maintenance as m
from connectnow.cli import main


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.old=self.root/'old';self.old.mkdir();self.binary=self.old/'connectnow';self.binary.write_text('old')
        self.link=self.root/'bin/connectnow';self.link.parent.mkdir();self.link.symlink_to(self.binary)
        self.releases=self.root/'releases'

    def tearDown(self):self.temp.cleanup()

    def archive(self,extras=(),script=b'#!/bin/sh\nprintf "0.3.0\\n"\n'):
        package=self.root/'ConnectNow-0.3.0-macos-arm64-cli.tar.gz'
        with tarfile.open(package,'w:gz') as f:
            for name,kind,content in [('connectnow',tarfile.DIRTYPE,b''),('connectnow/_internal',tarfile.DIRTYPE,b''),
                                      ('connectnow/connectnow',tarfile.REGTYPE,script),*extras]:
                item=tarfile.TarInfo(name);item.type=kind;item.mode=0o755
                if kind==tarfile.REGTYPE:item.size=len(content);f.addfile(item,io.BytesIO(content))
                elif kind==tarfile.SYMTYPE:item.linkname=content;f.addfile(item)
                else:f.addfile(item)
        (self.root/'SHA256SUMS').write_text(hashlib.sha256(package.read_bytes()).hexdigest()+'  '+package.name+'\n')
        return package

    def test_atomic_install_retains_old_program_and_unrelated_files(self):
        package=self.archive()
        state=self.root/'state';state.mkdir();(state/'cloud.json').write_text('private-config')
        with patch.object(m.sys,'platform','darwin'),patch.object(m.platform,'machine',return_value='arm64'):
            target,old=m.install(package,self.link,self.releases)
        self.assertEqual(self.link.resolve(),target)
        self.assertEqual(old,str(self.binary));self.assertEqual(self.binary.read_text(),'old')
        self.assertEqual((state/'cloud.json').read_text(),'private-config')

    def test_checksum_failure_does_not_change_entry(self):
        package=self.archive();package.write_bytes(package.read_bytes()+b'corrupted')
        with patch.object(m.sys,'platform','darwin'),patch.object(m.platform,'machine',return_value='arm64'):
            with self.assertRaisesRegex(ValueError,'SHA256'):m.install(package,self.link,self.releases)
        self.assertEqual(self.link.resolve(),self.binary)

    def test_bad_new_executable_keeps_old_entry(self):
        package=self.archive(script=b'#!/bin/sh\nexit 1\n')
        with patch.object(m.sys,'platform','darwin'),patch.object(m.platform,'machine',return_value='arm64'):
            with self.assertRaisesRegex(ValueError,'版本验证失败'):m.install(package,self.link,self.releases)
        self.assertEqual(self.link.resolve(),self.binary)

    def test_wrong_architecture_and_missing_checksum_are_rejected(self):
        package=self.archive()
        with patch.object(m.sys,'platform','darwin'),patch.object(m.platform,'machine',return_value='x86_64'):
            with self.assertRaisesRegex(ValueError,'架构'):m.install(package,self.link,self.releases)
        (self.root/'SHA256SUMS').unlink()
        with self.assertRaisesRegex(ValueError,'SHA256SUMS'):m.checksum(package)
        self.assertEqual(self.link.resolve(),self.binary)

    def test_archive_rejects_path_escape_external_links_duplicates_and_devices(self):
        attacks=[('../outside',tarfile.REGTYPE,b'bad'),('/tmp/outside',tarfile.REGTYPE,b'bad'),
                 ('connectnow/escape',tarfile.SYMTYPE,'../../outside'),
                 ('connectnow/escape',tarfile.SYMTYPE,'/tmp/outside'),
                 ('connectnow/CONNECTNOW',tarfile.REGTYPE,b'bad'),
                 ('connectnow/device',tarfile.CHRTYPE,b'')]
        for index,attack in enumerate(attacks):
            with self.subTest(attack=attack):
                package=self.archive([attack]);directory=self.root/f'unpack-{index}';directory.mkdir()
                with self.assertRaises(ValueError):m.extract(package,directory)
        self.assertFalse((self.root/'outside').exists())

    def test_internal_framework_symlinks_are_supported(self):
        package=self.archive([('._connectnow',tarfile.REGTYPE,b'metadata'),('connectnow/._install.sh',tarfile.REGTYPE,b'metadata'),('connectnow/_internal/python',tarfile.REGTYPE,b'runtime'),
                              ('connectnow/_internal/Python.framework',tarfile.SYMTYPE,'python')])
        directory=self.root/'unpack';directory.mkdir();m.extract(package,directory)
        self.assertEqual((directory/'connectnow/_internal/Python.framework').read_bytes(),b'runtime')

    def test_uninstall_only_removes_own_link(self):
        with patch.object(m,'current_link',return_value=self.link),redirect_stdout(io.StringIO()) as output:
            self.assertEqual(m.uninstall(),0)
        self.assertFalse(self.link.is_symlink());self.assertTrue(self.binary.exists())
        self.assertIn('后台服务',output.getvalue())

    def test_source_install_is_not_silently_replaced(self):
        with patch.object(m.sys,'frozen',False,create=True):
            with self.assertRaisesRegex(ValueError,'独立 CLI'):m.current_link()

    def test_check_does_not_install_or_require_a_running_service(self):
        with patch.object(m,'latest',return_value=('99.0.0','bundle',{})),patch.object(m,'install') as install, \
                patch('connectnow.cli.running') as running,redirect_stdout(io.StringIO()):
            self.assertEqual(main(['update','--check']),0)
            install.assert_not_called();running.assert_not_called()
        with patch.object(m,'uninstall',return_value=0),patch('connectnow.cli.running') as running:
            self.assertEqual(main(['uninstall']),0);running.assert_not_called()

    def test_latest_requires_official_matching_assets(self):
        prefix=f'https://github.com/{m.REPOSITORY}/releases/download/v0.3.0/'
        name='ConnectNow-0.3.0-macos-arm64-cli.tar.gz'
        data={'tag_name':'v0.3.0','draft':False,'prerelease':False,'assets':[
              {'name':name,'browser_download_url':prefix+name},
              {'name':'SHA256SUMS','browser_download_url':prefix+'SHA256SUMS'}]}
        def fetch(url,path,limit):path.write_text(json.dumps(data))
        with patch.object(m,'download',side_effect=fetch),patch.object(m.sys,'platform','darwin'), \
                patch.object(m.platform,'machine',return_value='arm64'):
            self.assertEqual(m.latest(self.root)[0],'0.3.0')
            data['assets'][0]['browser_download_url']='https://evil.test/installer'
            with self.assertRaisesRegex(ValueError,'官方仓库'):m.latest(self.root)

    def test_no_downgrade_online_and_conflicting_options(self):
        with patch.object(m,'latest',return_value=('0.1.0','bundle',{})),patch.object(m,'install') as install,redirect_stdout(io.StringIO()):
            self.assertEqual(m.update(),0);install.assert_not_called()
        with redirect_stderr(io.StringIO()):self.assertEqual(main(['update','--check','--package','test']),1)

    def rows(self):
        return [{'directory':str(self.root/name),'port':port,'codexHome':'/original/codex',
                 'service':{'instanceId':name,'version':'0.2.0','pid':123},
                 'status':{'enabled':enabled,'controllerId':None},'executable':str(self.binary)}
                for name,port,enabled in [('one',8769,True),('two',8770,False)]]

    def test_activate_restarts_all_snapshots_with_new_binary(self):
        rows=self.rows();target=self.root/'new'
        with patch.object(m,'stop_service') as stop,patch.object(m,'start_service',return_value='new-id') as start:
            m.activate(target,self.link,str(self.binary),'0.3.0',rows)
        self.assertEqual(self.link.resolve(),target)
        self.assertEqual(stop.call_count,2)
        self.assertEqual(start.call_args_list[1].args,(rows[1],target,'0.3.0'))

    def test_failed_restart_rolls_back_entry_and_both_original_services(self):
        rows=self.rows();target=self.root/'new'
        with patch.object(m,'stop_service') as stop,patch.object(m,'start_service',side_effect=['new-id',ValueError('failed'),'old-two','old-one']) as start, \
                patch('connectnow.cli.running',return_value=None):
            with self.assertRaisesRegex(ValueError,'已恢复原入口'):m.activate(target,self.link,str(self.binary),'0.3.0',rows)
        self.assertEqual(self.link.resolve(),self.binary)
        self.assertEqual(start.call_args_list[-1].args,(rows[0],str(self.binary),'0.2.0'))
        self.assertEqual(stop.call_args_list[-1].args,(rows[0],'new-id'))

    def test_rollback_failure_is_reported(self):
        rows=self.rows()[:1]
        with patch.object(m,'stop_service'),patch.object(m,'start_service',side_effect=ValueError('failed')), \
                patch('connectnow.cli.running',return_value=None):
            with self.assertRaisesRegex(ValueError,'恢复未完成'):m.activate(self.root/'new',self.link,str(self.binary),'0.3.0',rows)
        self.assertEqual(self.link.resolve(),self.binary)

    def test_snapshot_does_not_include_stopped_services(self):
        rows=self.rows()
        with patch('connectnow.services.list_services',return_value={'services':[{**rows[0],'running':True},{**rows[1],'running':False}]}), \
                patch('connectnow.cli.call',return_value=rows[0]['status']), \
                patch.object(m.subprocess,'check_output',return_value=str(self.binary)+'\n'):
            self.assertEqual(len(m.service_snapshots()),1)

    def test_bad_candidate_does_not_discover_or_stop_services(self):
        package=self.archive(script=b'#!/bin/sh\nexit 1\n')
        with patch.object(m.sys,'platform','darwin'),patch.object(m.platform,'machine',return_value='arm64'), \
                patch.object(m,'service_snapshots') as snapshot,patch.object(m,'stop_service') as stop:
            with self.assertRaises(ValueError):m.install(package,self.link,self.releases,restart=True)
        snapshot.assert_not_called();stop.assert_not_called()

    def test_start_preserves_disabled_bridge_and_original_arguments(self):
        row=self.rows()[1];Path(row['directory']).mkdir()
        info={'pid':42,'instanceId':'new','version':'0.3.0'}
        with patch('connectnow.cli.running',side_effect=[None,info]),patch('connectnow.cli.call',return_value=row['status']) as call, \
                patch.object(m.subprocess,'Popen') as popen:
            popen.return_value.pid=42
            self.assertEqual(m.start_service(row,self.binary,'0.3.0'),'new')
        args=popen.call_args.args[0]
        self.assertEqual(args,[str(self.binary),'serve','--state-dir',row['directory'],'--port','8770','--codex-home','/original/codex'])
        self.assertEqual(call.call_args_list[0].args[2],{'enabled':False})

    def test_stop_failure_keeps_entry_and_running_service(self):
        row=self.rows()[0]
        with patch.object(m,'stop_service',side_effect=ValueError('stop failed')),patch.object(m,'start_service') as start, \
                patch('connectnow.cli.running',return_value=row['service']):
            with self.assertRaisesRegex(ValueError,'stop failed'):m.activate(self.root/'new',self.link,str(self.binary),'0.3.0',[row])
        self.assertEqual(self.link.resolve(),self.binary);start.assert_not_called()

    def test_start_restores_controller_before_disabling_bridge(self):
        row=self.rows()[1];row['status']['controllerId']='thread-123';Path(row['directory']).mkdir()
        with patch('connectnow.cli.running',side_effect=[None,{'pid':42,'instanceId':'new','version':'0.3.0'}]), \
                patch('connectnow.cli.call',return_value=row['status']) as call,patch.object(m.subprocess,'Popen') as popen:
            popen.return_value.pid=42;m.start_service(row,self.binary,'0.3.0')
        self.assertEqual([(c.args[1],c.args[2]) for c in call.call_args_list[:-1]],
            [('/bridge',{'enabled':True}),('/controller',{'threadId':'thread-123'}),('/bridge',{'enabled':False})])

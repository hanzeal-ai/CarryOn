"""Isolated UI fixture. HTTPS names map to loopback HTTP only inside this fixture.
Never connects to Codex or a public gateway. Ctrl+C stops all fixture services.
"""
import http.client
import json
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from carryon.bridge import Bridge
from carryon.cloud_manager import CloudManager
from carryon.console import ConsoleServer
from carryon.pairing import LocalLink
from carryon.server import Handler,Server
from carryon.store import Journal
from serve_operations_smoke import FixtureIPC,FixtureCatalog


class FixtureCloud(CloudManager):
    def configure(self,data):
        if data.get('enabled'):
            data={**data,'url':data['url'].replace('wss:','ws:'),'devLocal':True}
        return super().configure(data)


class FixtureLink(LocalLink):
    @staticmethod
    def request(url,action,body):
        from urllib.parse import urlsplit
        parsed=urlsplit(url)
        if parsed.hostname!='127.0.0.1':raise ValueError('Fixture requires loopback')
        c=http.client.HTTPConnection('127.0.0.1',parsed.port,timeout=5)
        c.request('POST','/console/link/'+action,json.dumps(body),{'Content-Type':'application/json'})
        r=c.getresponse();data=json.loads(r.read());c.close()
        if r.status!=200:raise ValueError(data.get('error','Fixture request failed'))
        return data


def main():
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);servers=[];bridges=[]
        try:
            for index in range(2):
                console=ConsoleServer(('127.0.0.1',0),{'publicUrl':'http://127.0.0.1','consoleToken':'fixture-console-login-0123456789abcdef','devices':{}},root/f'console-{index}')
                console.origin=console.public_url=f'http://127.0.0.1:{console.server_port}'
                servers.append(console)
                threading.Thread(target=console.serve_forever,daemon=True).start()
                print(f'Console {index+1}: {console.public_url}/ | local binding URL: https://127.0.0.1:{console.server_port}',flush=True)
            print('Console login: fixture-console-login-0123456789abcdef',flush=True)
            for index in range(2):
                local_dir=root/f'local-{index}';local_dir.mkdir()
                bridge=Bridge('unused',FixtureCatalog(),Journal(local_dir/'jobs.sqlite'),FixtureIPC)
                from carryon.workspace import Workspace
                bridge.workspace=Workspace(bridge);bridge.workspace.catalog_refresh();bridge.workspace.start()
                bridge.enable();bridges.append(bridge)
                local=Server(('127.0.0.1',0),Handler);local.bridge=bridge;local.token='fixture-local-0123456789abcdef'
                local.allowed_hosts={f'127.0.0.1:{local.server_port}'};local.cloud=FixtureCloud(bridge,local_dir)
                local.local_link=FixtureLink(local.cloud,bridge,background=True)
                local.service_info={'version':'fixture'}
                from unittest.mock import Mock
                local.standby=Mock();local.standby.status.return_value={'enabled':False,'supported':False}
                servers.append(local);threading.Thread(target=local.serve_forever,daemon=True).start()
                print(f'Local {index+1}: http://127.0.0.1:{local.server_port}/#token={local.token}',flush=True)
            threading.Event().wait()
        except KeyboardInterrupt:pass
        finally:
            for server in reversed(servers):
                if hasattr(server,'local_link'):server.local_link.close();server.cloud.stop()
                server.shutdown();server.server_close()
            for bridge in bridges:bridge.workspace.close();bridge.disable()


if __name__=='__main__':main()

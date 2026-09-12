import base64
import unittest
from unittest.mock import Mock
import test_cloud
from carryon.images import validate_images, MAX_IMAGE_BYTES
from carryon.ipc import DesktopIPC

PNG='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aO1cAAAAASUVORK5CYII='

class ImageTests(unittest.TestCase):
    def test_validation_rejects_urls_types_count_and_size(self):
        self.assertEqual(validate_images([PNG]),[PNG])
        for value in [[PNG]*4,['https://example.test/image.png'],['file:///tmp/image.png'],['data:image/svg+xml;base64,PHN2Zz4='],['data:image/png;base64,YWJj'],['data:image/png;base64,'+base64.b64encode(b'x'*(MAX_IMAGE_BYTES+1)).decode()]]:
            with self.assertRaises(ValueError):validate_images(value)

    def test_native_image_envelope(self):
        ipc=DesktopIPC('unused');ipc.request=Mock(return_value={'result':{'result':{'turn':{'id':'t'}}}})
        guard=lambda write:write()
        ipc.start(test_cloud.T,'看一下这张图','owner','message',guard,images=[PNG])
        args=ipc.request.call_args.args
        self.assertEqual(args[0],'thread-follower-start-turn')
        self.assertEqual(args[1]['turnStart']['request']['input'],[{'type':'text','text':'看一下这张图','text_elements':[]},{'type':'image','url':PNG}])
        self.assertIs(args[4],guard)

class ImageCloudTests(unittest.TestCase):
    setUp=test_cloud.CloudTests.setUp
    tearDown=test_cloud.CloudTests.tearDown
    wait=test_cloud.CloudTests.wait
    connect=test_cloud.CloudTests.connect
    call=test_cloud.CloudTests.call
    request=test_cloud.CloudTests.request

    def test_image_control_boundary_and_idempotency(self):
        sent=[]
        class ImageIPC(test_cloud.IPC):
            def start(self,tid,prompt,owner,mid,before_send,images=None):
                before_send(lambda:sent.append((prompt,images)))
                return {'id':'image-turn'}
        self.bridge.ipc_factory=ImageIPC
        self.bridge.enable();self.connect()
        # Larger than the former 100 KB JSON limit, inside the image budget.
        large='data:image/jpeg;base64,'+base64.b64encode(b'\xff\xd8\xff'+b'x'*110000+b'\xff\xd9').decode()
        body={'requestId':'image-request','prompt':'','images':[large]}
        route='/api/threads/'+test_cloud.T+'/messages'
        self.assertEqual(self.request('POST',route,body)[0],403);self.assertFalse(sent)
        self.connect(control=True)
        self.assertEqual(self.request('POST',route,body)[0],202)
        self.wait(lambda:len(sent)==1);self.assertEqual(sent,[('',[large])])
        self.assertEqual(self.request('POST',route,body)[0],202);self.assertEqual(len(sent),1)
        self.assertNotEqual(self.request('POST',route,{**body,'images':[PNG]})[0],202)
        self.assertNotIn(large,str(self.journal.list()))

    def test_cloud_readonly_can_view_only_known_images_and_bridge_off_revokes(self):
        import tempfile
        from pathlib import Path
        from carryon.images import image_id
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'image.png';path.write_bytes(base64.b64decode(PNG.split(',')[1]))
            self.bridge.history=lambda tid:{'timeline':[{'type':'userMessage','data':{'content':[{'type':'localImage','path':str(path)}]}}]}
            self.bridge.enable();self.connect()
            route='/api/threads/'+test_cloud.T+'/images/'
            self.assertEqual(self.request('GET',route+image_id(str(path))),(200,{'url':PNG}))
            self.assertEqual(self.request('GET',route+'0'*64)[0],404)
            self.assertEqual(self.request('POST',route+image_id(str(path)),{})[0],403)
            self.bridge.disable()
            self.assertEqual(self.request('GET',route+image_id(str(path)))[0],403)


class HistoryImageTests(unittest.TestCase):
    def test_history_scoped_file_reads_and_no_native_mutation(self):
        import tempfile
        from pathlib import Path
        from carryon.images import read_history_image, image_id
        from carryon.bridge import snapshot_history
        from carryon.errors import BridgeError
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'image.png';path.write_bytes(base64.b64decode(PNG.split(',')[1]))
            native={'id':'thread','turns':[{'turnId':'t','items':[{'type':'userMessage','content':[{'type':'localImage','path':str(path)}]}]}]}
            history=snapshot_history(native);identifier=image_id(str(path))
            self.assertEqual(history['timeline'][1]['data']['content'][0]['imageId'],identifier)
            self.assertNotIn('imageId',native['turns'][0]['items'][0]['content'][0])
            self.assertEqual(read_history_image(history,identifier),{'url':PNG})
            with self.assertRaises(BridgeError):read_history_image(history,image_id('/etc/passwd'))
            with self.assertRaises(BridgeError):read_history_image({'timeline':[]},identifier)
            path.unlink();path.symlink_to(Path(tmp)/'missing')
            with self.assertRaises(BridgeError):read_history_image(history,identifier)
            path.unlink();path.write_bytes(b'not an image')
            with self.assertRaises(ValueError):read_history_image(history,identifier)
            path.write_bytes(b'x'*(8*1024*1024+1))
            with self.assertRaises(ValueError):read_history_image(history,identifier)

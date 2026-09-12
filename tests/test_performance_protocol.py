import json
import os
import unittest
from unittest.mock import Mock
from connectnow.websocket import mask_payload
from connectnow.patches import apply_patches
from connectnow.history_cache import HistoryCache, NativeSnapshot, TurnCache
from connectnow.bridge import snapshot_history
from connectnow.history_wire import HistoryWire
from connectnow.gateway import Device


def state(turns=100):
    return NativeSnapshot({'id':'11111111-1111-4111-8111-111111111111', 'threadRuntimeStatus':{'type':'idle'},
        'turns':[{'turnId':str(i),'status':'completed','params':{'input':[{'type':'text','text':f'prompt {i}'}]},
                  'items':[{'id':str(i),'type':'agentMessage','text':f'answer {i}'}]} for i in range(turns)]})


def packet(revision, items, **fields):
    return {'type':'update','subscription':'a','threadId':'t','history':{
        'historyRevision':revision,'timeline':items,**fields}}


class PerformanceProtocolTests(unittest.TestCase):
    def test_mask_matches_reference_across_chunk_and_tail_boundaries(self):
        for size in (0,1,2,3,4,125,126,65535,65536,65537,131075):
            data=os.urandom(size);mask=os.urandom(4)
            encoded=mask_payload(data,mask)
            self.assertEqual(encoded,bytes(v ^ mask[i % 4] for i,v in enumerate(data)))
            self.assertEqual(mask_payload(encoded,mask),data)

    def test_patch_shares_untouched_branches_and_failure_is_atomic(self):
        original=state()
        patches=[{'op':'replace','path':['turns',99,'items',0,'text'],'value':'new'}]
        changed=apply_patches(original,patches)
        self.assertIs(changed['turns'][0],original['turns'][0])
        self.assertIsNot(changed['turns'][99],original['turns'][99])
        self.assertEqual(original['turns'][99]['items'][0]['text'],'answer 99')
        with self.assertRaises((ValueError,KeyError)):
            apply_patches(original,patches+[{'op':'remove','path':['missing']}])
        self.assertEqual(original['turns'][99]['items'][0]['text'],'answer 99')
        inserted={'nested':[]}
        result=apply_patches(original,[{'op':'add','path':['extra'],'value':inserted}])
        inserted['nested'].append('later')
        self.assertEqual(result['extra'],{'nested':[]})

    def test_turn_projection_reuses_immutable_segments_and_window_keeps_order(self):
        native=state();cache=TurnCache()
        before=snapshot_history(native,turn_cache=cache,limit=40)
        changed=NativeSnapshot(apply_patches(native,[{'op':'replace','path':['turns',99,'items',0,'text'],'value':'new'}]))
        after=snapshot_history(changed,turn_cache=cache,limit=40)
        self.assertIs(before['timeline'][0],after['timeline'][0])
        self.assertEqual(after['timeline'][-1]['text'],'new')
        self.assertEqual(before['timeline'][-1]['text'],'answer 99')
        self.assertEqual(before['historyWindow'],{'limit':40,'total':100,'hasMore':True})
        self.assertEqual(before['timeline'][0]['title'],'第 61 轮')
        full=snapshot_history(native,turn_cache=cache,limit=120)
        self.assertFalse(full['historyWindow']['hasMore'])
        self.assertEqual(len(full['timeline']),300)

    def test_oversize_revision_stays_stable_and_window_is_cacheable(self):
        native=state(1000);cache=HistoryCache(max_bytes=100000)
        a=cache.project(native,snapshot_history,segmented=True)
        b=cache.project(native,snapshot_history,segmented=True)
        self.assertEqual(a['historyRevision'],b['historyRevision'])
        build=Mock(wraps=snapshot_history)
        a=cache.project(native,build,segmented=True,limit=10)
        b=cache.project(native,build,segmented=True,limit=10)
        self.assertEqual(build.call_count,1)
        self.assertLessEqual(cache.bytes,cache.max_bytes)

    def test_wire_handles_splices_metadata_removal_and_revision_gap(self):
        encoder,decoder=HistoryWire(),HistoryWire()
        values=[packet('1',[{'id':'a'},{'id':'b'}],old=True),
                packet('2',[{'id':'a'},{'id':'c'},{'id':'b'}],queue={'messages':[]}),
                packet('3',[{'id':'c'}]),packet('4',[])]
        for value in values:
            encoded=encoder.encode(value)
            self.assertEqual(decoder.decode(encoded),value)
        with self.assertRaisesRegex(ValueError,'gap'):
            HistoryWire().decode(encoded)
        other={**packet('5',[{'id':'new'}]),'subscription':'b'}
        complete=encoder.encode(other)
        self.assertIn('history',complete)
        self.assertEqual(HistoryWire().decode(complete),other)
        broken={'type':'update','subscription':'a','threadId':'t','historyDelta':{'base':'4','fields':{'historyRevision':'5'},'start':1,'delete':0,'items':[]}}
        with self.assertRaises(ValueError):decoder.decode(broken)

    def test_gateway_reconstructs_every_delta_before_latest_snapshot_is_read(self):
        device=Device(Mock());device.streams['s']={'revision':0,'body':None};encoder=HistoryWire()
        for index in range(5):
            value=packet(str(index),[{'id':'item','text':'x'*index}])
            device.receive({'type':'event','streamId':'s','body':encoder.encode(value)})
        self.assertEqual(device.streams['s']['body'],value)
        self.assertEqual(device.streams['s']['revision'],5)

    def test_small_update_wire_size_is_independent_of_unchanged_history(self):
        values=[{'id':str(i),'text':'x'*1000} for i in range(1000)]
        encoder=HistoryWire();encoder.encode(packet('1',values))
        update=encoder.encode(packet('2',values[:-1]+[{'id':'999','text':'changed'}]))
        self.assertLess(len(json.dumps(update)),500)

    def test_preview_does_not_wait_for_native_full_history(self):
        import threading
        from types import SimpleNamespace
        from connectnow.realtime import Subscription
        native=Mock();native.current.return_value=None
        bridge=SimpleNamespace(lock=threading.RLock(),status=lambda:{'enabled':True},require=lambda:(native,1),
            journal=SimpleNamespace(list=lambda limit=None:[]),
            preview_history=Mock(return_value={'syncing':True,'timeline':[]}),history=Mock())
        # An IPC mock has dynamic attributes; omit event adaptation for this fixture.
        del native.events
        owner=SimpleNamespace(bridge=bridge,sync_watches=lambda:None,unavailable={})
        subscription=Subscription(owner)
        subscription.selection.update(threadId='t',historyLimit=40)
        packet,*_=subscription.update()
        self.assertTrue(packet['history']['syncing'])
        self.assertEqual(packet['readSequence'],0)
        bridge.history.assert_not_called()
        native.current.return_value={'id':'t'}
        bridge.history.return_value={'timeline':[{'id':'live'}]}
        packet,*_=subscription.update()
        self.assertEqual(packet['history']['timeline'],[{'id':'live'}])
        bridge.history.assert_called_once_with('t',limit=40)

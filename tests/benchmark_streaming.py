"""Synthetic active-history pipeline, including real framing cost; PYTHONPATH=. python3 tests/benchmark_streaming.py."""
import json
import statistics
import time
from carryon.bridge import snapshot_history
from carryon.history_cache import HistoryCache, NativeSnapshot
from carryon.history_wire import HistoryWire
from carryon.patches import apply_patches
from carryon.websocket import mask_payload


def median(fn, count=9):
    samples=[]
    for _ in range(count):
        start=time.perf_counter();fn();samples.append((time.perf_counter()-start)*1000)
    return round(statistics.median(samples),4)


def fixture(count):
    return NativeSnapshot({'id':'11111111-1111-4111-8111-111111111111','threadRuntimeStatus':{'type':'active'},'requests':[],
        'turns':[{'turnId':str(i),'status':'completed','params':{'input':[{'type':'text','text':'request '*30}]},
            'items':[{'id':str(i),'type':'agentMessage','text':'response '*100}]} for i in range(count)]})


rows=[]
for count in (100,1000,4000):
    original=fixture(count);cache=HistoryCache()
    patch=[{'op':'replace','path':['turns',count-1,'items',0,'text'],'value':'response '*100+' token'}]
    projection=cache.project(original,snapshot_history,segmented=True,limit=40)
    latest=[original]
    def update():
        latest[0]=NativeSnapshot(apply_patches(latest[0],patch))
        return cache.project(latest[0],snapshot_history,segmented=True,limit=40)
    wire=HistoryWire()
    def packet(history):return {'type':'update','subscription':'s','threadId':original['id'],'history':{k:v for k,v in history.items() if k!='turns'}}
    first=wire.encode(packet(projection));delta=wire.encode(packet(update()))
    payload=json.dumps(first,ensure_ascii=False).encode()
    rows.append({'turns':count,'history_window_turns':40,'first_wire_bytes':len(payload),
        'delta_wire_bytes':len(json.dumps(delta,ensure_ascii=False).encode()),
        'patch_ms':median(lambda:apply_patches(original,patch)),
        'patch_and_window_projection_ms':median(update),
        'same_snapshot_cache_ms':median(lambda:cache.project(latest[0],snapshot_history,segmented=True,limit=40)),
        'mask_first_window_ms':median(lambda:mask_payload(payload,b'abcd'))})
large=json.dumps({'type':'update','history':{k:v for k,v in snapshot_history(fixture(1000)).items() if k!='turns'}},ensure_ascii=False).encode()
print(json.dumps({'rows':rows,'full_history_mask_bytes':len(large),'full_history_mask_ms':median(lambda:mask_payload(large,b'abcd'))},indent=2))

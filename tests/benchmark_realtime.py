"""Read-only synthetic projection benchmark; run PYTHONPATH=. python3 tests/benchmark_realtime.py."""
import json
import statistics
import time
from connectnow.bridge import snapshot_history
from connectnow.history_cache import HistoryCache
from connectnow.realtime import packet_signature

state={'id':'11111111-1111-4111-8111-111111111111','threadRuntimeStatus':{'type':'idle'},'requests':[],
       'turns':[{'turnId':str(i),'status':'completed','params':{'input':[{'type':'text','text':'request '*30}]},
                 'items':[{'id':str(i),'type':'agentMessage','text':'response '*100}]} for i in range(1000)]}

def median_ms(fn, count):
    times=[]
    for _ in range(count):
        start=time.perf_counter();fn();times.append((time.perf_counter()-start)*1000)
    return round(statistics.median(times),4)

cache=HistoryCache();projection=cache.project(state,snapshot_history)
packet={'type':'update','history':projection,'jobs':[]}
print(json.dumps({'fixture_turns':1000,'projection_bytes':len(json.dumps(projection).encode()),
    'uncached_projection_median_ms':median_ms(lambda:snapshot_history(state),10),
    'cached_projection_median_ms':median_ms(lambda:cache.project(state,snapshot_history),100),
    'full_packet_comparison_median_ms':median_ms(lambda:json.dumps(packet,ensure_ascii=False),10),
    'revision_packet_comparison_median_ms':median_ms(lambda:packet_signature(packet),100)},indent=2))

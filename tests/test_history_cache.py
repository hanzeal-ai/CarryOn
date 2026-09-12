import threading
import unittest
from unittest.mock import Mock
from carryon.history_cache import HistoryCache
from carryon.realtime import packet_signature


class HistoryCacheTests(unittest.TestCase):
    def test_same_snapshot_builds_once_and_new_snapshot_invalidates(self):
        cache = HistoryCache()
        build = Mock(side_effect=lambda state: {'timeline': [state['text']]})
        first = {'id':'one','text':'old'}
        cached = cache.project(first, build)
        cached['queue'] = {'messages':['caller-local']}
        for _ in range(20):
            result = cache.project(first, build)
            self.assertEqual(result['historyRevision'], cached['historyRevision'])
            self.assertNotIn('queue', result)
        self.assertEqual(build.call_count, 1)
        result = cache.project({'id':'one','text':'new'}, build)
        self.assertNotEqual(result['historyRevision'], cached['historyRevision'])
        self.assertEqual(result['timeline'], ['new'])
        self.assertEqual(build.call_count, 2)

    def test_byte_bound_lru_and_oversized_projection(self):
        cache = HistoryCache(max_entries=2, max_bytes=1000)
        build = lambda state: {'text':state.get('text','')}
        a,b,c = ({'id':key} for key in 'abc')
        cache.project(a,build);cache.project(b,build);cache.project(a,build);cache.project(c,build)
        self.assertEqual(list(cache.entries), ['a','c'])
        cache.project({'id':'big','text':'x'*2000},build)
        self.assertNotIn('big',cache.entries)
        self.assertLessEqual(cache.bytes,1000)
        cache.clear();self.assertEqual(cache.bytes,0)

    def test_simultaneous_consumers_share_build(self):
        cache = HistoryCache();entered=threading.Event();release=threading.Event()
        state={'id':'shared'}
        def build(value):
            entered.set();release.wait(2);return {'timeline':[]}
        builder=Mock(side_effect=build)
        workers=[threading.Thread(target=cache.project,args=(state,builder)) for _ in range(4)]
        try:
            for worker in workers:worker.start()
            self.assertTrue(entered.wait(1));release.set()
            for worker in workers:worker.join(2)
            self.assertEqual(builder.call_count,1)
        finally:
            release.set()
            for worker in workers:worker.join(2)

    def test_packet_signature_keeps_non_history_state_and_revision(self):
        a={'history':{'historyRevision':'one','timeline':['large']},'jobs':[]}
        self.assertEqual(packet_signature(a),packet_signature({**a,'history':{'historyRevision':'one','timeline':['same revision']}}))
        self.assertNotEqual(packet_signature(a),packet_signature({**a,'jobs':[{'state':'completed'}]}))
        self.assertNotEqual(packet_signature(a),packet_signature({**a,'history':{'historyRevision':'two'}}))

    def test_clear_during_build_does_not_restore_old_snapshot(self):
        cache=HistoryCache();entered=threading.Event();release=threading.Event()
        def build(state):entered.set();release.wait(2);return {'timeline':[]}
        worker=threading.Thread(target=cache.project,args=({'id':'old'},build));worker.start()
        try:
            self.assertTrue(entered.wait(1));cache.clear();release.set();worker.join(2)
            self.assertEqual(len(cache.entries),0)
        finally:release.set();worker.join(2)

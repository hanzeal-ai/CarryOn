"""Voice delivery boundaries, independent of real accounts and audio hardware."""
import copy
import unittest
from carryon.app_server.realtime_voice import append_audio, read
from carryon.desktop_ipc.ipc import IPCError
from carryon.sessions.operations import submit
from carryon.sessions.history_cache import NativeSnapshot
import test_native_skills as fixture
T = fixture.T

class NativeVoiceTests(unittest.TestCase):
    def setUp(self):
        fixture.NativeSkillsTests.setUp(self)
        self.after_reply = lambda: None
        self.error = None
    def rpc(self, method, params, before_send=None, **kwargs):
        if before_send: before_send(lambda: self.writes.append((method, copy.deepcopy(params))))
        if self.error: raise self.error
        self.after_reply()
        return {}
    def start(self, authorize=None):
        return submit(self.bridge, T, {'action':'voice-start','requestId':'voice-once'}, authorize=authorize)
    def test_post_reply_revocation_remains_uncertain(self):
        revoked = [False]
        def authorize():
            if revoked[0]: raise IPCError('revoked')
        self.after_reply = lambda: revoked.__setitem__(0, True)
        job=self.start(authorize)
        self.assertEqual(job['state'],'uncertain',job)
        self.assertEqual(self.runtime.current(T)['voice']['state'],'unknown')
    def test_old_failed_call_cannot_mutate_replacement_session(self):
        def replace():
            self.runtime.session_id='replacement'
            self.runtime.snapshots[T]=NativeSnapshot({**self.runtime.current(T),'voice':{'id':'replacement-voice','state':'active'}})
            raise IPCError('old call failed',uncertain=True)
        self.after_reply=replace
        self.assertEqual(self.start()['state'],'uncertain')
        self.assertEqual(self.runtime.current(T)['voice'],{'id':'replacement-voice','state':'active'})
    def test_native_events_audio_sequence_and_duplicate_start(self):
        job=self.start();self.assertEqual(job['state'],'completed',job)
        voice_id=job['result']['voiceId']
        self.assertEqual(self.start(),job);self.assertEqual(len(self.writes),1)
        self.runtime._event({'method':'thread/realtime/started','params':{'threadId':T,'realtimeSessionId':voice_id,'version':'v2'}})
        frame={'voiceId':voice_id,'sequence':1,'audio':{'data':'AAAAAA==','sampleRate':24000,'numChannels':1,'samplesPerChannel':2}}
        self.assertEqual(append_audio(self.bridge,T,frame),{'accepted':True,'sequence':1})
        with self.assertRaises(IPCError):append_audio(self.bridge,T,frame)
        self.runtime._event({'method':'thread/realtime/outputAudio/delta','params':{'threadId':T,'audio':frame['audio']}})
        self.assertEqual(len(read(self.bridge,T)['events']),1)
        self.runtime._event({'method':'thread/realtime/closed','params':{'threadId':T,'reason':'requested'}})
        self.assertEqual(read(self.bridge,T)['voice']['state'],'closed')
    def test_owner_audio_requires_current_owner_guard(self):
        from contextlib import contextmanager
        from types import SimpleNamespace
        job=self.start();voice_id=job['result']['voiceId']
        self.runtime._event({'method':'thread/realtime/started','params':{'threadId':T,'realtimeSessionId':voice_id,'version':'v2'}})
        self.bridge.ipc=SimpleNamespace(connected=True)
        @contextmanager
        def native_session(*args, **kwargs):
            def guard(write):raise IPCError('owner conflict')
            yield self.runtime,guard
        self.bridge.native_session=native_session
        frame={'voiceId':voice_id,'sequence':1,'audio':{'data':'AAAAAA==','sampleRate':24000,'numChannels':1,'samplesPerChannel':2}}
        count=len(self.writes)
        with self.assertRaises(IPCError):append_audio(self.bridge,T,frame)
        self.assertEqual(len(self.writes),count)
        self.assertEqual(self.runtime.voice_channels[T]['inputSequence'],0)
    def test_invalid_pcm_cannot_reach_native(self):
        frame={'voiceId':'voice','sequence':1,'audio':{'data':'AAAAAA==','sampleRate':24000,'numChannels':1,'samplesPerChannel':2}}
        for key,value in [('sampleRate',48000),('numChannels',2),('samplesPerChannel',3),('data','not-base64!')]:
            bad=copy.deepcopy(frame);bad['audio'][key]=value
            with self.assertRaises(ValueError):append_audio(self.bridge,T,bad)
        self.assertEqual(self.writes,[])
    def test_started_after_lost_reply_recovers_same_request_without_replay(self):
        self.error=IPCError('lost reply',uncertain=True)
        job=self.start();self.assertEqual(job['state'],'uncertain')
        identifier=job['result']['voiceId']
        self.runtime._event({'method':'thread/realtime/started','params':{'threadId':T,'realtimeSessionId':identifier,'version':'v2'}})
        recovered=self.start()
        self.assertEqual(recovered['state'],'completed',recovered)
        self.assertEqual(len(self.writes),1)
        self.assertEqual(self.runtime.current(T)['voice']['state'],'active')
    def test_slow_consumer_buffer_is_bounded_and_reports_gap(self):
        from carryon.app_server.realtime_voice import MAX_BUFFER
        job=self.start();identifier=job['result']['voiceId']
        self.runtime._event({'method':'thread/realtime/started','params':{'threadId':T,'realtimeSessionId':identifier,'version':'v2'}})
        snapshot=self.runtime.current(T)
        for _ in range(400):
            self.runtime._event({'method':'thread/realtime/outputAudio/delta','params':{'threadId':T,'audio':{'data':'A'*40000,'sampleRate':24000,'numChannels':1}}})
        current=self.runtime.voice_channels[T]
        self.assertLessEqual(current['bytes'],MAX_BUFFER);self.assertLessEqual(len(current['events']),256)
        result=read(self.bridge,T,0);self.assertTrue(result['dropped']);self.assertEqual(result['sequence'],400)
        self.assertIs(self.runtime.current(T),snapshot)
    def test_audio_revocation_before_write_does_not_consume_sequence(self):
        job=self.start();identifier=job['result']['voiceId']
        self.runtime._event({'method':'thread/realtime/started','params':{'threadId':T,'realtimeSessionId':identifier,'version':'v2'}})
        def deny():raise PermissionError('revoked')
        frame={'voiceId':identifier,'sequence':1,'audio':{'data':'AAAAAA==','sampleRate':24000,'numChannels':1,'samplesPerChannel':2}}
        with self.assertRaises(PermissionError):append_audio(self.bridge,T,frame,deny)
        self.assertEqual(self.runtime.voice_channels[T]['inputSequence'],0);self.assertEqual(len(self.writes),1)


    def test_started_before_lost_reply_preserves_confirmed_active_state(self):
        def started_then_lost():
            identifier=self.runtime.current(T)['voice']['id']
            self.runtime._event({'method':'thread/realtime/started','params':{'threadId':T,'realtimeSessionId':identifier,'version':'v2'}})
            raise IPCError('lost response after event',uncertain=True)
        self.after_reply=started_then_lost
        self.assertEqual(self.start()['state'],'uncertain')
        self.assertEqual(self.start()['state'],'completed')
        self.assertEqual(self.runtime.current(T)['voice']['state'],'active')
        self.assertEqual(len(self.writes),1)


    def test_native_error_after_started_survives_lost_reply_and_recovery(self):
        def events_then_lost():
            identifier=self.runtime.current(T)['voice']['id']
            self.runtime._event({'method':'thread/realtime/started','params':{'threadId':T,'realtimeSessionId':identifier,'version':'v2'}})
            self.runtime._event({'method':'thread/realtime/error','params':{'threadId':T,'message':'native stream failure'}})
            raise IPCError('lost response',uncertain=True)
        self.after_reply=events_then_lost
        self.assertEqual(self.start()['state'],'uncertain')
        self.assertEqual(self.start()['state'],'completed')
        voice=self.runtime.current(T)['voice']
        self.assertEqual(voice['state'],'unknown');self.assertEqual(voice['error'],'native stream failure')
    def test_native_start_failure_is_not_replaced_with_rpc_error(self):
        def error_then_lost():
            self.runtime._event({'method':'thread/realtime/error','params':{'threadId':T,'message':'native handshake failure'}})
            raise IPCError('lost response',uncertain=True)
        self.after_reply=error_then_lost
        self.assertEqual(self.start()['state'],'uncertain')
        self.assertEqual(self.start()['state'],'uncertain')
        self.assertEqual(self.runtime.current(T)['voice']['error'],'native handshake failure')
        self.assertEqual(len(self.writes),1)
    def test_started_after_stop_request_does_not_reactivate_capture(self):
        identifier=self.start()['result']['voiceId']
        def late_started():
            self.runtime._event({'method':'thread/realtime/started','params':{'threadId':T,'realtimeSessionId':identifier,'version':'v2'}})
            raise IPCError('lost stop response',uncertain=True)
        self.after_reply=late_started
        request={'action':'voice-stop','requestId':'stop-once','voiceId':identifier}
        self.assertEqual(submit(self.bridge,T,request)['state'],'uncertain')
        self.assertEqual(self.runtime.current(T)['voice']['state'],'stopping')
        self.runtime._event({'method':'thread/realtime/closed','params':{'threadId':T,'reason':'requested'}})
        self.assertEqual(submit(self.bridge,T,request)['state'],'completed')
        self.assertEqual(self.runtime.current(T)['voice']['state'],'closed')
        self.assertEqual(len(self.writes),2)

class VoiceOwnerLifetimeTests(unittest.TestCase):
    def setUp(self):
        import test_owner
        self.envelope=test_owner.OwnerTests.envelope.__get__(self)
        test_owner.AutoReleaseTests.setUp(self)
    def test_all_unresolved_voice_phases_prevent_automatic_and_manual_release(self):
        import test_owner
        test_owner.AutoReleaseTests.start(self)
        test_owner.AutoReleaseTests.finish(self)
        for phase in ('starting','active','stopping','unknown'):
            self.runtime.data['voice']={'id':'voice','state':phase}
            self.manager._release_finished()
            self.assertTrue(self.runtime.connected,phase)
            with self.assertRaises(IPCError):self.manager.release(T)
        self.runtime.data['voice']={'id':'voice','state':'closed','closed':True}
        self.manager._release_finished()
        self.assertFalse(self.runtime.connected)


import unittest
from carryon.bridge import idle_snapshot, BridgeError
from carryon.thread_status import project_status


class ThreadStatusTests(unittest.TestCase):
    def test_runtime_and_waiting_priority(self):
        self.assertEqual(project_status({'threadRuntimeStatus':{'type':'active'}})['state'],'running')
        self.assertEqual(project_status({'threadRuntimeStatus':{'type':'idle'}})['state'],'idle')
        self.assertEqual(project_status({'threadRuntimeStatus':{'type':'active','activeFlags':['waitingOnApproval']}})['state'],'waiting')
        self.assertEqual(project_status({'threadRuntimeStatus':{'type':'idle'},'requests':[{'id':'approval'}]})['state'],'waiting')
    def test_missing_and_error_are_never_idle(self):
        for state in (None,{}, {'threadRuntimeStatus':{'type':'newFutureType'}}):
            self.assertEqual(project_status(state)['state'],'unknown')
        self.assertEqual(project_status({'threadRuntimeStatus':{'type':'notLoaded'}})['state'],'notLoaded')
        self.assertEqual(project_status({'threadRuntimeStatus':{'type':'systemError'}})['state'],'error')

    def test_display_and_idle_gate_share_waiting_flags(self):
        for flag in ('waitingOnApproval', 'waitingOnUserInput'):
            for runtime in ('active', 'idle'):
                state = {'threadRuntimeStatus': {'type': runtime, 'activeFlags': [flag]}, 'requests': []}
                with self.subTest(flag=flag, runtime=runtime):
                    self.assertEqual(project_status(state)['state'], 'waiting')
                    with self.assertRaises(BridgeError): idle_snapshot(state)
        idle_snapshot({'threadRuntimeStatus': {'type': 'idle'}, 'requests': []})

    def test_malformed_state_is_not_idle(self):
        for state in ([], 'idle', {'threadRuntimeStatus':'idle'},
                      {'threadRuntimeStatus': {'type':'idle','activeFlags':'waitingOnApproval'}}):
            self.assertEqual(project_status(state)['state'], 'unknown')
            with self.assertRaises(BridgeError): idle_snapshot(state)

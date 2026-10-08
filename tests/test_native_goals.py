import copy
import unittest
import test_native_skills as fixtures
from carryon.app_server.goals import read, request
from carryon.desktop_ipc.ipc import IPCError
from carryon.sessions.operations import submit, controls
from carryon.workspaces.workspace_access import required_capabilities
from carryon.sessions.history_cache import HistoryCache

T = fixtures.T


class NativeGoalTests(unittest.TestCase):
    def setUp(self):
        self.goal = None; self.error = None; self.get_hook = lambda: None; self.reply_hook = lambda: None
        fixtures.NativeSkillsTests.setUp(self)
        self.data = {'action': 'goal-set', 'requestId': 'goal-once', 'objective': 'Fixture objective', 'status': 'active', 'tokenBudget': 100}

    def rpc(self, method, params, before_send=None, **kwargs):
        if method == 'thread/goal/get':
            result = {'goal': copy.deepcopy(self.goal)}; self.get_hook(); return result
        before_send(lambda: self.writes.append((method, copy.deepcopy(params))))
        if self.error: raise self.error
        if method == 'thread/goal/clear': self.goal = None; result = {'cleared': True}
        else:
            self.goal = {**(self.goal or {'threadId': T, 'objective': 'default', 'status': 'active',
                'tokenBudget': None, 'tokensUsed': 0, 'timeUsedSeconds': 0, 'createdAt': 1, 'updatedAt': 1}), **params}
            result = {'goal': copy.deepcopy(self.goal)}
        self.runtime._event({'method': 'thread/goal/cleared' if self.goal is None else 'thread/goal/updated',
                             'params': {'threadId': T, **({'goal': copy.deepcopy(self.goal)} if self.goal else {})}})
        self.reply_hook()
        return result

    def test_create_pause_resume_clear_use_native_state_and_same_request_once(self):
        job = submit(self.bridge, T, self.data)
        self.assertEqual(job['state'], 'completed', job)
        self.assertEqual(controls(self.runtime.current(T))['goal']['status'], 'active')
        self.assertEqual(submit(self.bridge, T, self.data), job); self.assertEqual(len(self.writes), 1)
        for action, fields, expected in [('goal-pause', {}, 'paused'), ('goal-set', {'status': 'active'}, 'active'), ('goal-clear', {}, None)]:
            job = submit(self.bridge, T, {'action': action, 'requestId': action + '-next', **fields})
            self.assertEqual(job['state'], 'completed', job)
            self.assertEqual((self.runtime.current(T).get('threadGoal') or {}).get('status'), expected)
        self.assertEqual([call[0] for call in self.writes], ['thread/goal/set'] * 3 + ['thread/goal/clear'])

    def test_lost_reply_is_unknown_and_cannot_replay(self):
        self.error = IPCError('lost', uncertain=True)
        job = submit(self.bridge, T, self.data)
        self.assertEqual(job['state'], 'uncertain'); self.assertTrue(self.runtime.current(T)['_goalUnknown'])
        self.assertEqual(submit(self.bridge, T, self.data), job); self.assertEqual(len(self.writes), 1)

    def test_post_reply_generation_change_is_unknown(self):
        self.reply_hook = lambda: setattr(self.bridge, 'generation', self.bridge.generation + 1)
        self.assertEqual(submit(self.bridge, T, self.data)['state'], 'uncertain')

    def test_stale_read_cannot_overwrite_new_native_goal_event(self):
        native = {'threadId': T, 'objective': 'event', 'status': 'paused'}
        self.get_hook = lambda: self.runtime._event({'method': 'thread/goal/updated', 'params': {'threadId': T, 'goal': native}})
        self.assertEqual(read(self.runtime, T), {'goal': native})

    def test_delayed_get_cannot_clear_new_unknown_write(self):
        def pending_write():
            self.get_hook = lambda: None
            self.error = IPCError('lost write', uncertain=True)
            job = submit(self.bridge, T, self.data)
            self.assertEqual(job['state'], 'uncertain', job)
        self.get_hook = pending_write
        read(self.runtime, T)
        self.assertTrue(self.runtime.current(T)['_goalUnknown'])

    def test_delayed_get_cannot_revert_confirmed_write_without_event(self):
        self.runtime._event = lambda event: None
        def pending_write():
            self.get_hook = lambda: None
            self.assertEqual(submit(self.bridge, T, self.data)['state'], 'completed')
        self.get_hook = pending_write
        self.assertEqual(read(self.runtime, T)['goal']['objective'], self.data['objective'])

    def test_budget_status_and_capability_boundaries(self):
        for fields in [{'tokenBudget': None}, {'tokenBudget': True}, {'tokenBudget': 0}, {'status': 'budgetLimited'}, {'status': 'paused'}, {'objective': ''}]:
            with self.assertRaises(ValueError): request(T, {'action': 'goal-set', 'requestId': 'invalid', **fields})
        for action, permission in [('goal-set', 'send'), ('goal-pause', 'stop'), ('goal-clear', 'stop')]:
            self.assertEqual(required_capabilities('POST', '/api/threads/' + T + '/operations', {'action': action}), (permission,))

    def test_cached_projection_changes_after_read_reply_and_unknown(self):
        cache = HistoryCache()
        def project():
            return cache.project(self.runtime.current(T), lambda state: {'controls': controls(state)})
        before = project()
        self.goal = {'threadId': T, 'objective': 'persisted', 'status': 'paused'}
        read(self.runtime, T)
        refreshed = project()
        self.assertNotEqual(before['historyRevision'], refreshed['historyRevision'])
        self.assertEqual(refreshed['controls']['goal'], self.goal)
        self.runtime._event = lambda event: None
        job = submit(self.bridge, T, self.data)
        self.assertEqual(job['state'], 'completed', job)
        replied = project()
        self.assertNotEqual(refreshed['historyRevision'], replied['historyRevision'])
        self.assertEqual(replied['controls']['goal']['status'], 'active')
        self.error = IPCError('lost', uncertain=True)
        job = submit(self.bridge, T, {'action': 'goal-clear', 'requestId': 'uncertain-clear'})
        self.assertEqual(job['state'], 'uncertain', job)
        unknown = project()
        self.assertTrue(unknown['controls']['goalUnknown'])
        self.error = None
        read(self.runtime, T)
        recovered = project()
        self.assertFalse(recovered['controls']['goalUnknown'])
        self.assertNotEqual(unknown['historyRevision'], recovered['historyRevision'])

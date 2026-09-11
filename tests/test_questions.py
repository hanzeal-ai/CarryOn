import json
import unittest
from connectnow.bridge import snapshot_history
from connectnow.questions import OPEN, CLOSE, reply_answers


class AsyncQuestionTests(unittest.TestCase):
    def state(self):
        return {'id': 'thread', 'threadRuntimeStatus': {'type': 'active'}, 'requests': [], 'turns': [
            {'turnId': 'turn', 'status': 'inProgress', 'items': [
                {'id': 'question', 'type': 'agentMessage', 'delivery': 'async', 'text': '选择方向',
                 'questions': [{'title': '选择方向', 'options': ['窗口', '客户端']}]},
                {'id': 'work', 'type': 'commandExecution', 'command': 'git status', 'status': 'inProgress'}]}]}

    def test_native_questions_are_projected_without_blocking_work(self):
        history = snapshot_history(self.state())
        question = history['timeline'][1]['asyncQuestions'][0]
        self.assertEqual(question['id'], '["request_user_input_async","question",0]')
        self.assertEqual(question['options'], ['窗口', '客户端'])
        self.assertTrue(question['active'])
        self.assertEqual(history['status']['state'], 'running')
        self.assertEqual(history['controls']['requests'], [])
        self.assertEqual(history['pendingRequests'], [])
        self.assertEqual(history['timeline'][2]['status'], 'inProgress')

    def test_regular_bullets_are_not_interactive_questions(self):
        state = self.state(); state['turns'][0]['items'][0].pop('delivery')
        self.assertNotIn('asyncQuestions', snapshot_history(state)['timeline'][1])

    def test_reply_roundtrip_and_rejected_steering_does_not_answer(self):
        state = self.state()
        records = [{'questionItemId': '["request_user_input_async","question",0]', 'question': '选择方向', 'answer': '窗口'}]
        wire = OPEN + '\n' + json.dumps(records) + '\n' + CLOSE
        reply = {'id': 'reply', 'type': 'steeringUserMessage', 'status': 'rejected', 'input': [{'type': 'text', 'text': wire}]}
        state['turns'][0]['items'].append(reply)
        self.assertIsNone(snapshot_history(state)['timeline'][1]['asyncQuestions'][0]['answer'])
        reply['status'] = 'accepted'
        history = snapshot_history(state)
        self.assertEqual(history['timeline'][1]['asyncQuestions'][0]['answer'], '窗口')
        self.assertEqual(history['timeline'][-1]['text'], '选择方向\n窗口')
        self.assertEqual(reply_answers(wire), records)
        self.assertEqual(reply_answers(OPEN + '\n{}\n' + CLOSE), [])

    def test_free_text_only_and_later_turn_answer(self):
        state = self.state(); item = state['turns'][0]['items'][0]; item.pop('questions')
        state['turns'][0]['status'] = 'completed'
        wire = OPEN + json.dumps({'questionItemId': 'question', 'question': '选择方向', 'answer': '自定义'}) + CLOSE
        state['turns'].append({'turnId': 'next', 'status': 'inProgress', 'items': [{'type': 'userMessage', 'content': [{'type': 'text', 'text': wire}]}]})
        question = snapshot_history(state)['timeline'][1]['asyncQuestions'][0]
        self.assertEqual(question['id'], 'question')
        self.assertEqual(question['answer'], '自定义')
        self.assertFalse(question['active'])


class AsyncQuestionComposeTests(unittest.TestCase):
    from test_compose import ComposeTests
    setUp = ComposeTests.setUp
    tearDown = ComposeTests.tearDown
    wait = ComposeTests.wait

    def test_answer_uses_steering_once_without_interrupt_or_approval(self):
        from test_operations import state, T
        from connectnow.remote_scope import scoped_dispatch
        from connectnow.errors import BridgeError
        native = state('active')
        self.bridge.ipc.snapshot = lambda tid: ('owner', native)
        self.bridge.ipc.current = lambda tid: native
        wire = OPEN + '\n' + json.dumps([{'questionItemId': 'q', 'question': '方向', 'answer': '窗口'}]) + '\n' + CLOSE
        body = {'requestId': 'question-answer-1', 'prompt': wire}
        route = f'/api/threads/{T}/compose'
        with self.assertRaises(BridgeError): scoped_dispatch(self.bridge, 'POST', route, body, False, 'reader')
        code, job = scoped_dispatch(self.bridge, 'POST', route, body, True, 'writer')
        self.assertEqual(code, 202)
        jobs = self.journal.list(); self.wait(jobs[0]['id'])
        self.assertEqual(jobs[0]['kind'], 'operation:steer')
        self.assertEqual(self.bridge.ipc.calls[0][1]['input'][0]['text'], wire)
        scoped_dispatch(self.bridge, 'POST', route, body, True, 'writer')
        self.assertEqual(len(self.bridge.ipc.calls), 1)

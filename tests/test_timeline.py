import json
import unittest
from carryon.bridge import snapshot_history


class TimelineTests(unittest.TestCase):
    def test_delegated_first_prompt_remains_a_user_message(self):
        output='<codex_delegation><input>Original task</input></codex_delegation>'
        result=snapshot_history({'id':'thread','turns':[{'turnId':'t','status':'completed',
            'params':{'toolOutput':{'output':output}},'items':[{'type':'functionCallOutput','output':output}]}]})
        self.assertEqual([i['type'] for i in result['timeline']],['turn','userMessage'])
        self.assertEqual(result['timeline'][1]['text'],'Original task')

    def history(self, items, status='completed', **extra):
        turn={'turnId':'t','status':status,'params':{'developer_instructions':'PRIVATE_SYSTEM'},'items':items}
        return snapshot_history({'id':'thread','turns':[turn],**extra})

    def test_native_order_full_text_and_no_duplicate_user(self):
        long='original\n'*6000
        result=self.history([{'type':'userMessage','id':'u','content':[{'type':'text','text':'hello'}]},
            {'type':'commandExecution','id':'c','command':'printf hello','status':'completed','aggregatedOutput':long,'exitCode':0},
            {'type':'agentMessage','id':'a','text':long,'phase':'final_answer'}])
        timeline=result['timeline']
        self.assertEqual([i['type'] for i in timeline],['turn','userMessage','commandExecution','agentMessage'])
        self.assertEqual(timeline[2]['data']['aggregatedOutput'],long)
        self.assertEqual(timeline[3]['text'],long)
        self.assertNotIn('PRIVATE_SYSTEM',json.dumps(result))

    def test_reasoning_is_only_display_summary(self):
        result=self.history([{'type':'reasoning','id':'r','summary':['摘要原文'],'content':['PRIVATE_THOUGHT'],
            'encryptedContent':'PRIVATE_ENCRYPTED'}, {'type':'agentMessage','phase':'analysis','text':'PRIVATE_ANALYSIS'}])
        encoded=json.dumps(result)
        self.assertNotIn('PRIVATE_',encoded)
        self.assertEqual(result['timeline'][1]['text'],'摘要原文')

    def test_compaction_running_completed_and_manual_source(self):
        item={'type':'contextCompaction','id':'c','completed':False,'source':'manual'}
        active=self.history([item],status='inProgress')['timeline'][1]
        self.assertEqual(active['status'],'inProgress')
        self.assertEqual(active['title'],'手动压缩上下文')
        done=self.history([item])['timeline'][1]
        self.assertEqual(done['status'],'completed')

    def test_running_thought_does_not_remain_active_after_next_item(self):
        result=self.history([{'type':'reasoning','id':'r','summary':[]},
            {'type':'commandExecution','id':'c','command':'pwd','status':'inProgress'}],status='inProgress')
        self.assertEqual(result['timeline'][1]['status'],'completed')
        self.assertEqual(result['timeline'][2]['status'],'inProgress')

    def test_tool_arguments_results_and_file_diff_preserved(self):
        args={'q':'<img src=x onerror=alert(1)>'}
        result={'content':[{'type':'text','text':'raw output'}]}
        rows=self.history([{'id':'m','type':'mcpToolCall','arguments':args,'result':result},
            {'id':'f','type':'fileChange','changes':[{'path':'app.py','diff':'-old\n+new'}]}])['timeline']
        self.assertEqual(rows[1]['data']['arguments'],args)
        self.assertEqual(rows[1]['data']['result'],result)
        self.assertEqual(rows[2]['data']['changes'][0]['diff'],'-old\n+new')

    def test_attachment_reference_and_unknown_type_reported(self):
        rows=self.history([{'id':'u','type':'userMessage','content':[{'type':'localImage','path':'/tmp/test.png'}]},
            {'id':'unknown','type':'futureNativeEvent','secret':'do not blindly expose'}])
        self.assertEqual(rows['timeline'][1]['data']['content'][0]['path'],'/tmp/test.png')
        self.assertEqual(rows['coverage']['unsupportedTypes'],['futureNativeEvent'])
        self.assertNotIn('secret',rows['timeline'][2]['data'])

    def test_more_than_200_native_events_are_retained(self):
        result=self.history([{'type':'agentMessage','id':str(i),'text':str(i)} for i in range(250)])
        self.assertEqual(len(result['timeline']),251)
        self.assertTrue(result['messagesTruncated'])
        self.assertFalse(result['truncated'])

    def test_runtime_change_present_without_new_messages(self):
        result=self.history([],threadRuntimeStatus={'type':'active','activeFlags':['waitingOnApproval']},
            requests=[{'id':'approval','method':'commandApproval','secret':'PRIVATE_REQUEST'}])
        self.assertEqual(result['runtime']['type'],'active')
        self.assertEqual(result['pendingRequests'],[{'id':'approval','method':'commandApproval'}])
        self.assertNotIn('PRIVATE_REQUEST',json.dumps(result))

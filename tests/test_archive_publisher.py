import copy
import json
from pathlib import Path
import tempfile
import unittest
from archive_incremental import IncrementalArchive
from archive_io import AdapterError
from archive_publisher import run


class Client:
    def __init__(self):
        self.bodies = {key:'' for key in ['guide','messages','looms','knowledge','corrections','status']}
        self.bodies['corrections'] = 'Corrections begin below.\n'
        self.writes=[]
        self.revision='r1'
        self.fail=None
    def read(self,key):
        return {'text':self.bodies[key],'revision':self.revision}
    def replace(self,key,text):
        if self.fail==key: raise OSError('lost write')
        if self.bodies[key]==text:return False
        self.bodies[key]=text;self.writes.append(key);return True


class Analyzer:
    def __init__(self):self.calls=0
    def analyze(self,payload):
        self.calls+=1
        return {'decisions':[{'source_id':s['source_id'],'label':'work','facts':[{'kind':'request','statement':s['text']}]} for s in payload['sources']],
                'usage':{'input_tokens':10,'output_tokens':5}}


def setup(root):
    message={'source_id':'archive://Casey/google-messages/1','revision':'v1','owner':'Casey','conversation_id':'alex',
             'timestamp':'2026-10-12T10:00:00Z','text':'Please organize links','kind':'message','origin_ids':[],
             'friendly_id':'M1','sender':'Tester','imported_at':'2026-10-12T10:01:00Z'}
    loom={'source_id':'archive://Casey/loom/video','revision':'v1','owner':'Casey','conversation_id':'alex',
          'timestamp':'2026-10-12T10:00:00Z','text':'Video request','kind':'loom','origin_ids':[message['source_id']],
          'friendly_id':'Loom-video','source_url':'https://www.loom.com/share/video','phrases':[{'ts':1.2,'value':'Video request'}],
          'captured_at':'2026-10-12T10:01:00Z'}
    config={'owner':'Casey','conversations':['alex'],'start_date':'2026-10-01',
            'documents':{key:key for key in ['guide','messages','looms','knowledge','corrections','status']},
            'analysis_path':str(Path(root)/'analysis.sqlite'),'correction_path':str(Path(root)/'corrections.sqlite'),
            'seed_revisions':{s['source_id']:s['revision'] for s in [message,loom]},
            'seed_decisions':[{'source_id':s['source_id'],'label':'work','facts':[]} for s in [message,loom]],
            'reviewed_facts':[{'kind':'request','statement':'Reviewed shared request','dependencies':{message['source_id']:'v1',loom['source_id']:'v1'}}],
            'owner_context':'Owner says payroll pending.'}
    return config,{'sources':[message,loom],'latest_scoped_message':message['timestamp'],'latest_import':'poll1'}


class PublisherTests(unittest.TestCase):
    def test_seed_idle_withdrawal_dependencies_and_undo(self):
        with tempfile.TemporaryDirectory() as root:
            config,snapshot=setup(root);client=Client();analyzer=Analyzer()
            first=run(config,snapshot,client,analyzer)
            self.assertEqual((first['work_messages'],first['work_looms']),(1,1))
            self.assertEqual(analyzer.calls,0)
            snapshot['latest_import']='poll2'
            self.assertEqual(run(config,snapshot,client,analyzer)['writes'],0)
            client.bodies['corrections']+='Correction ID: c1\nOwner: Casey\nTarget: M1\nScope: message\nAction: personal\nInstruction: personal\nRequested at: 2026-10-12T10:00:00Z\n'
            client.revision='r2'
            result=run(config,snapshot,client,analyzer)
            self.assertEqual((result['work_messages'],result['work_looms']),(0,0))
            self.assertNotIn('Reviewed shared request',client.bodies['knowledge'])
            self.assertNotIn('Video request',client.bodies['looms'])
            self.assertNotIn('Please organize links',client.bodies['messages'])
            self.assertIn('payroll pending',client.bodies['knowledge'])
            self.assertEqual(run(config,snapshot,client,analyzer)['writes'],0)
            client.bodies['corrections']+='\nCorrection ID: undo1\nOwner: Casey\nTarget: M1\nScope: message\nAction: undo\nInstruction: restore\nRequested at: 2026-10-12T11:00:00Z\nUndo correction: c1\n'
            client.revision='r3'
            restored=run(config,snapshot,client,analyzer)
            self.assertEqual((restored['work_messages'],restored['work_looms']),(1,1))
            self.assertEqual(analyzer.calls,0)
            self.assertNotIn('corrections',client.writes)
    def test_changed_source_cache_survives_publish_failure(self):
        with tempfile.TemporaryDirectory() as root:
            config,snapshot=setup(root);client=Client();analyzer=Analyzer()
            run(config,snapshot,client,analyzer)
            snapshot['sources'][0].update(revision='v2',text='New request')
            client.fail='messages'
            with self.assertRaises(OSError):run(config,snapshot,client,analyzer)
            calls=analyzer.calls
            client.fail=None
            run(config,snapshot,client,analyzer)
            self.assertEqual(analyzer.calls,calls)
            self.assertIn('New request',client.bodies['messages'])
            self.assertNotIn('Reviewed shared request',client.bodies['knowledge'])
            invalid=copy.deepcopy(snapshot);invalid['sources'][0]['owner']='Jordan'
            with self.assertRaises(ValueError):run(config,invalid,client,analyzer)
    def test_authentication_cannot_be_published_by_work_override(self):
        with tempfile.TemporaryDirectory() as root:
            config,snapshot=setup(root);client=Client();analyzer=Analyzer()
            snapshot['sources'][0]['text']='Your login verification code is 123456'
            client.bodies['corrections']+='Correction ID: c1\nOwner: Casey\nTarget: M1\nScope: message\nAction: work\nInstruction: work\nRequested at: 2026-10-12T10:00:00Z\n'
            result=run(config,snapshot,client,analyzer)
            self.assertEqual((result['work_messages'],result['work_looms']),(0,0))
            self.assertEqual(analyzer.calls,0)
            self.assertNotIn('123456',client.bodies['knowledge'])

    def test_spam_requires_undo_and_date_scope_cannot_be_bypassed(self):
        with tempfile.TemporaryDirectory() as root:
            config,current=setup(root);client=Client();analyzer=Analyzer()
            for cid,action in [('spam1','spam'),('work1','work')]:
                client.bodies['corrections']+=f'Correction ID: {cid}\nOwner: Casey\nTarget: M1\nScope: message\nAction: {action}\nInstruction: test\nRequested at: 2026-10-12T10:00:00Z\n'
            result=run(config,current,client,analyzer)
            self.assertEqual(result['work_messages'],0)
            client.bodies['corrections']+='Correction ID: undo1\nOwner: Casey\nTarget: M1\nScope: message\nAction: undo\nInstruction: remove exclusion\nRequested at: 2026-10-12T11:00:00Z\nUndo correction: spam1\n'
            self.assertEqual(run(config,current,client,analyzer)['work_messages'],1)
            current['sources'][0]['timestamp']='2025-01-01T10:00:00Z'
            with self.assertRaises(ValueError):run(config,current,client,analyzer)

    def test_oversized_source_reports_partial(self):
        with tempfile.TemporaryDirectory() as root:
            config,current=setup(root);client=Client();analyzer=Analyzer()
            current['sources'][0].update(text='x'*25000,revision='v2')
            result=run(config,current,client,analyzer)
            self.assertEqual(result['work_messages'],0)
            self.assertIn('Analysis state: pending/partial',client.bodies['status'])
            self.assertEqual(analyzer.calls,0)

    def test_failed_model_attempt_retains_usage_and_fixed_degraded_status(self):
        with tempfile.TemporaryDirectory() as root:
            config,current=setup(root);client=Client()
            current['sources'][0].update(revision='v2',text='PRIVATE SOURCE BODY')
            class Failed:
                calls=0
                def analyze(self,payload):
                    self.calls+=1
                    error=AdapterError('Codex analysis timed out', {'input_tokens':11,'output_tokens':3})
                    raise error
            analyzer=Failed()
            result=run(config,current,client,analyzer)
            self.assertEqual(result['model_attempts'],1)
            self.assertEqual(result['message_analysis']['model_calls'],1)
            self.assertEqual(result['message_analysis']['usage'],{'input_tokens':11,'output_tokens':3})
            self.assertEqual(result['analysis_state'],'retry_wait')
            self.assertEqual(result['analysis_error_code'],'analysis_timeout')
            self.assertTrue(result['analysis_retryable'])
            self.assertGreaterEqual(result['pending_sources'],1)
            self.assertNotIn('PRIVATE SOURCE BODY',json.dumps(result))
            self.assertNotIn('PRIVATE SOURCE BODY',client.bodies['messages'])

    def test_recovery_probe_does_not_issue_a_second_call_for_loom(self):
        with tempfile.TemporaryDirectory() as root:
            config,current=setup(root);client=Client();analyzer=Analyzer()
            run(config,current,client,analyzer)
            cache=IncrementalArchive(config['analysis_path'])
            with cache.db:
                cache.db.execute("INSERT INTO analysis_state(owner,consecutive_failures,failure_code,"
                    "failure_retryable,retry_after) VALUES ('Casey',2,'analysis_timeout',1,0)")
            cache.close()
            for item in current['sources']:
                item['revision']='v2'
            recovered=run(config,current,client,analyzer)
            self.assertTrue(recovered['message_analysis']['recovery_probe'])
            self.assertEqual(recovered['message_analysis']['model_calls'],1)
            self.assertEqual(recovered['loom_analysis']['model_calls'],0)
            self.assertEqual(recovered['pending_sources'],1)
            self.assertEqual(recovered['analysis_state'],'pending')
            self.assertEqual(analyzer.calls,1)
            complete=run(config,current,client,analyzer)
            self.assertEqual(complete['analysis_state'],'ready')
            self.assertEqual((complete['work_messages'],complete['work_looms']),(1,1))
            self.assertEqual(analyzer.calls,2)

    def test_config_pause_and_zero_model_budget_preserve_cached_outputs(self):
        for setting in ('analysis_paused','max_model_calls'):
            with self.subTest(setting=setting), tempfile.TemporaryDirectory() as root:
                config,current=setup(root);client=Client();analyzer=Analyzer()
                run(config,current,client,analyzer)
                config[setting]=True if setting=='analysis_paused' else 0
                current['sources'][0].update(revision='v2',text='Unresolved new request')
                result=run(config,current,client,analyzer)
                self.assertEqual(result['model_attempts'],0)
                self.assertEqual(analyzer.calls,0)
                self.assertGreaterEqual(result['pending_sources'],1)
                self.assertNotIn('Unresolved new request',client.bodies['messages'])
                self.assertNotIn('corrections',client.writes)
                if setting=='analysis_paused':
                    self.assertEqual(result['analysis_state'],'manual_hold')

import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('history_backfill', Path(__file__).resolve().parents[1] / 'history_backfill.py')
hb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hb)


class HistoryBackfillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / 'store'
        self.store.mkdir()
        self.state = Path(self.tmp.name) / 'private/progress.json'
        self.db = sqlite3.connect(self.store / 'gmcli.db')
        self.addCleanup(self.db.close)
        self.db.executescript('CREATE TABLE conversations(conversation_id TEXT PRIMARY KEY,last_message_ts INTEGER); CREATE TABLE messages(message_id TEXT PRIMARY KEY,conversation_id TEXT,timestamp_ms INTEGER);')
        self.db.executemany('INSERT INTO conversations VALUES(?,?)', [('recent', 200), ('older', 100), ('empty', 50)])
        self.db.executemany('INSERT INTO messages VALUES(?,?,?)', [('r', 'recent', 200), ('o', 'older', 100)])
        self.db.commit()
        self.calls = []
        self.now = 1000

    def invoke(self, **kwargs):
        return hb.collect('Owner', self.store, self.state, call=self.call,
                          clock=lambda: self.now, **kwargs)

    def call(self, path, method, params=None, timeout=30):
        self.calls.append((method, params))
        if method == 'status':
            return {'connected': True, 'auth_expired': False, 'offline': False, 'send_mode': 'off'}
        chat = params['conversation_id']
        before = self.db.execute('SELECT count(*) FROM messages WHERE conversation_id=?', (chat,)).fetchone()[0]
        return {'conversation_id': chat, 'messages_added_for_chat': 0, 'messages_after': before}

    def checkpoint(self):
        return json.loads(self.state.read_text())

    def test_resume_enumerates_empty_threads_and_operational_output(self):
        result = self.invoke(max_chats=1)
        self.assertEqual(self.calls[1][1], {'conversation_id': 'recent', 'requests': 2, 'count': 50})
        self.assertNotIn('recent', json.dumps(result))
        self.assertEqual(self.checkpoint()['threads']['recent']['state'], 'available_endpoint_or_stalled')
        self.invoke(max_chats=1)
        self.assertEqual(self.calls[-1][1]['conversation_id'], 'older')
        self.invoke(max_chats=1)
        self.assertEqual(self.calls[-1][1]['conversation_id'], 'empty')
        n = len(self.calls)
        self.invoke()
        self.assertEqual(len(self.calls), n)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)

    def test_read_only_check_does_not_create_state_or_call_rpc(self):
        before = self.db.total_changes
        self.invoke(check_only=True)
        self.assertFalse(self.state.exists())
        self.assertFalse(self.calls)
        self.assertEqual(before, self.db.total_changes)

    def test_auth_or_send_mode_pause_before_history(self):
        original = self.call
        for key, value in [('auth_expired', True), ('connected', False), ('offline', True), ('send_mode', 'approval')]:
            def unsafe(*a, **kw):
                status = original(*a, **kw)
                status[key] = value
                return status
            with patch.object(self, 'call', unsafe):
                result = self.invoke()
            self.assertEqual(result['outcome'], 'connection_or_send_safety_pause')
        self.assertTrue(all(method == 'status' for method, _ in self.calls))

    def test_budget_avoids_starting_request(self):
        result = self.invoke(max_seconds=20, rpc_timeout=30)
        self.assertEqual(result['outcome'], 'time_budget')
        self.assertEqual(self.calls, [])

    def test_timeout_waits_and_three_failures_pause(self):
        original = self.call
        def failed(*args, **kwargs):
            if args[1] == 'history.backfill':
                self.calls.append(('history.backfill', args[2]))
                raise hb.RPCFailure('must never appear in output')
            return original(*args, **kwargs)
        with patch.object(self, 'call', failed):
            for _ in range(3):
                self.invoke(max_chats=1)
                n = len(self.calls)
                result = self.invoke(max_chats=1)
                self.assertEqual(result['outcome'], 'waiting_for_daemon_operation')
                self.assertEqual(len(self.calls), n)
                self.now += 331
                # Retry order follows the queue; isolate the failed thread.
                state = self.checkpoint()
                state['queue'] = ['recent']
                hb.save(self.state, state)
            self.invoke(max_chats=1)
        self.assertEqual(self.checkpoint()['threads']['recent']['state'], 'paused_failures')
        self.assertEqual(sum(m == 'history.backfill' for m, _ in self.calls), 3)

    def test_progress_round_robin_and_cap(self):
        original = self.call
        def progressing(*args, **kwargs):
            if args[1] == 'status':
                return original(*args, **kwargs)
            self.calls.append(('history.backfill', args[2]))
            chat = args[2]['conversation_id']
            self.db.execute('INSERT INTO messages VALUES(?,?,?)', ('new'+str(len(self.calls)), chat, 10))
            self.db.commit()
            n = self.db.execute('SELECT count(*) FROM messages WHERE conversation_id=?', (chat,)).fetchone()[0]
            return {'conversation_id': chat, 'messages_added_for_chat': 1, 'messages_after': n}
        with patch.object(self, 'call', progressing):
            self.invoke(max_chats=3, max_batches_per_thread=1)
            self.assertEqual([p['conversation_id'] for m,p in self.calls if m == 'history.backfill'], ['recent','older','empty'])
            self.invoke(max_batches_per_thread=1)
        self.assertEqual(set(t['state'] for t in self.checkpoint()['threads'].values()), {'capped'})

    def test_zero_timestamp_gap_is_visible_and_bounded(self):
        self.db.execute('UPDATE messages SET timestamp_ms=0 WHERE conversation_id="recent"')
        self.db.commit()
        self.invoke(max_chats=1)
        self.assertEqual(self.checkpoint()['threads']['recent']['state'], 'zero_timestamp_gap')
        self.assertEqual(self.calls[1][1]['conversation_id'], 'older')

    def test_new_thread_is_enrolled_after_terminal_run(self):
        self.invoke()
        self.db.execute('INSERT INTO conversations VALUES("newly_discovered",999)')
        self.db.commit()
        self.invoke()
        self.assertEqual(self.calls[-1][1]['conversation_id'], 'newly_discovered')

    def test_timeout_with_source_progress_resumes_from_store(self):
        self.invoke(max_chats=1)
        state = self.checkpoint()
        state['inflight'] = {'id': 'recent', 'messages_before': 1}
        state['retry_after'] = self.now - 1
        state['threads']['recent'].update(state='retry_wait', failures=3)
        state['queue'] = ['recent']
        hb.save(self.state, state)
        self.db.execute('INSERT INTO messages VALUES("catchup","recent",20)')
        self.db.commit()
        self.invoke(max_chats=1)
        self.assertEqual(self.checkpoint()['threads']['recent']['failures'], 0)
        self.assertEqual(self.calls[-1][1]['conversation_id'], 'recent')

    def test_nonoverlap_lock(self):
        import fcntl
        self.state.parent.mkdir()
        with open(str(self.state) + '.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.invoke()
        self.assertEqual(result['outcome'], 'already_running')
        self.assertFalse(self.calls)

    def test_rpc_rejects_other_methods(self):
        with self.assertRaises(ValueError):
            hb.rpc(self.store / 'gmcli.sock', 'send.text', {})

    def test_bounds_and_owner_binding(self):
        self.invoke(check_only=True)
        self.invoke(max_chats=1)
        with self.assertRaises(ValueError):
            hb.collect('Other', self.store, self.state, check_only=True)
        with self.assertRaises(ValueError):
            self.invoke(rpc_timeout=61)
        with self.assertRaises(ValueError):
            self.invoke(count=101)


if __name__ == '__main__':
    unittest.main()

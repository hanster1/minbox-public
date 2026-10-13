#!/usr/bin/env python3
"""Bounded, private best-effort history collection through the existing daemon.

Endpoints and caps are coverage limits, never proof of complete phone history.
No sending, pairing, lookup, daemon startup or shutdown methods are used.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from storage import _outside_git


class RPCFailure(Exception):
    pass


def rpc(path, method, params=None, timeout=30):
    if method not in ('status', 'history.backfill'):
        raise ValueError('unsupported method')
    request = {'jsonrpc': '2.0', 'id': 1, 'method': method}
    if params is not None:
        request['params'] = params
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(path))
            sock.sendall(json.dumps(request).encode() + b'\n')
            with sock.makefile('rb') as stream:
                response = json.loads(stream.readline(65537))
        if response.get('id') != 1 or 'error' in response or not isinstance(response.get('result'), dict):
            raise RPCFailure()
        return response['result']
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RPCFailure() from exc


def source_threads(store):
    path = (Path(store) / 'gmcli.db').resolve()
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)
    try:
        db.execute('PRAGMA query_only=ON')
        return [{'id': row[0], 'messages': row[1], 'oldest_ms': row[2]}
                for row in db.execute('''SELECT c.conversation_id, count(m.message_id),
                    min(m.timestamp_ms) FROM conversations c LEFT JOIN messages m
                    ON m.conversation_id=c.conversation_id GROUP BY c.conversation_id
                    ORDER BY c.last_message_ts DESC, c.conversation_id''')]
    finally:
        db.close()


def save(path, state):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(state, stream, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load(path, owner):
    if not Path(path).exists():
        return {'version': 1, 'owner': owner, 'threads': {}, 'queue': [], 'retry_after': 0}
    state = json.loads(Path(path).read_text())
    if state.get('version') != 1 or state.get('owner') != owner or not isinstance(state.get('threads'), dict) or not isinstance(state.get('queue'), list):
        raise ValueError('invalid checkpoint')
    return state


def summary(state, threads, outcome, batches=0, added=0):
    counts = {}
    for thread in state['threads'].values():
        status = thread['state']
        counts[status] = counts.get(status, 0) + 1
    return {'outcome': outcome, 'known_conversations': len(threads),
            'source_messages': sum(t['messages'] for t in threads),
            'thread_states': counts, 'batches': batches, 'messages_added': added,
            'coverage': 'best_effort_known_conversations_no_full_history_guarantee'}


def healthy(status):
    return (status.get('connected') is True and status.get('auth_expired') is False
            and status.get('offline') is False and status.get('send_mode') == 'off')


def collect(owner, store, state_file, *, max_chats=10, requests=2, count=50,
            max_seconds=120, max_batches_per_thread=10, rpc_timeout=30,
            check_only=False, call=rpc, clock=time.time):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', owner):
        raise ValueError('invalid owner')
    if (min(max_chats, requests, count, max_seconds, max_batches_per_thread, rpc_timeout) <= 0
            or rpc_timeout > 60 or requests > 10 or count > 100):
        raise ValueError('invalid bounds')
    state_file = Path(state_file).expanduser().absolute()
    _outside_git(state_file)
    if any(p.is_symlink() for p in (state_file, *state_file.parents)):
        raise ValueError('checkpoint must not use symlinks')
    if check_only:
        threads = source_threads(store)
        return summary(load(state_file, owner), threads, 'check_only')
    state_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    state_file.parent.chmod(0o700)
    fd = os.open(str(state_file) + '.lock', os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as lock:
        os.fchmod(lock.fileno(), 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'outcome': 'already_running'}
        threads = source_threads(store)
        state = load(state_file, owner)
        current = {t['id']: t for t in threads}
        for t in threads:
            if t['id'] not in state['threads']:
                state['threads'][t['id']] = {'state': 'pending', 'batches': 0, 'failures': 0}
                state['queue'].append(t['id'])
        save(state_file, state)
        if clock() < state.get('retry_after', 0):
            return summary(state, threads, 'waiting_for_daemon_operation')
        # An interrupted/failed call may have imported rows. Inspect the source
        # before retrying; the daemon's operation can outlive our socket timeout.
        inflight = state.pop('inflight', None)
        if inflight:
            entry = state['threads'][inflight['id']]
            if inflight['id'] in current and current[inflight['id']]['messages'] > inflight['messages_before']:
                entry['failures'] = 0
                entry['state'] = 'progressing'
            elif entry['failures'] >= 3:
                entry['state'] = 'paused_failures'
        deadline = clock() + max_seconds
        batches = added = 0
        outcome = 'known_threads_bounded'
        while state['queue'] and batches < max_chats:
            if clock() + rpc_timeout > deadline:
                outcome = 'time_budget'
                break
            chat = state['queue'].pop(0)
            entry = state['threads'][chat]
            if chat not in current or entry['state'] in ('available_endpoint_or_stalled', 'paused_failures', 'capped', 'zero_timestamp_gap'):
                continue
            if entry['batches'] >= max_batches_per_thread:
                entry['state'] = 'capped'
                continue
            if current[chat]['oldest_ms'] == 0:
                entry['state'] = 'zero_timestamp_gap'
                continue
            try:
                status = call(Path(store) / 'gmcli.sock', 'status', timeout=min(10, rpc_timeout))
            except RPCFailure:
                state['queue'].insert(0, chat)
                outcome = 'status_unavailable'
                break
            if not healthy(status):
                state['queue'].insert(0, chat)
                outcome = 'connection_or_send_safety_pause'
                break
            if clock() + rpc_timeout > deadline:
                state['queue'].insert(0, chat)
                outcome = 'time_budget'
                break
            before = current[chat]['messages']
            state['inflight'] = {'id': chat, 'messages_before': before}
            state['retry_after'] = clock() + 330
            entry['batches'] += 1
            batches += 1
            state['queue'].append(chat)
            save(state_file, state)
            try:
                result = call(Path(store) / 'gmcli.sock', 'history.backfill',
                              {'conversation_id': chat, 'requests': requests, 'count': count}, timeout=rpc_timeout)
                n = result.get('messages_added_for_chat')
                if (result.get('conversation_id') != chat or type(n) is not int or n < 0
                        or type(result.get('messages_after')) is not int):
                    raise RPCFailure()
            except RPCFailure:
                entry['failures'] += 1
                entry['state'] = 'retry_wait'
                outcome = 'backfill_unavailable_retry_wait'
                save(state_file, state)
                break
            state.pop('inflight', None)
            state['retry_after'] = 0
            entry['failures'] = 0
            entry['state'] = 'progressing' if n else 'available_endpoint_or_stalled'
            entry['messages_after'] = result['messages_after']
            current[chat]['messages'] = result['messages_after']
            # Refresh cursor metadata without reading any message bodies.
            threads = source_threads(store)
            current = {t['id']: t for t in threads}
            added += n
            save(state_file, state)
        save(state_file, state)
        return summary(state, threads, outcome, batches, added)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner', required=True)
    parser.add_argument('--store', type=Path)
    parser.add_argument('--state-file', type=Path)
    for name, default in [('max-chats', 10), ('requests', 2), ('count', 50),
                          ('max-seconds', 120), ('max-batches-per-thread', 10), ('rpc-timeout', 30)]:
        parser.add_argument('--' + name, type=int, default=default)
    parser.add_argument('--check-only', '--status', action='store_true')
    args = vars(parser.parse_args())
    owner = args['owner']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', owner):
        parser.error('invalid owner')
    args['store'] = args['store'] or Path.home() / '.local/state/minbox-text-archive-collectors' / owner
    args['state_file'] = args['state_file'] or Path.home() / '.local/state/minbox-text-archive-backfill' / (owner + '.json')
    try:
        result = collect(**args)
    except Exception:
        print(json.dumps({'outcome': 'local_check_failed'}))
        return 1
    if not args['check_only']:
        save(args['state_file'].with_suffix('.last-run.json'), {'checked_at': datetime.now(timezone.utc).isoformat(), **result})
    print(json.dumps(result, sort_keys=True))
    return int(result['outcome'] in ('local_check_failed', 'status_unavailable', 'connection_or_send_safety_pause', 'backfill_unavailable_retry_wait'))


if __name__ == '__main__':
    raise SystemExit(main())

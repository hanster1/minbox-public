"""Private, bounded source analysis cache. No model or publication adapter is built in.

Context is accepted only as references to current supplied sources already known
as work. Free-form context is omitted. Corrected labels gate Loom access; security
exclusions always win. Publisher failures cannot erase successful analysis batches.
"""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
import urllib.error

LABELS = {'work', 'personal', 'uncertain', 'mixed', 'spam'}
SOURCE_FIELDS = {'source_id', 'revision', 'owner', 'conversation_id', 'timestamp',
                 'text', 'kind', 'origin_ids', 'context'}
MAX_INPUT_BYTES = 5_000_000
MAX_SOURCES = 10000
RECOVERY_DELAYS = (300, 900, 1800)
RETRYABLE_FAILURES = {'analysis_timeout', 'analysis_transport', 'analysis_unavailable', 'legacy_failure'}
FAILURE_CODES = RETRYABLE_FAILURES | {'analysis_authentication', 'analysis_action_rejected',
                                     'analysis_input_limit', 'analysis_invalid_output', 'analysis_failed'}
STATE_COLUMNS = {
    'model_attempts': 'INTEGER NOT NULL DEFAULT 0',
    'manual_hold': 'INTEGER NOT NULL DEFAULT 0',
    'failure_code': "TEXT NOT NULL DEFAULT ''",
    'failure_retryable': 'INTEGER NOT NULL DEFAULT 0',
    'recovery_probes': 'INTEGER NOT NULL DEFAULT 0',
    'retry_after': 'REAL NOT NULL DEFAULT 0',
    'recovery_limit': 'INTEGER NOT NULL DEFAULT 3',
}


class AnalysisFailure(ValueError):
    """Safe failed-attempt result; never retain a provider exception or payload."""
    def __init__(self, result):
        super().__init__('analysis failed; batch not checkpointed')
        self.result = result


class _InvalidAnalysisOutput(ValueError):
    pass


def _failure_code(error):
    code = getattr(error, 'error_code', None)
    if isinstance(code, str) and code in FAILURE_CODES - {'legacy_failure'}:
        return code
    if isinstance(error, (TimeoutError, subprocess.TimeoutExpired)):
        return 'analysis_timeout'
    if isinstance(error, urllib.error.HTTPError):
        if error.code in (401, 403):
            return 'analysis_authentication'
        if error.code in (429, 500, 502, 503, 504):
            return 'analysis_unavailable'
    if isinstance(error, ConnectionError):
        return 'analysis_transport'
    if isinstance(error, _InvalidAnalysisOutput):
        return 'analysis_invalid_output'
    # These exact strings are fixed diagnostics from the isolated transport.
    # Arbitrary provider/source text is never used as a status category.
    return {
        'Codex analysis timed out': 'analysis_timeout',
        'Codex emitted a prohibited tool or action event': 'analysis_action_rejected',
        'Codex input exceeds reviewed local limit': 'analysis_input_limit',
        'Codex output does not match the required schema': 'analysis_invalid_output',
        'Invalid archive analysis output': 'analysis_invalid_output',
    }.get(str(error), 'analysis_failed')


def _valid_usage(value):
    return (isinstance(value, dict) and set(value) == {'input_tokens', 'output_tokens'}
            and all(type(v) is int and v >= 0 for v in value.values()))


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def hard_excluded(text):
    """Conservative local exclusion of authentication codes and clear opt-out ads."""
    if not isinstance(text, str):
        raise ValueError('source text must be a string')
    auth = re.search(r'\b(?:verification|authentication|security|login|log[ -]?in|sign[ -]?in|one[ -]?time|otp|password|verify|2fa|two[ -]?factor)\b', text, re.I)
    code = re.search(r'\b\d{4,8}\b', text) or re.search(r'\bcode\s*(?:is|:)?\s*[A-Z0-9-]{4,12}\b', text, re.I)
    optout = re.search(r'\b(?:reply|text)\s+(?:STOP|UNSUBSCRIBE)\b|\b(?:to unsubscribe|unsubscribe here|to opt[ -]?out)\b', text, re.I)
    promo = re.search(r'\b(?:sale|discount|offer|promo|promotion|coupon|deal|win|prize|buy|shop|limited time|percent off)\b|\d+\s*%\s*off', text, re.I)
    direct_code = re.search(
        r'\b(?:your\s+(?:[\w-]+\s+){0,3}(?:code|pin)\s*(?:is|:)?\s*\d{4,8}\b|'
        r'(?:use|enter)\s+\d{4,8}\s+(?:as\s+your\s+(?:code|pin)|to\s+(?:verify|sign[ -]?in|log[ -]?in))\b|'
        r'\d{4,8}\s+is\s+your\s+(?:[\w-]+\s+){0,3}(?:code|pin)\b)', text, re.I)
    return bool((auth and code) or direct_code or (optout and promo))


def _validate_sources(owner, sources):
    if not isinstance(owner, str) or not owner.strip() or len(owner) > 128:
        raise ValueError('invalid owner')
    sources = list(sources)
    if len(sources) > MAX_SOURCES or len(_json(sources).encode('utf-8')) > MAX_INPUT_BYTES:
        raise ValueError('source input exceeds bounds')
    found = {}
    for source in sources:
        if not isinstance(source, dict) or set(source) - SOURCE_FIELDS:
            raise ValueError('unsupported source fields')
        for field in SOURCE_FIELDS - {'context', 'origin_ids'}:
            if not isinstance(source.get(field), str) or (field != 'text' and not source[field].strip()):
                raise ValueError('missing or invalid source field')
        if (source['owner'] != owner or source['kind'] not in {'message', 'loom'}
                or len(source['source_id']) > 256 or len(source['revision']) > 256):
            raise ValueError('source identity mismatch')
        if (not isinstance(source.get('origin_ids'), list)
                or len(source['origin_ids']) > 1000
                or any(not isinstance(i, str) or not i or len(i) > 256 for i in source['origin_ids'])):
            raise ValueError('invalid source origins')
        try:
            stamp = datetime.fromisoformat(source['timestamp'].replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError()
        except ValueError:
            raise ValueError('source timestamp must include timezone') from None
        if source['source_id'] in found:
            raise ValueError('duplicate source identity')
        found[source['source_id']] = source
    return found


def _validate_decisions(decisions, expected):
    if not isinstance(decisions, list) or len(decisions) != len(expected):
        raise ValueError('analysis must cover every requested source exactly once')
    result = {}
    for decision in decisions:
        if not isinstance(decision, dict) or set(decision) != {'source_id', 'label', 'facts'}:
            raise ValueError('unsupported analysis decision fields')
        sid, label, facts = decision['source_id'], decision['label'], decision['facts']
        if not isinstance(sid, str) or sid not in expected or sid in result or not isinstance(label, str) or label not in LABELS:
            raise ValueError('analysis source or label mismatch')
        if not isinstance(facts, list) or len(facts) > 100:
            raise ValueError('invalid source facts')
        for fact in facts:
            if (not isinstance(fact, dict) or set(fact) != {'kind', 'statement'}
                    or any(not isinstance(fact[k], str) or not fact[k].strip() for k in fact)
                    or len(fact['kind']) > 64 or len(fact['statement']) > 4000):
                raise ValueError('invalid source fact')
        result[sid] = decision
    return result


class IncrementalArchive:
    def __init__(self, path, *, scope=None, max_batch_chars=24000, max_model_calls=2,
                 recovery_enabled=True, operator_paused=False, clock=None):
        if type(max_batch_chars) is not int or not 256 <= max_batch_chars <= MAX_INPUT_BYTES:
            raise ValueError('invalid batch character limit')
        if type(max_model_calls) is not int or not 0 <= max_model_calls <= 100:
            raise ValueError('invalid model call limit')
        if type(recovery_enabled) is not bool or type(operator_paused) is not bool:
            raise ValueError('invalid analysis recovery setting')
        self.max_batch_chars, self.max_model_calls = max_batch_chars, max_model_calls
        self.recovery_enabled, self.operator_paused = recovery_enabled, operator_paused
        self.clock = clock or time.time
        self._probe_owners = set()
        self.scope = json.loads(_json(scope))
        if scope is not None:
            if (not isinstance(scope, dict) or set(scope) != {'owner', 'conversation_ids', 'start_date'}
                    or not isinstance(scope['owner'], str) or not scope['owner'].strip()
                    or not isinstance(scope['conversation_ids'], list) or not scope['conversation_ids']
                    or any(not isinstance(i, str) or not i for i in scope['conversation_ids'])):
                raise ValueError('invalid exact archive scope')
            date.fromisoformat(scope['start_date'])
        self.path = Path(path).expanduser().absolute()
        if any((p / '.git').is_file() or (p / '.git' / 'HEAD').is_file() for p in self.path.parents):
            raise ValueError('runtime cache must be outside Git')
        if self.path.is_symlink() or any(p.is_symlink() for p in self.path.parents):
            raise ValueError('cache path must not use symlinks')
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        except FileExistsError:
            pass
        os.chmod(self.path, 0o600)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('''CREATE TABLE IF NOT EXISTS analyses (
            owner TEXT NOT NULL, source_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
            source_hash TEXT NOT NULL, policy TEXT NOT NULL, metadata TEXT NOT NULL,
            decision TEXT NOT NULL, reason TEXT NOT NULL, security_filtered INTEGER NOT NULL,
            PRIMARY KEY(owner,source_id))''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS analysis_versions (
            owner TEXT NOT NULL, source_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
            source_hash TEXT NOT NULL, policy TEXT NOT NULL, metadata TEXT NOT NULL,
            decision TEXT NOT NULL, reason TEXT NOT NULL, security_filtered INTEGER NOT NULL,
            PRIMARY KEY(owner,source_id,fingerprint))''')
        # Preserve pre-versioning checkpoints when opening an existing runtime cache.
        self.db.execute('INSERT OR IGNORE INTO analysis_versions SELECT * FROM analyses')
        self.db.execute('''CREATE TABLE IF NOT EXISTS analysis_state (
            owner TEXT PRIMARY KEY, consecutive_failures INTEGER NOT NULL DEFAULT 0,
            input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
            unknown_usage_calls INTEGER NOT NULL DEFAULT 0)''')
        existing = {r['name'] for r in self.db.execute('PRAGMA table_info(analysis_state)')}
        legacy = 'failure_code' not in existing
        for name, declaration in STATE_COLUMNS.items():
            if name not in existing:
                self.db.execute(f'ALTER TABLE analysis_state ADD COLUMN {name} {declaration}')
        if legacy:
            # The old automatic breaker recorded no category. Permit one bounded
            # migration probe without discarding any accumulated usage or facts.
            self.db.execute("UPDATE analysis_state SET failure_code='legacy_failure', "
                            'failure_retryable=1, recovery_limit=1 WHERE consecutive_failures>=2')
        self.db.commit()

    def close(self):
        self.db.close()

    def state(self, owner):
        row = self.db.execute('SELECT * FROM analysis_state WHERE owner=?', (owner,)).fetchone()
        return dict(row) if row else {'owner': owner, 'consecutive_failures': 0,
                                     'input_tokens': 0, 'output_tokens': 0, 'unknown_usage_calls': 0,
                                     'model_attempts': 0, 'manual_hold': 0, 'failure_code': '',
                                     'failure_retryable': 0, 'recovery_probes': 0,
                                     'retry_after': 0, 'recovery_limit': len(RECOVERY_DELAYS)}

    def reset_failures(self, owner):
        """Explicit operator reset after inspecting the cause of failed analysis."""
        with self.db:
            self.db.execute("UPDATE analysis_state SET consecutive_failures=0, failure_code='', "
                            'failure_retryable=0, recovery_probes=0, retry_after=0, recovery_limit=3 WHERE owner=?',
                            (owner,))

    def set_manual_hold(self, owner, paused=True):
        """A durable operator pause is independent of the automatic breaker."""
        if type(paused) is not bool:
            raise ValueError('invalid manual analysis hold')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO analysis_state(owner) VALUES (?)', (owner,))
            self.db.execute('UPDATE analysis_state SET manual_hold=? WHERE owner=?', (int(paused), owner))

    def _account(self, owner, failed, usage=None, code='', now=None):
        self.db.execute('INSERT OR IGNORE INTO analysis_state(owner) VALUES (?)', (owner,))
        previous = self.state(owner)
        failures = previous['consecutive_failures'] + 1 if failed else 0
        # Authentication/action rejection never spends another automatic call.
        if failed and code in {'analysis_authentication', 'analysis_action_rejected'}:
            failures = max(failures, 2)
        retry_after = previous['retry_after'] if failed else 0
        if failed and previous['consecutive_failures'] < 2 <= failures:
            retry_after = (self.clock() if now is None else now) + RECOVERY_DELAYS[0]
        self.db.execute('UPDATE analysis_state SET consecutive_failures=?, input_tokens=input_tokens+?, '
                        'output_tokens=output_tokens+?, unknown_usage_calls=unknown_usage_calls-?, '
                        'failure_code=?, failure_retryable=?, '
                        'recovery_probes=?, retry_after=?, recovery_limit=? WHERE owner=?',
                        (failures,
                         usage['input_tokens'] if usage else 0, usage['output_tokens'] if usage else 0,
                         int(usage is not None), code if failed else '', int(failed and code in RETRYABLE_FAILURES),
                         previous['recovery_probes'] if failed else 0, retry_after,
                         previous['recovery_limit'] if failed else len(RECOVERY_DELAYS), owner))

    def _start_attempt(self, owner):
        # Reserve usage as unknown before calling the adapter. Worker termination
        # cannot erase an attempted call; validated completion converts it to
        # reported usage without counting the attempt twice.
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO analysis_state(owner) VALUES (?)', (owner,))
            self.db.execute('UPDATE analysis_state SET model_attempts=model_attempts+1, '
                            'unknown_usage_calls=unknown_usage_calls+1 WHERE owner=?', (owner,))

    def _hold(self, owner, now):
        current = self.state(owner)
        if self.operator_paused or current['manual_hold']:
            return 'manual_hold'
        if owner in self._probe_owners:
            return 'run_limit'
        if current['consecutive_failures'] < 2:
            return ''
        if not self.recovery_enabled:
            return 'manual_hold'
        if not current['failure_retryable']:
            return 'needs_attention'
        if current['recovery_probes'] >= current['recovery_limit']:
            return 'exhausted'
        return 'retry_wait' if now < current['retry_after'] else 'probe'

    def _reserve_probe(self, owner, now):
        current = self.state(owner)
        number = current['recovery_probes'] + 1
        next_delay = RECOVERY_DELAYS[min(number, len(RECOVERY_DELAYS) - 1)]
        # Persist the reservation before invoking the model, including a retry
        # time, so a killed worker or reopened cache cannot repeat the same probe.
        with self.db:
            changed = self.db.execute('UPDATE analysis_state SET recovery_probes=?, retry_after=? '
                                     'WHERE owner=? AND recovery_probes=? AND retry_after=? '
                                     'AND manual_hold=0 AND consecutive_failures>=2 AND failure_retryable=1 '
                                     'AND recovery_probes<recovery_limit AND retry_after<=?',
                                     (number, now + next_delay, owner,
                                      current['recovery_probes'], current['retry_after'], now)).rowcount
        if changed:
            self._probe_owners.add(owner)
        return bool(changed)

    def _scope_error(self, source):
        if self.scope is None:
            return False
        if source['owner'] != self.scope['owner']:
            return True
        return (source['conversation_id'] not in self.scope['conversation_ids']
                or source['timestamp'][:10] < self.scope['start_date'])

    def _cached(self, owner):
        return {r['source_id']: dict(r) for r in self.db.execute('SELECT * FROM analyses WHERE owner=?', (owner,))}

    def _prepare(self, owner, sources, policy, labels=None, seed_labels=None, source_overrides=None):
        sources = _validate_sources(owner, sources)
        if not isinstance(policy, str) or not policy.strip() or len(policy) > 4096:
            raise ValueError('invalid analysis policy')
        if self.scope is not None and self.scope['owner'] != owner:
            raise ValueError('configured scope owner mismatch')
        labels = {} if labels is None else labels
        if not isinstance(labels, dict) or any(not isinstance(k, str) or v not in LABELS for k, v in labels.items()):
            raise ValueError('invalid effective labels')
        source_overrides = {} if source_overrides is None else source_overrides
        if not isinstance(source_overrides, dict) or any(
                not isinstance(k, str) or v not in LABELS for k, v in source_overrides.items()):
            raise ValueError('invalid source overrides')
        cached = self._cached(owner)
        base_hash = {sid: _hash(source) for sid, source in sources.items()}
        excluded = {sid: ('security_filter' if hard_excluded(s['text']) else
                          'outside_scope' if self._scope_error(s) else
                          'manual_' + source_overrides[sid] if source_overrides.get(sid) in {'spam', 'personal', 'mixed'}
                          else '') for sid, s in sources.items()}
        effective = {}
        dependencies, kinds = {}, {}
        for sid in set(cached) | set(sources):
            old = cached.get(sid)
            if sid in sources:
                dependencies[sid] = base_hash[sid]
                safe_cache = old and old['source_hash'] == base_hash[sid] and old['policy'] == policy
                safe = not excluded[sid]
                kinds[sid] = sources[sid]['kind']
            else:
                dependencies[sid] = old['source_hash']
                safe_cache = old['policy'] == policy
                metadata = json.loads(old['metadata'])
                kinds[sid] = metadata['kind']
                safe = not old['security_filtered'] and old['reason'] != 'outside_scope' and not self._scope_error(metadata)
            label = json.loads(old['decision'])['label'] if safe_cache else 'uncertain'
            if seed_labels and sid in seed_labels:
                label = seed_labels[sid]
            label = source_overrides.get(sid, labels.get(sid, label))
            effective[sid] = label if safe else 'spam'
        prepared = {}
        for sid, source in sources.items():
            context_ids, declared_context_ids = [], []
            supplied_context = source.get('context')
            if isinstance(supplied_context, list):
                for ref in supplied_context:
                    refid = ref if isinstance(ref, str) else ref.get('source_id') if isinstance(ref, dict) else None
                    if isinstance(refid, str) and refid in sources and refid != sid:
                        declared_context_ids.append(refid)
                        if effective.get(refid) == 'work' and not excluded[refid]:
                            context_ids.append(refid)
            context_ids = sorted(set(context_ids))
            origins = sorted(set(source['origin_ids']))
            gate = source['kind'] == 'message' or any(effective.get(i) == 'work' and kinds.get(i) == 'message' for i in origins)
            reason = excluded[sid] or ('' if gate else 'no_work_origin')
            context = [{k: sources[i][k] for k in ('source_id', 'revision', 'kind', 'timestamp', 'text')}
                       for i in context_ids]
            projected = {k: source[k] for k in ('source_id', 'revision', 'conversation_id', 'timestamp', 'text', 'kind', 'origin_ids')}
            projected['context'] = context
            # A model's own labels becoming available are not new source evidence.
            # Explicit correction labels and all declared dependency revisions are.
            deps = {i: {'source_hash': dependencies.get(i),
                        'label': effective.get(i, 'uncertain') if i in origins else source_overrides.get(i, labels.get(i)),
                        'excluded': excluded.get(i, '')}
                    for i in sorted(set(declared_context_ids) | set(origins))}
            fingerprint = _hash({'source': base_hash[sid], 'policy': policy, 'scope': self.scope,
                                 'dependencies': deps, 'reason': reason})
            prepared[sid] = {'source': source, 'payload': projected, 'fingerprint': fingerprint,
                             'source_hash': base_hash[sid], 'reason': reason,
                             'security_filtered': reason == 'security_filter'}
            historical = self.db.execute(
                'SELECT * FROM analysis_versions WHERE owner=? AND source_id=? AND fingerprint=?',
                (owner, sid, fingerprint)).fetchone()
            if historical:
                cached[sid] = dict(historical)
        return prepared, cached

    def _restore(self, owner, sid, fingerprint):
        """Promote an exact historical match to the current source registry."""
        current = self.db.execute('SELECT fingerprint FROM analyses WHERE owner=? AND source_id=?',
                                  (owner, sid)).fetchone()
        if not current or current[0] != fingerprint:
            self.db.execute('INSERT OR REPLACE INTO analyses SELECT * FROM analysis_versions '
                            'WHERE owner=? AND source_id=? AND fingerprint=?', (owner, sid, fingerprint))

    def _store(self, owner, prepared, decisions, policy, reason=''):
        for sid, decision in decisions.items():
            entry = prepared[sid]
            source = entry['source']
            metadata = {k: source[k] for k in SOURCE_FIELDS - {'text', 'context'}}
            values = (owner, sid, entry['fingerprint'], entry['source_hash'], policy,
                      _json(metadata), _json(decision), entry['reason'] or reason,
                      entry['security_filtered'])
            self.db.execute('INSERT OR IGNORE INTO analysis_versions VALUES (?,?,?,?,?,?,?,?,?)', values)
            self.db.execute('INSERT OR REPLACE INTO analyses VALUES (?,?,?,?,?,?,?,?,?)', values)

    def seed(self, owner, sources, decisions, policy='v1'):
        """Seed missing sources only; never replace existing analysis with old reviews.

        Hard exclusions still override work. Changed existing sources require analysis.
        """
        sources = list(_validate_sources(owner, sources).values())
        checked = _validate_decisions(decisions, {s['source_id'] for s in sources})
        existing = self._cached(owner)
        prepared, cached = self._prepare(owner, sources, policy, seed_labels={
            k: d['label'] for k, d in checked.items() if k not in existing})
        seeded = {}
        for sid, decision in checked.items():
            if sid in cached:
                continue
            reason = prepared[sid]['reason']
            seeded[sid] = ({'source_id': sid, 'label': 'spam' if reason in {'security_filter', 'outside_scope'} else 'uncertain',
                            'facts': []} if reason else decision)
        with self.db:
            self._store(owner, prepared, seeded, policy, reason='reviewed_seed')
        return {'seeded': len(seeded), 'skipped': len(checked) - len(seeded), 'model_calls': 0}

    def analyze(self, owner, sources, analyzer, policy='v1', *, labels=None, source_overrides=None, max_calls=None):
        """Analyze pending sources only; checkpoint each entire validated batch.

        Limits defer sources as uncertain. The automatic breaker admits bounded
        cooldown probes; manual holds remain operator-controlled. Explicit source
        overrides exclude spam/personal/mixed before input projection. max_calls
        can reduce the instance budget for one phase of a shared run. Failed batches
        are never cached, and safe failed-attempt results retain usage and counts.
        """
        if max_calls is not None and (type(max_calls) is not int or not 0 <= max_calls <= self.max_model_calls):
            raise ValueError('invalid per-call model budget')
        call_limit = self.max_model_calls if max_calls is None else max_calls
        prepared, cached = self._prepare(owner, sources, policy, labels, source_overrides=source_overrides)
        pending, filtered, reusable, hits = [], {}, [], 0
        for sid, entry in prepared.items():
            if cached.get(sid, {}).get('fingerprint') == entry['fingerprint']:
                hits += 1
                reusable.append(sid)
            elif entry['reason']:
                filtered[sid] = {'source_id': sid, 'label': self._filtered_label(entry['reason']), 'facts': []}
            else:
                pending.append(sid)
        with self.db:
            for sid in reusable:
                self._restore(owner, sid, prepared[sid]['fingerprint'])
            self._store(owner, prepared, filtered, policy)
        calls, analyzed, deferred, unknown = 0, 0, [], 0
        deferred_reasons = {}
        usage = {'input_tokens': 0, 'output_tokens': 0}
        probe = False

        def defer(ids, reason):
            deferred.extend(ids)
            deferred_reasons[reason] = deferred_reasons.get(reason, 0) + len(ids)

        def result(failed=False):
            current = self.state(owner)
            if deferred or failed:
                if self.operator_paused or current['manual_hold'] or (
                        not self.recovery_enabled and current['consecutive_failures'] >= 2):
                    status = 'manual_hold'
                elif current['consecutive_failures'] >= 2 and not current['failure_retryable']:
                    status = 'needs_attention'
                elif (current['consecutive_failures'] >= 2 and
                      current['recovery_probes'] >= current['recovery_limit']):
                    status = 'exhausted'
                elif failed or current['consecutive_failures'] >= 2:
                    status = 'retry_wait'
                else:
                    status = 'pending'
            else:
                status = 'ready'
            return {'model_calls': calls, 'model_attempts': calls, 'analyzed': analyzed,
                    'cache_hits': hits, 'filtered': len(filtered), 'deferred': deferred,
                    'pending_sources': len(deferred), 'deferred_reasons': deferred_reasons,
                    'usage': usage, 'unknown_usage_calls': unknown,
                    'paused': status in {'manual_hold', 'retry_wait', 'needs_attention', 'exhausted'},
                    'analysis_failed': failed, 'analysis_state': status,
                    'error_code': current['failure_code'] if status not in {'ready', 'pending'} else '',
                    'retryable': bool(current['failure_retryable']) and status == 'retry_wait',
                    'recovery_probe': probe, 'recovery_probes': current['recovery_probes'],
                    'retry_after': current['retry_after'] if status == 'retry_wait' else 0,
                    'state': current}

        while pending:
            if calls >= call_limit:
                defer(pending, 'call_limit')
                break
            hold = self._hold(owner, self.clock())
            if hold and hold != 'probe':
                defer(pending, hold)
                break
            is_probe = hold == 'probe'
            batch_limit = self.max_batch_chars
            if is_probe:
                batch_limit = min(batch_limit, 6000)
                if self.state(owner)['failure_code'] == 'analysis_timeout':
                    batch_limit = max(256, min(batch_limit, self.max_batch_chars // 2))
            batch = []
            while pending:
                trial = batch + [pending[0]]
                payload = {'owner': owner, 'policy': policy, 'sources': [prepared[i]['payload'] for i in trial]}
                size = len(_json(payload))
                if size > batch_limit:
                    if not batch:
                        reason = 'probe_input_limit' if size <= self.max_batch_chars else 'input_limit'
                        # Keep complete sources; smaller recovery probes never
                        # truncate or merge evidence to make it fit.
                        defer([pending.pop(0)], reason)
                        continue
                    break
                batch.append(pending.pop(0))
            if not batch:
                continue
            if is_probe:
                if not self._reserve_probe(owner, self.clock()):
                    defer(batch + pending, 'retry_wait')
                    break
                probe = True
            payload = {'owner': owner, 'policy': policy, 'sources': [prepared[i]['payload'] for i in batch]}
            reported = None
            self._start_attempt(owner)
            calls += 1
            try:
                response = analyzer.analyze(payload)
                if isinstance(response, dict) and _valid_usage(response.get('usage')):
                    reported = response['usage']
                if not isinstance(response, dict) or set(response) != {'decisions', 'usage'}:
                    raise _InvalidAnalysisOutput()
                candidate_usage = response['usage']
                if not _valid_usage(candidate_usage):
                    raise _InvalidAnalysisOutput()
                reported = candidate_usage
                try:
                    decisions = _validate_decisions(response['decisions'], set(batch))
                except ValueError:
                    raise _InvalidAnalysisOutput() from None
                with self.db:
                    self._store(owner, prepared, decisions, policy, reason='analyzed')
                    self._account(owner, False, reported)
            except Exception as error:
                if reported is None and _valid_usage(getattr(error, 'reported_usage', None)):
                    reported = error.reported_usage
                if reported is None:
                    unknown += 1
                else:
                    for key in usage:
                        usage[key] += reported[key]
                with self.db:
                    self._account(owner, True, reported, _failure_code(error))
                defer(batch + pending, 'failed_batch')
                raise AnalysisFailure(result(failed=True)) from None
            analyzed += len(batch)
            for k in usage:
                usage[k] += reported[k]
        return result()

    @staticmethod
    def _filtered_label(reason):
        if reason in {'security_filter', 'outside_scope'}:
            return 'spam'
        return reason.removeprefix('manual_') if reason.startswith('manual_') else 'uncertain'

    def records(self, owner, sources, policy='v1', *, labels=None, source_overrides=None):
        prepared, cached = self._prepare(owner, sources, policy, labels, source_overrides=source_overrides)
        result = {}
        for sid, entry in prepared.items():
            old = cached.get(sid)
            hit = old and old['fingerprint'] == entry['fingerprint']
            source = entry['source']
            record = {k: source[k] for k in SOURCE_FIELDS - {'text', 'context'}}
            record.update(label='uncertain', facts=[], reason='unanalyzed', security_filtered=entry['security_filtered'], cache_hit=bool(hit))
            if hit:
                record.update(json.loads(old['decision']))
                record['reason'] = old['reason']
            elif entry['reason']:
                record.update(label=self._filtered_label(entry['reason']), reason=entry['reason'])
            result[sid] = record
        return result

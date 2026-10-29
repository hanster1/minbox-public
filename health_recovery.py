"""Bounded service recovery and deduplicated human-only escalation.

Observation never grants permission to change account bindings, pairing, privacy,
databases, budget limits or code. Only configured, enabled Minbox jobs can run.
"""
import re
import subprocess
import time

RETRY_DELAYS = (60, 300, 900)
OUTAGE_GRACE = 1800
HEALTHY_RESET = 21600
RUNNING = {'active', 'activating', 'deactivating'}
CRITICAL = {'authentication', 'session_permissions', 'send_mode',
            'source_integrity', 'integrity', 'low', 'configuration'}
LOCAL_ONLY = {'analysis_paused', 'input_limit', 'paused', 'loom_capture_pending'}


def service_action(action, unit):
    if action not in ('start', 'restart', 'stop') or not re.fullmatch(
            r'minbox-(?:text-(?:collector|import|backfill)@[A-Za-z0-9_-]+|'
            r'text-loom|archive-publisher@[A-Za-z0-9_-]+|owner-archive@[A-Za-z0-9_-]+)\.(?:service|timer)', unit):
        raise ValueError('recovery action outside allowlist')
    if action == 'stop' and not re.fullmatch(r'minbox-text-collector@[A-Za-z0-9_-]+\.service', unit):
        raise ValueError('only an unsafe collector may be quarantined')
    subprocess.run(['systemctl', '--user', action, '--no-block', unit],
                   capture_output=True, timeout=10, check=True)


def targets(config):
    result = {}
    for i, owner in enumerate(config.get('owners', []), 1):
        if isinstance(owner, str) and re.fullmatch(r'[A-Za-z0-9_-]+', owner):
            result[f'collector_{i}'] = {'service': f'minbox-text-collector@{owner}.service',
                'import_service': f'minbox-text-import@{owner}.service',
                'timer': f'minbox-text-import@{owner}.timer', 'essential': True}
    for i, publisher in enumerate(config.get('publishers', []), 1):
        name = publisher.get('name') if isinstance(publisher, dict) else None
        kind = publisher.get('kind', 'work') if isinstance(publisher, dict) else None
        if isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9_-]+', name) and kind in ('work', 'owner_all'):
            unit = ('minbox-owner-archive@' if kind == 'owner_all' else 'minbox-archive-publisher@') + name
            result[f'publisher_{i}'] = {'service': unit + '.service', 'timer': unit + '.timer',
                                      'essential': kind == 'owner_all'}
    for i, backfill in enumerate(config.get('backfills', []), 1):
        name = backfill.get('owner') if isinstance(backfill, dict) else None
        if isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9_-]+', name):
            unit = backfill.get('unit', 'minbox-text-backfill@' + name)
            if not isinstance(unit, str) or not re.fullmatch(r'[A-Za-z0-9@._-]{1,128}', unit) or unit.endswith(('.timer', '.service')):
                continue
            result[f'backfill_{i}'] = {'service': unit + '.service', 'timer': unit + '.timer', 'essential': False}
    if config.get('loom_monitor'):
        result['loom'] = {'service': 'minbox-text-loom.service', 'timer': 'minbox-text-loom.timer', 'essential': False}
    return result


def component_checked(observation, prefix):
    """An unrelated component failure cannot invalidate this observation."""
    if not observation.get('check_failed'):
        return True
    failed = {key.partition('.')[0] for key in observation.get('issues', ())
              if key.endswith('check_failed') or key.endswith(('.rpc_unavailable', '.configuration'))}
    # A failure without a located component remains conservatively unknown.
    return bool(failed) and prefix not in failed and not failed & {'monitor', 'archive', 'disk'}


def supervise(state, observation, config, now, *, properties, action=service_action, deliver=None):
    """A queued start is an attempt; only fresh observation confirms recovery."""
    records = state.setdefault('recovery', {})
    registry = targets(config)
    policy = config.get('recovery', {})
    paused = set(policy.get('paused_components', []))
    issues = set(observation['issues'])
    metadata = observation.get('components', {})
    grouped = {}
    for key in issues:
        prefix, _, suffix = key.partition('.')
        grouped.setdefault(prefix, []).append(suffix)
    # A previous Result resets at job start. Keep an open episode during retries.
    for key in observation.get('deferred_recoveries', []):
        prefix = key.partition('.')[0]
        if prefix in records and 'healthy_since' not in records[prefix]:
            grouped.setdefault(prefix, [])
    alerts, actions = [], []
    global_unsafe = any(k in issues for k in ('archive.integrity', 'archive.check_failed', 'disk.low'))
    for prefix, record in list(records.items()):
        if prefix not in grouped:
            # Unavailable observation cannot prove health or close an episode.
            if not component_checked(observation, prefix):
                continue
            record.setdefault('healthy_since', now)
            record['state'] = 'healthy'
            record.pop('quarantined', None)
            if now - record['healthy_since'] >= HEALTHY_RESET:
                del records[prefix]
    for prefix, suffixes in grouped.items():
        record = records.setdefault(prefix, {'first': now, 'attempts': 0, 'notified': False})
        if 'healthy_since' in record:
            # A relapse retains notification dedupe but earns a fresh repair budget.
            record.pop('healthy_since')
            record.update(first=now, attempts=0)
            record.pop('next_retry', None)
        record['issues'] = sorted(suffixes)
        record['state'] = 'observing'
        target = registry.get(prefix)
        component = metadata.get(prefix, {})
        fatal = bool(set(suffixes) & CRITICAL) or component.get('failure_kind') in ('auth', 'privacy', 'integrity')
        age = now - record['first']
        optional = (target is not None and not target['essential']) or bool(suffixes) and set(suffixes) <= LOCAL_ONLY
        if prefix in paused or target and target['service'] in paused:
            record['state'] = 'operator_paused'
            continue
        if target and prefix.startswith('collector_') and set(suffixes) & {'send_mode', 'source_integrity'} and not record.get('quarantined'):
            try:
                action('stop', target['service'])
                record['quarantined'] = True
                actions.append({'component': prefix, 'result': 'quarantined'})
            except Exception:
                record['last_action'] = 'quarantine_failed'
        disabled = False
        running = False
        blocked = not policy.get('enabled', True)
        stuck = False
        repairable = target is not None and bool(set(suffixes) - LOCAL_ONLY) and not fatal and not global_unsafe
        if repairable and policy.get('enabled', True):
            collector_restart = prefix.startswith('collector_') and bool(set(suffixes) & {'service', 'disconnected', 'rpc_unavailable'})
            service = target['service'] if collector_restart or 'import_service' not in target else target['import_service']
            try:
                timer = properties(target['timer'])
                worker = properties(service)
                if set(suffixes) & {'timer', 'import_timer'} and timer.get('ActiveState') != 'active':
                    service, worker = target['timer'], timer
                    collector_restart = False
                disabled = timer.get('UnitFileState') != 'enabled'
                if collector_restart:
                    disabled = disabled or worker.get('UnitFileState') != 'enabled'
                running = worker.get('ActiveState') in RUNNING and not collector_restart
                if running:
                    record.setdefault('running_since', now)
                    limit = 600 if target['service'].startswith('minbox-owner-archive@') else 420 if prefix == 'loom' else 180 if prefix.startswith('backfill_') else 360
                    start = float(worker.get('ExecMainStartTimestampMonotonic', 0)) / 1_000_000
                    elapsed = time.monotonic() - start if start > 0 else now - record['running_since']
                    stuck = elapsed > limit
                else:
                    record.pop('running_since', None)
                # A connected collector runs continuously; reconnect restart is allowed.
                busy = running and not collector_restart
                if disabled:
                    record['state'] = 'schedule_disabled'
                elif busy:
                    record['state'] = 'stuck_worker' if stuck else 'retry_running'
                elif age >= (300 if collector_restart else 60) and record['attempts'] < len(RETRY_DELAYS) and now >= record.get('next_retry', 0):
                    record['attempts'] += 1
                    record['next_retry'] = now + RETRY_DELAYS[record['attempts'] - 1]
                    record['last_action_at'] = now
                    try:
                        action('restart' if collector_restart else 'start', service)
                        record['last_action'] = 'queued'
                    except Exception:
                        record['last_action'] = 'failed'
                    actions.append({'component': prefix, 'result': record['last_action']})
                    record['state'] = 'recovering'
            except Exception:
                blocked = True
                record['state'] = 'recovery_unavailable'
        if fatal:
            record['state'] = 'human_required'
        elif optional:
            record['state'] = 'maintenance_pending' if not repairable else record['state']
        # Do not alert on a single failure, input deferral, or an active retry.
        # A completed outage requires failed recovery attempts and elapsed time.
        exhausted = age >= OUTAGE_GRACE and (record['attempts'] >= len(RETRY_DELAYS) or disabled or blocked or stuck or target is None)
        if not fatal and not optional and exhausted and (not running or stuck):
            record['state'] = 'human_required'
        signature = ('fatal:' + ','.join(sorted(set(suffixes) & CRITICAL)) + ':' + str(component.get('failure_kind', ''))
                     if fatal else 'availability')
        if record['state'] == 'human_required':
            record['notified'] = signature in record.get('notified_signatures', [])
        record['notice_signature'] = signature
        if record['state'] == 'human_required' and not record['notified']:
            alerts.append(prefix)
    delivery = 'idle'
    if alerts:
        delivery = 'unconfigured' if deliver is None else 'pending'
        if deliver is not None:
            from health_monitor import issue_text
            labels = observation.get('owner_labels', {})
            lines = ['Human action required: Minbox archive', '', 'Automatic recovery could not safely resolve:']
            for prefix in sorted(alerts):
                record = records[prefix]
                for suffix in record['issues']:
                    if suffix in LOCAL_ONLY:
                        continue
                    problem, _, next_action = issue_text(prefix + '.' + suffix, labels)
                    lines.append('- ' + problem + ' ' + next_action)
                if not record['issues']:
                    lines.append('- Archive progress remains unavailable. Inspect the local recovery report.')
                lines.append('  Recovery attempts: ' + str(record['attempts']) + '. Further operator diagnosis or authorization is required.')
            try:
                deliver('\n'.join(lines) + '\n')
            except Exception:
                delivery = 'failed'
            else:
                delivery = 'sent'
                for prefix in alerts:
                    records[prefix]['notified'] = True
                    signatures = records[prefix].setdefault('notified_signatures', [])
                    signatures.append(records[prefix]['notice_signature'])
    return {'components': records, 'actions': actions, 'pending_alerts': sorted(alerts),
            'delivery': delivery, 'pending_recoveries': []}

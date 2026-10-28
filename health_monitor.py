#!/usr/bin/env python3
"""Private archive observation, bounded recovery and human-only escalation."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import smtplib
import socket
import sqlite3
import ssl
import subprocess
import tempfile
import time
import urllib.request
from email.message import EmailMessage
from contextlib import closing

DISCONNECT_GRACE = 300
IMPORT_GRACE = 600
WORKER_FAILURE_GRACE = 600

from health_recovery import component_checked


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def unit_properties(unit):
    result = subprocess.run(['systemctl', '--user', 'show', unit,
                             '--property=LoadState,ActiveState,UnitFileState,Result,ExecMainStartTimestampMonotonic'],
                            capture_output=True, text=True, timeout=10, check=True)
    properties = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if properties.get('LoadState') in ('not-found', 'error', 'bad-setting'):
        raise ValueError('monitored unit unavailable')
    return properties


def rpc_status(path):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(10)
        sock.connect(str(path))
        sock.sendall(b'{"jsonrpc":"2.0","id":1,"method":"status"}\n')
        with sock.makefile('rb') as stream:
            response = json.loads(stream.readline(65537))
        result = response['result']
        if (not isinstance(result, dict) or
                any(not isinstance(result.get(key), bool) for key in ('connected', 'auth_expired', 'offline')) or
                not isinstance(result.get('send_mode'), str)):
            raise ValueError('invalid status')
        return result


def read_db(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=10)
    db.execute('PRAGMA query_only=ON')
    return db


def observe(config, now):
    """Return fixed-label issues; exceptions never escape into diagnostics."""
    issues, missing = {}, {}
    deferred_recoveries = []
    check_failed = False
    components = {}
    def add(key, grace=0):
        issues[key] = grace
    archive = Path(config.get('archive', '~/.local/share/minbox-text-archive/archive.sqlite3')).expanduser()
    collectors = Path(config.get('collectors', '~/.local/state/minbox-text-archive-collectors')).expanduser()
    try:
        usage = shutil.disk_usage(archive.parent)
        if usage.free < 2 * 1024**3 or usage.free / usage.total < .05:
            add('disk.low')
    except Exception:
        add('disk.check_failed'); check_failed = True
    derived = None
    try:
        derived = read_db(archive)
        if derived.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            add('archive.integrity')
    except Exception:
        add('archive.check_failed'); check_failed = True
    if config.get('loom_monitor'):
        try:
            timer = unit_properties('minbox-text-loom.timer')
            if timer.get('ActiveState') != 'active' or timer.get('UnitFileState') != 'enabled':
                add('loom.timer')
            worker = unit_properties('minbox-text-loom.service')
            if worker.get('ActiveState') in ('activating', 'active', 'deactivating'):
                deferred_recoveries.append('loom.worker_failure')
            if worker.get('Result') != 'success':
                add('loom.worker_failure', WORKER_FAILURE_GRACE)
            if derived is not None:
                row = derived.execute("SELECT last_completed_at FROM loom_worker WHERE id=1").fetchone()
                stamp = dt.datetime.fromisoformat(row[0].replace('Z', '+00:00')).timestamp() if row else 0
                if now - stamp > 900:
                    add('loom.worker_stale')
                for owner, status, first_seen in derived.execute("SELECT owner,status,COALESCE(failure_since,discovered_at) FROM loom_queue WHERE status != 'captured'"):
                    stamp = dt.datetime.fromisoformat(first_seen.replace('Z', '+00:00')).timestamp()
                    if now - stamp >= 3600:
                        owners = config.get('owners', [])
                        prefix = f'collector_{owners.index(owner) + 1}' if owner in owners else 'loom'
                        add(prefix + '.loom_capture_pending')
        except Exception:
            add('loom.check_failed'); check_failed = True
    for index, publisher in enumerate(config.get('publishers', [])):
        prefix = f'publisher_{index + 1}'
        if (not isinstance(publisher, dict) or
                not isinstance(publisher.get('name'), str) or
                not re.fullmatch(r'[A-Za-z0-9_-]+', publisher['name']) or
                not isinstance(publisher.get('status_file'), str) or
                not publisher['status_file']):
            add(prefix + '.configuration'); check_failed = True
            continue
        try:
            kind = publisher.get('kind', 'work')
            if kind not in ('work', 'owner_all'):
                raise ValueError('unknown publisher kind')
            unit = ('minbox-owner-archive@' if kind == 'owner_all' else 'minbox-archive-publisher@') + publisher['name']
            timer = unit_properties(unit + '.timer')
            if timer.get('ActiveState') != 'active' or timer.get('UnitFileState') != 'enabled':
                add(prefix + '.timer')
            worker = unit_properties(unit + '.service')
            # A retry resets Result before establishing completed-run recovery.
            if worker.get('ActiveState') in ('activating', 'active', 'deactivating'):
                deferred_recoveries.append(prefix + '.worker_failure')
            if worker.get('Result') != 'success':
                add(prefix + '.worker_failure', WORKER_FAILURE_GRACE)
            status = json.loads(Path(publisher['status_file']).expanduser().read_text())
            components[prefix] = {key: status[key] for key in
                ('run_state', 'failure_kind', 'error_code', 'http_status', 'consecutive_failures',
                 'last_success_at', 'last_publication_at', 'last_analysis_success_at',
                 'analysis_state', 'analysis_retry_after', 'pending_sources') if key in status}
            stamp = dt.datetime.fromisoformat(status['checked_at'].replace('Z', '+00:00')).timestamp()
            started = dt.datetime.fromisoformat(status.get('started_at', status['checked_at']).replace('Z', '+00:00')).timestamp()
            bounded_running = worker.get('ActiveState') in ('activating', 'active', 'deactivating') and now - started <= (600 if kind == 'owner_all' else 360)
            contention = status.get('last_contention_at')
            contended = (contention is not None and
                         stamp < dt.datetime.fromisoformat(contention.replace('Z', '+00:00')).timestamp() <= now and
                         now - dt.datetime.fromisoformat(contention.replace('Z', '+00:00')).timestamp() <= 600)
            if now - stamp > 600 and not bounded_running and not contended:
                add(prefix + '.worker_stale')
            if status.get('run_state') == 'failed':
                add(prefix + '.worker_failure', WORKER_FAILURE_GRACE)
            if status.get('failure_kind') in ('auth', 'privacy', 'integrity') and status.get('run_state') == 'failed':
                add(prefix + '.human_required')
            if kind == 'owner_all' and 'last_publication_at' in status:
                success = dt.datetime.fromisoformat(status['last_publication_at'].replace('Z', '+00:00')).timestamp()
                if now - success > 1800:
                    add(prefix + '.publication_stale')
            if status.get('analysis_failed_or_paused'):
                add(prefix + '.analysis_paused')
            if status.get('deferred_sources', 0) > 0:
                add(prefix + '.input_limit', 1800)
        except Exception:
            add(prefix + '.check_failed'); check_failed = True
    for index, backfill in enumerate(config.get('backfills', [])):
        prefix = f'backfill_{index + 1}'
        try:
            name = backfill['owner']
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', name):
                raise ValueError('invalid owner')
            unit = backfill.get('unit', 'minbox-text-backfill@' + name)
            if not isinstance(unit, str) or not re.fullmatch(r'[A-Za-z0-9@._-]{1,128}', unit) or unit.endswith(('.timer', '.service')):
                raise ValueError('invalid unit')
            timer = unit_properties(unit + '.timer')
            if timer.get('ActiveState') != 'active' or timer.get('UnitFileState') != 'enabled':
                add(prefix + '.timer')
            worker = unit_properties(unit + '.service')
            if worker.get('ActiveState') in ('activating', 'active', 'deactivating'):
                deferred_recoveries.append(prefix + '.worker_failure')
            if worker.get('Result') != 'success':
                add(prefix + '.worker_failure', WORKER_FAILURE_GRACE)
            status = json.loads(Path(backfill['status_file']).expanduser().read_text())
            stamp = dt.datetime.fromisoformat(status['checked_at'].replace('Z', '+00:00')).timestamp()
            if now - stamp > 1200:
                add(prefix + '.worker_stale')
            if status.get('outcome') == 'failed':
                add(prefix + '.worker_failure', WORKER_FAILURE_GRACE)
            if status.get('thread_states', {}).get('paused_failures', 0):
                add(prefix + '.paused')
        except Exception:
            add(prefix + '.check_failed'); check_failed = True
    try:
        for index, owner in enumerate(config.get('owners', [])):
            # Labels deliberately use a numeric slot, never names or message identities.
            prefix = f'collector_{index + 1}'
            if not isinstance(owner, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', owner):
                add(prefix + '.configuration'); check_failed = True
                continue
            root = collectors / owner
            if config.get('auto_enroll') and not ((root / 'session.json').exists() or (root / 'gmcli.db').exists()):
                try:
                    if unit_properties(f'minbox-text-collector@{owner}.service').get('UnitFileState') != 'enabled':
                        continue
                except Exception:
                    add(prefix + '.enrollment_check_failed'); check_failed = True
                    continue
            for unit, name, active in [(f'minbox-text-collector@{owner}.service', 'service', True),
                                      (f'minbox-text-import@{owner}.timer', 'import_timer', True),
                                      (f'minbox-text-import@{owner}.service', 'import_service', False)]:
                try:
                    props = unit_properties(unit)
                    if active and (props.get('ActiveState') != 'active' or props.get('UnitFileState') != 'enabled'):
                        add(prefix + '.' + name)
                    if not active:
                        if props.get('ActiveState') in ('activating', 'active', 'deactivating'):
                            deferred_recoveries.append(prefix + '.import_failure')
                        if props.get('Result') != 'success':
                            add(prefix + '.import_failure', WORKER_FAILURE_GRACE)
                except Exception:
                    add(prefix + '.' + name + '_check_failed'); check_failed = True
            try:
                session = root / 'session.json'
                if not session.is_file() or session.is_symlink() or session.stat().st_mode & 0o777 != 0o600:
                    add(prefix + '.session_permissions')
            except Exception:
                add(prefix + '.session_check_failed'); check_failed = True
            try:
                status = rpc_status(root / 'gmcli.sock')
                if status.get('auth_expired') is True:
                    add(prefix + '.authentication')
                if status.get('send_mode') != 'off':
                    add(prefix + '.send_mode')
                if status.get('connected') is not True or status.get('offline') is not False:
                    add(prefix + '.disconnected', DISCONNECT_GRACE)
            except Exception:
                add(prefix + '.rpc_unavailable', DISCONNECT_GRACE); check_failed = True
            if derived is not None:
                try:
                    latest = derived.execute('SELECT MAX(imported_at) FROM imports WHERE owner=? AND source=?',
                                             (owner, 'google-messages')).fetchone()[0]
                    stamp = dt.datetime.fromisoformat(latest.replace('Z', '+00:00')).timestamp() if latest else 0
                    if now - stamp > IMPORT_GRACE:
                        add(prefix + '.import_stale')
                except Exception:
                    add(prefix + '.import_check_failed'); check_failed = True
            try:
                with closing(read_db(root / 'gmcli.db')) as source:
                    if source.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                        add(prefix + '.source_integrity')
                    if derived is not None:
                        ids = {str(row[0]) for row in derived.execute(
                            'SELECT id FROM messages WHERE owner=? AND source=?', (owner, 'google-messages'))}
                        # Track capture observation age rather than conversation activity.
                        missing[prefix] = [hashlib.sha256(str(row[0]).encode()).hexdigest()
                                           for row in source.execute('SELECT message_id FROM messages')
                                           if str(row[0]) not in ids]
            except Exception:
                add(prefix + '.source_check_failed'); check_failed = True
    finally:
        if derived is not None:
            derived.close()
    return {'issues': issues, 'missing': missing, 'check_failed': check_failed, 'components': components,
            'deferred_recoveries': deferred_recoveries}


# Fixed operational wording only: no source messages, provider errors or contacts.
# Each entry is (problem, recovery, next action).
ISSUE_TEXT = {
    'loom.timer': ('Loom capture schedule is stopped.', 'Loom capture schedule is running again.', 'Check the Loom timer.'),
    'loom.worker_failure': ('The last Loom capture run failed.', 'Loom capture runs are succeeding again.', 'Check the Loom service logs.'),
    'loom.worker_stale': ('No Loom capture run has completed in 15 minutes.', 'A recent Loom capture run has completed.', 'Check the Loom service.'),
    'loom_capture_pending': ('Some Loom transcripts have been unavailable or pending for at least an hour.', 'The overdue Loom transcript condition has cleared.', 'Check capture status; videos may be restricted or still processing.'),
    'archive.integrity': ('The archive database failed its integrity check.', 'The archive database passes its integrity check.', 'Inspect the database before attempting repairs.'),
    'disk.low': ('The archive computer is low on free disk space.', 'Free disk space is above the alert threshold again.', 'Free space on the archive drive.'),
}
PUBLISHER_TEXT = {
    'human_required': ('Publisher authorization or privacy checks require attention.', 'Publisher authorization and privacy checks pass.', 'Inspect the private recovery report; renew authorization or restore the approved private binding.'),
    'publication_stale': ('No complete Drive publication has been verified for thirty minutes.', 'A complete Drive publication was verified.', 'Inspect the recovery report and Drive authorization on the archive computer.'),
    'timer': ('Publisher schedule is stopped.', 'Publisher schedule is running again.', 'Check the publisher timer.'),
    'worker_failure': ('The last publisher update failed.', 'Publisher updates are succeeding again.', 'Check the publisher service logs.'),
    'worker_stale': ('No publisher status check has completed in ten minutes.', 'A recent publisher status check has completed.', 'Check the publisher service.'),
    'analysis_paused': ('Publisher analysis failed or is paused.', 'Publisher analysis no longer reports a failure or pause.', 'Inspect the cause before resetting a failure hold; archive collection continues.'),
    'input_limit': ('Some sources are deferred from publisher analysis.', 'No deferred sources are currently reported.', 'Review pending analysis on the archive computer.'),
    'configuration': ('A publisher setting is invalid.', 'The publisher setting passes validation.', 'Check the health monitor configuration.'),
}
BACKFILL_TEXT = {
    'timer': ('Older-message collection schedule is stopped.', 'Older-message collection schedule is running again.', 'Check the backfill timer.'),
    'worker_failure': ('The last older-message collection run failed.', 'Older-message collection runs are succeeding again.', 'Inspect the backfill status and collector connection.'),
    'worker_stale': ('Older-message collection has not been checked in twenty minutes.', 'A recent older-message collection check completed.', 'Inspect the backfill worker.'),
    'paused': ('Some older-message collection attempts are paused after repeated failures.', 'No paused older-message attempts remain.', 'Inspect the private progress checkpoint before retrying.'),
}
COLLECTOR_TEXT = {
    'service': ('Text collection is stopped.', 'Text collection is running again.', 'Check the collector service.'),
    'import_timer': ('The archive import schedule is stopped.', 'The archive import schedule is running again.', 'Check the import timer.'),
    'import_failure': ('The last archive import failed.', 'Archive imports are succeeding again.', 'Check the import service logs.'),
    'session_permissions': ('Pairing data is missing or has unsafe file permissions.', 'Pairing data passes its file checks.', 'Check pairing setup and file permissions.'),
    'authentication': ('Google Messages pairing has expired.', 'Google Messages pairing is valid again.', 'Re-pair Google Messages with the archive computer.'),
    'send_mode': ('The collector is allowed to send messages.', 'The collector is read-only again.', 'Set collector send mode to off.'),
    'disconnected': ('The collector has been disconnected or offline for at least five minutes.', 'The collector is connected again.', 'Check the phone internet connection and collector.'),
    'rpc_unavailable': ('Minbox cannot read the collector connection status.', 'Collector connection status is available again.', 'Check the collector service.'),
    'import_stale': ('No archive import has been recorded in ten minutes.', 'A recent archive import has been recorded.', 'Check the import service.'),
    'source_integrity': ('The collector database failed its integrity check.', 'The collector database passes its integrity check.', 'Inspect the collector database before repairs.'),
    'archive_backlog': ('Captured messages have been waiting for archive import for ten minutes.', 'The observed archive import backlog has cleared.', 'Check the import service.'),
    'configuration': ('An archive account setting is invalid.', 'The archive account setting passes validation.', 'Check the health monitor configuration.'),
}


def issue_text(key, owner_labels=None):
    prefix, _, suffix = key.partition('.')
    collector = prefix.startswith('collector_')
    publisher = prefix.startswith('publisher_')
    backfill = prefix.startswith('backfill_')
    entry = (COLLECTOR_TEXT.get(suffix) if collector else
             PUBLISHER_TEXT.get(suffix) if publisher else
             BACKFILL_TEXT.get(suffix) if backfill else ISSUE_TEXT.get(key))
    if collector and suffix == 'loom_capture_pending':
        entry = ISSUE_TEXT['loom_capture_pending']
    if entry is None:
        component = ('Text collection' if collector else 'Publisher' if publisher else 'History collection' if backfill else
                     {'loom': 'Loom capture', 'archive': 'Archive',
                      'disk': 'Disk space', 'monitor': 'Health monitor'}.get(prefix, 'Archive'))
        entry = (component + ' health could not be checked.',
                 component + ' health checks are working again.',
                 'Inspect the local health monitor and service logs on the archive computer.')
    if collector:
        label = (owner_labels or {}).get(prefix, 'Account ' + prefix.removeprefix('collector_'))
        entry = (label + ': ' + entry[0], label + ': ' + entry[1], entry[2])
    if backfill:
        label = 'History collection ' + prefix.removeprefix('backfill_')
        entry = (label + ': ' + entry[0], label + ': ' + entry[1], entry[2])
    if publisher:
        label = 'Publisher ' + prefix.removeprefix('publisher_')
        entry = (label + ': ' + entry[0], label + ': ' + entry[1], entry[2])
    return entry


def track_observation(state, observation, now):
    """Track private backlog ages and local failures without a delivery policy."""
    tracked = state.setdefault('issues', {})
    seen = state.setdefault('missing', {})
    issues = dict(observation['issues'])
    for prefix, hashes in observation.get('missing', {}).items():
        previous = seen.get(prefix, {})
        seen[prefix] = {key: previous.get(key, now) for key in hashes}
        if any(now - first >= IMPORT_GRACE for first in seen[prefix].values()):
            issues[prefix + '.archive_backlog'] = 0
    for key in issues:
        tracked.setdefault(key, {'first': now})
    for key, record in list(tracked.items()):
        # Earlier monitor versions stored notification flags here. Current human
        # notices belong exclusively to the recovery controller's episode state.
        for obsolete in ('notified', 'last_sent', 'recovered'):
            record.pop(obsolete, None)
        if key not in issues:
            if not component_checked(observation, key.partition('.')[0]) or key in observation.get('deferred_recoveries', []):
                continue
            del tracked[key]
    return {'checked_at': dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(),
            'healthy': not issues, 'issues': sorted(issues),
            'check_failed': observation.get('check_failed', False)}


def send_notification(settings, body):
    subject = body.splitlines()[0][:160] + ' - Minbox Text Health'
    if settings['type'] == 'ntfy':
        url = settings['url']
        if not url.startswith('https://'):
            raise ValueError('HTTPS required')
        headers = {'Title': subject}
        if settings.get('token'):
            headers['Authorization'] = 'Bearer ' + settings['token']
        request = urllib.request.Request(url, data=body.encode(), headers=headers, method='POST')
        # Reject redirects rather than forwarding credentials to another endpoint.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
            if response.status != 200:
                raise ValueError('delivery failed')
    elif settings['type'] == 'smtp':
        message = EmailMessage()
        message['From'], message['To'] = settings['from'], settings['to']
        message['Subject'] = subject
        message.set_content(body)
        mode = settings.get('security', 'ssl')
        if mode not in ('ssl', 'starttls'):
            raise ValueError('encrypted SMTP required')
        context = ssl.create_default_context()
        smtp_class = smtplib.SMTP_SSL if mode == 'ssl' else smtplib.SMTP
        kwargs = {'context': context} if mode == 'ssl' else {}
        with smtp_class(settings['host'], settings.get('port', 465 if mode == 'ssl' else 587), timeout=20, **kwargs) as smtp:
            if mode == 'starttls':
                smtp.ehlo(); smtp.starttls(context=context); smtp.ehlo()
            if settings.get('username'):
                smtp.login(settings['username'], settings['password'])
            smtp.send_message(message)
    else:
        raise ValueError('unsupported delivery')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--test-notification', action='store_true')
    args = parser.parse_args(argv)
    root = None
    if args.check_only and args.test_notification:
        parser.error('choose one mode')
    try:
        config_path = Path(args.config).expanduser()
        if config_path.is_symlink() or config_path.stat().st_mode & 0o777 != 0o600:
            raise ValueError('private config required')
        config = json.loads(config_path.read_text())
        root = Path(config.get('state_dir', '~/.local/state/minbox-text-archive-health')).expanduser()
        root.mkdir(parents=True, mode=0o700, exist_ok=True)
        root.chmod(0o700)
        with open(root / 'monitor.lock', 'a') as lock:
            os.fchmod(lock.fileno(), 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print(json.dumps({'status': 'already_running'})); return 0
            delivery = config.get('delivery')
            if delivery and delivery.get('type') == 'none':
                delivery = None
            if args.test_notification:
                if not delivery:
                    raise ValueError('delivery missing')
                send_notification(delivery, 'Test notification\n\n- Email delivery is working.\n- No archive content is included.')
                print(json.dumps({'test_notification': 'sent'})); return 0
            path = root / 'state.json'
            state = json.loads(path.read_text()) if path.exists() else {}
            observation = observe(config, time.time())
            observation['owner_labels'] = {f'collector_{i + 1}': owner for i, owner in enumerate(config.get('owners', []))
                                           if isinstance(owner, str) and re.fullmatch(r'[A-Za-z0-9_-]+', owner)}
            now = time.time()
            report = track_observation(state, observation, now)
            from health_recovery import supervise
            recovery_observation = {**observation, 'issues': report['issues']}
            sender = (lambda body: send_notification(delivery, body)) if delivery and not args.check_only else None
            if not args.check_only:
                recovery = supervise(state, recovery_observation, config, now,
                                     properties=unit_properties, deliver=sender)
                report.update(recovery=recovery, delivery=recovery['delivery'],
                              pending_alerts=recovery['pending_alerts'], pending_recoveries=[])
            else:
                report.update(pending_alerts=[], pending_recoveries=[])
            report['delivery_configured'] = bool(delivery)
            if args.check_only:
                report['delivery'] = 'suppressed'
            if not args.check_only:
                atomic_json(path, state)
            atomic_json(root / 'health.json', report)
            print(json.dumps(report, sort_keys=True))
            return 1 if report['issues'] or report['check_failed'] or report['delivery'] == 'failed' else 0
    except Exception:
        report = {'healthy': False, 'check_failed': True, 'issues': ['monitor.check_failed']}
        if root is not None:
            try:
                atomic_json(root / 'health.json', report)
            except Exception:
                pass
        print(json.dumps(report))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

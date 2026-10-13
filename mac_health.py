"""Private, conservative macOS launchd health controller. No source/provider reads."""
import argparse
from datetime import datetime, timezone
import fcntl
import functools
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import tempfile
import time

LABEL = 'com.minbox-text-archive'
LIMIT = 2 * 1024 * 1024
RETRIES = (60, 300, 900)
HUMAN = {'auth', 'privacy', 'integrity', 'tcc'}


class Hold(ValueError):
    pass


def safe(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise Hold('integrity')
    if any((p / '.git').is_file() or (p / '.git/HEAD').is_file() for p in (path, *path.parents)):
        raise Hold('integrity')
    return path


def read(path, *, private=True):
    path = safe(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > LIMIT:
            raise Hold('integrity')
        if private and stat.S_IMODE(info.st_mode) != 0o600:
            raise Hold('privacy')
        data = os.read(fd, LIMIT + 1)
        if len(data) > LIMIT:
            raise Hold('integrity')
        return data
    finally:
        os.close(fd)


def record(path):
    value = json.loads(read(path))
    if not isinstance(value, dict):
        raise Hold('observability_unknown')
    return value


def stamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError()
        return result.timestamp()
    except (ValueError, AttributeError, TypeError):
        raise Hold('observability_unknown') from None


def launch_info(labels):
    """Unknown launchctl output is a hold, never permission to restart."""
    target = f'gui/{os.getuid()}'
    disabled = subprocess.run(['/bin/launchctl', 'print-disabled', target],
                              capture_output=True, text=True, timeout=20)
    if disabled.returncode or not re.fullmatch(r'\s*\{.*\}\s*', disabled.stdout, re.S):
        raise Hold('observability_unknown')
    result = {}
    for label in labels:
        override = re.search(r'"' + re.escape(label) + r'"\s*=>\s*(true|false)', disabled.stdout)
        job = subprocess.run(['/bin/launchctl', 'print', target + '/' + label],
                             capture_output=True, text=True, timeout=20)
        if job.returncode == 113 and 'Could not find service' in job.stderr:
            # An absent/unreadable job is intentionally never bootstrapped.
            result[label] = {'loaded': False, 'disabled': bool(override and override[1] == 'true')}
            continue
        if job.returncode:
            raise Hold('observability_unknown')
        state = re.search(r'^\s*state = ([a-z ]+)\s*$', job.stdout, re.M)
        if not state or state[1] not in ('running', 'waiting', 'not running', 'exited'):
            raise Hold('observability_unknown')
        exit_code = re.search(r'^\s*last exit code = (-?\d+)\s*$', job.stdout, re.M)
        result[label] = {'loaded': True, 'running': state[1] == 'running',
                         'disabled': bool(override and override[1] == 'true'),
                         'exit_code': int(exit_code[1]) if exit_code else None}
    return result


def kickstart(label):
    subprocess.run(['/bin/launchctl', 'kickstart', f'gui/{os.getuid()}/{label}'],
                   capture_output=True, timeout=20, check=True)


def installation(home, owner):
    support = safe(home / 'Library/Application Support/Minbox Text Archive')
    manifest = record(support / f'installation-{owner}.json')
    allowed = {f'{LABEL}.{kind}.{owner}' for kind in ('collector', 'looms', 'publisher', 'health')}
    if (manifest.get('version') != 1 or manifest.get('owner') != owner or
            not isinstance(manifest.get('files'), dict) or
            not isinstance(manifest.get('enabled'), list) or
            not set(manifest['enabled']) <= allowed):
        raise Hold('observability_unknown')
    units = {}
    for name, digest in manifest['files'].items():
        path = Path(name)
        is_app = path.parent == support / 'app' and path.suffix == '.py'
        is_unit = path.parent == home / 'Library/LaunchAgents' and path.suffix == '.plist' and path.stem in allowed
        if not (is_app or is_unit) or not isinstance(digest, str):
            raise Hold('integrity')
        raw = read(path, private=not is_unit)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise Hold('integrity')
        if is_unit and path.stem != f'{LABEL}.health.{owner}':
            unit = plistlib.loads(raw)
            if unit.get('Label') != path.stem:
                raise Hold('integrity')
            units[path.stem] = unit
    enabled = set(manifest['enabled']) - {f'{LABEL}.health.{owner}'}
    if not enabled <= units.keys():
        raise Hold('integrity')
    configs = None
    binding = manifest.get('publisher_config')
    if binding:
        if not isinstance(binding, dict) or set(binding) != {'path', 'sha256'}:
            raise Hold('integrity')
        if not isinstance(binding['path'], str) or not Path(binding['path']).is_absolute():
            raise Hold('integrity')
        path = safe(binding['path'])
        raw = read(path)
        if hashlib.sha256(raw).hexdigest() != binding['sha256']:
            raise Hold('integrity')
        configs = json.loads(raw)
        if configs.get('owner') != owner or configs.get('scope') not in ('owner_all', 'work'):
            # Legacy scoped configs use absent scope with explicit conversations.
            if configs.get('owner') != owner or configs.get('scope') is not None or not configs.get('conversations'):
                raise Hold('privacy')
    observations = {}
    for label, unit in units.items():
        kind = label.split('.')[-2]
        args = unit.get('ProgramArguments')
        expected = {'collector': 'mac_messages.py', 'looms': 'archive_cli.py',
                    'publisher': 'owner_publish_cli.py' if configs and configs.get('scope') == 'owner_all' else 'archive_publish_cli.py'}[kind]
        if (not isinstance(args, list) or len(args) < 2 or not all(isinstance(a, str) for a in args) or
                not Path(args[0]).is_absolute() or args[1] != str(support / 'app' / expected) or
                args[1] not in manifest['files'] or unit.get('WorkingDirectory') != str(support / 'app')):
            raise Hold('integrity')
        # The trusted, hashed plist pins the venv interpreter path; venv Python
        # normally links to its base executable. Metadata paths remain link-free.
        if not Path(args[0]).is_file() or not os.access(args[0], os.X_OK):
            raise Hold('integrity')
        if kind == 'collector':
            if len(args) != 14 or args[2::2] != ['--root', '--owner', '--database', '--status-file', '--max-messages', '--max-bytes'] or args[5] != owner:
                raise Hold('integrity')
            root = safe(args[3])
            if not Path(args[3]).is_absolute() or args[9] != str(support / 'collector-status.json'):
                raise Hold('integrity')
            status_path = support / 'collector-status.json'
        elif kind == 'publisher':
            if not configs or args != [args[0], args[1], '--config', str(path)]:
                raise Hold('integrity')
            status_value = configs['status_file'] if configs.get('scope') == 'owner_all' else str(Path(configs['analysis_path']).with_suffix('.last-run.json'))
            if not isinstance(status_value, str) or not Path(status_value).is_absolute():
                raise Hold('integrity')
            status_path = safe(status_value)
        else:
            if len(args) != 5 or args[2] != '--root' or args[4] != 'loom-capture' or not Path(args[3]).is_absolute():
                raise Hold('integrity')
            safe(args[3])
            status_path = None
        observations[label] = {'kind': kind, 'essential': kind == 'collector' or kind == 'publisher' and configs.get('scope') == 'owner_all',
                               'enabled': label in enabled and unit.get('Disabled') is False,
                               'status_path': status_path, 'owner': owner}
    if f'{LABEL}.collector.{owner}' not in observations:
        raise Hold('observability_unknown')
    collector_args = units[f'{LABEL}.collector.{owner}']['ProgramArguments']
    for unit in units.values():
        args = unit['ProgramArguments']
        if args[0] != collector_args[0]:
            raise Hold('integrity')
        if '--root' in args and args[args.index('--root') + 1] != collector_args[3]:
            raise Hold('privacy')
    if configs and configs.get('archive_root') != collector_args[3]:
        raise Hold('privacy')
    return support, observations


def observe(job, live, now):
    if not job['enabled'] or live.get('disabled'):
        return 'paused', False
    if not live.get('loaded'):
        return 'unloaded', False
    if job['status_path'] is None:
        return ('busy' if live.get('running') else 'optional_unknown'), False
    try:
        status = record(job['status_path'])
    except FileNotFoundError:
        return 'status_missing', not live.get('running')
    if job['kind'] == 'collector' and (status.get('owner') != job.get('owner') or status.get('source') != 'apple-messages'):
        return 'privacy', False
    checked = stamp(status.get('last_checked_at') if job['kind'] == 'collector' else status.get('checked_at', status.get('started_at')))
    if checked > now + 60:
        raise Hold('observability_unknown')
    failure = status.get('failure_kind')
    code = status.get('error_code')
    if failure in HUMAN or code in {'messages_permission_denied', 'permission_denied', 'database_permission_denied'}:
        return failure if failure in HUMAN else 'tcc', False
    if code == 'database_unavailable':
        return 'source_unavailable', not live.get('running')
    if live.get('running'):
        if job['kind'] == 'publisher' and status.get('run_state') == 'running':
            progress = stamp(status.get('heartbeat_at', status.get('started_at')))
            return ('busy' if 0 <= now - progress <= 1800 else 'running_overdue'), False
        return 'busy', False
    if job['kind'] == 'collector':
        healthy = status.get('health') != 'error' and status.get('status') in ('imported', 'checked', 'read')
    else:
        healthy = status.get('run_state') in ('succeeded', 'degraded')
    if healthy and now - checked <= 600 and live.get('exit_code') in (None, 0):
        return 'healthy', False
    return ('stale' if now - checked > 600 else 'failed'), True


def control(jobs, live, state, now, *, paused=False, action=kickstart, deliver=None, plan=False):
    episodes = state.setdefault('episodes', {})
    report = {'checked_at': datetime.fromtimestamp(now, timezone.utc).isoformat(), 'components': {}, 'delivery': 'none', 'actions': []}
    alerts = []
    for label, job in jobs.items():
        try:
            condition, recoverable = ((live[label]['hold'], False) if 'hold' in live[label] else observe(job, live[label], now))
        except (Hold, ValueError, OSError, KeyError, TypeError) as error:
            condition = str(error) if isinstance(error, Hold) and str(error) in HUMAN else 'observability_unknown'
            recoverable = False
        report['components'][label] = condition
        if condition == 'healthy':
            if label in episodes:
                episode = episodes[label]
                episode.setdefault('healthy_since', now)
                if now - episode['healthy_since'] >= 21600:
                    episodes.pop(label)
            continue
        if condition in ('paused', 'busy') or paused:
            continue
        episode = episodes.setdefault(label, {'since': now, 'attempts': 0, 'last_attempt': None, 'notified': False})
        episode.pop('healthy_since', None)
        attempts = episode['attempts']
        due = now >= (episode['since'] + RETRIES[0] if not attempts else episode['last_attempt'] + RETRIES[min(attempts, 2)])
        if recoverable and attempts < 3 and due:
            report['actions'].append({'label': label, 'action': 'kickstart', 'planned': plan})
            if not plan:
                episode.update(attempts=attempts + 1, last_attempt=now)
                try:
                    action(label)
                except Exception:
                    report['components'][label] = 'recovery_failed'
        emergency = condition in HUMAN
        emergency = emergency or job['essential'] and now - episode['since'] >= 1800 and (episode['attempts'] >= 3 or not recoverable)
        if emergency and not episode['notified']:
            alerts.append(label)
    report['pending_alerts'] = alerts
    if alerts and deliver and not plan and not paused:
        body = 'Minbox Mac health needs human action\n' + '\n'.join(label + ': ' + report['components'][label] for label in alerts)
        try:
            deliver(body)
        except Exception:
            report['delivery'] = 'failed'
        else:
            report['delivery'] = 'sent'
            for label in alerts:
                episodes[label]['notified'] = True
    report['healthy'] = all(value in ('healthy', 'paused', 'busy', 'optional_unknown') for value in report['components'].values())
    return report


def write(path, value):
    safe(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def setup_guard(function):
    """Serialize installed-state observation and actions with setup/recovery."""
    @functools.wraps(function)
    def guarded(owner, home, *args, **kwargs):
        if kwargs.get('plan', False):
            return function(owner, home, *args, **kwargs)
        support = safe(Path(home).expanduser().absolute() / 'Library/Application Support/Minbox Text Archive')
        support.mkdir(parents=True, exist_ok=True, mode=0o700)
        if support.stat().st_uid != os.getuid() or stat.S_IMODE(support.stat().st_mode) != 0o700:
            raise Hold('privacy')
        fd = os.open(safe(support / '.operation.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            mode = os.fstat(fd)
            if mode.st_uid != os.getuid() or stat.S_IMODE(mode.st_mode) != 0o600:
                raise Hold('privacy')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {'status': 'setup_in_progress', 'mutations_suppressed': True}
            return function(owner, home, *args, **kwargs)
        finally:
            os.close(fd)
    return guarded


@setup_guard
def check(owner, home, config=None, *, plan=False, info=launch_info, action=kickstart, deliver=None, clock=time.time):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', owner):
        raise Hold('integrity')
    home = safe(Path(home).expanduser().absolute())
    support = safe(home / 'Library/Application Support/Minbox Text Archive')
    directory = safe(support / 'health' / owner)
    config = safe(Path(config)) if config else support / 'config' / f'health-{owner}.json'
    settings = record(config) if config.exists() else {'version': 1, 'owner': owner}
    if settings.get('version') != 1 or settings.get('owner') != owner or type(settings.get('paused', False)) is not bool:
        raise Hold('privacy')
    paused = settings.get('paused', False) or any(support.glob('operation-journal-*.json'))
    delivery = settings.get('delivery')
    if delivery is not None and not isinstance(delivery, dict):
        raise Hold('privacy')
    if deliver is None and delivery and delivery.get('type') != 'none' and not plan:
        from health_monitor import send_notification
        if not isinstance(delivery, dict) or delivery.get('type') not in ('smtp', 'ntfy'):
            raise Hold('privacy')
        deliver = lambda body: send_notification(delivery, body)
    def run():
        state = record(directory / 'state.json') if (directory / 'state.json').exists() else {'version': 1, 'owner': owner, 'episodes': {}}
        if state.get('version') != 1 or state.get('owner') != owner or not isinstance(state.get('episodes'), dict):
            raise Hold('observability_unknown')
        for label, episode in state['episodes'].items():
            if (not isinstance(label, str) or not label.startswith(LABEL + '.') or not label.endswith('.' + owner) or
                    not isinstance(episode, dict) or type(episode.get('attempts')) is not int or not 0 <= episode['attempts'] <= 3 or
                    type(episode.get('notified')) is not bool or type(episode.get('since')) not in (int, float) or
                    (episode.get('last_attempt') is not None and type(episode['last_attempt']) not in (int, float)) or
                    (episode.get('attempts') and episode.get('last_attempt') is None) or
                    ('healthy_since' in episode and type(episode['healthy_since']) not in (int, float))):
                raise Hold('observability_unknown')
        try:
            _, jobs = installation(home, owner)
            live = info(list(jobs))
            for label in set(state['episodes']) - set(jobs):
                episode = state['episodes'][label]
                episode.setdefault('healthy_since', clock())
                if clock() - episode['healthy_since'] >= 21600:
                    del state['episodes'][label]
            report = control(jobs, live, state, clock(), paused=paused, action=action, deliver=deliver, plan=plan)
        except (Hold, ValueError, OSError, KeyError, TypeError) as error:
            # No untrusted path, exception text, account or source content enters reports.
            for episode in state['episodes'].values():
                episode.pop('healthy_since', None)
            job = {'kind': 'manifest', 'essential': True, 'enabled': True, 'status_path': None}
            label = f'{LABEL}.installation.{owner}'
            category = str(error) if isinstance(error, Hold) and str(error) in HUMAN else 'observability_unknown'
            report = control({label: job}, {label: {'hold': category}}, state, clock(), paused=paused, deliver=deliver, plan=plan)
        report['mutations_suppressed'] = bool(paused or plan)
        if not plan:
            write(directory / 'state.json', state)
            write(directory / 'report.json', report)
        return report
    if plan:
        return run()
    (support / 'health').mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.mkdir(exist_ok=True, mode=0o700)
    for path in (support / 'health', directory):
        if path.stat().st_uid != os.getuid() or stat.S_IMODE(path.stat().st_mode) != 0o700:
            raise Hold('privacy')
    lock = directory / 'lock'
    fd = os.open(safe(lock), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if os.fstat(fd).st_uid != os.getuid() or stat.S_IMODE(os.fstat(fd).st_mode) != 0o600:
            raise Hold('privacy')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'already_running'}
        return run()
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check'])
    parser.add_argument('--owner', required=True)
    parser.add_argument('--home', default=str(Path.home()))
    parser.add_argument('--config')
    parser.add_argument('--plan', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = check(args.owner, args.home, args.config, plan=args.plan)
    except Exception:
        result = {'healthy': False, 'failure_kind': 'observability_unknown', 'mutations_suppressed': True}
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get('healthy') or result.get('status') in ('already_running', 'setup_in_progress') else 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Owner-authorized, per-user macOS archive setup; plans and doctor never publish."""
import argparse
import base64
import fcntl
import functools
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from storage import _owner

VERSION = 1
LABEL = 'com.minbox-text-archive'
LAUNCHCTL = '/bin/launchctl'


_ACTIVE_LOCKS = {}


def operation_lock(function):
    @functools.wraps(function)
    def guarded(args, *values, **kwargs):
        if getattr(args, 'plan', False):
            return function(args, *values, **kwargs)
        _owner(args.owner)
        identity = str(absolute(args.home))
        if identity in _ACTIVE_LOCKS:
            if _ACTIVE_LOCKS[identity] != args.owner:
                raise ValueError('another local installation operation is active')
            return function(args, *values, **kwargs)
        require_mac()
        home = absolute(args.home)
        if home != absolute(Path.home()):
            raise ValueError('live operation must use the current user home')
        support = home / 'Library/Application Support/Minbox Text Archive'
        outside_git(support)
        outside_git(absolute(args.archive_root))
        for directory in reversed((support, *support.parents)):
            if not directory.exists():
                directory.mkdir(mode=0o700)
                sync_directory(directory.parent)
        if support.stat().st_uid != os.getuid():
            raise ValueError('runtime directory belongs to another user')
        path = support / '.operation.lock'
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            stat = os.fstat(fd)
            if stat.st_uid != os.getuid() or stat.st_mode & 0o777 != 0o600:
                raise ValueError('unsafe installation operation lock')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('another local installation operation is active') from None
            _ACTIVE_LOCKS[identity] = args.owner
            try:
                return function(args, *values, **kwargs)
            finally:
                del _ACTIVE_LOCKS[identity]
        finally:
            os.close(fd)
    return guarded


def absolute(value):
    return Path(value).expanduser().absolute()


def safe_path(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('symlink paths are not supported')


def outside_git(path):
    safe_path(path)
    if any((p / '.git').is_file() or (p / '.git/HEAD').is_file()
           for p in (path, *path.parents)):
        raise ValueError('runtime paths must be outside Git')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def private_json(path):
    safe_path(path)
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o777 != 0o600:
        raise ValueError('configuration must be user-owned mode 0600')
    return json.loads(path.read_text())


def publisher_paths(config):
    if config.get('scope') == 'owner_all':
        return ('credentials_file', 'correction_path', 'manifest_file', 'status_file')
    return ('credentials_file', 'analysis_path', 'correction_path')


def publisher_config(path, owner, archive):
    outside_git(path)
    config = private_json(path)
    if config.get('owner') != owner or absolute(config.get('archive_root', '')) != archive:
        raise ValueError('publisher owner/archive binding does not match')
    full = config.get('scope') == 'owner_all'
    if not re.fullmatch(r'[^\s@]+@[^\s@]+', config.get('google_account_email', '')):
        raise ValueError('publisher requires an explicit account')
    if not full and (not isinstance(config.get('conversations'), list) or not config['conversations'] or
            not all(isinstance(v, str) and v for v in config['conversations']) or
            not re.fullmatch(r'\d{4}-\d{2}-\d{2}', config.get('start_date', ''))):
        raise ValueError('publisher requires an explicit owner, thread/date scope and account')
    docs = config.get('documents', {})
    required = {'guide', 'corrections', 'status'} if full else {
        'guide', 'messages', 'looms', 'knowledge', 'corrections', 'status'}
    if not isinstance(docs, dict) or set(docs) != required:
        raise ValueError('publisher requires all three authorized documents' if full else
                         'publisher requires all six authorized documents')
    folders = [config.get('folder_id', '')]
    if 'corrections_folder_id' in config:
        folders.append(config['corrections_folder_id'])
    ids = [*folders, *docs.values()]
    if not all(isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9_-]{10,}', v) for v in ids):
        raise ValueError('invalid document or folder identifier shape')
    if len(set(docs.values())) != len(docs) or set(folders) & set(docs.values()):
        raise ValueError('publisher document identifiers must be distinct')
    for key in publisher_paths(config):
        if not isinstance(config.get(key), str) or not Path(config[key]).expanduser().is_absolute():
            raise ValueError('publisher runtime paths must be absolute')
        outside_git(absolute(config[key]))
    private_json(absolute(config['credentials_file']))
    return config


def options(args):
    _owner(args.owner)
    if not 1 <= args.max_messages <= 1000000 or not 1024 <= args.max_bytes <= 512 * 1024 * 1024:
        raise ValueError('invalid bounded collection limits')
    home = absolute(args.home)
    checkout = absolute(args.checkout)
    if (not (checkout / 'README.md').is_file() or
            not (checkout / 'README.md').read_text().startswith('# Minbox text archive') or
            not (checkout / 'archive_cli.py').is_file()):
        raise ValueError('checkout must be the minbox-text-archive repository')
    if not Path(args.python).is_absolute():
        raise ValueError('Python executable must be absolute')
    python = absolute(args.python)
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError('Python executable is not available')
    archive = absolute(args.archive_root)
    outside_git(archive)
    support = home / 'Library/Application Support/Minbox Text Archive'
    outside_git(support)
    if archive == checkout or checkout in archive.parents or support == checkout or checkout in support.parents:
        raise ValueError('runtime paths must be outside the source checkout')
    messages = absolute(args.messages_db or home / 'Library/Messages/chat.db')
    if args.enable_publisher and not args.publisher_config:
        raise ValueError('publisher enable requires a separately authorized configuration')
    config = publisher_config(absolute(args.publisher_config), args.owner, archive) if args.publisher_config else None
    if config is not None:
        for value in (args.publisher_config, *(config[key] for key in publisher_paths(config))):
            path = absolute(value)
            if path == checkout or checkout in path.parents:
                raise ValueError('publisher runtime paths must be outside the source checkout')
    return {'home': home, 'checkout': checkout, 'python': python, 'archive': archive,
            'support': support, 'messages': messages, 'publisher': config}


def job_enabled(args, kind):
    if kind == 'publisher':
        return args.enable_publisher
    if kind == 'health':
        return getattr(args, 'enable_monitor', False)
    return args.enable


def render(args, opts=None):
    opts = opts or options(args)
    app = opts['support'] / 'app'
    logs = opts['support'] / 'logs'
    commands = {
        'collector': [str(opts['python']), str(app / 'mac_messages.py'),
                      '--root', str(opts['archive']), '--owner', args.owner,
                      '--database', str(opts['messages']),
                      '--status-file', str(opts['support'] / 'collector-status.json'),
                      '--max-messages', str(args.max_messages), '--max-bytes', str(args.max_bytes)],
        'looms': [str(opts['python']), str(app / 'archive_cli.py'),
                  '--root', str(opts['archive']), 'loom-capture'],
    }
    if opts['publisher'] is not None:
        script = 'owner_publish_cli.py' if opts['publisher'].get('scope') == 'owner_all' else 'archive_publish_cli.py'
        commands['publisher'] = [str(opts['python']), str(app / script),
                                 '--config', str(absolute(args.publisher_config))]
    if getattr(args, 'monitor', False) or getattr(args, 'enable_monitor', False):
        commands['health'] = [str(opts['python']), str(app / 'mac_health.py'),
                              'check', '--owner', args.owner]
    # launchd does not inherit the interactive shell's executable search path.
    search_path = ':'.join(dict.fromkeys([str(opts['python'].parent),
        *[p for p in os.environ.get('PATH', '').split(':') if Path(p).is_absolute()],
        '/usr/bin', '/bin', '/usr/sbin', '/sbin']))
    units = {}
    for kind, command in commands.items():
        label = f'{LABEL}.{kind}.{args.owner}'
        enabled = job_enabled(args, kind)
        units[label] = {'Label': label, 'ProgramArguments': command,
                        'StartInterval': 300 if kind == 'looms' else 60 if kind == 'health' else 120,
                        'RunAtLoad': bool(enabled), 'Disabled': not bool(enabled),
                        'WorkingDirectory': str(app),
                        'Umask': 0o077, 'EnvironmentVariables': {'PATH': search_path},
                        'StandardOutPath': str(logs / (label + '.stdout.log')),
                        'StandardErrorPath': str(logs / (label + '.stderr.log'))}
    return units


def inspect_messages(path, python, checkout):
    # Probe with the launchd interpreter, without importing or reading source rows.
    code = ('import json, sys; sys.path.insert(0, sys.argv[1]); '
            'from mac_messages import inspect_database; '
            'r = inspect_database(sys.argv[2]); '
            'print(json.dumps({"supported": bool(r.get("supported", False)), '
            '"database_messages": r.get("database_messages", 0)}))')
    result = subprocess.run([str(python), '-c', code, str(checkout), str(path)],
                            capture_output=True, text=True, timeout=30, check=True)
    return json.loads(result.stdout)



def python_check(python, modules):
    code = 'import ' + ', '.join(modules)
    result = subprocess.run([str(python), '-c', code], capture_output=True, timeout=20)
    return result.returncode == 0


def doctor(args, opts=None):
    opts = opts or options(args)
    checks = {'macos': platform.system() == 'Darwin',
              'python_sqlite': python_check(opts['python'], ['sqlite3', 'plistlib']),
              'typedstream_available': python_check(opts['python'], ['typedstream']),
              'apple_identity': 'unknown_user_verification_required',
              'device_sync': 'unknown_user_verification_required',
              'capture_completeness': 'unverified', 'messages_readable': False,
              'publisher_configured': opts['publisher'] is not None}
    try:
        inspection = inspect_messages(opts['messages'], opts['python'], opts['checkout'])
        checks['messages_readable'] = bool(inspection.get('ready', inspection.get('supported', False)))
        checks['within_row_bound'] = inspection.get('database_messages', 0) <= args.max_messages
    except Exception:
        pass
    if opts['publisher'] is not None:
        checks['google_modules'] = python_check(opts['python'], ['google.auth', 'google.oauth2.credentials'])
        if opts['publisher'].get('scope') != 'owner_all':
            executable = opts['publisher'].get('model_executable', 'codex')
            checks['codex_binary'] = bool(shutil.which(executable))
            auth_file = opts['home'] / '.codex/auth.json'
            checks['codex_auth_present'] = (auth_file.is_file() and not auth_file.is_symlink()
                                            and auth_file.stat().st_uid == os.getuid()
                                            and auth_file.stat().st_mode & 0o777 == 0o600)
        checks['google_account_authorization'] = 'unverified_offline'
        checks['private_document_permissions'] = 'unverified_offline'
    return checks


def write(path, data, mode):
    safe_path(path)
    for directory in reversed((path.parent, *path.parent.parents)):
        if not directory.exists():
            directory.mkdir(mode=0o700)
            sync_directory(directory.parent)
    if path.parent.stat().st_uid != os.getuid():
        raise ValueError('runtime directory belongs to another user')
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def remove_file(path):
    if path.exists():
        path.unlink()
        sync_directory(path.parent)


def journal_path(opts, owner):
    return opts['support'] / ('operation-journal-' + owner + '.json')


def no_pending(opts, owner):
    safe_path(opts['support'])
    if any(opts['support'].glob('operation-journal-*.json')):
        raise ValueError('pending installation journal; run recover with the original owner/archive root first')


def launch_loaded(label):
    result = subprocess.run([LAUNCHCTL, 'print', f'gui/{os.getuid()}/{label}'],
                            capture_output=True, text=True, timeout=30)
    if result.returncode == 0:
        return True
    if result.returncode == 113 and 'Could not find service' in result.stderr:
        return False
    raise RuntimeError('launchd service inspection failed')


def file_record(path, candidate):
    original = path.read_bytes() if path.exists() else None
    if path.exists() and path.stat().st_mode & 0o777 not in (0o600, 0o644):
        raise ValueError('unsupported original installation file mode')
    if any(data is not None and len(data) > 2 * 1024 * 1024 for data in (original, candidate)):
        raise ValueError('installation file exceeds the bounded recovery size')
    return {'original': base64.b64encode(original).decode() if original is not None else None,
            'original_sha256': digest(original) if original is not None else None,
            'candidate_sha256': digest(candidate) if candidate is not None else None,
            'mode': path.stat().st_mode & 0o777 if original is not None else None,
            'candidate': base64.b64encode(candidate).decode() if candidate is not None else None}


def save_journal(opts, owner, journal):
    data = json.dumps(journal, sort_keys=True).encode()
    if len(data) > 32 * 1024 * 1024 or len(journal['files']) > 512:
        raise ValueError('installation exceeds the bounded recovery journal size')
    write(journal_path(opts, owner), data, 0o600)


def journal_inventory_binding(opts, owner, records, jobs):
    manifest_record = records.get(str(manifest_path(opts, owner)))
    if not isinstance(manifest_record, dict):
        raise ValueError('recovery journal requires both manifest inventories')
    inventories = {}
    for kind in ('original', 'candidate'):
        raw = manifest_record.get(kind)
        try:
            manifest = json.loads(base64.b64decode(raw, validate=True)) if raw is not None else {
                'owner': owner, 'version': VERSION, 'files': {}, 'enabled': []}
            if (manifest.get('owner') != owner or manifest.get('version') != VERSION or
                    not isinstance(manifest.get('files'), dict) or not isinstance(manifest.get('enabled'), list)):
                raise ValueError()
        except Exception:
            raise ValueError('invalid recovery manifest inventory') from None
        allowed_labels = {f'{LABEL}.{job_kind}.{owner}' for job_kind in ('collector', 'looms', 'publisher', 'health')}
        for filename, expected in manifest['files'].items():
            target = Path(filename)
            allowed_path = (target.parent == opts['support'] / 'app' and target.suffix == '.py' or
                            target.parent == opts['home'] / 'Library/LaunchAgents' and
                            target.stem in allowed_labels and target.suffix == '.plist')
            if not allowed_path or not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
                raise ValueError('invalid recovery manifest inventory path or hash')
            safe_path(target)
        inventories[kind] = manifest
    old, new = inventories['original']['files'], inventories['candidate']['files']
    touched = set(records) - {str(manifest_path(opts, owner))}
    if not touched <= set(old) | set(new):
        raise ValueError('recovery file is outside manifest inventories')
    changed = {filename for filename in set(old) | set(new) if old.get(filename) != new.get(filename)}
    if not changed <= touched:
        raise ValueError('recovery journal omitted a changed inventory file')
    for filename in touched:
        record = records[filename]
        for kind, inventory in (('original', old), ('candidate', new)):
            expected = inventory.get(filename)
            if record.get(kind + '_sha256') != expected:
                raise ValueError('recovery payload does not match manifest inventory')
            if (record.get(kind) is None) != (expected is None):
                raise ValueError('recovery payload presence does not match manifest inventory')
    plist_labels = {Path(filename).stem for filename in set(old) | set(new) if Path(filename).suffix == '.plist'}
    if set(jobs) != plist_labels:
        raise ValueError('recovery jobs do not match journal plist records')
    for filename in (set(old) | set(new)) - touched:
        target = Path(filename)
        if not target.is_file() or target.stat().st_uid != os.getuid() or digest(target.read_bytes()) != old.get(filename):
            raise ValueError('recovery conflict in an unchanged inventory file')
    for label in jobs:
        filename = str(opts['home'] / 'Library/LaunchAgents' / (label + '.plist'))
        record = records.get(filename)
        if not isinstance(record, dict):
            raise ValueError('recovery job omitted its owned plist record')
        if jobs[label].get('loaded') and record.get('original') is None:
            raise ValueError('recovery loaded job has no original owned plist')
        for kind in ('original', 'candidate'):
            raw = record.get(kind)
            if raw is None:
                continue
            try:
                plist = plistlib.loads(base64.b64decode(raw, validate=True))
                if plist.get('Label') != label:
                    raise ValueError()
            except Exception:
                raise ValueError('recovery plist label does not match owned job') from None
    for manifest in inventories.values():
        labels = {Path(filename).stem for filename in manifest['files'] if Path(filename).suffix == '.plist'}
        if not set(manifest['enabled']) <= labels:
            raise ValueError('recovery enabled inventory has no owned plist')


def restore_journal(opts, owner, archive, plan=False):
    path = journal_path(opts, owner)
    outside_git(path)
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('recovery journal exceeds the bounded size')
    journal = private_json(path)
    if (journal.get('version') != 1 or journal.get('owner') != owner or
            journal.get('uid') != os.getuid() or journal.get('home') != str(opts['home']) or
            journal.get('archive') != str(archive)):
        raise ValueError('recovery owner/home/archive binding does not match')
    allowed = {f'{LABEL}.{kind}.{owner}' for kind in ('collector', 'looms', 'publisher', 'health')}
    records = journal.get('files')
    jobs = journal.get('jobs')
    if not isinstance(records, dict) or len(records) > 512 or not isinstance(jobs, dict) or not set(jobs) <= allowed:
        raise ValueError('invalid recovery journal')
    decoded = {}
    for filename, record in records.items():
        target = Path(filename)
        valid = (target == manifest_path(opts, owner) or
                 target.parent == opts['support'] / 'app' and target.suffix == '.py' or
                 target.parent == opts['home'] / 'Library/LaunchAgents' and target.stem in allowed and target.suffix == '.plist')
        if not valid or not target.is_absolute():
            raise ValueError('invalid recovery path')
        safe_path(target)
        if not isinstance(record, dict):
            raise ValueError('invalid recovery file record')
        try:
            original, candidate = [base64.b64decode(record[k], validate=True)
                if record[k] is not None else None for k in ('original', 'candidate')]
        except (KeyError, TypeError, ValueError):
            raise ValueError('invalid recovery file record') from None
        for kind, data in (('original', original), ('candidate', candidate)):
            if (data is not None and len(data) > 2 * 1024 * 1024 or
                    record.get(kind + '_sha256') != (digest(data) if data is not None else None)):
                raise ValueError('recovery payload integrity check failed')
        if original is not None and record.get('mode') not in (0o600, 0o644):
            raise ValueError('invalid recovery file mode')
        current = target.read_bytes() if target.exists() else None
        if target.exists() and target.stat().st_uid != os.getuid():
            raise ValueError('recovery file belongs to another user')
        if current not in (original, candidate):
            raise ValueError('recovery conflict; a file changed outside this operation')
        decoded[target] = (original, record.get('mode'))
    for label, state in jobs.items():
        if (not isinstance(state, dict) or type(state.get('loaded')) is not bool or
                type(state.get('disabled')) is not bool):
            raise ValueError('invalid recovery job state')
    journal_inventory_binding(opts, owner, records, jobs)
    # A user can pause a job after the interrupted operation. Inspect all
    # current overrides before mutation and preserve every current pause,
    # even when the old journal would otherwise restore an enabled job.
    current_overrides = launch_overrides(jobs)
    paused = {label for label, state in jobs.items()
              if not state['disabled'] and current_overrides.get(label) is True}
    if plan:
        return {'recovery_pending': True, 'mutations': False, 'files': len(decoded),
                'jobs': len(jobs), 'preserved_pauses': len(paused)}
    # Validate every file before touching any job or file. Replaying restoration
    # is safe after a second interruption because originals are accepted too.
    for label in jobs:
        launch('bootout', opts['home'] / 'Library/LaunchAgents' / (label + '.plist'))
    for target, (data, mode) in decoded.items():
        if data is None:
            remove_file(target)
        else:
            write(target, data, mode)
    for label, state in jobs.items():
        launch('disable' if state['disabled'] or label in paused else 'enable', label)
        if state['loaded'] and not state['disabled'] and label not in paused:
            launch('bootstrap', opts['home'] / 'Library/LaunchAgents' / (label + '.plist'))
    remove_file(path)
    return {'recovered': True, 'restored_files': len(decoded), 'restored_jobs': sum(s['loaded'] and not s['disabled'] and label not in paused for label, s in jobs.items()), 'preserved_pauses': len(paused)}


@operation_lock
def recover(args):
    _owner(args.owner)
    home, archive = absolute(args.home), absolute(args.archive_root)
    opts = {'home': home, 'support': home / 'Library/Application Support/Minbox Text Archive'}
    outside_git(archive)
    outside_git(opts['support'])
    if not args.plan:
        require_mac()
        if home != absolute(Path.home()):
            raise ValueError('live recovery must use the current user home')
    return restore_journal(opts, args.owner, archive, args.plan)


def manifest_path(opts, owner):
    return opts['support'] / ('installation-' + owner + '.json')


def read_manifest(opts, owner):
    path = manifest_path(opts, owner)
    if not path.exists():
        return {'version': VERSION, 'owner': owner, 'files': {}, 'enabled': []}
    manifest = private_json(path)
    if manifest.get('version') != VERSION or manifest.get('owner') != owner:
        raise ValueError('unsupported installation manifest')
    allowed_units = {f'{LABEL}.{kind}.{owner}' for kind in ('collector', 'looms', 'publisher', 'health')}
    if not set(manifest.get('enabled', [])) <= allowed_units:
        raise ValueError('invalid tracked labels')
    for filename, expected in manifest['files'].items():
        p = Path(filename)
        allowed = (p.parent == opts['support'] / 'app' and p.suffix == '.py' or
                   p.parent == opts['home'] / 'Library/LaunchAgents' and p.stem in allowed_units and p.suffix == '.plist')
        if not allowed:
            raise ValueError('invalid tracked path')
        safe_path(p)
        if p.exists() and (p.stat().st_uid != os.getuid() or digest(p.read_bytes()) != expected):
            raise ValueError('tracked file was modified; review before updating')
    return manifest


def launch_overrides(labels):
    result = subprocess.run([LAUNCHCTL, 'print-disabled', f'gui/{os.getuid()}'],
                            capture_output=True, text=True, timeout=30, check=True)
    if not result.stdout.strip().startswith('{') or not result.stdout.strip().endswith('}'):
        raise RuntimeError('launchd override inspection failed')
    states = {}
    for label in labels:
        match = re.search(r'"' + re.escape(label) + r'"\s*=>\s*(true|false)', result.stdout)
        states[label] = match.group(1) == 'true' if match else None
    return states


def launch(action, target):
    if action in ('enable', 'disable'):
        command = [LAUNCHCTL, action, f'gui/{os.getuid()}/{target}']
    else:
        command = [LAUNCHCTL, action, f'gui/{os.getuid()}', str(target)]
    if action == 'bootout':
        # A previously installed job can be legitimately unloaded. Only the
        # exact owned service's explicit not-found result is an accepted no-op.
        probe = subprocess.run([LAUNCHCTL, 'print', f'gui/{os.getuid()}/{Path(target).stem}'],
                               capture_output=True, text=True, timeout=30)
        if probe.returncode == 113 and 'Could not find service' in probe.stderr:
            return False
        if probe.returncode != 0:
            raise RuntimeError('launchd service inspection failed')
    subprocess.run(command, capture_output=True, timeout=30, check=True)
    return True


def require_mac():
    if platform.system() != 'Darwin':
        raise ValueError('installation and uninstallation require macOS')


@operation_lock
def install(args, checks=None):
    require_mac()
    opts = options(args)
    if opts['home'] != absolute(Path.home()):
        raise ValueError('live installation must use the current user home')
    no_pending(opts, args.owner)
    legacy_support = opts['home'] / 'Library/Application Support/Family Text Archive'
    if (not manifest_path(opts, args.owner).exists() and
            (legacy_support.exists() or legacy_support.is_symlink())):
        raise ValueError('legacy Family Text Archive support exists; review its archive, settings and '
                         'LaunchAgents for migration before installing Minbox Text Archive')
    units = render(args, opts)
    old = read_manifest(opts, args.owner)
    if args.enable or args.enable_publisher or getattr(args, 'enable_monitor', False):
        checks = checks if checks is not None else doctor(args, opts)
        if args.enable and not (checks['python_sqlite'] and checks['messages_readable'] and checks.get('within_row_bound', True)):
            raise ValueError('collector requires a successful local read-only preflight')
        dependencies = ['python_sqlite', 'google_modules']
        if opts['publisher'] is not None and opts['publisher'].get('scope') != 'owner_all':
            dependencies.extend(('codex_binary', 'codex_auth_present'))
        if args.enable_publisher and not all(checks.get(k) for k in dependencies):
            raise ValueError('publisher dependencies and local authorization must be prepared first')
        if getattr(args, 'enable_monitor', False) and (not checks.get('python_sqlite') or
                not (opts['checkout'] / 'mac_health.py').is_file()):
            raise ValueError('monitor requires its authored module and a working local Python')
    desired = {}
    for source in opts['checkout'].glob('*.py'):
        if source.is_symlink():
            raise ValueError('authored application source must not be a symlink')
        desired[opts['support'] / 'app' / source.name] = (source.read_bytes(), 0o600)
    if not any(p.name == 'mac_messages.py' for p in desired):
        raise ValueError('checkout does not contain the Mac capture adapter')
    for label, plist in units.items():
        desired[opts['home'] / 'Library/LaunchAgents' / (label + '.plist')] = (plistlib.dumps(plist), 0o644)
    for path in desired:
        safe_path(path)
        if path.exists() and str(path) not in old['files']:
            raise ValueError('refusing to overwrite an untracked installation file')
    # All existing files are inspected before changing or stopping anything.
    obsolete = {Path(p) for p in old['files'] if Path(p).suffix == '.plist' and Path(p) not in desired}
    manifest = manifest_path(opts, args.owner)
    overrides = launch_overrides(set(units) | {Path(p).stem for p in obsolete})
    prior_disabled = {}
    for label, state in overrides.items():
        unit_path = opts['home'] / 'Library/LaunchAgents' / (label + '.plist')
        prior_disabled[label] = state if state is not None else (
            plistlib.loads(unit_path.read_bytes()).get('Disabled', False) if unit_path.exists() else True)
    enabled = [label for label in units if job_enabled(args, label.split('.')[-2])]
    tracked = {**{p: h for p, h in old['files'].items() if Path(p) not in obsolete},
               **{str(p): digest(data) for p, (data, _) in desired.items()}}
    configuration = ({'path': str(absolute(args.publisher_config)),
                      'sha256': digest(absolute(args.publisher_config).read_bytes())}
                     if opts['publisher'] is not None else None)
    new_manifest = json.dumps({'version': VERSION, 'owner': args.owner, 'files': tracked,
        'enabled': enabled, 'publisher_config': configuration}, sort_keys=True).encode()
    jobs = {label: {'loaded': launch_loaded(label), 'disabled': prior_disabled[label]}
            for label in overrides}
    journal = {'version': 1, 'owner': args.owner, 'uid': os.getuid(),
               'home': str(opts['home']), 'archive': str(opts['archive']),
               'jobs': jobs, 'files': {str(p): file_record(p, desired[p][0] if p in desired else None)
                                     for p in set(desired) | obsolete}}
    journal['files'][str(manifest)] = file_record(manifest, new_manifest)
    save_journal(opts, args.owner, journal)
    try:
        for label, state in jobs.items():
            if not state['loaded']:
                continue
            launch('bootout', opts['home'] / 'Library/LaunchAgents' / (label + '.plist'))
        for directory in (opts['support'], opts['support'] / 'app', opts['support'] / 'logs',
                          opts['support'] / 'config', opts['archive']):
            safe_path(directory)
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if directory.stat().st_uid != os.getuid():
                raise ValueError('runtime directory belongs to another user')
            directory.chmod(0o700)
        for path in obsolete:
            if path.exists():
                remove_file(path)
        for path, (data, mode) in desired.items():
            write(path, data, mode)
        enabled = [label for label in units if job_enabled(args, label.split('.')[-2])]
        for label in overrides:
            launch('enable' if label in enabled else 'disable', label)
        for label in enabled:
            launch('bootstrap', opts['home'] / 'Library/LaunchAgents' / (label + '.plist'))
        write(manifest, new_manifest, 0o600)
        remove_file(journal_path(opts, args.owner))
    except Exception:
        try:
            restore_journal(opts, args.owner, opts['archive'])
        except Exception:
            raise RuntimeError('installation failed; launchd rollback needs local inspection') from None
        raise RuntimeError('installation failed; previous tracked files and jobs restored') from None
    return {'installed': True, 'enabled_jobs': len(enabled), 'publisher_enabled': args.enable_publisher,
            'monitor_enabled': getattr(args, 'enable_monitor', False)}


@operation_lock
def update(args):
    """Refresh authored source using only verified, installed owner settings."""
    if not args.plan:
        require_mac()
    if getattr(args, '_runtime_options', []):
        raise ValueError('update recovers installed settings; use install to change runtime options')
    _owner(args.owner)
    home = absolute(args.home)
    if not args.plan and home != absolute(Path.home()):
        raise ValueError('live update must use the current user home')
    opts = {'home': home, 'support': home / 'Library/Application Support/Minbox Text Archive'}
    outside_git(opts['support'])
    no_pending(opts, args.owner)
    if not manifest_path(opts, args.owner).is_file():
        raise ValueError('update requires an existing owned installation manifest')
    old = read_manifest(opts, args.owner)
    if any(not Path(p).is_file() for p in old['files']):
        raise ValueError('tracked installation file is missing; review the local installation first')
    units = {}
    for kind in ('collector', 'looms', 'publisher', 'health'):
        label = f'{LABEL}.{kind}.{args.owner}'
        path = home / 'Library/LaunchAgents' / (label + '.plist')
        if str(path) in old['files']:
            units[kind] = plistlib.loads(path.read_bytes())
        elif path.exists() or kind not in ('publisher', 'health'):
            raise ValueError('update requires tracked collector/Loom and publisher plists')
    if not set(old['enabled']) <= {unit.get('Label') for unit in units.values()}:
        raise ValueError('enabled manifest label has no tracked launchd plist')
    collector = units['collector']['ProgramArguments']
    try:
        # Accept only the exact argument layout generated by this installer.
        if len(collector) != 14:
            raise ValueError('unsupported collector settings')
        args.python = collector[0]
        args.messages_db = collector[7]
        args.max_messages = int(collector[11])
        args.max_bytes = int(collector[13])
        if absolute(collector[3]) != absolute(args.archive_root) or collector[5] != args.owner:
            raise ValueError('installed owner/archive binding does not match update request')
    except (IndexError, TypeError):
        raise ValueError('unsupported installed collector settings') from None
    args.publisher_config = None
    if 'publisher' in units:
        binding = old.get('publisher_config')
        command = units['publisher']['ProgramArguments']
        if not isinstance(binding, dict) or len(command) != 4 or binding.get('path') != command[3]:
            raise ValueError('publisher configuration is untracked; review it and run install before update')
        path = absolute(binding['path'])
        if not path.is_file():
            raise ValueError('tracked publisher configuration is missing; review the local installation first')
        private_json(path)
        if digest(path.read_bytes()) != binding.get('sha256'):
            raise ValueError('publisher configuration was modified; review it and run install before update')
        args.publisher_config = str(path)
    elif old.get('publisher_config'):
        raise ValueError('tracked publisher configuration has no owned publisher plist')
    # Validate both the manifest and plist enable state before applying launchd overrides.
    effective = {}
    overrides = (launch_overrides([unit['Label'] for unit in units.values()])
                 if platform.system() == 'Darwin' else {})
    for kind, unit in units.items():
        label = f'{LABEL}.{kind}.{args.owner}'
        enabled = label in old['enabled']
        if unit.get('Label') != label or unit.get('Disabled') != (not enabled) or unit.get('RunAtLoad') != enabled:
            raise ValueError('installed launchd state does not match the owned manifest')
        disabled = overrides.get(label)
        if not enabled and disabled is False:
            raise ValueError('paused job has an external enable override; review its local launchd state before update')
        effective[kind] = enabled and disabled is not True
    if effective['collector'] != effective['looms']:
        raise ValueError('collector and Loom launchd overrides differ; review their local pause state before update')
    args.enable = effective['collector']
    args.enable_publisher = effective.get('publisher', False)
    args.monitor = 'health' in units
    args.enable_monitor = effective.get('health', False)
    recovered = options(args)
    rendered = render(args, recovered)
    for kind, unit in units.items():
        if unit['ProgramArguments'] != rendered[f'{LABEL}.{kind}.{args.owner}']['ProgramArguments']:
            raise ValueError('unsupported installed runtime settings; review the local installation first')
    sources = list(recovered['checkout'].glob('*.py'))
    if not sources or any(p.is_symlink() for p in sources):
        raise ValueError('authored application source must not be a symlink')
    required = {Path(unit['ProgramArguments'][1]).name for unit in rendered.values()}
    if not required <= {p.name for p in sources}:
        raise ValueError('new source is missing an installed job entry point')
    # Compile with the saved interpreter without writing caches or importing runtime code.
    code = ('import pathlib, sys; '
            '[compile(p.read_bytes(), str(p), "exec") for p in '
            'pathlib.Path(sys.argv[1]).glob("*.py")]')
    result = subprocess.run([str(recovered['python']), '-c', code, str(recovered['checkout'])],
                            capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError('new application source failed compilation; installed files and jobs unchanged')
    checks = doctor(args, recovered)
    if not checks.get('python_sqlite') or (recovered['publisher'] is not None and not checks.get('google_modules')):
        raise ValueError('saved Python dependencies failed read-only preflight; prepare them locally before update')
    if args.plan:
        return {'units': rendered, 'mutations': False, 'preflight': checks,
                'launchd_overrides_verified': platform.system() == 'Darwin'}
    return {**install(args, checks=checks), 'updated': True}


@operation_lock
def uninstall(args):
    require_mac()
    opts = options(args)
    if opts['home'] != absolute(Path.home()):
        raise ValueError('live uninstallation must use the current user home')
    no_pending(opts, args.owner)
    old = read_manifest(opts, args.owner)
    agents = opts['home'] / 'Library/LaunchAgents'
    removed = [filename for filename in old['files']
               if Path(filename).parent == agents and Path(filename).exists()]
    retained = {**old, 'files': {p: sha for p, sha in old['files'].items() if p not in removed}, 'enabled': []}
    manifest = manifest_path(opts, args.owner)
    if not manifest.exists():
        return {'uninstalled': True, 'removed_jobs': 0, 'archive_credentials_logs_app_preserved': True}
    labels = {Path(filename).stem for filename in removed}
    overrides = launch_overrides(labels)
    jobs = {}
    for label in labels:
        plist = plistlib.loads((agents / (label + '.plist')).read_bytes())
        jobs[label] = {'loaded': launch_loaded(label),
                       'disabled': overrides[label] if overrides[label] is not None else bool(plist.get('Disabled', False))}
    candidate = json.dumps(retained, sort_keys=True).encode()
    journal = {'version': 1, 'owner': args.owner, 'uid': os.getuid(),
               'home': str(opts['home']), 'archive': str(opts['archive']), 'jobs': jobs,
               'files': {filename: file_record(Path(filename), None) for filename in removed}}
    journal['files'][str(manifest)] = file_record(manifest, candidate)
    save_journal(opts, args.owner, journal)
    try:
        for label, state in jobs.items():
            if state['loaded']:
                launch('bootout', agents / (label + '.plist'))
            launch('disable', label)
        for filename in removed:
            remove_file(Path(filename))
        write(manifest, candidate, 0o600)
        remove_file(journal_path(opts, args.owner))
    except Exception:
        try:
            restore_journal(opts, args.owner, opts['archive'])
        except Exception:
            raise RuntimeError('installation failed; launchd rollback needs local inspection') from None
        raise RuntimeError('installation failed; previous tracked files and jobs restored') from None
    return {'uninstalled': True, 'removed_jobs': len(removed), 'archive_credentials_logs_app_preserved': True}


def parser():
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument('command', choices=('install', 'update', 'uninstall', 'doctor', 'plan', 'recover'))
    p.add_argument('--owner', required=True)
    p.add_argument('--checkout', default=str(Path(__file__).resolve().parent))
    p.add_argument('--home', default=str(Path.home()))
    p.add_argument('--archive-root', required=True)
    p.add_argument('--python', default=sys.executable)
    p.add_argument('--messages-db')
    p.add_argument('--max-messages', type=int, default=100000)
    p.add_argument('--max-bytes', type=int, default=64 * 1024 * 1024)
    p.add_argument('--publisher-config')
    p.add_argument('--enable', action='store_true', help='enable collector and Loom jobs after read-only preflight')
    p.add_argument('--enable-publisher', action='store_true', help='explicitly authorize configured publisher startup')
    p.add_argument('--monitor', action='store_true', help='include a disabled health job without enabling it')
    p.add_argument('--enable-monitor', action='store_true', help='explicitly enable local recovery-first monitoring')
    p.add_argument('--plan', action='store_true', help='render only; do not write or start jobs')
    return p


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = parser().parse_args(arguments)
    args._runtime_options = [flag for flag in arguments if flag.split('=')[0] in {
        '--python', '--messages-db', '--max-messages', '--max-bytes',
        '--publisher-config', '--enable', '--enable-publisher', '--monitor', '--enable-monitor'}]
    try:
        if args.command == 'recover':
            result = recover(args)
        elif args.command == 'update':
            result = update(args)
        elif args.command == 'plan' or args.plan:
            result = {'units': render(args), 'mutations': False}
        elif args.command == 'doctor':
            result = doctor(args)
        else:
            result = globals()[args.command](args)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        reason = 'Local operation failed; private details withheld.'
        code = 'operation_failed'
        if type(error) is ValueError:
            code, reason = 'validation_failed', str(error)
        elif type(error) is RuntimeError and str(error).startswith('installation failed;'):
            reason = str(error)
            code = 'rollback_incomplete' if 'needs local inspection' in reason else 'launch_failed_restored'
        print(json.dumps({'ok': False, 'error_code': code, 'error': reason,
            'next_action': 'Inspect doctor/check-only and the owned launchd labels; follow MAC_SETUP.md.'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())

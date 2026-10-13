"""Portable, read-only sanitized Mac setup evidence (Python 3.9+, stdlib only)."""
import argparse
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

PREFIX = 'com.minbox-text-archive'
KINDS = ('collector', 'looms', 'publisher', 'health')


def safe(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('unsafe path')
    return path


def metadata(path):
    try:
        safe(path)
        stat = path.stat()
        return {'state': 'present', 'private': stat.st_mode & 0o777 == 0o600,
                'user_owned': stat.st_uid == os.getuid()}
    except FileNotFoundError:
        return {'state': 'missing'}
    except Exception:
        return {'state': 'unavailable'}


def venv_interpreter_metadata(path):
    # A normal venv interpreter is a symlink to its base Python. Inspect only
    # its target stat; never execute it or disclose the resolved path.
    try:
        safe(path.parent)
        stat = path.stat()
        return {'state': 'present', 'executable': path.is_file() and bool(stat.st_mode & 0o111),
                'symlink': path.is_symlink()}
    except FileNotFoundError:
        return {'state': 'missing'}
    except Exception:
        return {'state': 'unavailable'}


def read_json(path):
    safe(path)
    stat = path.stat()
    if stat.st_uid != os.getuid() or stat.st_mode & 0o777 != 0o600 or stat.st_size > 2 * 1024 * 1024:
        raise ValueError('unsafe metadata file')
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('invalid metadata')
    return value


def json_state(path, expected_owner=None):
    result = metadata(path)
    if result['state'] == 'present':
        try:
            value = read_json(path)
            result['state'] = 'valid' if expected_owner is None or value.get('owner') == expected_owner else 'binding_mismatch'
        except Exception:
            result['state'] = 'invalid'
    return result


def status_metadata(path):
    result = json_state(path)
    if result['state'] != 'valid':
        return result
    try:
        value = read_json(path)
        summary = {}
        for key in ('last_checked_at', 'last_attempt_at', 'last_progress_at', 'last_success_at'):
            timestamp = value.get(key)
            if isinstance(timestamp, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})', timestamp):
                summary[key] = timestamp
        for key in ('imported', 'examined_rows', 'normalized_records', 'message_count', 'filtered_count'):
            count = value.get(key)
            if type(count) is int and 0 <= count <= 1000000000:
                summary[key] = count
        category = value.get('error_category', value.get('failure_category'))
        if category in ('authentication', 'authorization', 'privacy', 'integrity', 'transport', 'dependency', 'configuration', 'unknown'):
            summary['error_category'] = category
        result['summary'] = summary
    except Exception:
        result['state'] = 'invalid'
    return result


def installed_integrity(manifest, support, home, owner):
    files = manifest.get('files')
    if not isinstance(files, dict) or len(files) > 512:
        return {'state': 'unverified'}
    matched = changed = missing = invalid = 0
    for filename, expected in files.items():
        try:
            path = Path(filename)
            allowed = (path.parent == support / 'app' and path.suffix == '.py' or
                       path.parent == home / 'Library/LaunchAgents' and path.name in {
                           PREFIX + '.' + kind + '.' + owner + '.plist' for kind in KINDS})
            if not allowed or not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
                raise ValueError('invalid tracked metadata')
            safe(path)
            stat = path.stat()
            if stat.st_uid != os.getuid() or stat.st_size > 2 * 1024 * 1024:
                raise ValueError('unsafe tracked metadata')
            if hashlib.sha256(path.read_bytes()).hexdigest() == expected:
                matched += 1
            else:
                changed += 1
        except FileNotFoundError:
            missing += 1
        except Exception:
            invalid += 1
    return {'state': 'verified' if not (changed or missing or invalid) else 'review_required',
            'matched': matched, 'changed': changed, 'missing': missing, 'invalid': invalid}


def command_state(command):
    try:
        completed = subprocess.run(command, capture_output=True, timeout=5)
        return 'passed' if completed.returncode == 0 else 'failed'
    except subprocess.TimeoutExpired:
        return 'timeout'
    except Exception:
        return 'unavailable'


def agent_state(name):
    binary = shutil.which(name)
    if not binary:
        return {'available': False}
    # Only fixed local metadata commands; never send prompts or expose captured
    # provider output, account names, emails, tokens or executable paths.
    return {'available': True, 'version_probe': command_state([binary, '--version']),
            'authorization_probe': command_state([binary, 'login', 'status'] if name == 'codex' else [binary, 'auth', 'status'])}


def report(owner, home):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', owner):
        raise ValueError('invalid owner')
    home = Path(home).expanduser().absolute()
    support = home / 'Library/Application Support/Minbox Text Archive'
    result = {'schema_version': 1, 'owner': owner, 'macos': platform.system() == 'Darwin',
              'python_supported': sys.version_info >= (3, 9), 'mutations': False,
              'installation': json_state(support / ('installation-' + owner + '.json'), owner),
              'pending_recovery': json_state(support / ('operation-journal-' + owner + '.json'), owner),
              'legacy_support': metadata(home / 'Library/Application Support/Family Text Archive'),
              'messages_database': metadata(home / 'Library/Messages/chat.db'),
              'venv_python': venv_interpreter_metadata(support / 'venv/bin/python3'),
              'jobs': {}, 'agents': {name: agent_state(name) for name in ('codex', 'claude')},
              'apple_identity': 'user_verification_required', 'device_sync': 'user_verification_required',
              'capture_completeness': 'unverified', 'google_authorization': 'unverified_offline'}
    for kind in KINDS:
        label = PREFIX + '.' + kind + '.' + owner
        path = home / 'Library/LaunchAgents' / (label + '.plist')
        job = metadata(path)
        if job['state'] == 'present':
            try:
                safe(path)
                if path.stat().st_size > 1024 * 1024 or path.stat().st_uid != os.getuid():
                    raise ValueError('unsafe plist')
                value = plistlib.loads(path.read_bytes())
                job['state'] = 'valid' if value.get('Label') == label else 'binding_mismatch'
                job['configured_disabled'] = value.get('Disabled') is True
            except Exception:
                job['state'] = 'invalid'
        if platform.system() == 'Darwin':
            job['loaded_probe'] = command_state(['/bin/launchctl', 'print', 'gui/' + str(os.getuid()) + '/' + label])
        status_path = support / 'publisher/status.json' if kind == 'publisher' else support / (kind + '-status.json')
        job['status'] = status_metadata(status_path)
        if kind == 'publisher':
            job['status']['binding'] = 'default_path_unverified'
        result['jobs'][kind] = job
    # The publisher config's content is never copied into output. Credential
    # paths in that config are not followed; credentials/auth files stay unread.
    result['publisher_config'] = {'state': 'untracked'}
    result['installed_integrity'] = {'state': 'unverified'}
    try:
        manifest = read_json(support / ('installation-' + owner + '.json'))
        if manifest.get('owner') == owner:
            result['installed_integrity'] = installed_integrity(manifest, support, home, owner)
        binding = manifest.get('publisher_config')
        if manifest.get('owner') == owner and isinstance(binding, dict) and isinstance(binding.get('path'), str):
            config_path = Path(binding['path'])
            if config_path.is_absolute():
                result['publisher_config'] = metadata(config_path)
    except Exception:
        pass
    pending = result['pending_recovery']['state']
    if pending != 'missing':
        stage, action = 'recovery_required', 'Review recover --plan with the original owner and archive root; resolve any conflicts before recovery.'
    elif result['legacy_support']['state'] != 'missing':
        stage, action = 'legacy_review', 'Review the existing Family Text Archive installation before installing.'
    elif result['installation']['state'] == 'missing':
        stage, action = 'installation_required', 'Prepare Python dependencies and an explicit owner/archive root, then review the setup plan.'
    elif result['installation']['state'] != 'valid' or result['installed_integrity']['state'] == 'review_required' or any(result['jobs'][k]['state'] != 'valid' for k in ('collector', 'looms')):
        stage, action = 'installation_review', 'Review the owned manifest and launchd files; preserve archive and account bindings.'
    else:
        stage, action = 'local_acceptance_required', 'Verify Messages sync and Full Disk Access, then collection, private publication and reboot recovery.'
    result['stage'] = stage
    result['next_action'] = action
    return result


def bundle_write(path, result):
    path = Path(path).expanduser().absolute()
    safe(path)
    if any((p / '.git').is_file() or (p / '.git/HEAD').is_file() for p in (path, *path.parents)):
        raise ValueError('bundle must be outside Git')
    # No overwrite: a report is a new artifact, never a credential/config edit.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(result, stream, sort_keys=True)
        stream.write('\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('command', choices=('report',))
    parser.add_argument('--owner', required=True)
    parser.add_argument('--home', default=str(Path.home()))
    parser.add_argument('--bundle')
    args = parser.parse_args(argv)
    try:
        result = report(args.owner, args.home)
        if args.bundle:
            bundle_write(args.bundle, result)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({'ok': False, 'error_code': 'support_report_failed', 'error': 'Local diagnostic operation failed; private details withheld.'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())

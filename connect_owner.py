"""Authorize an owner's Drive locally, then provision locally or on a configured Linux host over SSH."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

from storage import _owner
from owner_publish_cli import private_path
from archive_io import FILE_SCOPES

MAX_ENVELOPE = 64 * 1024
REMOTE_ARCHIVE_ROOT = '@owner-archive-root'


def read_private(path):
    path = private_path(path)
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o777 != 0o600 or path.stat().st_size > MAX_ENVELOPE:
        raise ValueError('authorization files must be private and bounded')
    return json.loads(path.read_text())


def envelope(owner, config_dir):
    directory = private_path(config_dir) / _owner(owner)
    binding = read_private(directory / 'drive.json')
    if binding.get('owner') != owner:
        raise ValueError('authorization owner mismatch')
    if (binding.get('google_scopes') != FILE_SCOPES or binding.get('folder_access') != 'selected_folder' or
            binding.get('archive_root_folder_id') != binding.get('folder_id')):
        raise ValueError('Reconnect with the selected-folder permission before onboarding')
    credentials = read_private(binding['credentials_file'])
    payload = json.dumps({'binding': {k: binding[k] for k in
        ('owner', 'google_account_email', 'folder_id', 'google_scopes', 'folder_access',
         'archive_root_folder_id')}, 'credentials': credentials}).encode()
    if len(payload) > MAX_ENVELOPE:
        raise ValueError('authorization envelope exceeds bounds')
    return payload


def ssh_command(host, arguments):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', host):
        raise ValueError('SSH host must be a configured alias')
    # Remote shell syntax contains only fixed paths and individually quoted public
    # arguments. Credentials are sent through stdin, never command arguments.
    remote = ('exec "$HOME/.local/lib/minbox-text-archive/.venv/bin/python" '
              '"$HOME/.local/lib/minbox-text-archive/' + arguments[0] + '" ' +
              ' '.join('"$HOME/.local/share/minbox-text-archive"' if value == REMOTE_ARCHIVE_ROOT else shlex.quote(value) for value in arguments[1:]))
    return ['ssh', '-F', str(Path.home() / '.ssh/config'), '-o', 'BatchMode=yes',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10', host, remote]


def invoke(command, *, input_data=None, timeout=360, execute=subprocess.run):
    result = execute(command, input=input_data, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('setup command failed; authorization files remain private')
    data = json.loads(result.stdout)
    if not isinstance(data, dict):
        raise ValueError('invalid setup acknowledgement')
    return data


def connect(args, *, execute=subprocess.run, authorize=None):
    owner = _owner(args.owner)
    config_dir = private_path(args.config_dir)
    if args.host and any((args.archive_root, args.publisher_config, args.runtime_dir)):
        raise ValueError('remote setup uses the standard Linux private destination paths')
    if args.activate and not args.host:
        raise ValueError('activation through this helper requires --host for a Linux collector; use mac_setup.py on macOS')
    if args.host:
        # Fail before asking for consent if the recipient code/environment is missing.
        probe = ssh_command(args.host, ['owner_onboarding.py', 'receive', '--help'])
        result = execute(probe, capture_output=True, timeout=20)
        if result.returncode:
            raise RuntimeError('recipient setup helper is unavailable')
    if not args.reuse_authorization:
        if not args.client_file:
            raise ValueError('Desktop OAuth client file is required for sign-in')
        if authorize is None:
            from configure_google import main as authorize
        authorize([args.client_file, '--owner', owner, '--account-email', args.account_email,
                   '--config-dir', str(config_dir)])
    local_binding = read_private(config_dir / owner / 'drive.json')
    if local_binding.get('google_account_email', '').lower() != args.account_email.lower():
        raise ValueError('connected account differs from requested account')
    if (local_binding.get('google_scopes') != FILE_SCOPES or
            local_binding.get('folder_access') != 'selected_folder'):
        raise ValueError('Reconnect with the selected-folder permission before onboarding')
    if args.host:
        invoke(ssh_command(args.host, ['owner_onboarding.py', 'receive', '--owner', owner]),
               input_data=envelope(owner, config_dir), execute=execute)
        provision_args = ['owner_onboarding.py', 'provision', '--owner', owner,
                          '--archive-root', REMOTE_ARCHIVE_ROOT]
        if args.publish_now and not args.activate:
            provision_args.append('--publish-now')
        result = invoke(ssh_command(args.host, provision_args), execute=execute)
        if args.activate:
            result['activation'] = invoke(ssh_command(args.host, ['activate_owner.py', '--owner', owner]), execute=execute)
    else:
        from owner_onboarding import provision
        root = args.archive_root or str(Path.home() / '.local/share/minbox-text-archive')
        result = provision(owner, config_dir / owner / 'drive.json', root,
                           args.publisher_config or Path.home() / '.config/minbox-text-archive/publishers' / (owner + '-full.json'),
                           args.runtime_dir or Path.home() / '.local/share/minbox-text-archive/publishers' / (owner + '-full'))
        if args.publish_now:
            from contextlib import redirect_stdout
            import io
            from owner_publish_cli import main
            with redirect_stdout(io.StringIO()) as captured:
                main(['--config', result['publisher_config']])
            result['publication'] = json.loads(captured.getvalue())
    return result


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--owner', required=True, type=_owner)
    p.add_argument('--account-email', required=True)
    p.add_argument('--client-file', help='Private Desktop OAuth client JSON')
    p.add_argument('--host', help='Existing SSH alias; omit for local provisioning')
    p.add_argument('--config-dir', default=str(Path.home() / '.config/minbox-text-archive/owners'))
    p.add_argument('--archive-root')
    p.add_argument('--publisher-config')
    p.add_argument('--runtime-dir')
    p.add_argument('--reuse-authorization', action='store_true', help='Reuse an already connected private owner account')
    p.add_argument('--publish-now', action='store_true', help='Explicitly publish all currently captured filtered owner records once')
    p.add_argument('--activate', action='store_true', help='On the Linux collector host, verify paired collection and publication, then enable owner timers')
    return p


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        if not re.fullmatch(r'[^\s@]+@[^\s@]+', args.account_email):
            raise ValueError('invalid account email')
        result = connect(args)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({'ok': False, 'error_code':'owner_setup_failed',
                         'next_action':'Check the private owner binding, SSH access and Google consent result; see ONBOARDING.md.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

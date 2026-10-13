"""Verify a paired Android owner before enabling that owner's Linux archive jobs."""
import argparse
from contextlib import redirect_stdout
import io
import fcntl
import json
import os
from pathlib import Path
import platform
import subprocess
import time
from datetime import datetime, timezone

from storage import Archive, _owner
from owner_publish_cli import private_path, write_json, OwnerDocs
from health_monitor import rpc_status
from archive_cli import import_gmkit


def read_private(path):
    path = private_path(path)
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o777 != 0o600:
        raise ValueError('private configuration required')
    return json.loads(path.read_text())


def command(arguments):
    return subprocess.run(['systemctl', '--user', *arguments], capture_output=True, timeout=30, check=True)


def enroll(health_path, owner, publisher_entry, backfill_entry):
    lock_path = private_path(health_path).with_suffix('.enrollment.lock')
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Collection/consent can take time. Merge into current settings, never a
        # pre-publication snapshot that could erase another account or pause.
        health = read_private(health_path)
        publishers, backfills = list(health.get('publishers', [])), list(health.get('backfills', []))
        for previous in publishers:
            if previous.get('name') == owner and previous.get('kind', 'work') == 'owner_all' and previous != publisher_entry:
                raise ValueError('existing publisher monitoring binding differs')
        for previous in backfills:
            if previous.get('owner') == owner and previous != backfill_entry:
                raise ValueError('existing backfill monitoring binding differs')
        if publisher_entry not in publishers:
            publishers.append(publisher_entry)
        if backfill_entry not in backfills:
            backfills.append(backfill_entry)
        health['publishers'], health['backfills'] = publishers, backfills
        owners = list(health.get('owners', []))
        if owner not in owners:
            owners.append(owner)
        health['owners'] = owners
        write_json(health_path, health)


def activate(owner, *, home=None, run=command, status=rpc_status, validate=OwnerDocs,
             publish=None, importer=import_gmkit, history_check=None, clock=time.monotonic, sleep=time.sleep):
    if platform.system() != 'Linux':
        raise ValueError('use mac_setup.py on macOS')
    owner = _owner(owner)
    home = Path(home or Path.home())
    config_path = home / '.config/minbox-text-archive/publishers' / (owner + '-full.json')
    config = read_private(config_path)
    if private_path(config['archive_root']) != private_path(home / '.local/share/minbox-text-archive'):
        raise ValueError('Linux scheduled imports require the standard archive root')
    if config.get('owner') != owner or config.get('scope') != 'owner_all':
        raise ValueError('publisher owner/scope mismatch')
    health_path = home / '.config/minbox-text-archive/health.json'
    health = read_private(health_path)
    # Enrollment never enables globally paused monitoring or changes delivery.
    publishers = list(health.get('publishers', []))
    backfills = list(health.get('backfills', []))
    publisher_entry = {'name':owner, 'kind':'owner_all', 'status_file':config['status_file']}
    backfill_entry = {'owner':owner, 'status_file':str(home / '.local/state/minbox-text-archive-backfill' / (owner + '.last-run.json'))}
    for previous in publishers:
        if previous.get('name') == owner and previous.get('kind', 'work') == 'owner_all' and previous != publisher_entry:
            raise ValueError('existing publisher monitoring binding differs')
    for previous in backfills:
        if previous.get('owner') == owner and previous != backfill_entry:
            raise ValueError('existing backfill monitoring binding differs')
    store = home / '.local/state/minbox-text-archive-collectors' / owner
    read_private(store / 'session.json')
    for unit in ('minbox-text-collector@.service', 'minbox-text-import@.timer',
                 'minbox-text-backfill@.timer', 'minbox-owner-archive@.timer'):
        if not (home / '.config/systemd/user' / unit).is_file():
            raise ValueError('owner service templates are not installed')
    validate(config)  # Private account/folder/doc checks precede unit mutations.
    run(['enable', '--now', 'minbox-text-collector@' + owner + '.service',
         'minbox-text-import@' + owner + '.timer'])
    deadline = clock() + 30
    while True:
        try:
            connection = status(store / 'gmcli.sock')
            ready = (connection.get('connected') is True and connection.get('auth_expired') is False and
                     connection.get('offline') is False and connection.get('send_mode') == 'off')
        except Exception:
            ready = False
        if ready:
            break
        if clock() >= deadline:
            raise RuntimeError('collection is still connecting; rerun after reviewing pairing')
        sleep(.5)
    importer(Archive(Path(config['archive_root'])), owner, store / 'gmcli.db')
    if publish is None:
        from owner_publish_cli import main as publish
    with redirect_stdout(io.StringIO()) as captured:
        code = publish(['--config', str(config_path)])
    if code not in (None, 0):
        raise RuntimeError('first publication failed')
    publication = json.loads(captured.getvalue())
    history_status = Path(backfill_entry['status_file'])
    if not history_status.exists():
        if history_check is None:
            from history_backfill import collect as history_check
        checked = history_check(owner, store, history_status.parent / (owner + '.json'), check_only=True)
        write_json(history_status, {'checked_at': datetime.now(timezone.utc).isoformat(), **checked})
    run(['enable', '--now', 'minbox-owner-archive@' + owner + '.timer',
         'minbox-text-backfill@' + owner + '.timer'])
    enroll(health_path, owner, publisher_entry, backfill_entry)
    return {'owner':owner, 'activated':True, 'collection_connected':True, 'send_mode':'off',
            'publication':{k:publication[k] for k in ('published_messages','excluded_messages','model_calls')},
            'global_monitor_state_preserved':True}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--owner', required=True, type=_owner)
    args = p.parse_args(argv)
    try:
        print(json.dumps(activate(args.owner), sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({'ok':False,'error_code':'owner_activation_failed',
            'next_action':'Check paired collector connection and private owner settings, then rerun. Capture may still be connecting; no success is claimed.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

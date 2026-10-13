"""Inventory and migrate an existing owner's registered Drive destinations.

Consent, revocation and schedule control belong to the interactive coordinator.
This helper never discovers unregistered Drive files or prints credential/source
content. The narrow GoogleAuth path must verify an unscoped refresh response.
"""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from archive_io import GoogleAuth, _http_request
from owner_onboarding import onboarding_lock, _id
from publisher_status import private_path, write_json
from storage import _owner


FILE_SCOPES = ['https://www.googleapis.com/auth/drive.file']
FOLDER = 'application/vnd.google-apps.folder'
DOCUMENT = 'application/vnd.google-apps.document'
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_ITEMS = 5000
MAX_PUBLISHERS = 100
PUBLICATION_TIMEOUT = 900
FIELDS = 'id,name,mimeType,parents,shared,trashed,owners(emailAddress),capabilities(canEdit),isAppAuthorized'


class MigrationError(RuntimeError):
    def __init__(self, code='drive_migration_failed', *, staged_grant_retained=False):
        super().__init__('Drive migration failed; private details withheld')
        self.error_code = code
        self.staged_grant_retained = staged_grant_retained


def _config_dir(value):
    return private_path(value or Path.home() / '.config/minbox-text-archive')


def _read(path, *, missing=False):
    path = private_path(path)
    if missing and not path.exists():
        return None
    stat = path.stat()
    if not path.is_file() or stat.st_uid != os.getuid() or stat.st_mode & 0o777 != 0o600:
        raise MigrationError('migration_private_file_required')
    with path.open('rb') as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise MigrationError('migration_file_too_large')
    return raw


def _json(path, *, missing=False):
    raw = _read(path, missing=missing)
    if raw is None:
        return None, None
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise MigrationError('migration_invalid_configuration')
    return value, raw


def _client_fingerprint(credentials):
    if (not isinstance(credentials, dict) or credentials.get('type') != 'authorized_user' or
            any(not isinstance(credentials.get(key), str) or not credentials[key]
                for key in ('client_id', 'client_secret', 'refresh_token')) or
            credentials.get('token_uri', 'https://oauth2.googleapis.com/token') !=
            'https://oauth2.googleapis.com/token'):
        raise MigrationError('migration_invalid_credential')
    encoded = json.dumps({key: credentials[key] for key in ('client_id', 'client_secret')},
                         sort_keys=True, separators=(',', ':')).encode()
    return sha256(encoded).hexdigest()


def _snapshot(owner, directory):
    """Read only publisher registrations; no API/file enumeration is performed."""
    publishers = []
    paths = sorted(private_path(directory / 'publishers').glob('*.json'))
    if len(paths) > MAX_PUBLISHERS:
        raise MigrationError('migration_too_many_publishers')
    originals, digests = {}, {}
    for path in paths:
        config, raw = _json(path)
        if config.get('owner') != owner:
            continue
        if (not isinstance(config.get('documents'), dict) or not config['documents'] or
                not isinstance(config.get('google_scopes'), list) or
                not config['google_scopes'] or
                any(not isinstance(scope, str) for scope in config['google_scopes'])):
            raise MigrationError('migration_invalid_configuration')
        kind = 'full' if config.get('scope') == 'owner_all' else 'work'
        publishers.append({'path': str(path), 'kind': kind, 'config': config})
        originals[str(path)] = raw
        digests[str(path)] = sha256(raw).hexdigest()
    full = [entry for entry in publishers if entry['kind'] == 'full']
    if len(full) != 1:
        raise MigrationError('migration_requires_one_full_publisher')
    root = _id(full[0]['config']['folder_id'])
    account = full[0]['config'].get('google_account_email')
    if not isinstance(account, str) or '@' not in account:
        raise MigrationError('migration_invalid_account')
    credential_path = private_path(full[0]['config']['credentials_file'])
    credential, raw = _json(credential_path)
    fingerprint = _client_fingerprint(credential)
    originals[str(credential_path)] = raw
    digests[str(credential_path)] = sha256(raw).hexdigest()
    entries, manifests = {}, {}

    def register(identity, mime, parent=None):
        identity = _id(identity)
        item = {'id': identity, 'mime_type': mime, 'parent': parent}
        previous = entries.get(identity)
        if previous is not None and previous != item:
            if mime == FOLDER and previous['mime_type'] == FOLDER:
                if parent is None:
                    return
                if previous['parent'] is not None:
                    raise MigrationError('migration_conflicting_destination')
            else:
                raise MigrationError('migration_conflicting_destination')
        entries[identity] = item

    register(root, FOLDER)
    for entry in publishers:
        config = entry['config']
        if (config.get('google_account_email', '').casefold() != account.casefold() or
                private_path(config['credentials_file']) != credential_path or
                config.get('archive_root_folder_id', root) != root):
            raise MigrationError('migration_publisher_binding_differs')
        folder = _id(config['folder_id'])
        correction_folder = _id(config.get('corrections_folder_id', folder))
        register(folder, FOLDER)
        register(correction_folder, FOLDER)
        managed_parents = config.get('managed_folder_parents', {})
        if not isinstance(managed_parents, dict):
            raise MigrationError('migration_invalid_configuration')
        for child, parent in managed_parents.items():
            register(child, FOLDER, _id(parent))
            register(parent, FOLDER)
            if child == root:
                raise MigrationError('migration_folder_outside_root')
        for kind, identity in config['documents'].items():
            register(identity, DOCUMENT, correction_folder if kind == 'corrections' else folder)
        manifest_path = config.get('manifest_file')
        if manifest_path:
            manifest_path = private_path(manifest_path)
            manifest, manifest_raw = _json(manifest_path, missing=True)
            digests[str(manifest_path)] = sha256(manifest_raw).hexdigest() if manifest_raw is not None else None
            if manifest is not None:
                if (manifest.get('owner') != owner or manifest.get('folder_id') != folder or
                        not isinstance(manifest.get('chunks'), dict)):
                    raise MigrationError('migration_manifest_binding_differs')
                for identity in manifest['chunks'].values():
                    register(identity, DOCUMENT, folder)
            manifests[str(manifest_path)] = manifest
    # A guide link must already identify a registered output; it cannot broaden
    # this inventory to an unrelated arbitrary Drive file.
    for entry in publishers:
        guide = entry['config'].get('work_guide_id')
        if guide is not None and (_id(guide) not in entries or entries[guide]['mime_type'] != DOCUMENT):
            raise MigrationError('migration_unregistered_guide')
    if len(entries) > MAX_ITEMS:
        raise MigrationError('migration_too_many_destinations')
    drive_path = directory / 'owners' / owner / 'drive.json'
    drive, raw = _json(drive_path, missing=True)
    if drive is not None and (drive.get('owner') != owner or drive.get('folder_id') != root or
            drive.get('google_account_email', '').casefold() != account.casefold() or
            private_path(drive['credentials_file']) != credential_path):
        raise MigrationError('migration_owner_binding_differs')
    originals[str(drive_path)] = raw
    digests[str(drive_path)] = sha256(raw).hexdigest() if raw is not None else None
    return dict(owner=owner, account=account, root=root, credential_path=credential_path,
                fingerprint=fingerprint, credential=credential, publishers=publishers,
                entries=entries, manifests=manifests, drive_path=drive_path, drive=drive,
                originals=originals, digests=digests)


def _call(request, token, suffix):
    return request('GET', 'https://www.googleapis.com/drive/v3/' + suffix, None,
                   {'Authorization': 'Bearer ' + token(), 'Content-Type': 'application/json'}, 20)


def _metadata(snapshot, request, token, baseline=None):
    account = _call(request, token, 'about?fields=user(emailAddress)')['user']['emailAddress']
    if account.casefold() != snapshot['account'].casefold():
        raise MigrationError('migration_account_differs')
    result = {}
    for identity, expected in sorted(snapshot['entries'].items()):
        item = _call(request, token, 'files/' + _id(identity) + '?fields=' + FIELDS)
        parents = item.get('parents', [])
        if (item.get('id') != identity or item.get('mimeType') != expected['mime_type'] or
                item.get('shared') or item.get('trashed') or
                not item.get('capabilities', {}).get('canEdit') or
                not any(owner.get('emailAddress', '').casefold() == account.casefold()
                        for owner in item.get('owners', []) if isinstance(owner, dict)) or
                not isinstance(parents, list) or any(_id(parent) != parent for parent in parents) or
                (expected['parent'] is not None and parents != [expected['parent']])):
            raise MigrationError('migration_destination_binding_differs')
        if baseline is not None and identity in baseline and identity != snapshot['root'] and (
                parents != baseline[identity]['parents']):
            raise MigrationError('migration_destination_changed')
        result[identity] = dict(id=identity, mime_type=expected['mime_type'], name=item.get('name'),
                                parents=parents, is_app_authorized=item.get('isAppAuthorized') is True)
    folders = {identity for identity, item in result.items() if item['mime_type'] == FOLDER}
    for identity in folders - {snapshot['root']}:
        seen, current = set(), identity
        while current != snapshot['root']:
            if current in seen or current not in folders or len(result[current]['parents']) != 1:
                raise MigrationError('migration_folder_outside_root')
            seen.add(current)
            current = result[current]['parents'][0]
    return result


def gather_inventory(owner, config_dir=None, *, request=None, token_provider=None):
    """Return registered destination metadata and hashes, never credentials/content."""
    owner, directory = _owner(owner), _config_dir(config_dir)
    with onboarding_lock(directory / 'owners' / owner):
        snapshot = _snapshot(owner, directory)
        auth = GoogleAuth(snapshot['credential_path'], scopes=snapshot['publishers'][0]['config']['google_scopes'])
        entries = _metadata(snapshot, request or _http_request, token_provider or auth.token)
        return dict(schema_version=1, owner=owner, google_account_email=snapshot['account'],
                    archive_root_folder_id=snapshot['root'], credentials_file=str(snapshot['credential_path']),
                    credential_client_fingerprint=snapshot['fingerprint'], config_digests=snapshot['digests'],
                    publishers=[{key: entry[key] for key in ('path', 'kind')} for entry in snapshot['publishers']],
                    entries=list(entries.values()),
                    picker_file_ids=[identity for identity, item in entries.items() if not item['is_app_authorized']])


def _check_inventory(snapshot, inventory):
    if (not isinstance(inventory, dict) or inventory.get('schema_version') != 1 or
            inventory.get('owner') != snapshot['owner'] or
            inventory.get('google_account_email', '').casefold() != snapshot['account'].casefold() or
            inventory.get('archive_root_folder_id') != snapshot['root'] or
            inventory.get('credentials_file') != str(snapshot['credential_path']) or
            inventory.get('credential_client_fingerprint') != snapshot['fingerprint'] or
            inventory.get('config_digests') != snapshot['digests'] or
            inventory.get('publishers') != [{key: entry[key] for key in ('path', 'kind')}
                                           for entry in snapshot['publishers']]):
        raise MigrationError('migration_inventory_changed')
    items = inventory.get('entries')
    if not isinstance(items, list) or len(items) != len(snapshot['entries']):
        raise MigrationError('migration_inventory_changed')
    baseline = {}
    for item in items:
        if (not isinstance(item, dict) or item.get('id') not in snapshot['entries'] or
                item['id'] in baseline or item.get('mime_type') != snapshot['entries'][item['id']]['mime_type'] or
                not isinstance(item.get('parents'), list) or not isinstance(item.get('name'), str)):
            raise MigrationError('migration_inventory_changed')
        expected = snapshot['entries'][item['id']]['parent']
        if expected is not None and item['parents'] != [expected]:
            raise MigrationError('migration_inventory_changed')
        baseline[item['id']] = item
    return baseline


def _publish(kind, config_path):
    script = 'owner_publish_cli.py' if kind == 'full' else 'archive_publish_cli.py'
    result = subprocess.run([sys.executable, str(Path(__file__).with_name(script)), '--config', str(config_path)],
                            capture_output=True, timeout=PUBLICATION_TIMEOUT)
    if result.returncode or len(result.stdout) > MAX_FILE_BYTES:
        raise MigrationError('migration_publication_failed')
    return json.loads(result.stdout)


def _publication_checked(kind, result):
    fields = ('writes', 'model_calls', 'published_messages', 'excluded_messages') if kind == 'full' else (
        'writes', 'model_calls', 'work_messages', 'work_looms')
    if (not isinstance(result, dict) or result.get('status') == 'already_running' or
            result.get('ok') is False or
            kind == 'full' and (result.get('analysis_failed_or_paused') or result.get('deferred_sources')) or
            any(type(result.get(field)) is not int or result[field] < 0 for field in fields)):
        raise MigrationError('migration_publication_failed')


def _write_bytes(path, raw):
    path = private_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _cutover(stage, snapshot, values):
    """Back up validated bytes, then replace files; restore our writes on errors."""
    rollback = stage / 'rollback'
    rollback.mkdir(mode=0o700)
    journal, replacements = [], {}
    for index, (path, value) in enumerate(values.items()):
        raw = snapshot['originals'][path]
        replacements[path] = json.dumps(value, sort_keys=True).encode()
        backup = rollback / (str(index) + '.json')
        if raw is not None:
            _write_bytes(backup, raw)
            if _read(backup) != raw:
                raise MigrationError('migration_rollback_verification_failed')
        journal.append(dict(path=path, backup=str(backup) if raw is not None else None,
                            original_digest=sha256(raw).hexdigest() if raw is not None else None,
                            replacement_digest=sha256(replacements[path]).hexdigest()))
    write_json(stage / 'journal.json', dict(state='prepared', files=journal,
               old_grant_validity='not_established'))
    attempted = []
    try:
        for item in journal:
            path = item['path']
            current = _read(path, missing=True)
            digest = sha256(current).hexdigest() if current is not None else None
            if digest != item['original_digest']:
                raise MigrationError('migration_inventory_changed')
            attempted.append(path)
            write_json(path, values[path])
        write_json(stage / 'journal.json', dict(state='complete', files=journal,
                   old_grant_validity='not_established'))
    except Exception:
        failed = False
        for path in reversed(attempted):
            try:
                raw = snapshot['originals'][path]
                current = _read(path, missing=True)
                if current == raw:
                    continue
                if current != replacements[path]:
                    # Another writer changed this path after our replacement.
                    # Preserve that change and report incomplete rollback.
                    failed = True
                    continue
                if raw is None:
                    private_path(path).unlink(missing_ok=True)
                else:
                    _write_bytes(path, raw)
                if _read(path, missing=True) != raw:
                    failed = True
            except Exception:
                failed = True
        write_json(stage / 'journal.json', dict(state='rollback_incomplete' if failed else 'rolled_back',
                   files=journal, old_grant_validity='not_established'))
        raise MigrationError('migration_rollback_incomplete' if failed else 'migration_cutover_failed',
                             staged_grant_retained=True) from None


def apply_migration(owner, credential_envelope, inventory, config_dir=None, *,
                    request=None, token_provider=None, publish=None):
    """Verify a staged narrow grant and both publishers before active-file cutover.

    A trusted test token_provider receives the staged private credential path.
    publish(kind, staged_config_path) must return the existing CLI's safe counts.
    Failed attempts retain their private staged credential for consent-free retry.
    """
    owner, directory = _owner(owner), _config_dir(config_dir)
    retained = False
    try:
        with onboarding_lock(directory / 'owners' / owner):
            snapshot = _snapshot(owner, directory)
            baseline = _check_inventory(snapshot, inventory)
            if not isinstance(credential_envelope, dict) or set(credential_envelope) != {'binding', 'credentials'}:
                raise MigrationError('migration_invalid_envelope')
            binding, credential = credential_envelope['binding'], credential_envelope['credentials']
            if (not isinstance(binding, dict) or binding.get('owner') != owner or
                    binding.get('google_account_email', '').casefold() != snapshot['account'].casefold() or
                    binding.get('folder_id') != snapshot['root'] or
                    binding.get('archive_root_folder_id') != snapshot['root'] or
                    binding.get('folder_access') != 'selected_folder' or binding.get('google_scopes') != FILE_SCOPES or
                    _client_fingerprint(credential) != snapshot['fingerprint']):
                raise MigrationError('migration_new_binding_differs')
            stage = Path(tempfile.mkdtemp(prefix='.migration-', dir=directory / 'owners' / owner))
            stage.chmod(0o700)
            staged_credential = stage / 'grant.json'
            value = {key: credential[key] for key in ('type', 'refresh_token', 'client_id', 'client_secret')}
            value['token_uri'] = 'https://oauth2.googleapis.com/token'
            write_json(staged_credential, value)
            retained = True
            write_json(stage / 'inventory.json', inventory)
            auth = GoogleAuth(staged_credential, scopes=FILE_SCOPES)
            token = (lambda: token_provider(staged_credential)) if token_provider else auth.token
            request = request or _http_request
            _metadata(snapshot, request, token, baseline)
            values = {}
            # Full publication precedes the optional work view. Both use the
            # existing runtime paths and unchanged document identities/guards.
            for index, entry in enumerate(sorted(snapshot['publishers'], key=lambda entry: entry['kind'])):
                migrated = deepcopy(entry['config'])
                migrated.update(google_scopes=FILE_SCOPES, folder_access='selected_folder',
                                archive_root_folder_id=snapshot['root'])
                staged_config = dict(migrated, credentials_file=str(staged_credential))
                config_path = stage / ('publisher-' + str(index) + '.json')
                write_json(config_path, staged_config)
                _publication_checked(entry['kind'], (publish or _publish)(entry['kind'], config_path))
                values[entry['path']] = migrated
            latest = _snapshot(owner, directory)
            # Staged publication may append chunks, but cannot alter registered
            # bindings, an existing chunk identity, or active authorization.
            if set(latest['digests']) != set(snapshot['digests']):
                raise MigrationError('migration_inventory_changed')
            for path, digest in snapshot['digests'].items():
                if path not in snapshot['manifests'] and latest['digests'].get(path) != digest:
                    raise MigrationError('migration_inventory_changed')
            for path, old in snapshot['manifests'].items():
                current = latest['manifests'].get(path)
                if old is not None and (current is None or
                        any(current.get('chunks', {}).get(key) != identity for key, identity in old['chunks'].items())):
                    raise MigrationError('migration_manifest_binding_differs')
            _metadata(latest, request, token, baseline)
            drive = deepcopy(snapshot['drive']) if snapshot['drive'] is not None else dict(
                owner=owner, google_account_email=snapshot['account'], folder_id=snapshot['root'],
                credentials_file=str(snapshot['credential_path']))
            drive.update(google_scopes=FILE_SCOPES, folder_access='selected_folder',
                         archive_root_folder_id=snapshot['root'])
            values[str(snapshot['drive_path'])] = drive
            values[str(snapshot['credential_path'])] = value
            _cutover(stage, snapshot, values)
            return dict(ok=True, publishers=len(latest['publishers']),
                        folders=sum(item['mime_type'] == FOLDER for item in latest['entries'].values()),
                        documents=sum(item['mime_type'] == DOCUMENT for item in latest['entries'].values()))
    except MigrationError as error:
        error.staged_grant_retained = error.staged_grant_retained or retained
        raise
    except Exception:
        raise MigrationError(staged_grant_retained=retained) from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('inventory', 'apply'))
    parser.add_argument('--owner', required=True, type=_owner)
    parser.add_argument('--config-dir', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'inventory':
            result = gather_inventory(args.owner, args.config_dir)
        else:
            raw = sys.stdin.buffer.read(MAX_FILE_BYTES + 1)
            if len(raw) > MAX_FILE_BYTES:
                raise MigrationError('migration_envelope_too_large')
            envelope = json.loads(raw)
            if not isinstance(envelope, dict) or set(envelope) != {'inventory', 'credential_envelope'}:
                raise MigrationError('migration_invalid_envelope')
            result = apply_migration(args.owner, envelope['credential_envelope'], envelope['inventory'], args.config_dir)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        print(json.dumps(dict(ok=False, error_code=error.error_code if isinstance(error, MigrationError)
                              else 'drive_migration_failed',
                              staged_grant_retained=getattr(error, 'staged_grant_retained', False)), sort_keys=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

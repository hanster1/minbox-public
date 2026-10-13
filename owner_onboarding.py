"""Receive owner credentials privately and provision an idle owner-wide publisher."""
import argparse
from contextlib import redirect_stdout, contextmanager
from hashlib import sha256
import io
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlencode

from archive_drive import DocsClient
from archive_io import GoogleAuth, _http_request, DRIVE_SCOPES, FILE_SCOPES
from folder_policy import verify_selected_folders
from owner_publish_cli import OwnerDocs, private_path, write_json
from storage import Archive, _owner

MAX_ENVELOPE_BYTES = 64 * 1024
FOLDER = 'application/vnd.google-apps.folder'
DOCUMENT = 'application/vnd.google-apps.document'


def _path(value):
    path = private_path(value)
    if path.exists() and (not path.is_file() or path.stat().st_mode & 0o777 != 0o600):
        raise ValueError('configuration must be a private regular file')
    return path


def _load(path):
    return json.loads(path.read_text()) if path.exists() else None


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError('invalid Drive identity')
    return value


class Binding:
    def __init__(self, config, request=None, token_provider=None):
        self.config = config
        self.request = request or _http_request
        self.token_provider = token_provider or GoogleAuth(config['credentials_file'], config['google_scopes']).token
        self.email = self.call('GET', 'about?fields=user(emailAddress)')['user']['emailAddress']
        if self.email.casefold() != config['google_account_email'].casefold():
            raise ValueError('Google account differs from owner binding')
        self.verify(config['folder_id'], FOLDER)
        verify_selected_folders(config, self.email, self.metadata)

    def metadata(self, identity):
        return self.call('GET', 'files/' + _id(identity) + '?fields=id,mimeType,parents,shared,trashed,owners(emailAddress),capabilities(canEdit)')

    def call(self, method, suffix, body=None):
        return self.request(method, 'https://www.googleapis.com/drive/v3/' + suffix, body,
                            {'Authorization': 'Bearer ' + self.token_provider(), 'Content-Type': 'application/json'}, 20)

    def verify(self, identity, mime, parent=None):
        metadata = self.metadata(identity)
        if (metadata.get('mimeType') != mime or metadata.get('shared') or metadata.get('trashed') or
                not metadata.get('capabilities', {}).get('canEdit') or
                not any(o.get('emailAddress', '').casefold() == self.email.casefold() for o in metadata.get('owners', [])) or
                (parent is not None and metadata.get('parents') != [parent])):
            raise ValueError('destination must be private, editable and owner-matched')


@contextmanager
def onboarding_lock(directory):
    directory = private_path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    fd = os.open(directory / '.onboarding.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def receive(owner, envelope, config_dir=None, *, request=None, token_provider=None):
    owner = _owner(owner)
    directory = private_path(config_dir or Path.home() / '.config/minbox-text-archive/owners') / owner
    with onboarding_lock(directory):
        return _receive(owner, envelope, config_dir, request=request, token_provider=token_provider)


def provision(owner, drive_config, archive_root, publisher_config, runtime_dir, *, request=None, token_provider=None):
    _owner(owner)
    with onboarding_lock(private_path(drive_config).parent):
        return _provision(owner, drive_config, archive_root, publisher_config, runtime_dir,
                          request=request, token_provider=token_provider)


def _receive(owner, envelope, config_dir=None, *, request=None, token_provider=None):
    """Validate a staged refresh credential before replacing this owner's files.

    Injectable token_provider receives the staged private credential path.
    """
    owner = _owner(owner)
    if not isinstance(envelope, dict) or set(envelope) != {'binding', 'credentials'}:
        raise ValueError('invalid credential envelope')
    binding, credentials = envelope['binding'], envelope['credentials']
    if not isinstance(binding, dict) or binding.get('owner') != owner:
        raise ValueError('owner binding differs')
    email = binding.get('google_account_email')
    scopes = binding.get('google_scopes')
    if (not isinstance(email, str) or '@' not in email or scopes != FILE_SCOPES or
            binding.get('folder_access') != 'selected_folder' or
            binding.get('archive_root_folder_id') != binding.get('folder_id')):
        raise ValueError('invalid account or scope binding')
    _id(binding.get('folder_id'))
    if (not isinstance(credentials, dict) or credentials.get('type') != 'authorized_user' or
            any(not isinstance(credentials.get(k), str) or not credentials[k] for k in ('refresh_token', 'client_id', 'client_secret')) or
            credentials.get('token_uri', 'https://oauth2.googleapis.com/token') != 'https://oauth2.googleapis.com/token'):
        raise ValueError('invalid authorized-user credential')
    directory = private_path(config_dir or Path.home() / '.config/minbox-text-archive/owners') / owner
    directory = private_path(directory)
    config_path, target = _path(directory / 'drive.json'), _path(directory / 'google-authorized-user.json')
    previous = _load(config_path)
    if previous and previous.get('folder_access') != 'selected_folder':
        raise ValueError('Existing broad authorization requires coordinated migration')
    if previous:
        target = _path(previous['credentials_file'])
    if previous and (previous.get('owner') != owner or previous.get('folder_id') != binding['folder_id'] or
                     previous.get('google_account_email', '').casefold() != email.casefold() or
                     private_path(previous['credentials_file']) != target):
        raise ValueError('existing owner binding differs')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    fd, staged = tempfile.mkstemp(prefix='.receive-', dir=directory)
    staged = Path(staged)
    try:
        # Discard access token/expiry so the destination verifies a fresh grant.
        value = {k: credentials[k] for k in ('type', 'refresh_token', 'client_id', 'client_secret')}
        value['token_uri'] = 'https://oauth2.googleapis.com/token'
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream)
            stream.flush(); os.fsync(stream.fileno())
        config = dict(owner=owner, google_account_email=email, folder_id=binding['folder_id'],
                      google_scopes=scopes, credentials_file=str(target), folder_access='selected_folder',
                      archive_root_folder_id=binding['archive_root_folder_id'])
        token = (lambda: token_provider(staged)) if token_provider else GoogleAuth(staged, scopes).token
        Binding(dict(config, credentials_file=str(staged)), request, token)
        # Both files bind the same already-verified account. A crash between replacements
        # leaves either the prior or renewed grant for that same account.
        os.replace(staged, target)
        write_json(config_path, config)
        return dict(owner=owner, folder_id=config['folder_id'], drive_config=str(config_path), credentials_file=str(target))
    finally:
        staged.unlink(missing_ok=True)


def _provision(owner, drive_config, archive_root, publisher_config, runtime_dir, *, request=None, token_provider=None):
    owner = _owner(owner)
    drive_path, publisher_path = _path(drive_config), _path(publisher_config)
    drive = _load(drive_path)
    existing = _load(publisher_path)
    scopes = drive.get('google_scopes', []) if drive else []
    narrow = scopes == FILE_SCOPES and drive.get('folder_access') == 'selected_folder' and drive.get('archive_root_folder_id') == drive.get('folder_id')
    legacy = (existing and isinstance(scopes, list) and DRIVE_SCOPES[0] in scopes and drive.get('folder_access') is None and
              existing.get('google_scopes') == scopes and existing.get('folder_access') is None)
    if (not drive or drive.get('owner') != owner or
            not isinstance(scopes, list) or not (narrow or legacy) or
            any(not isinstance(scope, str) or not scope.startswith('https://www.googleapis.com/auth/') for scope in drive['google_scopes'])):
        raise ValueError('Drive configuration owner or scopes differ')
    _path(drive['credentials_file'])
    root, runtime = private_path(archive_root), private_path(runtime_dir)
    if existing:
        if (existing.get('owner') != owner or existing.get('scope') != 'owner_all' or
                private_path(existing['archive_root']) != root or existing.get('folder_id') != drive['folder_id'] or
                existing.get('google_account_email', '').casefold() != drive['google_account_email'].casefold() or
                private_path(existing['credentials_file']) != private_path(drive['credentials_file'])):
            raise ValueError('existing publisher binding differs')
        if (existing.get('google_scopes') != scopes or
                existing.get('folder_access') != drive.get('folder_access') or
                existing.get('archive_root_folder_id') != drive.get('archive_root_folder_id')):
            raise ValueError('Existing publisher authorization requires coordinated migration')
        # Validate all persisted Doc/chunk bindings without rewriting config, manifests or ledger.
        OwnerDocs(existing, request=request, token_provider=token_provider)
        return dict(owner=owner, folder_id=drive['folder_id'], publisher_config=str(publisher_path), documents=existing['documents'])
    binding = Binding(drive, request, token_provider)
    docs = {}
    for kind, label in (('guide', 'Start Here'), ('corrections', 'Corrections'), ('status', 'Status')):
        identity = sha256((owner + ':' + drive['folder_id'] + ':' + kind).encode()).hexdigest()
        query = ("'" + _id(drive['folder_id']) + "' in parents and trashed = false and "
                 "appProperties has { key='familyArchiveOwnerDoc' and value='" + identity + "' }")
        found = binding.call('GET', 'files?' + urlencode({'q': query, 'fields': 'nextPageToken,files(id)', 'pageSize': 100}))
        if found.get('nextPageToken') or len(found['files']) > 1:
            raise ValueError('duplicate provisioning identities need review')
        doc = found['files'][0]['id'] if found['files'] else binding.call('POST', 'files?fields=id', {
            'name': owner + ' Text Archive — ' + label, 'mimeType': DOCUMENT,
            'parents': [drive['folder_id']], 'appProperties': {'familyArchiveOwnerDoc': identity}})['id']
        binding.verify(doc, DOCUMENT, drive['folder_id'])
        docs[kind] = doc
    if len(set(docs.values())) != 3:
        raise ValueError('provisioning document identities overlap')
    client = DocsClient(set(docs.values()), request=request, token_provider=binding.token_provider)
    # Only initialize a blank identity-owned input. Retried onboarding never replaces entries.
    before = client.read(docs['corrections'])
    if not before['text'].strip():
        text = correction_template(owner)
        # Guard the exact blank revision checked above. A user edit during setup
        # must cause a retry, never a deletion/replacement of their entry.
        client._call(docs['corrections'], 'POST', ':batchUpdate', {
            'requests': [{'insertText': {'location': {'index': 1, 'tabId': before['tab_id']},
                                         'text': text.rstrip('\n')}}],
            'writeControl': {'requiredRevisionId': before['revision']}})
        if client.read(docs['corrections'])['text'] != text:
            raise ValueError('correction initialization readback differs')
    Archive(root).init([owner])
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    runtime.chmod(0o700)
    config = dict(drive, scope='owner_all', archive_root=str(root), documents=docs,
                  correction_path=str(runtime / 'corrections.sqlite3'),
                  manifest_file=str(runtime / 'manifest.json'), status_file=str(runtime / 'status.json'))
    write_json(publisher_path, config)
    return dict(owner=owner, folder_id=drive['folder_id'], publisher_config=str(publisher_path), documents=docs)


def correction_template(owner):
    return (owner + ' Text Archive Corrections\n'
            'Only explicit entries below are applied. Ask your AI to prepare a precise entry using the source message ID.\n'
            'Entry fields, each on its own line: Correction ID, Owner, Target, Scope, Action, Instruction, Requested at.\n'
            'Owner must be ' + owner + '; Scope must be message. Target is the exact source message ID.\n'
            'Action: work, personal, mixed, spam, uncertain, or undo. Requested at must be an ISO timestamp with timezone.\n'
            'For undo also include Undo correction with the prior Correction ID.\n'
            'Corrections begin below.\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    incoming = commands.add_parser('receive')
    incoming.add_argument('--owner', required=True, type=_owner)
    incoming.add_argument('--config-dir', type=Path)
    setup = commands.add_parser('provision')
    setup.add_argument('--owner', required=True, type=_owner)
    setup.add_argument('--drive-config', type=Path)
    setup.add_argument('--archive-root', required=True, type=Path)
    setup.add_argument('--publisher-config', type=Path)
    setup.add_argument('--runtime-dir', type=Path)
    setup.add_argument('--publish-now', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'receive':
            raw = sys.stdin.buffer.read(MAX_ENVELOPE_BYTES + 1)
            if len(raw) > MAX_ENVELOPE_BYTES:
                raise ValueError('credential envelope exceeds limit')
            result = receive(args.owner, json.loads(raw), args.config_dir)
        else:
            drive = args.drive_config or Path.home() / '.config/minbox-text-archive/owners' / args.owner / 'drive.json'
            config = args.publisher_config or Path.home() / '.config/minbox-text-archive/publishers' / (args.owner + '-full.json')
            runtime = args.runtime_dir or Path.home() / '.local/share/minbox-text-archive/publishers' / (args.owner + '-full')
            result = provision(args.owner, drive, args.archive_root, config, runtime)
            if args.publish_now:
                from owner_publish_cli import main as publish
                with redirect_stdout(io.StringIO()) as output:
                    if publish(['--config', str(config)]) != 0:
                        raise ValueError('publication failed')
                counts = json.loads(output.getvalue())
                result['publication'] = {k: counts[k] for k in ('writes', 'published_messages', 'excluded_messages', 'model_calls')}
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print('Owner onboarding failed; private details withheld. Existing bindings are preserved; retry after checking configuration.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

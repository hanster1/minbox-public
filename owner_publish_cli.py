"""Publish all captured, filtered owner texts privately; no AI model is required."""
import argparse
import fcntl
import json
import os
from urllib.parse import urlencode

from folder_policy import verify_selected_folders
from archive_drive import DocsClient
from archive_io import GoogleAuth, _http_request
from archive_snapshot import snapshot
from storage import _owner
from publisher_status import PublisherStatus, failure_details, private_path, write_json


class OwnerDocs:
    """Private account/folder binding and persistent dynamic output allowlist."""
    def __init__(self, config, *, request=None, token_provider=None, raw_request=None):
        self.config = config
        self.request = request or _http_request
        auth = GoogleAuth(config['credentials_file'], scopes=config.get('google_scopes'))
        self.token_provider = token_provider or auth.token
        self.path = private_path(config['manifest_file'])
        if self.path.exists():
            if self.path.stat().st_mode & 0o777 != 0o600:
                raise ValueError('manifest must be private')
            self.manifest = json.loads(self.path.read_text())
            if (self.manifest.get('owner') != config['owner'] or
                    self.manifest.get('folder_id') != config['folder_id']):
                raise ValueError('manifest owner/folder differs')
        else:
            self.manifest = {'owner': config['owner'], 'folder_id': config['folder_id'], 'chunks': {}}
        account = self.call('GET', 'about?fields=user(emailAddress)')['user']['emailAddress']
        if account.lower() != config['google_account_email'].lower():
            raise ValueError('Google account differs from owner binding')
        self.account = account
        selected = verify_selected_folders(config, account, self.metadata)
        correction_folder = config.get('corrections_folder_id', config['folder_id'])
        if not selected:
            self.verify(self.metadata(config['folder_id']), 'application/vnd.google-apps.folder')
            if correction_folder != config['folder_id']:
                self.verify(self.metadata(correction_folder), 'application/vnd.google-apps.folder')
        docs = config['documents']
        if set(docs) != {'guide', 'corrections', 'status'} or len(set(docs.values())) != 3:
            raise ValueError('distinct guide/corrections/status documents required')
        known = [*docs.values(), *self.manifest['chunks'].values()]
        if len(set(known)) != len(known):
            raise ValueError('overlapping output and input identities')
        for kind, doc in docs.items():
            self.verify(self.metadata(doc), 'application/vnd.google-apps.document',
                        correction_folder if kind == 'corrections' else config['folder_id'])
        for doc in self.manifest['chunks'].values():
            self.verify(self.metadata(doc), 'application/vnd.google-apps.document', config['folder_id'])
        from attachment_drive import AttachmentDrive
        self.attachments = AttachmentDrive(self, raw_request=raw_request)
        self.client = self.adapter()

    def call(self, method, suffix, body=None):
        return self.request(method, 'https://www.googleapis.com/drive/v3/' + suffix, body,
                            {'Authorization': 'Bearer ' + self.token_provider(),
                             'Content-Type': 'application/json'}, 20)

    def metadata(self, file_id):
        return self.call('GET', 'files/' + file_id + '?fields=id,mimeType,parents,shared,trashed,owners(emailAddress),capabilities(canEdit)')

    def verify(self, metadata, mime_type, parent=None):
        if (metadata.get('mimeType') != mime_type or metadata.get('shared') or metadata.get('trashed') or
                not metadata.get('capabilities', {}).get('canEdit') or
                not any(o.get('emailAddress') == self.account for o in metadata.get('owners', [])) or
                (parent is not None and metadata.get('parents') != [parent])):
            raise ValueError('archive destination must remain private, owner-matched and in its authorized folder')

    def adapter(self):
        docs = self.config['documents']
        outputs = {docs['guide'], docs['status'], *self.manifest['chunks'].values()}
        return DocsClient(outputs | {docs['corrections']}, request=self.request,
                          token_provider=self.token_provider, write_ids=outputs)

    def ensure_document(self, key, title):
        if key in self.manifest['chunks']:
            return self.manifest['chunks'][key]
        if not isinstance(key, str) or len(key) > 100 or not title.startswith(self.config['owner'] + ' Text Archive'):
            raise ValueError('invalid owner chunk identity')
        # appProperties provide retry identity if creation succeeds but manifest
        # persistence fails. Never adopt an unrelated same-title file.
        from hashlib import sha256
        identity = sha256((self.config['owner'] + ':' + key).encode()).hexdigest()
        query = ("'" + self.config['folder_id'] + "' in parents and trashed = false and "
                 "appProperties has { key='familyArchiveChunk' and value='" + identity + "' }")
        found = self.call('GET', 'files?' + urlencode({'q': query, 'fields': 'files(id)', 'pageSize': 100}))['files']
        if len(found) > 1:
            raise ValueError('duplicate chunk identities need review')
        doc = found[0]['id'] if found else self.call('POST', 'files?fields=id', {
            'name': title, 'mimeType': 'application/vnd.google-apps.document',
            'parents': [self.config['folder_id']], 'appProperties': {'familyArchiveChunk': identity}})['id']
        self.verify(self.metadata(doc), 'application/vnd.google-apps.document', self.config['folder_id'])
        if (doc in self.config['documents'].values() or doc in self.manifest['chunks'].values() or
                doc == self.manifest.get('attachments_folder_id') or
                doc in {entry['drive_file_id'] for entry in self.manifest['attachments'].values()}):
            raise ValueError('chunk overlaps another identity')
        self.manifest['chunks'][key] = doc
        write_json(self.path, self.manifest)
        self.client = self.adapter()
        return doc

    def withdraw_phone_spam(self, source_ids, images=()):
        return self.attachments.withdraw_phone_spam(source_ids, images)

    def publish_attachments(self, messages):
        return self.attachments.publish(messages)

    def read(self, document_id):
        # Output replacements may already have verified this exact content.
        # Corrections always require a fresh read, including the final race check.
        take = getattr(self.client, 'take_verified_readback', None)
        if document_id != self.config['documents']['corrections'] and take is not None:
            verified = take(document_id)
            if verified is not None:
                return verified
        return self.client.read(document_id)

    def replace(self, document_id, text):
        return self.client.replace(document_id, text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args(argv)
    path = private_path(args.config)
    if path.stat().st_mode & 0o777 != 0o600:
        raise ValueError('publisher config must be private')
    config = json.loads(path.read_text())
    state = private_path(config['status_file'])
    state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(state.with_suffix('.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+b') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'status': 'already_running'}, sort_keys=True))
            return 0
        from phone_spam import owner_operation
        with owner_operation(config['archive_root'], config['owner'], blocking=False) as acquired:
            if not acquired:
                print(json.dumps({'status': 'owner_busy'}, sort_keys=True))
                return 0
            with PublisherStatus(state) as status:
                _owner(config['owner'])
                if config.get('scope') != 'owner_all':
                    raise ValueError('all-owner publication must be explicitly configured')
                client = OwnerDocs(config)
                config['previous_chunk_keys'] = list(client.manifest['chunks'])
                status.phase('snapshot')
                current = snapshot(config['archive_root'], config['owner'], None, '1970-01-01',
                                   phone_spam_policy=config.get('phone_spam_policy'))
                status.phase('publishing', current['latest_import'])
                from owner_archive_publisher import run
                result = run(config, current, client)
                safe = {k: result[k] for k in ('writes', 'published_messages', 'excluded_messages', 'model_calls',
                                                'verified_images', 'published_images', 'pending_images', 'unavailable_images', 'attachment_writes',
                                                'withdrawn_images', 'phone_spam_conversations')}
                status.success(current['latest_import'], {'analysis_failed_or_paused': False,
                                                        'deferred_sources': 0, **safe})
                print(json.dumps(safe, sort_keys=True))
                return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        import sys
        print('Owner archive publication failed; private details withheld. Next run reconciles outputs.', file=sys.stderr)
        print(json.dumps(failure_details(error), sort_keys=True), file=sys.stderr)
        raise SystemExit(1)

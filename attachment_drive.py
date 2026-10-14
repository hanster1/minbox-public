"""Private, content-verified image publication with durable Drive retry identities."""
import hashlib
import json
import os
from pathlib import Path
import stat
from urllib.parse import urlencode
import urllib.request

from archive_io import AdapterError, _urlopen
from folder_policy import _identifier
from publisher_status import failure_details, write_json
from attachment_capture import FORMATS, image_mime

MAX_IMAGE_BYTES = 20 * 1024 * 1024
FOLDER_MIME = 'application/vnd.google-apps.folder'
FIELDS = 'id,mimeType,parents,shared,trashed,owners(emailAddress),capabilities(canEdit),appProperties,size,md5Checksum,sha256Checksum'


def binary_request(method, url, body, headers, timeout):
    """Single-attempt bounded HTTPS upload; a later run reconciles uncertain writes."""
    if (method != 'PATCH' or not url.startswith('https://www.googleapis.com/upload/drive/v3/files/') or
            not isinstance(body, bytes) or len(body) > MAX_IMAGE_BYTES):
        raise ValueError('invalid image upload transport')
    try:
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        with _urlopen(request, min(max(float(timeout), 1), 60)) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise AdapterError('Image upload response exceeds local limit')
            return json.loads(raw)
    except AdapterError:
        raise
    except Exception:
        raise AdapterError('Image upload failed; private details withheld') from None


def image_bytes(config, item):
    """Open each path component without following symlinks, including the file."""
    root = Path(config['archive_root']).expanduser().absolute() / config['owner'] / 'attachments'
    path = Path(item['local_path'])
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('invalid attachment local path')
    try:
        path.relative_to(root)
    except ValueError:
        raise ValueError('attachment outside owner attachment root') from None
    descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
        with os.fdopen(file_fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_IMAGE_BYTES:
                raise ValueError('invalid attachment size or type')
            data = source.read(MAX_IMAGE_BYTES + 1)
    finally:
        os.close(descriptor)
    mime = image_mime(data)
    if (mime != item.get('mime_type') or len(data) != item.get('size_bytes') or
            hashlib.sha256(data).hexdigest() != item.get('sha256')):
        raise ValueError('attachment content metadata mismatch')
    return data


class AttachmentDrive:
    def __init__(self, docs, raw_request=None):
        self.docs = docs
        self.raw_request = raw_request or binary_request
        self._metadata = {}
        self._published_once = False
        manifest = docs.manifest
        manifest.setdefault('attachments', {})
        if not isinstance(manifest['attachments'], dict):
            raise ValueError('invalid attachment manifest')
        for key in ('attachments_pending_deletions', 'attachments_pending_uploads'):
            manifest.setdefault(key, {})
            if not isinstance(manifest[key], dict):
                raise ValueError('invalid attachment manifest identity')
        self.writes = 0
        self._folder = None
        folder = manifest.get('attachments_folder_id')
        if folder:
            _identifier(folder)
            metadata = self.metadata(folder)
            docs.verify(metadata, FOLDER_MIME, docs.config['folder_id'])
            identity = hashlib.sha256((docs.config['owner'] + ':' + docs.config['folder_id'] + ':attachments').encode()).hexdigest()
            if metadata.get('appProperties', {}).get('familyArchiveAttachments') != identity:
                raise ValueError('attachment folder identity mismatch')
            self.prefetch(folder)
        elif any(manifest[key] for key in ('attachments', 'attachments_pending_deletions', 'attachments_pending_uploads')):
            raise ValueError('attachment folder binding missing')
        # Resolve deletion crash windows before eager checks of registered files.
        self._resume_deletions(folder)
        known = [*docs.config['documents'].values(), *manifest['chunks'].values()]
        if folder:
            known.append(folder)
        for identity, entry in manifest['attachments'].items():
            if not isinstance(entry, dict) or identity != self.identity(entry['source_id'], entry):
                raise ValueError('invalid attachment manifest identity')
            self.verify(entry['drive_file_id'], entry, folder, identity)
            known.append(entry['drive_file_id'])
        if len(known) != len(set(known)):
            raise ValueError('attachment destination identities overlap')
        self.writes = 0
        self._folder = None

    def metadata(self, file_id):
        file_id = _identifier(file_id)
        if file_id not in self._metadata:
            self._metadata[file_id] = self.docs.call('GET', 'files/' + file_id + '?fields=' + FIELDS)
        return self._metadata[file_id]

    def prefetch(self, folder):
        """Read child metadata in pages instead of one request per archived image."""
        token = None
        seen = set()
        for _ in range(100):
            params = {'q': "'" + _identifier(folder) + "' in parents and trashed = false",
                      'fields': 'nextPageToken,files(' + FIELDS + ')', 'pageSize': 1000}
            if token:
                params['pageToken'] = token
            result = self.docs.call('GET', 'files?' + urlencode(params))
            for item in result['files']:
                # Test adapters may return IDs only; production fields are explicit.
                if 'mimeType' in item:
                    self._metadata[_identifier(item['id'])] = item
            token = result.get('nextPageToken')
            if not token:
                return
            if token in seen:
                raise ValueError('attachment metadata pagination repeated')
            seen.add(token)
        raise ValueError('attachment metadata exceeds page bound')

    def identity(self, source_id, item):
        media, digest = item.get('media_id'), item.get('sha256')
        if (not isinstance(media, str) or not media or len(media) > 512 or
                not isinstance(digest, str) or len(digest) != 64 or
                any(c not in '0123456789abcdef' for c in digest)):
            raise ValueError('invalid image identity')
        return hashlib.sha256(json.dumps([self.docs.config['owner'], source_id, media, digest],
                                        separators=(',', ':')).encode()).hexdigest()

    def find(self, parent, property_name, identity):
        query = ("'" + _identifier(parent) + "' in parents and trashed = false and appProperties has { key='" +
                 property_name + "' and value='" + identity + "' }")
        result = self.docs.call('GET', 'files?' + urlencode({'q': query, 'fields': 'nextPageToken,files(id)', 'pageSize': 100}))
        if result.get('nextPageToken') or len(result['files']) > 1:
            raise ValueError('duplicate attachment identities need review')
        return _identifier(result['files'][0]['id']) if result['files'] else None

    def folder(self):
        if self._folder is not None:
            return self._folder
        manifest = self.docs.manifest
        identity = hashlib.sha256((self.docs.config['owner'] + ':' + self.docs.config['folder_id'] + ':attachments').encode()).hexdigest()
        folder = manifest.get('attachments_folder_id') or self.find(self.docs.config['folder_id'], 'familyArchiveAttachments', identity)
        if not folder:
            folder = self.docs.call('POST', 'files?fields=id', {'name': 'Attachments', 'mimeType': FOLDER_MIME,
                'parents': [self.docs.config['folder_id']], 'appProperties': {'familyArchiveAttachments': identity}})['id']
            self.writes += 1
        metadata = self.metadata(folder)
        self.docs.verify(metadata, FOLDER_MIME, self.docs.config['folder_id'])
        if metadata.get('appProperties', {}).get('familyArchiveAttachments') != identity:
            raise ValueError('attachment folder identity mismatch')
        if folder in [*self.docs.config['documents'].values(), *manifest['chunks'].values()]:
            raise ValueError('attachment folder overlaps another destination')
        manifest['attachments_folder_id'] = folder
        write_json(self.docs.path, manifest)
        self._folder = folder
        return folder

    def verify(self, file_id, entry, folder, identity):
        metadata = self.metadata(file_id)
        self.docs.verify(metadata, entry['mime_type'], folder)
        if (metadata.get('appProperties', {}).get('familyArchiveImage') != identity or
                metadata.get('size') != str(entry['size_bytes']) or metadata.get('md5Checksum') != entry['md5'] or
                metadata.get('sha256Checksum') is not None and metadata['sha256Checksum'] != entry['sha256']):
            raise RuntimeError('attachment readback mismatch')
        return metadata

    def _validate_deletion(self, identity, record, folder):
        entry = record['entry']
        file_id = _identifier(entry['drive_file_id'])
        if (not folder or identity != self.identity(entry['source_id'], entry) or
                entry['mime_type'] not in FORMATS or type(entry['size_bytes']) is not int or
                not 0 < entry['size_bytes'] <= MAX_IMAGE_BYTES or
                not isinstance(entry.get('md5'), str) or len(entry['md5']) != 32 or
                any(c not in '0123456789abcdef' for c in entry['md5']) or
                type(record.get('allow_empty')) is not bool):
            raise ValueError('invalid attachment manifest identity')
        protected = {self.docs.config['folder_id'], folder,
                     self.docs.config.get('corrections_folder_id'),
                     *self.docs.config['documents'].values(), *self.docs.manifest['chunks'].values()}
        for key in ('attachments', 'attachments_pending_uploads', 'attachments_pending_deletions'):
            for other, value in self.docs.manifest[key].items():
                if other != identity:
                    protected.add((value['entry'] if key == 'attachments_pending_deletions' else value)['drive_file_id'])
        if file_id in protected:
            raise ValueError('attachment destination identities overlap')
        saved = self.docs.manifest['attachments'].get(identity)
        uploading = self.docs.manifest['attachments_pending_uploads'].get(identity)
        if saved is not None and saved != entry or uploading is not None and uploading != entry:
            raise ValueError('attachment saved metadata differs')
        if record['allow_empty'] and uploading != entry:
            raise ValueError('invalid attachment manifest identity')
        return entry

    def _verify_deletion(self, identity, record, folder):
        entry = self._validate_deletion(identity, record, folder)
        file_id = entry['drive_file_id']
        self._metadata.pop(file_id, None)
        metadata = self.metadata(file_id)
        self.docs.verify(metadata, entry['mime_type'], folder)
        if metadata.get('id') != file_id or metadata.get('appProperties', {}).get('familyArchiveImage') != identity:
            raise ValueError('image destination identity mismatch')
        if (record['allow_empty'] and metadata.get('size') == '0' and
                metadata.get('md5Checksum') in (None, hashlib.md5(b'').hexdigest()) and
                metadata.get('sha256Checksum') in (None, hashlib.sha256(b'').hexdigest())):
            return
        self.verify(file_id, entry, folder, identity)

    @staticmethod
    def _missing(error):
        return failure_details(error).get('http_status') == 404

    def _finish_deletion(self, identity):
        manifest = self.docs.manifest
        removed = {}
        for key in ('attachments', 'attachments_pending_uploads', 'attachments_pending_deletions'):
            if identity in manifest[key]:
                removed[key] = manifest[key].pop(identity)
        try:
            write_json(self.docs.path, manifest)
        except Exception:
            for key, value in removed.items():
                manifest[key][identity] = value
            raise

    def _resume_deletions(self, folder):
        completed = 0
        for identity, record in list(self.docs.manifest['attachments_pending_deletions'].items()):
            entry = self._validate_deletion(identity, record, folder)
            try:
                self._verify_deletion(identity, record, folder)
            except Exception as error:
                if not self._missing(error):
                    raise
                self._finish_deletion(identity)
                completed += 1
                continue
            # The durable journal proves the registered identity was checked before
            # deletion. A timeout or crash keeps it until an independent 404 read.
            try:
                self.docs.call('DELETE', 'files/' + entry['drive_file_id'])
                self.writes += 1
            except Exception as error:
                status = failure_details(error).get('http_status')
                if status is not None and status not in (404, 429, 500, 502, 503, 504):
                    raise
                delete_error = error
            else:
                delete_error = None
            self._metadata.pop(entry['drive_file_id'], None)
            try:
                self.metadata(entry['drive_file_id'])
            except Exception as error:
                if not self._missing(error):
                    raise
                self._finish_deletion(identity)
                completed += 1
            else:
                if delete_error is not None:
                    raise delete_error
                raise AdapterError('Image deletion is pending readback')
        return completed

    def withdraw_phone_spam(self, source_ids, images=()):
        """Remove verified image identities only; failure retains the retry journal.

        Images include historical revisions so uploads whose manifest write failed
        can be discovered by their exact app-property identity. No Doc body is read.
        """
        sources = set(source_ids)
        if any(not isinstance(source, str) or not source for source in sources):
            raise ValueError('invalid source field')
        manifest = self.docs.manifest
        folder = manifest.get('attachments_folder_id')
        if not folder:
            return {'withdrawn_images': 0, 'pending_image_deletions': 0}
        # Recheck privacy on every withdrawal, even on one client.
        root = self.docs.config['folder_id']
        self._metadata.pop(root, None)
        self.docs.verify(self.metadata(root), FOLDER_MIME)
        self._metadata.pop(folder, None)
        self.docs.verify(self.metadata(folder), FOLDER_MIME, self.docs.config['folder_id'])
        expected = hashlib.sha256((self.docs.config['owner'] + ':' + self.docs.config['folder_id'] + ':attachments').encode()).hexdigest()
        if self.metadata(folder).get('appProperties', {}).get('familyArchiveAttachments') != expected:
            raise ValueError('attachment folder identity mismatch')
        candidates = {}
        for key in ('attachments', 'attachments_pending_uploads'):
            for identity, entry in manifest[key].items():
                if entry['source_id'] in sources:
                    candidates[identity] = dict(entry=entry, allow_empty=(key == 'attachments_pending_uploads'))
        for message in images:
            if message['source_id'] not in sources:
                continue
            for item in message.get('attachments', []):
                if item.get('mime_type') not in FORMATS or not item.get('sha256') or not item.get('media_id'):
                    continue
                identity = self.identity(message['source_id'], item)
                if identity in candidates or identity in manifest['attachments_pending_deletions']:
                    continue
                file_id = self.find(folder, 'familyArchiveImage', identity)
                if file_id is None:
                    continue
                # Never trust a candidate's remote checksum as its own proof.
                digest = item.get('md5')
                if digest is None:
                    digest = hashlib.md5(image_bytes(self.docs.config, item)).hexdigest()
                entry = dict(source_id=message['source_id'], media_id=item['media_id'], sha256=item['sha256'],
                             mime_type=item['mime_type'], size_bytes=item['size_bytes'], md5=digest, drive_file_id=file_id)
                candidates[identity] = dict(entry=entry, allow_empty=False)
        for identity, record in candidates.items():
            if identity in manifest['attachments_pending_deletions']:
                continue
            self._verify_deletion(identity, record, folder)
            manifest['attachments_pending_deletions'][identity] = record
            # This persist must succeed before any DELETE request can be made.
            try:
                write_json(self.docs.path, manifest)
            except Exception:
                manifest['attachments_pending_deletions'].pop(identity, None)
                raise
        completed = self._resume_deletions(folder)
        return {'withdrawn_images': completed, 'pending_image_deletions': len(manifest['attachments_pending_deletions'])}

    def publish_one(self, message, item):
        data = image_bytes(self.docs.config, item)
        identity = self.identity(message['source_id'], item)
        entry = dict(source_id=message['source_id'], media_id=item['media_id'], sha256=item['sha256'],
                     size_bytes=len(data), mime_type=item['mime_type'], md5=hashlib.md5(data).hexdigest())
        folder = self.folder()
        saved = self.docs.manifest['attachments'].get(identity)
        pending = self.docs.manifest['attachments_pending_uploads'].get(identity)
        create = False
        if saved:
            file_id = saved['drive_file_id']
        elif pending is not None:
            # Search visibility can lag an uncertain POST. The persisted generated
            # ID is authoritative; never replace it with a second generated ID.
            file_id = _identifier(pending['drive_file_id'])
            if pending != dict(entry, drive_file_id=file_id):
                raise ValueError('attachment saved metadata differs')
            self._validate_deletion(identity, dict(entry=pending, allow_empty=True), folder)
            self._metadata.pop(file_id, None)
            try:
                self.metadata(file_id)
            except Exception as error:
                if not self._missing(error):
                    raise
                create = True
        else:
            file_id = self.find(folder, 'familyArchiveImage', identity)
            if not file_id:
                generated = self.docs.call('GET', 'files/generateIds?count=1&space=drive&type=files')['ids'][0]
                file_id = _identifier(generated)
                pending = dict(entry, drive_file_id=file_id)
                self.docs.manifest['attachments_pending_uploads'][identity] = pending
                self._validate_deletion(identity, dict(entry=pending, allow_empty=True), folder)
                create = True
        if create:
            # Repeat persistence even for an in-memory pending entry whose first
            # write failed. Creation always requires a durable exact-ID journal.
            write_json(self.docs.path, self.docs.manifest)
            # OwnerDocs.call applies the publisher's write guard on every create,
            # including retries of this exact generated ID after a confirmed 404.
            label = str(message.get('friendly_id') or 'Image')[:100]
            filename = label + ' ' + message['timestamp'][:10] + ' ' + identity[:12] + '.' + FORMATS[item['mime_type']]
            self.docs.call('POST', 'files?fields=id', {'id': file_id, 'name': filename,
                'mimeType': item['mime_type'], 'parents': [folder], 'appProperties': {'familyArchiveImage': identity}})
            self.writes += 1
        metadata = self.metadata(file_id)
        self.docs.verify(metadata, item['mime_type'], folder)
        if metadata.get('appProperties', {}).get('familyArchiveImage') != identity:
            raise ValueError('image destination identity mismatch')
        if metadata.get('size') in (None, '0') and metadata.get('md5Checksum') in (None, hashlib.md5(b'').hexdigest()):
            self.raw_request('PATCH', 'https://www.googleapis.com/upload/drive/v3/files/' + file_id + '?uploadType=media&fields=id', data,
                             {'Authorization': 'Bearer ' + self.docs.token_provider(), 'Content-Type': item['mime_type']}, 20)
            self._metadata.pop(file_id, None)
            self.writes += 1
        self.verify(file_id, entry, folder, identity)
        other_ids = [*self.docs.config['documents'].values(), *self.docs.manifest['chunks'].values(), folder]
        other_ids.extend(v['drive_file_id'] for k, v in self.docs.manifest['attachments'].items() if k != identity)
        if file_id in other_ids:
            raise ValueError('image destination overlaps another identity')
        entry['drive_file_id'] = file_id
        if saved != entry:
            self.docs.manifest['attachments'][identity] = entry
            self.docs.manifest['attachments_pending_uploads'].pop(identity, None)
            write_json(self.docs.path, self.docs.manifest)
        item.update(drive_file_id=file_id, drive_url='https://drive.google.com/file/d/' + file_id + '/view', publication_status='verified')

    def publish(self, messages):
        if self._published_once:
            self._metadata.clear()
            if self.docs.manifest.get('attachments_folder_id'):
                self.prefetch(self.docs.manifest['attachments_folder_id'])
        self._published_once = True
        self.writes = 0
        counts = {'verified_images': 0, 'unavailable_images': 0, 'pending_images': 0, 'attachment_writes': 0}
        limit = self.docs.config.get('max_image_attempts', 5)
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError('invalid image attempt bound')
        attempts = 0
        for message in sorted(messages, key=lambda m: (m['timestamp'], m['source_id']), reverse=True):
            for item in message.get('attachments', []):
                for key in ('drive_url', 'drive_file_id', 'publication_status'):
                    item.pop(key, None)
                if item.get('capture_status') != 'captured' or item.get('mime_type') not in FORMATS:
                    item['publication_status'] = 'unavailable'
                    counts['unavailable_images'] += 1
                    continue
                identity = self.identity(message['source_id'], item)
                saved = self.docs.manifest['attachments'].get(identity)
                if saved:
                    if any(saved[k] != item.get(k) for k in ('mime_type', 'size_bytes', 'sha256', 'media_id')):
                        raise ValueError('attachment saved metadata differs')
                    self.verify(saved['drive_file_id'], saved, self.docs.manifest['attachments_folder_id'], identity)
                    item.update(drive_file_id=saved['drive_file_id'], drive_url='https://drive.google.com/file/d/' + saved['drive_file_id'] + '/view', publication_status='verified')
                    counts['verified_images'] += 1
                    continue
                if attempts >= limit:
                    item['publication_status'] = 'pending'
                    counts['pending_images'] += 1
                    continue
                attempts += 1
                try:
                    self.publish_one(message, item)
                except FileNotFoundError:
                    attempts -= 1
                    item['publication_status'] = 'unavailable'
                    counts['unavailable_images'] += 1
                except AdapterError as error:
                    details = failure_details(error)
                    if ('authentication' in str(error).lower() or
                            details.get('http_status') is not None and
                            details['http_status'] not in (429, 500, 502, 503, 504)):
                        raise
                    item['publication_status'] = 'pending'
                    counts['pending_images'] += 1
                else:
                    counts['verified_images'] += 1
        counts['attachment_writes'] = self.writes
        counts['published_images'] = counts['verified_images']
        return counts

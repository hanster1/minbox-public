"""Revision-guarded text-only Docs adapter for explicitly allowlisted archive files."""
import hashlib
import json
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode
from archive_io import AdapterError, GoogleAuth, _http_request
from publisher_status import private_path, write_json


VERIFICATION_MAX_AGE = 24 * 60 * 60


def canonical_hash(text):
    return hashlib.sha256((text.rstrip('\n') + '\n').encode('utf-8')).hexdigest()


class DocsVerificationCache:
    """Content-free proofs; publishers provide a freshly checked Drive binding."""
    def __init__(self, path, binding, *, clock=None):
        if (not isinstance(binding, dict)
                or set(binding) != {'account', 'owner', 'root_id', 'parent_id'}
                or any(not isinstance(v, str) or not v for v in binding.values())):
            raise ValueError('invalid Docs verification binding')
        self.path = private_path(path)
        self.binding = dict(binding)
        self.clock = clock or time.time
        self.documents = {}
        if self.path.exists():
            if self.path.stat().st_mode & 0o777 != 0o600:
                raise AdapterError('Docs verification cache must be private')
            try:
                value = json.loads(self.path.read_text())
                if (set(value) != {'version', 'binding', 'documents'} or value['version'] != 1
                        or not isinstance(value['binding'], dict)
                        or not isinstance(value['documents'], dict)):
                    raise ValueError()
                for identifier, proof in value['documents'].items():
                    if not re.fullmatch(r'[A-Za-z0-9_-]+', identifier) or not self.valid_proof(proof):
                        raise ValueError()
                if value['binding'] == self.binding:
                    self.documents = value['documents']
            except (ValueError, TypeError, AttributeError):
                raise AdapterError('Invalid Docs verification cache') from None

    @staticmethod
    def valid_proof(proof):
        return (isinstance(proof, dict) and set(proof) == {'hash', 'revision', 'verified_at'}
                and isinstance(proof['hash'], str) and bool(re.fullmatch(r'[0-9a-f]{64}', proof['hash']))
                and isinstance(proof['revision'], str) and bool(proof['revision'])
                and type(proof['verified_at']) in (int, float) and math.isfinite(proof['verified_at']))

    def fresh(self, document_id):
        """Return a recent full plaintext proof, regardless of the next output."""
        proof = self.documents.get(document_id)
        if proof and 0 <= self.clock() - proof['verified_at'] < VERIFICATION_MAX_AGE:
            return dict(proof)
        return None

    def reusable(self, document_id, desired_hash):
        proof = self.fresh(document_id)
        return proof if proof and proof['hash'] == desired_hash else None

    def remember(self, document_id, desired_hash, revision):
        proof = {'hash': desired_hash, 'revision': revision, 'verified_at': self.clock()}
        if not self.valid_proof(proof):
            raise AdapterError('Invalid Docs verification proof')
        documents = {**self.documents, document_id: proof}
        try:
            write_json(self.path, {'version': 1, 'binding': self.binding, 'documents': documents})
        except Exception:
            raise AdapterError('Docs verification persistence failed; publication is not confirmed') from None
        self.documents = documents
        return dict(proof)


class DocsClient:
    def __init__(self, allowed_ids, credentials_file=None, *, request=None, token_provider=None, write_ids=None,
                 verification_cache=None):
        self.allowed_ids = frozenset(allowed_ids)
        if not self.allowed_ids or any(not re.fullmatch(r'[A-Za-z0-9_-]+', i) for i in self.allowed_ids):
            raise ValueError('invalid document allowlist')
        self.write_ids = self.allowed_ids if write_ids is None else frozenset(write_ids)
        if not self.write_ids <= self.allowed_ids:
            raise ValueError('write allowlist must be a subset of readable documents')
        self.request = request or _http_request
        auth = GoogleAuth(credentials_file, scopes=['https://www.googleapis.com/auth/drive.file'])
        self.token_provider = token_provider or auth.token
        self._token_lock = threading.Lock()
        self._verified_readbacks = {}
        self._prefetched_revisions = {}
        self.verification_cache = verification_cache
        self.verification_counts = {'body_reads': 0, 'revision_probes': 0, 'cache_hits': 0, 'writes': 0}

    def take_verified_readback(self, document_id):
        """Consume the readback from the immediately preceding replacement once."""
        return self._verified_readbacks.pop(document_id, None)

    def _call(self, document_id, method, suffix, body=None, *, required_proof=None, request_gate=None):
        if document_id not in self.allowed_ids or (method != 'GET' and document_id not in self.write_ids):
            raise AdapterError('Document is not allowlisted')
        try:
            # Large native Docs can read slowly; writes retain their shorter bound.
            with self._token_lock:
                token = self.token_provider()
            headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
            if required_proof is not None and (self.verification_cache is None
                    or self.verification_cache.fresh(document_id) != required_proof):
                raise AdapterError('Text repair proof expired before request')
            if request_gate is not None:
                request_gate()
            result = self.request(method, 'https://docs.googleapis.com/v1/documents/' + document_id + suffix,
                                  body, headers, 90 if method == 'GET' else 45)
            if not isinstance(result, dict) or 'error' in result:
                raise ValueError()
            return result
        except Exception:
            raise AdapterError('Docs request failed; read current state before retrying any write') from None

    def read(self, document_id):
        # Omit formatting metadata that can multiply a plain-text archive into
        # many megabytes. Keep indices and suggestion markers; non-text elements
        # project to an empty object and are still rejected below.
        fields = ('revisionId,tabs(tabProperties(tabId),childTabs,documentTab('
                  'body(content(startIndex,endIndex,sectionBreak,paragraph('
                  'positionedObjectIds,elements(textRun(content,suggestedInsertionIds,'
                  'suggestedDeletionIds,suggestedTextStyleChanges))))),headers,footers,footnotes))')
        self.verification_counts['body_reads'] += 1
        raw = self._call(document_id, 'GET', '?' + urlencode({'includeTabsContent':'true', 'fields':fields}))
        try:
            if not isinstance(raw['revisionId'], str) or not raw['revisionId']:
                raise ValueError()
            tabs = raw['tabs']
            if len(tabs) != 1 or tabs[0].get('childTabs'):
                raise ValueError()
            tab = tabs[0]
            document_tab = tab['documentTab']
            if any(document_tab.get(k) for k in ('headers', 'footers', 'footnotes')):
                raise ValueError()
            content = document_tab['body']['content']
            text = []
            for block in content:
                if 'sectionBreak' in block:
                    continue
                if set(block) - {'startIndex', 'endIndex', 'paragraph'}:
                    raise ValueError()
                if block['paragraph'].get('positionedObjectIds'):
                    raise ValueError()
                for element in block['paragraph']['elements']:
                    if ('textRun' not in element or any(k.startswith('suggested') for k in element) or
                            any(k.startswith('suggested') for k in element['textRun'])):
                        raise ValueError()
                    text.append(element['textRun']['content'])
            return {'text': ''.join(text), 'revision': raw['revisionId'],
                    'tab_id': tab['tabProperties']['tabId'], 'end_index': content[-1]['endIndex']}
        except (KeyError, IndexError, TypeError, ValueError):
            raise AdapterError('Doc must have one plain text tab; no writes performed') from None

    def replace(self, document_id, text):
        return self.replace_verified(document_id, text)['changed']

    def prefetch_revisions(self, candidates, *, workers=1, progress=None):
        """Read unchanged output revisions; consume each result once on this client."""
        if type(workers) is not int or not 1 <= workers <= 3:
            raise ValueError('invalid revision probe worker bound')
        self._prefetched_revisions.clear()
        for document_id, desired_hash in candidates.items():
            if document_id not in self.write_ids:
                raise AdapterError('Document is not allowlisted')
            if not isinstance(desired_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', desired_hash):
                raise ValueError('invalid revision probe hash')
        if workers == 1 or self.verification_cache is None:
            return
        eligible = {}
        for document_id, desired_hash in candidates.items():
            proof = self.verification_cache.reusable(document_id, desired_hash)
            if proof is not None:
                eligible[document_id] = (desired_hash, proof)
        rate_lock = threading.Lock()
        next_launch = 0.0

        def throttle():
            nonlocal next_launch
            # Bound logical GET launches separately from the HTTP retry limit.
            with rate_lock:
                delay = max(0.0, next_launch - time.monotonic())
                if delay:
                    time.sleep(delay)
                next_launch = time.monotonic() + 1.0

        def probe(document_id):
            return self._call(document_id, 'GET', '?' + urlencode({'fields': 'revisionId'}),
                              request_gate=throttle)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(probe, identifier): identifier for identifier in eligible}
            try:
                for future in as_completed(futures):
                    identifier = futures[future]
                    desired_hash, proof = eligible[identifier]
                    result = {'hash': desired_hash, 'proof': proof}
                    self.verification_counts['revision_probes'] += 1
                    try:
                        revision = future.result().get('revisionId')
                        if not isinstance(revision, str) or not revision:
                            raise AdapterError('Invalid Docs revision probe')
                        result['revision'] = revision
                    except Exception as error:
                        result['error'] = error
                    self._prefetched_revisions[identifier] = result
                    if progress is not None:
                        progress()
            finally:
                for future in futures:
                    future.cancel()

    def _probe_write_state(self, document_id, proof):
        """Reuse verified plaintext structure only at its unchanged revision."""
        fields = ('revisionId,tabs(tabProperties(tabId),childTabs(tabProperties(tabId)),'
                  'documentTab(body(content(endIndex))))')
        self.verification_counts['revision_probes'] += 1
        raw = self._call(document_id, 'GET', '?' + urlencode({'includeTabsContent': 'true', 'fields': fields}))
        try:
            if raw['revisionId'] != proof['revision']:
                return None
            tabs = raw['tabs']
            if not isinstance(tabs, list) or len(tabs) != 1:
                return None
            tab = tabs[0]
            children = tab.get('childTabs', [])
            tab_id = tab['tabProperties']['tabId']
            if (not isinstance(children, list) or children
                    or not isinstance(tab_id, str) or not tab_id):
                return None
            content = tab['documentTab']['body']['content']
            if not isinstance(content, list) or not content:
                return None
            previous = 0
            for block in content:
                if not isinstance(block, dict) or set(block) != {'endIndex'}:
                    return None
                end_index = block['endIndex']
                if type(end_index) is not int or end_index <= previous:
                    return None
                previous = end_index
            if end_index < 2:
                return None
            return {'revision': raw['revisionId'], 'tab_id': tab_id, 'end_index': end_index}
        except (KeyError, TypeError, AttributeError):
            return None

    def replace_verified(self, document_id, text, *, previous_text=None):
        """Verify owned outputs; previous_text explicitly opts into guarded literal repair."""
        if document_id not in self.write_ids:
            raise AdapterError('Document is not allowlisted')
        if not isinstance(text, str) or len(text.encode()) > 1_000_000:
            raise ValueError('output exceeds bounds')
        if previous_text is not None and (not isinstance(previous_text, str)
                or len(previous_text.encode()) > 1_000_000):
            raise ValueError('previous output exceeds bounds')
        text = text.rstrip('\n') + '\n'
        desired_hash = canonical_hash(text)
        self._verified_readbacks.pop(document_id, None)
        prefetched = self._prefetched_revisions.pop(document_id, None)
        cache = self.verification_cache
        proof = cache.fresh(document_id) if cache is not None else None
        before = None
        if (proof and previous_text is not None and previous_text.rstrip('\n')
                and proof['hash'] != desired_hash
                and proof['hash'] == canonical_hash(previous_text)):
            # Explicit repair of an entire previously verified body. Literal
            # matching avoids requesting the expensive old body/geometry again.
            request = {'replaceAllText': {'containsText': {
                'text': previous_text.rstrip('\n'), 'matchCase': True},
                'replaceText': text.rstrip('\n')}}
            if cache.fresh(document_id) == proof:
                self.verification_counts['writes'] += 1
                response = self._call(document_id, 'POST', ':batchUpdate', {
                    'requests': [request],
                    'writeControl': {'requiredRevisionId': proof['revision']}}, required_proof=proof)
                replies = response.get('replies')
                if (not isinstance(replies, list) or len(replies) != 1
                        or not isinstance(replies[0], dict) or set(replies[0]) != {'replaceAllText'}
                        or not isinstance(replies[0]['replaceAllText'], dict)
                        or set(replies[0]['replaceAllText']) != {'occurrencesChanged'}
                        or type(replies[0]['replaceAllText']['occurrencesChanged']) is not int
                        or replies[0]['replaceAllText']['occurrencesChanged'] != 1):
                    raise AdapterError('Text repair replacement count is unconfirmed')
                return self._confirm_replacement(document_id, text, desired_hash)
            # Expiry during preparation earns no write permission.
            proof = cache.fresh(document_id)
        if proof and proof['hash'] == desired_hash:
            if (prefetched is not None and prefetched['hash'] == desired_hash
                    and prefetched['proof'] == proof):
                if 'error' in prefetched:
                    raise prefetched['error']
                revision = prefetched['revision']
            else:
                self.verification_counts['revision_probes'] += 1
                raw = self._call(document_id, 'GET', '?' + urlencode({'fields': 'revisionId'}))
                revision = raw.get('revisionId')
                if not isinstance(revision, str) or not revision:
                    raise AdapterError('Invalid Docs revision probe')
            # A slow response can cross the guarantee window. Only accept a
            # proof that remains fresh when the revision probe completes.
            if revision == proof['revision'] and cache.reusable(document_id, desired_hash) == proof:
                self.verification_counts['cache_hits'] += 1
                return {'changed': False, **proof, 'verification': 'revision_probe'}
        elif proof:
            # The proof already established plain text at this revision. Fetch
            # only its current UTF-16 range, retaining the full post-write read.
            before = self._probe_write_state(document_id, proof)
            if cache.fresh(document_id) != proof:
                before = None
        if before is None:
            before = self.read(document_id)
            if before['text'] == text:
                proof = (cache.remember(document_id, desired_hash, before['revision']) if cache is not None
                         else {'hash': desired_hash, 'revision': before['revision'], 'verified_at': time.time()})
                self._verified_readbacks[document_id] = before
                return {'changed': False, **proof, 'verification': 'full_readback'}
        tab = before['tab_id']
        requests = []
        if before['end_index'] > 2:
            requests.append({'deleteContentRange': {'range': {'startIndex': 1,
                            'endIndex': before['end_index'] - 1, 'tabId': tab}}})
        # Retain Docs' mandatory final newline.
        if text[:-1]:
            requests.append({'insertText': {'location': {'index': 1, 'tabId': tab}, 'text': text[:-1]}})
        self.verification_counts['writes'] += 1
        self._call(document_id, 'POST', ':batchUpdate', {'requests': requests,
                   'writeControl': {'requiredRevisionId': before['revision']}})
        return self._confirm_replacement(document_id, text, desired_hash)

    def _confirm_replacement(self, document_id, text, desired_hash):
        cache = self.verification_cache
        after = self.read(document_id)
        if after['text'] != text:
            raise AdapterError('Output readback differs; publication is not confirmed')
        proof = (cache.remember(document_id, desired_hash, after['revision']) if cache is not None
                 else {'hash': desired_hash, 'revision': after['revision'], 'verified_at': time.time()})
        self._verified_readbacks[document_id] = after
        return {'changed': True, **proof, 'verification': 'full_readback'}

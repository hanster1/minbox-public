"""Revision-guarded text-only Docs adapter for explicitly allowlisted archive files."""
import re
from urllib.parse import urlencode
from archive_io import AdapterError, GoogleAuth, _http_request


class DocsClient:
    def __init__(self, allowed_ids, credentials_file=None, *, request=None, token_provider=None, write_ids=None):
        self.allowed_ids = frozenset(allowed_ids)
        if not self.allowed_ids or any(not re.fullmatch(r'[A-Za-z0-9_-]+', i) for i in self.allowed_ids):
            raise ValueError('invalid document allowlist')
        self.write_ids = self.allowed_ids if write_ids is None else frozenset(write_ids)
        if not self.write_ids <= self.allowed_ids:
            raise ValueError('write allowlist must be a subset of readable documents')
        self.request = request or _http_request
        auth = GoogleAuth(credentials_file, scopes=['https://www.googleapis.com/auth/drive.file'])
        self.token_provider = token_provider or auth.token
        self._verified_readbacks = {}

    def take_verified_readback(self, document_id):
        """Consume the readback from the immediately preceding replacement once."""
        return self._verified_readbacks.pop(document_id, None)

    def _call(self, document_id, method, suffix, body=None):
        if document_id not in self.allowed_ids or (method != 'GET' and document_id not in self.write_ids):
            raise AdapterError('Document is not allowlisted')
        try:
            # Large native Docs can read slowly; writes retain their shorter bound.
            result = self.request(method, 'https://docs.googleapis.com/v1/documents/' + document_id + suffix,
                                  body, {'Authorization': 'Bearer ' + self.token_provider(),
                                         'Content-Type': 'application/json'}, 90 if method == 'GET' else 45)
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
        raw = self._call(document_id, 'GET', '?' + urlencode({'includeTabsContent':'true', 'fields':fields}))
        try:
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
        """Only publisher-owned outputs. Input correction Docs must never be passed here."""
        if not isinstance(text, str) or len(text.encode()) > 1_000_000:
            raise ValueError('output exceeds bounds')
        text = text.rstrip('\n') + '\n'
        self._verified_readbacks.pop(document_id, None)
        before = self.read(document_id)
        if before['text'] == text:
            self._verified_readbacks[document_id] = before
            return False
        tab = before['tab_id']
        requests = []
        if before['end_index'] > 2:
            requests.append({'deleteContentRange': {'range': {'startIndex': 1,
                            'endIndex': before['end_index'] - 1, 'tabId': tab}}})
        # Retain Docs' mandatory final newline.
        if text[:-1]:
            requests.append({'insertText': {'location': {'index': 1, 'tabId': tab}, 'text': text[:-1]}})
        self._call(document_id, 'POST', ':batchUpdate', {'requests': requests,
                   'writeControl': {'requiredRevisionId': before['revision']}})
        after = self.read(document_id)
        if after['text'] != text:
            raise AdapterError('Output readback differs; publication is not confirmed')
        self._verified_readbacks[document_id] = after
        return True

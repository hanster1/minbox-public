import unittest
import json
import copy
from pathlib import Path
import tempfile
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from archive_drive import DocsClient, DocsVerificationCache, VERIFICATION_MAX_AGE, canonical_hash
from archive_io import AdapterError


def write_probe(url):
    fields = parse_qs(urlparse(url).query).get('fields', [''])[0]
    return 'endIndex' in fields and 'textRun' not in fields


class Transport:
    def __init__(self, text='old\n'):
        self.text, self.revision, self.posts = text, 1, []
        self.fail = None
        self.calls = []
    def __call__(self, method, url, body, headers, timeout):
        self.calls.append((method, parse_qs(urlparse(url).query)))
        if method == 'GET':
            if parse_qs(urlparse(url).query).get('fields') == ['revisionId']:
                return {'revisionId': str(self.revision)}
            value = {'revisionId': str(self.revision), 'tabs': [{'tabProperties': {'tabId': 't.0'},
                    'documentTab': {'body': {'content': [
                        {'endIndex': 1, 'sectionBreak': {}},
                        {'startIndex': 1, 'endIndex': len(self.text.encode('utf-16-le')) // 2 + 1,
                         'paragraph': {'elements': [{'textRun': {'content': self.text}}]}}]}}}]}
            if write_probe(url):
                content = value['tabs'][0]['documentTab']['body']['content']
                value['tabs'][0]['documentTab']['body']['content'] = [{'endIndex': block['endIndex']} for block in content]
            return value
        self.posts.append(body)
        if self.fail == 'conflict':
            raise RuntimeError('conflict')
        assert body['writeControl']['requiredRevisionId'] == str(self.revision)
        response = {}
        if 'replaceAllText' in body['requests'][0]:
            replacement = body['requests'][0]['replaceAllText']
            body_text = self.text[:-1]
            count = body_text.count(replacement['containsText']['text'])
            self.text = body_text.replace(replacement['containsText']['text'], replacement['replaceText']) + '\n'
            response = {'replies': [{'replaceAllText': {'occurrencesChanged': count}}]}
        else:
            self.text = next((r['insertText']['text'] for r in body['requests'] if 'insertText' in r), '') + '\n'
        self.revision += 1
        if self.fail == 'uncertain':
            raise RuntimeError('lost response')
        return response


class CachedDocsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'docs-cache.json'
        self.binding = {'account': 'synthetic@example.invalid', 'owner': 'Synthetic Owner',
                        'root_id': 'root', 'parent_id': 'parent'}
        self.now = 1000
        self.transport = Transport()

    def cache(self, binding=None):
        return DocsVerificationCache(self.path, binding or self.binding, clock=lambda: self.now)

    def client(self, *, cache=None, request=None):
        return DocsClient(['doc', 'corrections'], write_ids=['doc'],
                          request=request or self.transport, token_provider=lambda: 'synthetic',
                          verification_cache=cache or self.cache())

    def test_explicit_text_repair_is_literal_guarded_and_strictly_read_back(self):
        old = 'First 😀 [a.*] "quoted"\nsecond line $1 (literal)\\path'
        self.client().replace('doc', old)
        proof = self.cache().fresh('doc')
        self.now += 60
        client = self.client()
        result = client.replace_verified('doc', 'Short 🐈\nnew text', previous_text=old + '\n\n')
        self.assertEqual(client.verification_counts, {'body_reads': 1, 'revision_probes': 0,
                                                     'cache_hits': 0, 'writes': 1})
        self.assertEqual(self.transport.posts[-1], {'requests': [{'replaceAllText': {
            'containsText': {'text': old, 'matchCase': True}, 'replaceText': 'Short 🐈\nnew text'}}],
            'writeControl': {'requiredRevisionId': proof['revision']}})
        self.assertEqual(result['verification'], 'full_readback')
        self.assertEqual(client.take_verified_readback('doc')['text'], 'Short 🐈\nnew text\n')
        self.assertIsNone(client.take_verified_readback('doc'))
        value = json.loads(self.path.read_text())
        self.assertEqual(value['version'], 1)
        self.assertEqual(set(value['documents']['doc']), {'hash', 'revision', 'verified_at'})

    def test_text_repair_can_empty_body_and_empty_old_uses_normal_path(self):
        self.client().replace('doc', 'original')
        client = self.client()
        result = client.replace_verified('doc', '', previous_text='original')
        self.assertTrue(result['changed'])
        self.assertEqual(client.take_verified_readback('doc')['text'], '\n')
        self.assertEqual(self.transport.posts[-1]['requests'][0]['replaceAllText']['replaceText'], '')
        for empty in ('', '\n\n'):
            with self.subTest(previous_text=empty):
                client = self.client()
                client.replace_verified('doc', 'content' + empty, previous_text=empty)
                self.assertNotIn('replaceAllText', self.transport.posts[-1]['requests'][0])
                self.client().replace('doc', '')

    def test_text_repair_invalid_input_and_readonly_targets_make_no_requests(self):
        for previous in (True, 4, [], '😀' * 250001):
            with self.subTest(previous_type=type(previous)):
                with self.assertRaises(ValueError):
                    self.client().replace_verified('doc', 'changed', previous_text=previous)
        for identifier in ('corrections', 'other'):
            with self.assertRaises(AdapterError):
                self.client().replace_verified(identifier, 'changed', previous_text='old')
        self.assertEqual(self.transport.calls, [])

    def test_text_repair_requires_matching_fresh_bound_proof_and_changes(self):
        for mode in ('missing', 'mismatch', 'expired', 'future', 'binding', 'unchanged', 'omitted'):
            with self.subTest(mode=mode):
                if self.path.exists():
                    self.path.unlink()
                self.now = 1000
                self.transport = Transport()
                self.client().replace('doc', 'original')
                binding = dict(self.binding)
                if mode == 'missing':
                    self.path.unlink()
                elif mode == 'expired':
                    self.now += VERIFICATION_MAX_AGE
                elif mode == 'future':
                    self.now -= 1
                elif mode == 'binding':
                    binding['account'] = 'other@example.invalid'
                client = self.client(cache=self.cache(binding))
                before_posts = len(self.transport.posts)
                previous = 'wrong' if mode == 'mismatch' else None if mode == 'omitted' else 'original'
                client.replace_verified('doc', 'original' if mode == 'unchanged' else 'changed',
                                        previous_text=previous)
                self.assertTrue(all('replaceAllText' not in p['requests'][0]
                                    for p in self.transport.posts[before_posts:]))
                if mode == 'unchanged':
                    self.assertEqual(client.verification_counts['writes'], 0)

    def test_text_repair_expiry_during_preparation_falls_back_without_literal_post(self):
        self.client().replace('doc', 'original')
        client = self.client()
        from archive_drive import canonical_hash as real_hash
        def expiring_hash(text):
            value = real_hash(text)
            if text == 'original':
                self.now += VERIFICATION_MAX_AGE
            return value
        with patch('archive_drive.canonical_hash', side_effect=expiring_hash):
            client.replace_verified('doc', 'changed', previous_text='original')
        self.assertNotIn('replaceAllText', self.transport.posts[-1]['requests'][0])
        self.assertEqual(client.verification_counts['body_reads'], 2)

    def test_text_repair_expiry_during_token_preparation_makes_no_post(self):
        self.client().replace('doc', 'original')
        previous = self.path.read_bytes()
        client = self.client()
        def token():
            self.now += VERIFICATION_MAX_AGE
            return 'synthetic'
        client.token_provider = token
        original_calls = len(self.transport.calls)
        with self.assertRaises(AdapterError):
            client.replace_verified('doc', 'changed', previous_text='original')
        self.assertEqual(len(self.transport.calls), original_calls)
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertIsNone(client.take_verified_readback('doc'))

    def test_text_repair_count_failures_never_renew_proof(self):
        responses = ({}, {'replies': []}, {'replies': [{}]},
            {'replies': [{'replaceAllText': {}}]},
            *({'replies': [{'replaceAllText': {'occurrencesChanged': count}}]}
              for count in (0, 2, True, '1', 1.0)),
            {'replies': [{'replaceAllText': {'occurrencesChanged': 1}}] * 2})
        for response in responses:
            with self.subTest(response=response):
                if self.path.exists():
                    self.path.unlink()
                self.transport = Transport()
                self.client().replace('doc', 'original')
                previous = self.path.read_bytes()
                def request(*args):
                    result = self.transport(*args)
                    return response if args[0] == 'POST' else result
                client = self.client(request=request)
                with self.assertRaisesRegex(AdapterError, 'count is unconfirmed'):
                    client.replace_verified('doc', 'changed', previous_text='original')
                self.assertEqual(self.path.read_bytes(), previous)
                self.assertEqual(client.verification_counts['body_reads'], 0)
                self.assertIsNone(client.take_verified_readback('doc'))

    def test_text_repair_write_race_ambiguity_and_strict_readback_fail_closed(self):
        modes = ('race', 'uncertain', 'readback', 'mismatch', 'suggestion', 'nontext',
                 'extra_tab', 'header', 'persist')
        for mode in modes:
            with self.subTest(mode=mode):
                if self.path.exists():
                    self.path.unlink()
                self.transport = Transport()
                self.client().replace('doc', 'original')
                previous = self.path.read_bytes()
                original_posts = len(self.transport.posts)
                cache = self.cache()
                if mode == 'uncertain':
                    self.transport.fail = 'uncertain'
                def request(*args):
                    if mode == 'race' and args[0] == 'POST':
                        self.transport.text = 'concurrent edit\n'
                        self.transport.revision += 1
                    value = self.transport(*args)
                    if args[0] == 'GET':
                        if mode == 'readback':
                            raise TimeoutError('synthetic readback failure')
                        tab = value['tabs'][0]['documentTab']
                        if mode == 'mismatch':
                            tab['body']['content'][-1]['paragraph']['elements'][0]['textRun']['content'] = 'different\n'
                        elif mode == 'suggestion':
                            tab['body']['content'][-1]['paragraph']['elements'][0]['textRun']['suggestedInsertionIds'] = ['s']
                        elif mode == 'nontext':
                            tab['body']['content'].append({'table': {}})
                        elif mode == 'extra_tab':
                            value['tabs'].append(copy.deepcopy(value['tabs'][0]))
                        elif mode == 'header':
                            tab['headers'] = {'h': {}}
                    return value
                client = self.client(cache=cache, request=request)
                if mode == 'persist':
                    with patch('archive_drive.write_json', side_effect=OSError('synthetic failure')):
                        with self.assertRaises(AdapterError):
                            client.replace_verified('doc', 'changed', previous_text='original')
                else:
                    with self.assertRaises(AdapterError):
                        client.replace_verified('doc', 'changed', previous_text='original')
                self.assertEqual(len(self.transport.posts), original_posts + 1)
                self.assertEqual(self.path.read_bytes(), previous)
                self.assertEqual(cache.documents, self.cache().documents)
                self.assertIsNone(client.take_verified_readback('doc'))

    def test_warm_restart_uses_only_revision_probe_without_fabricated_readback(self):
        first = self.client()
        cold = first.replace_verified('doc', 'new')
        self.assertTrue(cold['changed'])
        self.assertEqual(first.verification_counts, {'body_reads': 2, 'revision_probes': 0,
                                                   'cache_hits': 0, 'writes': 1})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('new', self.path.read_text())
        self.now += 60
        resumed = self.client()
        warm = resumed.replace_verified('doc', 'new\n\n')
        self.assertEqual(warm['verification'], 'revision_probe')
        self.assertEqual(warm['verified_at'], cold['verified_at'])
        self.assertEqual(warm['hash'], canonical_hash('new'))
        self.assertEqual(resumed.verification_counts, {'body_reads': 0, 'revision_probes': 1,
                                                     'cache_hits': 1, 'writes': 0})
        self.assertIsNone(resumed.take_verified_readback('doc'))
        resumed.read('corrections')
        self.assertEqual(resumed.verification_counts['body_reads'], 1)
        with self.assertRaises(AdapterError):
            resumed.replace_verified('corrections', 'old')

    def test_warm_changed_restart_probes_utf16_range_then_fully_reads_back(self):
        old = self.client().replace_verified('doc', 'old😀')
        saved = self.path.read_bytes()
        self.now += 60
        def request(*args):
            if args[0] == 'POST' or write_probe(args[1]):
                self.assertEqual(self.path.read_bytes(), saved)
            return self.transport(*args)
        changed = self.client(request=request)
        result = changed.replace_verified('doc', 'new😀')
        self.assertEqual(changed.verification_counts, {'body_reads': 1, 'revision_probes': 1,
                                                     'cache_hits': 0, 'writes': 1})
        post = self.transport.posts[-1]
        self.assertEqual(post['writeControl'], {'requiredRevisionId': old['revision']})
        self.assertEqual(post['requests'][0]['deleteContentRange']['range'],
                         {'startIndex': 1, 'endIndex': 6, 'tabId': 't.0'})
        self.assertEqual((result['changed'], result['verification']), (True, 'full_readback'))
        self.assertEqual(result['verified_at'], self.now)
        self.assertEqual(changed.take_verified_readback('doc')['text'], 'new😀\n')
        self.assertIsNone(changed.take_verified_readback('doc'))
        cache = json.loads(self.path.read_text())
        self.assertEqual(cache['version'], 1)
        self.assertEqual(set(cache['documents']['doc']), {'hash', 'revision', 'verified_at'})
        self.assertNotIn('😀', self.path.read_text())

    def test_invalid_changed_geometry_falls_back_to_full_read(self):
        cases = [
            (('revisionId',), None), (('revisionId',), 1),
            (('tabs',), []), (('tabs',), {}), (('tabs',), [None]), (('tabs',), [{}, {}]),
            (('tabs', 0, 'childTabs'), [{'tabProperties': {'tabId': 'child'}}]),
            (('tabs', 0, 'childTabs'), {}),
            (('tabs', 0, 'tabProperties', 'tabId'), ''),
            (('tabs', 0, 'tabProperties', 'tabId'), True),
            (('tabs', 0, 'documentTab', 'body', 'content'), []),
            (('tabs', 0, 'documentTab', 'body', 'content'), {}),
            (('tabs', 0, 'documentTab', 'body', 'content'), [{}]),
            (('tabs', 0, 'documentTab', 'body', 'content'), [{'endIndex': True}]),
            (('tabs', 0, 'documentTab', 'body', 'content'), [{'endIndex': 2.0}]),
            (('tabs', 0, 'documentTab', 'body', 'content'), [{'endIndex': 1}]),
            (('tabs', 0, 'documentTab', 'body', 'content'), [{'endIndex': 0}]),
            (('tabs', 0, 'documentTab', 'body', 'content'), [{'endIndex': 2}, {'endIndex': 1}]),
            (('tabs', 0, 'documentTab', 'body', 'content'), [{'endIndex': 2}, {'endIndex': 2}]),
            (('tabs', 0, 'documentTab', 'body', 'content'), [{'endIndex': 2, 'table': {}}]),
        ]
        for path, invalid in cases:
            with self.subTest(path=path, invalid=invalid):
                if self.path.exists():
                    self.path.unlink()
                self.transport = Transport()
                self.client().replace('doc', 'original')
                def request(*args):
                    value = self.transport(*args)
                    if write_probe(args[1]):
                        target = value
                        for key in path[:-1]:
                            target = target[key]
                        target[path[-1]] = copy.deepcopy(invalid)
                    return value
                changed = self.client(request=request)
                self.assertTrue(changed.replace('doc', 'changed'))
                self.assertEqual(changed.verification_counts['body_reads'], 2)
                self.assertEqual(changed.verification_counts['revision_probes'], 1)

    def test_changed_probe_revision_mismatch_validates_current_structure(self):
        self.client().replace('doc', 'original')
        self.transport.text = 'external edit\n'
        self.transport.revision += 1
        changed = self.client()
        self.assertTrue(changed.replace('doc', 'changed'))
        self.assertEqual(changed.verification_counts['body_reads'], 2)
        self.assertEqual(changed.verification_counts['revision_probes'], 1)
        self.assertEqual(self.transport.posts[-1]['writeControl'], {'requiredRevisionId': '3'})

    def test_changed_probe_expiry_or_replaced_proof_forces_full_read(self):
        for mode in ('expired', 'replaced'):
            with self.subTest(mode=mode):
                if self.path.exists():
                    self.path.unlink()
                self.transport = Transport()
                self.client().replace('doc', 'original')
                cache = self.cache()
                self.now += VERIFICATION_MAX_AGE - 1
                def request(*args):
                    value = self.transport(*args)
                    if write_probe(args[1]):
                        if mode == 'expired':
                            self.now += 2
                        else:
                            cache.documents['doc'] = {**cache.documents['doc'], 'hash': '0' * 64}
                    return value
                changed = self.client(cache=cache, request=request)
                self.assertTrue(changed.replace('doc', 'changed'))
                self.assertEqual(changed.verification_counts['body_reads'], 2)

    def test_changed_cold_expired_future_and_binding_mismatch_read_full_bodies(self):
        for mode in ('cold', 'expired', 'future', *self.binding):
            with self.subTest(mode=mode):
                if self.path.exists():
                    self.path.unlink()
                self.transport = Transport()
                self.client().replace('doc', 'original')
                binding = dict(self.binding)
                if mode == 'cold':
                    self.path.unlink()
                elif mode in ('expired', 'future'):
                    value = json.loads(self.path.read_text())
                    value['documents']['doc']['verified_at'] = (
                        self.now - VERIFICATION_MAX_AGE if mode == 'expired' else self.now + 1)
                    self.path.write_text(json.dumps(value))
                else:
                    binding[mode] = 'different'
                changed = self.client(cache=self.cache(binding))
                self.assertTrue(changed.replace('doc', 'changed'))
                self.assertEqual(changed.verification_counts['body_reads'], 2)
                self.assertEqual(changed.verification_counts['revision_probes'], 0)

    def test_changed_probe_failure_and_revision_race_do_not_write_or_renew_proof(self):
        for mode in ('probe', 'race'):
            with self.subTest(mode=mode):
                if self.path.exists():
                    self.path.unlink()
                self.transport = Transport()
                self.client().replace('doc', 'original')
                previous = self.path.read_bytes()
                self.now += 60
                def request(*args):
                    if mode == 'probe' and write_probe(args[1]):
                        raise TimeoutError('synthetic probe failure')
                    if mode == 'race' and args[0] == 'POST':
                        self.transport.text = 'concurrent edit\n'
                        self.transport.revision += 1
                    return self.transport(*args)
                changed = self.client(request=request)
                with self.assertRaises(AdapterError):
                    changed.replace('doc', 'changed')
                self.assertEqual(changed.verification_counts['body_reads'], 0)
                self.assertEqual(self.path.read_bytes(), previous)
                self.assertIsNone(changed.take_verified_readback('doc'))
                self.assertEqual(self.transport.text, 'concurrent edit\n' if mode == 'race' else 'original\n')

    def test_cached_input_still_requires_full_read_and_cannot_be_replaced(self):
        cache = self.cache()
        cache.remember('corrections', canonical_hash(self.transport.text), str(self.transport.revision))
        client = self.client(cache=cache)
        for identifier in ('corrections', 'other'):
            with self.assertRaises(AdapterError):
                client.replace_verified(identifier, 'changed')
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(client.read('corrections')['text'], 'old\n')
        self.assertEqual(client.verification_counts, {'body_reads': 1, 'revision_probes': 0,
                                                    'cache_hits': 0, 'writes': 0})

    def test_changed_post_readback_and_persistence_failures_keep_previous_proof(self):
        for mode in ('uncertain', 'readback', 'mismatch', 'suggestion', 'nontext', 'extra_tab', 'header', 'persist'):
            with self.subTest(mode=mode):
                if self.path.exists():
                    self.path.unlink()
                self.transport = Transport()
                self.client().replace('doc', 'original')
                previous = self.path.read_bytes()
                original_posts = len(self.transport.posts)
                cache = self.cache()
                self.now += 60
                if mode == 'uncertain':
                    self.transport.fail = 'uncertain'
                def request(*args):
                    value = self.transport(*args)
                    if args[0] == 'GET' and not write_probe(args[1]) and len(self.transport.posts) > original_posts:
                        if mode == 'readback':
                            raise TimeoutError('synthetic readback failure')
                        paragraph = value['tabs'][0]['documentTab']['body']['content'][-1]['paragraph']
                        if mode == 'mismatch':
                            paragraph['elements'][0]['textRun']['content'] = 'unexpected text\n'
                        elif mode == 'suggestion':
                            paragraph['elements'][0]['textRun']['suggestedInsertionIds'] = ['suggestion']
                        elif mode == 'nontext':
                            value['tabs'][0]['documentTab']['body']['content'].append({'table': {}})
                        elif mode == 'extra_tab':
                            value['tabs'].append(copy.deepcopy(value['tabs'][0]))
                        elif mode == 'header':
                            value['tabs'][0]['documentTab']['headers'] = {'synthetic-header': {}}
                    return value
                changed = self.client(cache=cache, request=request)
                if mode == 'persist':
                    with patch('archive_drive.write_json', side_effect=OSError('synthetic persistence failure')):
                        with self.assertRaises(AdapterError):
                            changed.replace('doc', 'changed')
                else:
                    with self.assertRaises(AdapterError):
                        changed.replace('doc', 'changed')
                self.assertEqual(self.path.read_bytes(), previous)
                self.assertEqual(cache.documents, self.cache().documents)
                self.assertIsNone(changed.take_verified_readback('doc'))
                self.transport.fail = None
                recovered = self.client()
                self.assertFalse(recovered.replace('doc', 'changed'))
                self.assertEqual(recovered.verification_counts['body_reads'], 1)
                self.assertEqual(len(self.transport.posts), original_posts + 1)

    def test_changed_hash_reuses_structure_external_edits_require_full_read(self):
        self.client().replace('doc', 'new')
        changed = self.client()
        self.assertTrue(changed.replace('doc', 'changed'))
        self.assertEqual(changed.verification_counts['revision_probes'], 1)
        self.assertEqual(changed.verification_counts['body_reads'], 1)
        self.transport.text = 'external edit\n'
        self.transport.revision += 1
        edited = self.client()
        self.assertTrue(edited.replace('doc', 'changed'))
        self.assertEqual(edited.verification_counts['revision_probes'], 1)
        self.assertEqual(edited.verification_counts['body_reads'], 2)
        # Formatting-only changes still advance revision and require a structural read.
        self.transport.revision += 1
        formatted = self.client()
        self.assertFalse(formatted.replace('doc', 'changed'))
        self.assertEqual(formatted.verification_counts['body_reads'], 1)

    def test_expired_future_and_cold_entries_read_bodies_without_probe(self):
        self.client().replace('doc', 'new')
        for stamp in (self.now - VERIFICATION_MAX_AGE, self.now + 1):
            value = json.loads(self.path.read_text())
            value['documents']['doc']['verified_at'] = stamp
            self.path.write_text(json.dumps(value))
            client = self.client()
            self.assertFalse(client.replace('doc', 'new'))
            self.assertEqual(client.verification_counts['revision_probes'], 0)
            self.assertEqual(client.verification_counts['body_reads'], 1)
        self.path.unlink()
        cold = self.client()
        self.assertFalse(cold.replace('doc', 'new'))
        self.assertEqual(cold.verification_counts['body_reads'], 1)

    def test_namespace_bindings_cannot_reuse_other_proofs(self):
        self.client().replace('doc', 'new')
        for field in self.binding:
            other = {**self.binding, field: 'different'}
            cache = self.cache(other)
            self.assertIsNone(cache.reusable('doc', canonical_hash('new')))
            self.assertEqual(cache.documents, {})

    def test_slow_probe_crossing_full_verification_expiry_reads_body(self):
        self.client().replace('doc', 'new')
        self.now += VERIFICATION_MAX_AGE - 1
        def slow_probe(*args):
            value = self.transport(*args)
            if parse_qs(urlparse(args[1]).query).get('fields') == ['revisionId']:
                self.now += 2
            return value
        client = self.client(request=slow_probe)
        proof = client.replace_verified('doc', 'new')
        self.assertEqual(proof['verification'], 'full_readback')
        self.assertEqual(client.verification_counts['body_reads'], 1)
        self.assertEqual(client.verification_counts['cache_hits'], 0)

    def test_one_changed_document_leaves_other_documents_on_revision_probes(self):
        states = {identifier: Transport() for identifier in ('one', 'two')}
        def request(*args):
            identifier = urlparse(args[1]).path.split('/')[-1].split(':')[0]
            return states[identifier](*args)
        first = DocsClient(states, request=request, token_provider=lambda: 'synthetic',
                           verification_cache=self.cache())
        first.replace('one', 'first body')
        first.replace('two', 'second body')
        resumed = DocsClient(states, request=request, token_provider=lambda: 'synthetic',
                             verification_cache=self.cache())
        self.assertTrue(resumed.replace('one', 'changed body'))
        self.assertFalse(resumed.replace('two', 'second body'))
        self.assertEqual(resumed.verification_counts,
                         {'body_reads': 1, 'revision_probes': 2, 'cache_hits': 1, 'writes': 1})

    def test_empty_chunk_withdrawal_is_verified_then_reused(self):
        first = self.client()
        self.assertTrue(first.replace('doc', ''))
        self.assertEqual(self.transport.text, '\n')
        self.assertFalse(self.client().replace('doc', ''))
        self.assertEqual(len(self.transport.posts), 1)

    def test_probe_errors_fail_closed_without_read_or_write(self):
        self.client().replace('doc', 'new')
        def failed_probe(*args):
            raise TimeoutError('synthetic failed probe')
        failed = self.client(request=failed_probe)
        with self.assertRaises(AdapterError):
            failed.replace('doc', 'new')
        self.assertEqual(failed.verification_counts['body_reads'], 0)
        self.assertIsNone(failed.take_verified_readback('doc'))
        self.assertFalse(self.client().replace('doc', 'new'))

    def test_revision_changes_require_structural_validation(self):
        self.client().replace('doc', 'new')
        self.transport.revision += 1
        def unsupported(*args):
            value = self.transport(*args)
            if 'tabs' in value:
                value['tabs'][0]['documentTab']['body']['content'].append({'table': {}})
            return value
        failed = self.client(request=unsupported)
        with self.assertRaises(AdapterError):
            failed.replace('doc', 'new')
        self.assertIsNone(failed.take_verified_readback('doc'))
        self.assertEqual(len(self.transport.posts), 1)

    def test_uncertain_post_readback_and_persistence_recover_without_repeated_post(self):
        for failure in ('post', 'readback', 'persist'):
            with self.subTest(failure=failure):
                if self.path.exists():
                    self.path.unlink()
                self.transport = Transport()
                cache = self.cache()
                if failure == 'post':
                    self.transport.fail = 'uncertain'
                def request(*args):
                    value = self.transport(*args)
                    if failure == 'readback' and args[0] == 'GET' and self.transport.posts:
                        raise TimeoutError('synthetic failed readback')
                    return value
                client = self.client(cache=cache, request=request)
                if failure == 'persist':
                    with patch('archive_drive.write_json', side_effect=OSError('synthetic disk error')):
                        with self.assertRaises(AdapterError):
                            client.replace('doc', 'new')
                else:
                    with self.assertRaises(AdapterError):
                        client.replace('doc', 'new')
                self.assertIsNone(client.take_verified_readback('doc'))
                self.assertEqual(cache.documents, {})
                self.transport.fail = None
                recovered = self.client()
                self.assertFalse(recovered.replace('doc', 'new'))
                self.assertEqual(recovered.verification_counts['body_reads'], 1)
                self.assertEqual(len(self.transport.posts), 1)

    def test_private_and_malformed_proofs_fail_closed(self):
        self.client().replace('doc', 'new')
        self.path.chmod(0o644)
        with self.assertRaises(AdapterError):
            self.cache()
        self.path.chmod(0o600)
        value = json.loads(self.path.read_text())
        value['documents']['doc']['verified_at'] = float('nan')
        self.path.write_text(json.dumps(value))
        with self.assertRaises(AdapterError):
            self.cache()


class DocsTests(unittest.TestCase):
    def test_slow_reads_get_more_time_without_extending_or_replaying_writes(self):
        transport = Transport()
        calls = []
        def bounded(method, url, body, headers, timeout):
            calls.append((method, timeout))
            if method == 'GET' and timeout < 90:
                raise TimeoutError('synthetic slow document read')
            if method == 'POST':
                self.assertEqual(timeout, 45)
            return transport(method, url, body, headers, timeout)
        client = DocsClient(['doc'], request=bounded, token_provider=lambda: 'test')
        transport.fail = 'uncertain'
        with self.assertRaises(AdapterError):
            client.replace('doc', 'new')
        transport.fail = None
        self.assertFalse(client.replace('doc', 'new'))
        self.assertEqual(len(transport.posts), 1)
        self.assertTrue(all(timeout == 90 for method, timeout in calls if method == 'GET'))

    def test_verified_readback_is_consumed_once_and_failed_write_clears_it(self):
        transport = Transport()
        client = DocsClient(['doc'], request=transport, token_provider=lambda: 'test')
        self.assertTrue(client.replace('doc', 'new'))
        self.assertEqual(client.take_verified_readback('doc')['text'], 'new\n')
        self.assertIsNone(client.take_verified_readback('doc'))
        self.assertFalse(client.replace('doc', 'new'))
        transport.fail = 'conflict'
        with self.assertRaises(AdapterError):
            client.replace('doc', 'changed')
        self.assertIsNone(client.take_verified_readback('doc'))

    def test_noop_and_unicode_guarded_write(self):
        transport = Transport('old😀\n')
        client = DocsClient(['doc'], request=transport, token_provider=lambda: 'test')
        self.assertTrue(client.replace('doc', 'new😀'))
        self.assertEqual(transport.posts[0]['requests'][0]['deleteContentRange']['range']['endIndex'], 6)
        self.assertFalse(client.replace('doc', 'new😀'))
        self.assertEqual(len(transport.posts), 1)
    def test_conflict_and_uncertain_reconcile(self):
        for mode in ['conflict', 'uncertain']:
            transport = Transport()
            transport.fail = mode
            client = DocsClient(['doc'], request=transport, token_provider=lambda: 'test')
            with self.assertRaises(AdapterError):
                client.replace('doc', 'new')
            self.assertEqual(len(transport.posts), 1)
            transport.fail = None
            changed = client.replace('doc', 'new')
            self.assertEqual(changed, mode == 'conflict')
    def test_read_only_input_cannot_be_written(self):
        transport = Transport()
        client = DocsClient(['input','output'], request=transport, token_provider=lambda: 'test', write_ids=['output'])
        self.assertEqual(client.read('input')['text'], 'old\n')
        with self.assertRaises(AdapterError):
            client.replace('input', 'changed')
        self.assertEqual(transport.posts, [])

    def test_partial_read_still_rejects_suggestions_and_nontext_objects(self):
        for mode in ('suggestion', 'empty_element', 'positioned_object'):
            transport = Transport()
            def modified(*args):
                data = transport(*args)
                paragraph = data['tabs'][0]['documentTab']['body']['content'][1]['paragraph']
                if mode == 'suggestion':
                    paragraph['elements'][0]['textRun']['suggestedDeletionIds'] = ['suggestion']
                elif mode == 'empty_element':
                    paragraph['elements'].append({})
                else:
                    paragraph['positionedObjectIds'] = ['image']
                return data
            client = DocsClient(['doc'], request=modified, token_provider=lambda:'test')
            with self.assertRaises(AdapterError):
                client.replace('doc', 'changed')
            self.assertEqual(transport.posts, [])

    def test_allowlist_and_nontext_refused(self):
        transport = Transport()
        client = DocsClient(['doc'], request=transport, token_provider=lambda: 'test')
        with self.assertRaises(AdapterError):
            client.read('other')
        def table(*args):
            data = transport(*args)
            data['tabs'][0]['documentTab']['body']['content'].append({'table': {}})
            return data
        client.request = table
        with self.assertRaises(AdapterError):
            client.replace('doc', 'new')
        self.assertEqual(transport.posts, [])



if __name__ == '__main__':
    unittest.main()

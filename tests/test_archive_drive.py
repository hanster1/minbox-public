import unittest
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from archive_drive import DocsClient, DocsVerificationCache, VERIFICATION_MAX_AGE, canonical_hash
from archive_io import AdapterError


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
            return {'revisionId': str(self.revision), 'tabs': [{'tabProperties': {'tabId': 't.0'},
                    'documentTab': {'body': {'content': [
                        {'endIndex': 1, 'sectionBreak': {}},
                        {'startIndex': 1, 'endIndex': len(self.text.encode('utf-16-le')) // 2 + 1,
                         'paragraph': {'elements': [{'textRun': {'content': self.text}}]}}]}}}]}
        self.posts.append(body)
        if self.fail == 'conflict':
            raise RuntimeError('conflict')
        assert body['writeControl']['requiredRevisionId'] == str(self.revision)
        self.text = next((r['insertText']['text'] for r in body['requests'] if 'insertText' in r), '') + '\n'
        self.revision += 1
        if self.fail == 'uncertain':
            raise RuntimeError('lost response')
        return {}


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

    def test_changed_hash_external_text_and_formatting_force_full_verification(self):
        self.client().replace('doc', 'new')
        changed = self.client()
        self.assertTrue(changed.replace('doc', 'changed'))
        self.assertEqual(changed.verification_counts['revision_probes'], 0)
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
                         {'body_reads': 2, 'revision_probes': 1, 'cache_hits': 1, 'writes': 1})

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

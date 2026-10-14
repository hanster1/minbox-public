import unittest
from archive_drive import DocsClient
from archive_io import AdapterError


class Transport:
    def __init__(self, text='old\n'):
        self.text, self.revision, self.posts = text, 1, []
        self.fail = None
    def __call__(self, method, url, body, headers, timeout):
        if method == 'GET':
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

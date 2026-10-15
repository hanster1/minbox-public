"""Optional SDK adapter tests: auth, rebinding, tool boundary and freshness."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

from archive_search_mcp import load_token

SDK = importlib.util.find_spec('mcp') is not None


class TokenFileTests(unittest.TestCase):
    def test_private_token_and_rejected_permissions_symlink_fifo(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'token'
            p.write_text('a' * 64)
            p.chmod(0o600)
            self.assertEqual(load_token(p), b'a' * 64)
            p.chmod(0o644)
            with self.assertRaises(ValueError): load_token(p)
            p.chmod(0o600)
            link = Path(folder) / 'link'
            link.symlink_to(p)
            with self.assertRaises(OSError): load_token(link)
            fifo = Path(folder) / 'fifo'
            os.mkfifo(fifo, 0o600)
            with self.assertRaises(ValueError): load_token(fifo)
            p.write_text('too-short')
            with self.assertRaises(ValueError): load_token(p)


@unittest.skipUnless(SDK, 'Optional requirements-search.txt environment not installed')
class MCPBoundaryTests(unittest.TestCase):
    def setUp(self):
        from starlette.testclient import TestClient
        from archive_search_mcp import TokenGate, create_server
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sample = self.root / 'sample.txt'
        self.sample.write_text('alpha sample value-one\n')
        self.server = create_server(self.root)
        self.client = TestClient(TokenGate(self.server.streamable_http_app(), b'a' * 64),
                                 base_url='http://127.0.0.1:8769')
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.headers = {'Authorization': 'Bearer ' + 'a' * 64,
                        'Accept': 'application/json, text/event-stream'}
        response = self.rpc('initialize', {'protocolVersion': '2025-11-25', 'capabilities': {},
                            'clientInfo': {'name': 'synthetic-test', 'version': '1'}})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('error', response.json())

    def rpc(self, method, params=None, headers=None):
        return self.client.post('/mcp', headers=headers if headers is not None else self.headers,
                                json={'jsonrpc': '2.0', 'id': 1, 'method': method,
                                      'params': params or {}})

    def result(self, method, params=None):
        r = self.rpc(method, params)
        self.assertEqual(r.status_code, 200)
        return r.json()['result']

    def tool(self, name, arguments):
        return self.result('tools/call', {'name': name, 'arguments': arguments})

    def test_auth_and_rebinding_fail_closed(self):
        for headers in [{'Accept': 'application/json, text/event-stream'},
                        dict(self.headers, Authorization='Bearer wrong')]:
            r = self.rpc('tools/list', headers=headers)
            self.assertEqual(r.status_code, 401)
            self.assertNotIn('alpha', r.text)
        self.assertEqual(self.rpc('tools/list', headers=dict(self.headers, Origin='https://evil.example')).status_code, 403)
        self.assertEqual(self.rpc('tools/list', headers=dict(self.headers, Host='evil.example')).status_code, 421)
        self.assertEqual(self.client.get('/sample.txt', headers=self.headers).status_code, 404)

    def test_only_read_tools_and_fresh_results(self):
        tools = self.result('tools/list')['tools']
        self.assertEqual({t['name'] for t in tools}, {'search_archive', 'read_source'})
        self.assertTrue(all(t['annotations']['readOnlyHint'] for t in tools))
        old = self.tool('search_archive', {'query': 'alpha'})['structuredContent']
        source = old['sources'][0]
        self.sample.write_text('alpha changed value-two\n')
        stale = self.tool('read_source', {'source_id': source['source_id'], 'expected_hash': source['sha256']})
        self.assertTrue(stale['isError'])
        fresh = self.tool('read_source', {'source_id': source['source_id']})
        self.assertIn('value-two', json.dumps(fresh))
        self.assertNotIn('value-one', json.dumps(fresh))
        self.assertNotIn(str(self.root), json.dumps(fresh))
        self.assertTrue(self.tool('run_command', {'command': 'echo bad'})['isError'])
        self.assertEqual(self.sample.read_text(), 'alpha changed value-two\n')

    def test_invalid_and_oversized_requests(self):
        self.assertTrue(self.tool('read_source', {'source_id': '../../etc/passwd'})['isError'])
        self.assertTrue(self.tool('search_archive', {'query': 'x' * 257})['isError'])
        self.assertEqual(self.rpc('tools/call', {'name': 'search_archive', 'arguments': {'query': 'x' * 20000}}).status_code, 413)


if __name__ == '__main__': unittest.main()

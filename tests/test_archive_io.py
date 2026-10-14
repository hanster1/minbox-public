import errno
import io
import json
import os
from pathlib import Path
import sys
import socket
import ssl
import tempfile
import time
import types
import unittest
import urllib.error
from unittest.mock import call, patch

from archive_io import AdapterError, GoogleAuth, JsonCodexAnalyzer, _NoRedirect, _http_request, _urlopen


class SourceAnalyzer(JsonCodexAnalyzer):
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['decisions'],
              'properties': {'decisions': {'type': 'array', 'items': {'type': 'string'}}}}
    prompt = 'TEST SCHEMA PROMPT: untrusted source data\n'

    @staticmethod
    def _validate(result):
        JsonCodexAnalyzer._validate(result)
        if any(not isinstance(d, str) for d in result['decisions']):
            raise AdapterError('Invalid source decision')


VALID = {'decisions': ['source-1']}


class HttpTests(unittest.TestCase):
    def http_error(self, code):
        body = io.BytesIO(b'PRIVATE response body')
        return urllib.error.HTTPError('https://example.invalid/PRIVATE', code,
                                      'PRIVATE status detail', {}, body), body

    def test_only_delete_accepts_empty_204(self):
        class Empty204(io.BytesIO):
            status = 204
        with patch('archive_io._urlopen', return_value=Empty204()):
            self.assertEqual(_http_request('DELETE', 'https://example.invalid', None, {}, 20), {})
        for method in ('GET', 'POST', 'PATCH'):
            with patch('archive_io._urlopen', return_value=Empty204()), self.assertRaises(AdapterError):
                _http_request(method, 'https://example.invalid', None, {}, 20)
        with patch('archive_io._urlopen', return_value=io.BytesIO()), self.assertRaises(AdapterError):
            _http_request('DELETE', 'https://example.invalid', None, {}, 20)

    def test_transient_get_statuses_recover_and_close_errors_before_sleep(self):
        for code in (429, 500, 502, 503, 504):
            with self.subTest(code=code):
                first, first_body = self.http_error(code)
                second, second_body = self.http_error(code)
                def slept(delay):
                    self.assertTrue(first_body.closed)
                    if delay == 1:
                        self.assertTrue(second_body.closed)
                with patch('archive_io._urlopen', side_effect=[first, second, io.BytesIO(b'{"ok":true}')]) as opened, \
                        patch('archive_io.time.sleep', side_effect=slept) as sleep:
                    self.assertEqual(_http_request('GET', 'https://example.invalid', None, {}, 20), {'ok': True})
                self.assertEqual(opened.call_count, 3)
                self.assertEqual(sleep.call_args_list, [call(.5), call(1)])

    def test_transient_get_connection_errors_recover(self):
        for error in (TimeoutError('PRIVATE timeout'), ConnectionResetError('PRIVATE reset'),
                      urllib.error.URLError(TimeoutError('PRIVATE timeout')),
                      urllib.error.URLError(ConnectionRefusedError('PRIVATE refused')),
                      OSError(errno.ENETUNREACH, 'PRIVATE network'),
                      socket.gaierror(socket.EAI_AGAIN, 'PRIVATE DNS')):
            with self.subTest(error=type(error).__name__), \
                    patch('archive_io._urlopen', side_effect=[error, io.BytesIO(b'{}')]) as opened, \
                    patch('archive_io.time.sleep') as sleep:
                self.assertEqual(_http_request('GET', 'https://example.invalid', None, {}, 20), {})
                self.assertEqual(opened.call_count, 2)
                sleep.assert_called_once_with(.5)

    def test_interrupted_get_response_closes_before_retry(self):
        class InterruptedResponse(io.BytesIO):
            def read(self, size):
                raise ConnectionResetError('PRIVATE interrupted response')
        interrupted = InterruptedResponse(b'PRIVATE partial response')
        with patch('archive_io._urlopen', side_effect=[interrupted, io.BytesIO(b'{}')]) as opened, \
                patch('archive_io.time.sleep', side_effect=lambda delay: self.assertTrue(interrupted.closed)) as sleep:
            self.assertEqual(_http_request('GET', 'https://example.invalid', None, {}, 20), {})
        self.assertEqual(opened.call_count, 2)
        sleep.assert_called_once_with(.5)

    def test_transient_get_exhaustion_is_bounded_and_sanitized(self):
        for make_error in (lambda: self.http_error(503)[0],
                           lambda: urllib.error.URLError(TimeoutError('PRIVATE timeout'))):
            errors = [make_error() for _ in range(3)]
            with patch('archive_io._urlopen', side_effect=errors) as opened, \
                    patch('archive_io.time.sleep') as sleep, self.assertRaises(AdapterError) as caught:
                _http_request('GET', 'https://example.invalid/PRIVATE', None, {'Authorization': 'PRIVATE token'}, 20)
            self.assertEqual(opened.call_count, 3)
            self.assertEqual(sleep.call_args_list, [call(.5), call(1)])
            self.assertEqual(str(caught.exception), 'HTTP request failed; private details withheld')
            self.assertTrue(caught.exception.__suppress_context__)
            for error in errors:
                if isinstance(error, urllib.error.HTTPError):
                    self.assertTrue(error.fp.closed)

    def test_write_failures_are_never_replayed(self):
        for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            for make_error in (lambda: self.http_error(503)[0],
                               lambda: TimeoutError('PRIVATE uncertain write')):
                error = make_error()
                with self.subTest(method=method, error=type(error).__name__), \
                        patch('archive_io._urlopen', side_effect=error) as opened, \
                        patch('archive_io.time.sleep') as sleep, self.assertRaises(AdapterError) as caught:
                    _http_request(method, 'https://example.invalid', {'private': 'body'}, {}, 20)
                self.assertEqual(opened.call_count, 1)
                sleep.assert_not_called()
                self.assertNotIn('PRIVATE', str(caught.exception))
                if isinstance(error, urllib.error.HTTPError):
                    self.assertTrue(error.fp.closed)

    def test_permanent_get_failures_are_not_retried(self):
        errors = [self.http_error(code)[0] for code in (301, 302, 307, 308, 400, 401, 403, 404)]
        errors += [ssl.SSLCertVerificationError('PRIVATE certificate'),
                   urllib.error.URLError(ssl.SSLCertVerificationError('PRIVATE certificate')),
                   urllib.error.URLError('PRIVATE unknown error'),
                   OSError(errno.EACCES, 'PRIVATE permission'),
                   socket.gaierror(socket.EAI_NONAME, 'PRIVATE DNS'),
                   RuntimeError('PRIVATE programming error'), AdapterError('existing sanitized failure')]
        for error in errors:
            with self.subTest(error=type(error).__name__), \
                    patch('archive_io._urlopen', side_effect=error) as opened, \
                    patch('archive_io.time.sleep') as sleep, self.assertRaises(AdapterError) as caught:
                _http_request('GET', 'https://example.invalid', None, {}, 20)
            self.assertEqual(opened.call_count, 1)
            sleep.assert_not_called()
            self.assertNotIn('PRIVATE', str(caught.exception))
            if isinstance(error, urllib.error.HTTPError):
                self.assertTrue(error.fp.closed)

    def test_malformed_and_oversize_get_responses_fail_without_retry(self):
        for payload in (b'PRIVATE malformed', b'x' * 21):
            response = io.BytesIO(payload)
            with self.subTest(payload_length=len(payload)), \
                    patch('archive_io._urlopen', return_value=response) as opened, \
                    patch('archive_io.MAX_HTTP_BYTES', 20), patch('archive_io.time.sleep') as sleep, \
                    self.assertRaises(AdapterError) as caught:
                _http_request('GET', 'https://example.invalid', None, {}, 20)
            self.assertEqual(opened.call_count, 1)
            sleep.assert_not_called()
            self.assertTrue(response.closed)
            self.assertNotIn('PRIVATE', str(caught.exception))

    def test_https_redirect_guard_and_bounded_response(self):
        opener = types.SimpleNamespace(open=lambda *a, **k: io.BytesIO(b'{"ok":true}'))
        with patch('archive_io.urllib.request.build_opener', return_value=opener) as build:
            self.assertEqual(_http_request('GET', 'https://example.invalid', None, {}, 20), {'ok': True})
            self.assertIs(build.call_args.args[0], _NoRedirect)
            self.assertIsNone(build.call_args.args[0]().redirect_request(None))
        with patch('archive_io.urllib.request.build_opener') as build:
            with self.assertRaisesRegex(AdapterError, 'Encrypted'):
                _http_request('GET', 'http://example.invalid', None, {}, 20)
            build.assert_not_called()
        with patch('archive_io._urlopen', return_value=io.BytesIO(b'x' * 21)), patch('archive_io.MAX_HTTP_BYTES', 20):
            with self.assertRaisesRegex(AdapterError, 'exceeds'):
                _http_request('GET', 'https://example.invalid', None, {}, 20)

    def test_http_error_and_invalid_json_are_sanitized_without_retry(self):
        with patch('archive_io._urlopen', side_effect=RuntimeError('PRIVATE-token-payload')) as opened:
            with self.assertRaises(AdapterError) as caught:
                _http_request('POST', 'https://example.invalid', {'private': 'body'}, {}, 20)
            self.assertEqual(opened.call_count, 1)
        self.assertNotIn('PRIVATE', str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)
        with patch('archive_io._urlopen', return_value=io.BytesIO(b'PRIVATE malformed')):
            with self.assertRaises(AdapterError) as caught:
                _http_request('GET', 'https://example.invalid', None, {}, 20)
        self.assertNotIn('PRIVATE', str(caught.exception))


def google_modules(factory):
    names = ['google', 'google.auth', 'google.auth.transport', 'google.oauth2',
             'google.oauth2.service_account', 'google.oauth2.credentials']
    modules = {name: types.ModuleType(name) for name in names}
    for name, module in modules.items():
        module.__path__ = []
        if '.' in name:
            parent, attr = name.rsplit('.', 1)
            setattr(modules[parent], attr, module)
    modules['google.auth.transport'].Response = object
    modules['google.auth.transport'].Request = object
    modules['google.oauth2.service_account'].Credentials = types.SimpleNamespace(from_service_account_info=factory)
    modules['google.oauth2.credentials'].Credentials = types.SimpleNamespace(from_authorized_user_info=factory)
    return modules


class AuthTests(unittest.TestCase):
    def test_real_google_auth_refresh_omits_scope_and_checks_provider_grant(self):
        try:
            import google.oauth2.credentials
        except ImportError:
            self.skipTest('Optional Google auth dependency unavailable')
        self.path.write_text(json.dumps({'type':'authorized_user','refresh_token':'synthetic',
            'client_id':'synthetic-client','client_secret':'synthetic-secret',
            'token':'unverified','expiry':'2099-01-01T00:00:00Z','scopes':['https://www.googleapis.com/auth/drive']}))
        def response(request, timeout):
            from urllib.parse import parse_qs
            body = parse_qs(request.data.decode())
            self.assertNotIn('scope',body)
            self.assertEqual(body['grant_type'],['refresh_token'])
            stream=io.BytesIO(json.dumps({'access_token':'verified','expires_in':3600,
                'token_type':'Bearer','scope':'https://www.googleapis.com/auth/drive.file'}).encode())
            stream.status,stream.headers=200,{}
            return stream
        with patch('archive_io._urlopen',side_effect=response) as opened:
            auth=GoogleAuth(self.path)
            self.assertEqual(auth.token(),'verified')
            self.assertEqual(auth.effective_scopes,['https://www.googleapis.com/auth/drive.file'])
        self.assertEqual(opened.call_count,1)

    def test_default_file_scope_proves_unscoped_refresh_and_discards_cached_token(self):
        self.path.write_text(json.dumps({'type': 'authorized_user', 'refresh_token': 'synthetic',
            'token': 'persisted-unverified', 'expiry': '2099-01-01T00:00:00Z',
            'scopes': ['https://www.googleapis.com/auth/drive']}))
        calls = []
        class Credentials:
            valid = True
            token = 'persisted-unverified'
            def refresh(self, request):
                response = request('https://oauth2.googleapis.com/token', method='POST',
                    body=b'grant_type=refresh_token&refresh_token=synthetic')
                json.loads(response.data)
                self.token = 'verified-file-token'
        def factory(info, scopes):
            self.assertEqual(scopes, [])
            self.assertFalse(set(info) & {'token', 'expiry', 'scopes'})
            return Credentials()
        def response(request, timeout):
            calls.append(request)
            self.assertNotIn('scope=', request.data.decode())
            stream = io.BytesIO(json.dumps({'access_token': 'verified-file-token',
                'scope': 'https://www.googleapis.com/auth/drive.file'}).encode())
            stream.status, stream.headers = 200, {}
            return stream
        with patch.dict(sys.modules, google_modules(factory)), patch('archive_io._urlopen', side_effect=response):
            auth = GoogleAuth(self.path)
            self.assertEqual(auth.token(), 'verified-file-token')
            self.assertEqual(auth.token(), 'verified-file-token')
            self.assertEqual(auth.effective_scopes, ['https://www.googleapis.com/auth/drive.file'])
        self.assertEqual(len(calls), 1)

    def test_broad_refresh_cannot_be_hidden_by_requesting_file_scope(self):
        class Credentials:
            valid = False
            token = 'PRIVATE'
            def refresh(self, request):
                request('https://oauth2.googleapis.com/token', method='POST', body=b'grant_type=refresh_token')
        def response(request, timeout):
            # A scoped request would misleadingly look narrow. The actual full
            # refresh grant is broad and must be refused before any Drive access.
            scope = 'https://www.googleapis.com/auth/drive.file' if b'scope=' in request.data else 'https://www.googleapis.com/auth/drive'
            stream = io.BytesIO(json.dumps({'access_token': 'PRIVATE', 'scope': scope}).encode())
            stream.status, stream.headers = 200, {}
            return stream
        with patch.dict(sys.modules, google_modules(lambda info, scopes: Credentials())), patch('archive_io._urlopen', side_effect=response):
            auth = GoogleAuth(self.path)
            with self.assertRaises(AdapterError) as error:
                auth.token()
            self.assertIsNone(auth.credentials.token)
            self.assertIsNone(auth.effective_scopes)
            self.assertNotIn('PRIVATE', str(error.exception))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve())
        self.path = Path(self.temp.name) / 'google.json'
        self.path.write_text(json.dumps({'type': 'authorized_user', 'refresh_token': 'synthetic'}))
        self.path.chmod(0o600)

    def tearDown(self):
        self.temp.cleanup()

    def test_lazy_private_auth_types_and_scope_injection(self):
        calls = []
        def factory(info, scopes):
            calls.append((info['type'], scopes))
            return types.SimpleNamespace(valid=True, token='synthetic-token')
        with patch.dict(sys.modules, google_modules(factory)):
            auth = GoogleAuth(self.path, scopes=['https://www.googleapis.com/auth/drive'])
            self.assertEqual(calls, [])
            self.assertEqual(auth.token(), 'synthetic-token')
            self.assertEqual(auth.token(), 'synthetic-token')
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1], ['https://www.googleapis.com/auth/drive'])
            self.path.write_text(json.dumps({'type': 'service_account'}))
            auth = GoogleAuth(self.path, scopes=['existing-grant'], timeout=200)
            self.assertEqual(auth.timeout, 60)
            auth.token()
            self.assertEqual(calls[-1], ('service_account', ['existing-grant']))
            self.path.chmod(0o644)
            with self.assertRaises(AdapterError) as caught:
                GoogleAuth(self.path).token()
            self.assertEqual(str(caught.exception), 'Google authentication failed')
            self.assertTrue(caught.exception.__suppress_context__)
            self.path.chmod(0o600)
            link = self.path.with_name('link.json')
            link.symlink_to(self.path)
            with self.assertRaises(AdapterError):
                GoogleAuth(link).token()

    def test_refresh_transport_https_bounds_and_sanitized_errors(self):
        class Credentials:
            valid = False
            token = 'synthetic-token'
            url = 'https://oauth2.example.invalid/token'
            def refresh(self, request):
                response = request(self.url, method='POST', body=b'synthetic')
                if response.data != b'{}':
                    raise RuntimeError('PRIVATE auth detail')
                self.valid = True
        credential = Credentials()
        def factory(info, scopes):
            return credential
        def response():
            stream = io.BytesIO(b'{}')
            stream.status, stream.headers = 200, {}
            return stream
        with patch.dict(sys.modules, google_modules(factory)), patch('archive_io._urlopen', side_effect=lambda *a: response()):
            self.assertEqual(GoogleAuth(self.path, scopes=['https://www.googleapis.com/auth/drive']).token(), 'synthetic-token')
        credential.valid = False
        credential.url = 'http://oauth2.example.invalid/token'
        with patch.dict(sys.modules, google_modules(factory)), patch('archive_io._urlopen') as opened:
            with self.assertRaises(AdapterError) as caught:
                GoogleAuth(self.path).token()
            opened.assert_not_called()
        self.assertEqual(str(caught.exception), 'Google authentication failed')
        credential.url = 'https://oauth2.example.invalid/token'
        huge = io.BytesIO(b'x' * (1024 * 1024 + 1))
        huge.status, huge.headers = 200, {}
        with patch.dict(sys.modules, google_modules(factory)), patch('archive_io._urlopen', return_value=huge):
            with self.assertRaises(AdapterError):
                GoogleAuth(self.path).token()
        with patch.dict(sys.modules, google_modules(lambda *a, **k: (_ for _ in ()).throw(RuntimeError('PRIVATE token')))):
            with self.assertRaises(AdapterError) as caught:
                GoogleAuth(self.path).token()
        self.assertNotIn('PRIVATE', str(caught.exception))


class CodexTests(unittest.TestCase):
    def test_isolation_flags_and_schema_subclass_private_files(self):
        analyzer = SourceAnalyzer()
        command = analyzer.command('schema', 'output')
        for flag in ('--ignore-user-config', '--ignore-rules', '--ephemeral', '--skip-git-repo-check', '--json'):
            self.assertIn(flag, command)
        self.assertEqual(command[command.index('--sandbox') + 1], 'read-only')
        for config in ('project_doc_max_bytes=0', 'web_search="disabled"', 'mcp_servers={}', 'model_reasoning_effort="medium"'):
            self.assertIn(config, command)
        for feature in ('shell_tool', 'apps', 'plugins', 'multi_agent', 'browser_use'):
            self.assertIn(feature, command)
        def execute(command, cwd, prompt):
            self.assertEqual(cwd.stat().st_mode & 0o777, 0o700)
            for file in cwd.iterdir():
                self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            self.assertIn(SourceAnalyzer.prompt, prompt.read_text())
            self.assertEqual(json.loads((cwd / 'schema.json').read_text()), SourceAnalyzer.schema)
            Path(command[command.index('--output-last-message') + 1]).write_text(json.dumps(VALID))
            return [{'type': 'turn.completed', 'usage': {'input_tokens': 12, 'output_tokens': 8, 'cached_input_tokens': 3}}]
        with patch.object(analyzer, '_execute', side_effect=execute):
            result = analyzer.analyze({'sources': ['synthetic']})
        self.assertEqual(result, {'decisions': ['source-1'], 'usage': {'input_tokens': 12, 'output_tokens': 8}})

    def test_output_errors_preserve_usage_and_no_private_details(self):
        for output, usage in [('PRIVATE malformed', {'input_tokens': 1, 'output_tokens': 1}),
                              (json.dumps({'decisions': [123]}), {'input_tokens': 1, 'output_tokens': 1}),
                              (json.dumps(VALID), {})]:
            analyzer = SourceAnalyzer()
            def execute(command, cwd, prompt):
                Path(command[command.index('--output-last-message') + 1]).write_text(output)
                return [{'type': 'turn.completed', 'usage': usage}]
            with patch.object(analyzer, '_execute', side_effect=execute), self.assertRaises(AdapterError) as caught:
                analyzer.analyze({})
            self.assertNotIn('PRIVATE', str(caught.exception))
            if usage:
                self.assertEqual(caught.exception.reported_usage, usage)
        with patch('archive_io.subprocess.Popen', side_effect=OSError('PRIVATE token')):
            with self.assertRaises(AdapterError) as caught:
                SourceAnalyzer().analyze({})
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertNotIn('PRIVATE', str(caught.exception))

    def script(self, root, body):
        script = root / 'fake-codex'
        script.write_text('#!/usr/bin/env python3\n' + body)
        script.chmod(0o700)
        return str(script)

    def test_timeout_kills_helper_process_group(self):
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as directory:
            root = Path(directory)
            marker = root / 'helper.pid'
            body = ('import subprocess,time,sys,pathlib\n'
                    'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"])\n'
                    f'pathlib.Path({str(marker)!r}).write_text(str(child.pid))\n'
                    'time.sleep(30)\n')
            started = time.monotonic()
            with self.assertRaises(AdapterError) as caught:
                SourceAnalyzer(executable=self.script(root, body), timeout=.3).analyze({})
            self.assertLess(time.monotonic() - started, 3)
            self.assertIn('timed out', str(caught.exception))
            if marker.exists():
                stat = Path('/proc') / marker.read_text() / 'stat'
                self.assertTrue(not stat.exists() or stat.read_text().split()[2] == 'Z')

    def test_diagnostic_success_and_prohibited_or_bounded_stream(self):
        body = ('import sys,json,pathlib\n'
                'pathlib.Path(sys.argv[sys.argv.index("--output-last-message")+1]).write_text('
                + repr(json.dumps(VALID)) + ')\n'
                'print(json.dumps({"type":"item.completed","item":{"type":"error","message":"PRIVATE diagnostic"}}))\n'
                'print(json.dumps({"type":"turn.completed","usage":{"input_tokens":12,"output_tokens":8}}))\n')
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as directory:
            root = Path(directory)
            self.assertEqual(SourceAnalyzer(executable=self.script(root, body)).analyze({})['decisions'], VALID['decisions'])
            for body in [
                'print(\'{"type":"item.started","item":{"type":"command_execution","command":"PRIVATE"}}\',flush=True)',
                'print("PRIVATE" * 20000,flush=True)',
                'import sys\nsys.stderr.write("PRIVATE" * 20000)\nsys.stderr.flush()',
                'print(\'{"type":"turn.failed","error":{"message":"PRIVATE"}}\',flush=True)',
                'print("[]",flush=True)']:
                with self.subTest(body=body):
                    with self.assertRaises(AdapterError) as caught:
                        SourceAnalyzer(executable=self.script(root, body), max_output_chars=100).analyze({})
                    self.assertNotIn('PRIVATE', str(caught.exception))


if __name__ == '__main__':
    unittest.main()

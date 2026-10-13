import base64
import hashlib
import io
import types
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlencode, urlsplit
from folder_authorization import (SCOPES, FOLDER_MIME, FolderAuthorizationError,
                                  _guard_callback, authorize_folder, authorize_existing_items,
                                  _folder_id_from_url, _prepare_folder)


class FakeFlow:
    redirect_uri='http://127.0.0.1:4567/'
    def __init__(self):
        self.exchanges=[]
        self.token={'scope':SCOPES}
        self.params={'state':'expected-state','scope':SCOPES[0],
                     'picked_file_ids':'folder-123','code':'sensitive-code'}
        self.credentials=types.SimpleNamespace(granted_scopes=SCOPES,refresh_token='sensitive-refresh')
    def authorization_url(self,**kwargs):
        self.url_kwargs=kwargs
        return 'https://accounts.google.com/oauth','expected-state'
    def fetch_token(self,**kwargs):
        self.exchanges.append(kwargs)
        return self.token
    def response(self):return 'https://127.0.0.1:4567/?'+urlencode(self.params)
    def run_local_server(self,**kwargs):
        self.local_kwargs=kwargs
        self.authorization_url(**kwargs)
        self.fetch_token(authorization_response=self.response())
        return self.credentials


class FolderAuthorizationTests(unittest.TestCase):
    def test_loopback_server_preserves_https_scope_query_and_does_not_log_secrets(self):
        from folder_authorization import _run_local_picker
        flow=FakeFlow();_guard_callback(flow)
        query=urlencode(flow.params)
        handlers=[]
        class Server:
            server_port=4567
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def handle_request(self):
                response=handlers[0]({'PATH_INFO':'/','REQUEST_METHOD':'GET','QUERY_STRING':query},lambda *args:None)
                self_response=b''.join(response).decode()
                assert 'sensitive' not in self_response
        def server(host,port,app,**kwargs):
            self.assertEqual((host,port),('127.0.0.1',0))
            handlers.append(app)
            self.assertIsNone(kwargs['handler_class'].log_message(None,'sensitive-code'))
            return Server()
        with patch('folder_authorization.make_server',side_effect=server), patch('folder_authorization.webbrowser.open',return_value=True):
            credentials=_run_local_picker(flow,timeout_seconds=1,success_message='Done',prompt='consent')
        self.assertIs(credentials,flow.credentials)
        self.assertEqual(parse_qs(urlsplit(flow.exchanges[0]['authorization_response']).query)['scope'],SCOPES)
        self.assertEqual(flow.exchanges[0]['timeout'],20)

    def flow_module(self, flow):
        factory=Mock();factory.from_client_secrets_file.return_value=flow
        module=types.ModuleType('google_auth_oauthlib.flow');module.InstalledAppFlow=factory
        return module,factory

    def authorize(self,flow):
        module,factory=self.flow_module(flow)
        with patch.dict('sys.modules',{'google_auth_oauthlib.flow':module}), patch('folder_authorization._prepare_folder',return_value='folder-123'), patch('folder_authorization._run_local_picker',side_effect=lambda flow,**kw:flow.run_local_server(**kw)):
            result=authorize_folder('client.json')
        return result,factory

    def test_native_picker_options_and_no_callback_secrets_in_browser(self):
        flow=FakeFlow()
        (credentials,folder),factory=self.authorize(flow)
        self.assertIs(credentials,flow.credentials);self.assertEqual(folder,'folder-123')
        self.assertEqual(factory.from_client_secrets_file.call_args.kwargs,
                         {'scopes':SCOPES,'autogenerate_code_verifier':True})
        for key,value in {'host':'127.0.0.1','bind_addr':'127.0.0.1','port':0,
                          'prompt':'consent','trigger_onepick':'true','allow_multiple':'false',
                          'mimetypes':FOLDER_MIME,'allow_folder_selection':'true',
                          'file_ids':'folder-123',
                          'include_granted_scopes':'false','timeout_seconds':300}.items():
            self.assertEqual(flow.local_kwargs[key],value)
        self.assertEqual(flow.local_kwargs['authorization_prompt_message'],'')
        self.assertNotIn('sensitive',flow.local_kwargs['success_message'])
        self.assertEqual(flow.exchanges[0]['authorization_response'],flow.response())

    def test_bad_callbacks_fail_before_exchange(self):
        cases=[{'state':'wrong'},{'state':''},{'picked_file_ids':''},
               {'picked_file_ids':'one,two'},{'picked_file_ids':'root'},
               {'scope':'https://www.googleapis.com/auth/drive'},
               {'scope':SCOPES[0]+' https://www.googleapis.com/auth/spreadsheets'},
               {'code':''},{'error':'cancelled-sensitive-detail'}]
        for change in cases:
            with self.subTest(change=change):
                flow=FakeFlow();flow.params.update(change)
                with self.assertRaises(FolderAuthorizationError) as caught:self.authorize(flow)
                self.assertFalse(flow.exchanges)
                self.assertNotIn('sensitive',str(caught.exception))

    def test_duplicate_callback_parameters_rejected(self):
        for parameter in ('state','code','scope','picked_file_ids','extra'):
            flow=FakeFlow();selection=_guard_callback(flow);flow.authorization_url()
            response=flow.response()+'&'+parameter+'=duplicate'
            if parameter=='extra':response+='&extra=again'
            with self.assertRaises(FolderAuthorizationError):flow.fetch_token(authorization_response=response)
            self.assertFalse(flow.exchanges)
            self.assertNotIn('folder_id',selection)

    def test_wrong_callback_origin_rejected(self):
        flow=FakeFlow();_guard_callback(flow);flow.authorization_url()
        with self.assertRaises(FolderAuthorizationError):
            flow.fetch_token(authorization_response=flow.response().replace('127.0.0.1','attacker.invalid'))
        self.assertFalse(flow.exchanges)

    def test_granted_scope_mismatch_rejected(self):
        for token_scope,credential_scope in [(None,SCOPES),(['https://www.googleapis.com/auth/drive'],SCOPES),
                                               (SCOPES,None),(SCOPES,['https://www.googleapis.com/auth/drive'])]:
            flow=FakeFlow();flow.token={'scope':token_scope};flow.credentials.granted_scopes=credential_scope
            with self.subTest(token_scope=token_scope,credential_scope=credential_scope):
                with self.assertRaises(FolderAuthorizationError):self.authorize(flow)

    def test_provider_and_timeout_errors_are_sanitized(self):
        for exception in (RuntimeError('sensitive-code sensitive-refresh'),TimeoutError('sensitive-code')):
            flow=FakeFlow();flow.run_local_server=Mock(side_effect=exception)
            with self.assertRaises(FolderAuthorizationError) as caught:self.authorize(flow)
            self.assertNotIn('sensitive',str(caught.exception))
            self.assertTrue(caught.exception.__suppress_context__)
        for timeout in (0,901):
            with self.assertRaises(FolderAuthorizationError):authorize_folder('client.json',timeout)

    def test_missing_refresh_token_rejected(self):
        flow=FakeFlow();flow.credentials.refresh_token=None
        with self.assertRaisesRegex(FolderAuthorizationError,'offline'):self.authorize(flow)

    def test_migration_picker_only_accepts_complete_known_inventory(self):
        for picked, accepted in [('folder,doc', True), ('folder', False), ('folder,unrelated', False),
                                  ('folder,doc,unrelated', False), ('folder,folder', False)]:
            flow=FakeFlow();flow.params['picked_file_ids']=picked
            module,factory=self.flow_module(flow)
            with patch.dict('sys.modules',{'google_auth_oauthlib.flow':module}), patch('folder_authorization._prepare_folder',side_effect=AssertionError('Migration must not prepare a new folder')), patch('folder_authorization._run_local_picker',side_effect=lambda flow,**kw:flow.run_local_server(**kw)):
                if accepted:
                    credentials, ids=authorize_existing_items('client.json',['folder','doc'])
                    self.assertEqual(ids,['folder','doc'])
                    self.assertEqual(flow.local_kwargs['file_ids'],'folder,doc')
                    self.assertEqual(flow.local_kwargs['allow_multiple'],'true')
                else:
                    with self.assertRaises(FolderAuthorizationError):
                        authorize_existing_items('client.json',['folder','doc'])
                    self.assertFalse(flow.exchanges)

    def test_oversized_callback_rejected_before_exchange(self):
        flow=FakeFlow();_guard_callback(flow);flow.authorization_url()
        with self.assertRaises(FolderAuthorizationError):
            flow.fetch_token(authorization_response=flow.response()+'&extra='+'x'*16384)
        self.assertFalse(flow.exchanges)

    def test_actual_library_pkce_url_and_exchange(self):
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError:
            self.skipTest('Optional Google OAuth dependencies unavailable')
        flow=InstalledAppFlow.from_client_config({'installed':{
            'client_id':'client-id','client_secret':'client-secret',
            'auth_uri':'https://accounts.google.com/o/oauth2/auth',
            'token_uri':'https://oauth2.googleapis.com/token'}},scopes=SCOPES,
            autogenerate_code_verifier=True)
        flow.redirect_uri='http://127.0.0.1:4567/'
        selection=_guard_callback(flow)
        url,state=flow.authorization_url(prompt='consent',trigger_onepick='true',allow_multiple='false',
                                         mimetypes=FOLDER_MIME,allow_folder_selection='true',
                                         include_granted_scopes='false')
        params=parse_qs(urlsplit(url).query)
        self.assertEqual(params['scope'],SCOPES)
        self.assertEqual(params['state'],[state])
        self.assertEqual(params['code_challenge_method'],['S256'])
        challenge=base64.urlsafe_b64encode(hashlib.sha256(flow.code_verifier.encode()).digest()).decode().rstrip('=')
        self.assertEqual(params['code_challenge'],[challenge])
        response='https://127.0.0.1:4567/?'+urlencode({'state':state,'code':'one-time-code',
                   'picked_file_ids':'folder','scope':SCOPES[0]})
        with patch.object(flow.oauth2session,'fetch_token',return_value={'scope':SCOPES}) as exchange:
            flow.fetch_token(authorization_response=response)
        self.assertEqual(exchange.call_args.kwargs['authorization_response'],response)
        self.assertEqual(exchange.call_args.kwargs['code_verifier'],flow.code_verifier)
        self.assertEqual(selection['folder_id'],'folder')

    def test_selected_folder_must_match_preflight_before_exchange(self):
        flow=FakeFlow();flow.params['picked_file_ids']='some-other-folder'
        with self.assertRaisesRegex(FolderAuthorizationError,'folder you chose'):self.authorize(flow)
        self.assertFalse(flow.exchanges)

    def test_folder_link_parser_accepts_drive_folder_links_only(self):
        for link in ('https://drive.google.com/drive/folders/folder-123',
                     'https://drive.google.com/drive/u/0/folders/folder-123/?usp=sharing'):
            self.assertEqual(_folder_id_from_url(link),'folder-123')
        for link in ('http://drive.google.com/drive/folders/folder',
                     'https://drive.google.com.attacker.invalid/drive/folders/folder',
                     'https://drive.google.com@attacker.invalid/drive/folders/folder',
                     'https://drive.google.com:443/drive/folders/folder',
                     'https://drive.google.com/drive/folders/root',
                     'https://drive.google.com/file/d/document/view',
                     'https://accounts.google.com/o/oauth2/auth?scope=drive',
                     'https://drive.google.com/drive/folders/folder#fragment'):
            with self.subTest(link=link):
                with self.assertRaises(FolderAuthorizationError):_folder_id_from_url(link)

    def preflight(self, requests):
        applications=[];responses=[]
        class Server:
            server_port=4567
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def handle_request(inner):
                environ={'HTTP_HOST':'127.0.0.1:4567','PATH_INFO':'/', 'REQUEST_METHOD':'GET'}
                environ.update(requests.pop(0))
                result=applications[0](environ,lambda status,headers:responses.append([status,dict(headers)]))
                responses[-1].append(b''.join(result).decode())
        def server(host,port,app,**kwargs):
            self.assertEqual((host,port),('127.0.0.1',0));applications.append(app)
            self.assertIsNone(kwargs['handler_class'].log_message(None,'private-folder-link'))
            return Server()
        with patch('folder_authorization.make_server',side_effect=server), \
             patch('folder_authorization.webbrowser.open',return_value=True) as browser, \
             patch('folder_authorization.secrets.token_urlsafe',return_value='test-csrf'):
            folder=_prepare_folder(1)
        browser.assert_called_once_with('http://127.0.0.1:4567/',new=1,autoraise=True)
        return folder,responses

    def form_request(self,params,**changes):
        body=urlencode(params).encode()
        environ={'REQUEST_METHOD':'POST','HTTP_ORIGIN':'http://127.0.0.1:4567',
                 'CONTENT_TYPE':'application/x-www-form-urlencoded','CONTENT_LENGTH':str(len(body)),
                 'wsgi.input':io.BytesIO(body)}
        environ.update(changes)
        return environ

    def successful_preflight_requests(self):
        return [{},self.form_request({'csrf':'test-csrf','step':'folder',
                'folder_url':'https://drive.google.com/drive/folders/folder-123?usp=sharing'}),
                self.form_request({'csrf':'test-csrf','step':'confirm','folder_id':'folder-123'})]

    def test_preflight_instructions_and_exact_folder_confirmation(self):
        folder,responses=self.preflight(self.successful_preflight_requests())
        self.assertEqual(folder,'folder-123')
        page=responses[0][2]
        for text in ('new empty, private folder','Name it anything you like',
                     'https://drive.google.com/drive/my-drive','Show my chosen folder',
                     'You can safely rename this folder at any time in Google Drive',
                     'Use the same folder already connected', 'Do not create a replacement folder'):
            self.assertIn(text,page)
        confirmation=responses[1][2]
        self.assertIn('https://drive.google.com/drive/folders/folder-123',confirmation)
        self.assertNotIn('usp=sharing',confirmation)
        self.assertIn('select only this folder',confirmation)
        self.assertIn('You can safely rename this folder at any time in Google Drive',confirmation)
        for status,headers,body in responses:
            self.assertEqual(status,'200 OK')
            self.assertEqual(headers['Cache-Control'],'no-store')
            self.assertEqual(headers['Referrer-Policy'],'same-origin')
            self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])

    def test_preflight_rejects_csrf_origin_duplicates_and_oversized_body(self):
        fields={'csrf':'test-csrf','step':'folder','folder_url':'https://drive.google.com/drive/folders/folder-123'}
        invalid=[self.form_request(dict(fields,csrf='wrong')),
                 self.form_request(fields,HTTP_ORIGIN='null'),
                 self.form_request(fields,HTTP_ORIGIN='https://attacker.invalid'),
                 self.form_request(fields,HTTP_HOST='attacker.invalid'),
                 self.form_request(fields,CONTENT_LENGTH='4097'),
                 self.form_request(fields,HTTP_TRANSFER_ENCODING='chunked'),
                 self.form_request(fields,CONTENT_TYPE='application/json'),
                 self.form_request(dict(fields,csrf='非ASCII')),
                 self.form_request({'csrf':'test-csrf','step':'confirm','folder_id':'folder-123'})]
        body=(urlencode(fields)+'&csrf=test-csrf').encode()
        invalid.append(self.form_request(fields,CONTENT_LENGTH=str(len(body)),**{'wsgi.input':io.BytesIO(body)}))
        folder,responses=self.preflight(invalid+self.successful_preflight_requests())
        self.assertEqual(folder,'folder-123')
        self.assertTrue(all(response[0] in ('400 Bad Request','404 Not Found') for response in responses[:len(invalid)]))

    def test_preflight_requires_confirmation_of_the_displayed_folder(self):
        requests=self.successful_preflight_requests()
        requests.insert(2,self.form_request({'csrf':'test-csrf','step':'confirm','folder_id':'different'}))
        folder,responses=self.preflight(requests)
        self.assertEqual(folder,'folder-123');self.assertEqual(responses[2][0],'400 Bad Request')

    def test_preflight_timeout_and_browser_failure_are_fixed_errors(self):
        class Server:
            server_port=4567
            def __enter__(self):return self
            def __exit__(self,*args):return False
        with patch('folder_authorization.make_server',return_value=Server()), \
             patch('folder_authorization.webbrowser.open',return_value=False):
            with self.assertRaisesRegex(FolderAuthorizationError,'setup browser'):_prepare_folder(1)
        with patch('folder_authorization.make_server',return_value=Server()), \
             patch('folder_authorization.webbrowser.open',return_value=True), \
             patch('folder_authorization.time.monotonic',side_effect=[0,2]):
            with self.assertRaisesRegex(FolderAuthorizationError,'timed out'):_prepare_folder(1)

    def test_real_loopback_preflight_form_flow(self):
        import re
        import threading
        from urllib.request import Request, urlopen
        browser_threads=[];pages=[];failures=[]
        def browser(url,**kwargs):
            def visit():
                try:
                    origin=url.rstrip('/')
                    with urlopen(url,timeout=3) as response:page=response.read().decode()
                    pages.append(page)
                    csrf=re.search(r'name="csrf" value="([^"]+)"',page)[1]
                    for params in ({'csrf':csrf,'step':'folder',
                                    'folder_url':'https://drive.google.com/drive/folders/folder-123'},
                                   {'csrf':csrf,'step':'confirm','folder_id':'folder-123'}):
                        request=Request(url,data=urlencode(params).encode(),
                            headers={'Origin':origin,'Content-Type':'application/x-www-form-urlencoded'})
                        with urlopen(request,timeout=3) as response:pages.append(response.read().decode())
                except Exception as error:
                    failures.append(error)
            thread=threading.Thread(target=visit,daemon=True);browser_threads.append(thread);thread.start()
            return True
        with patch('folder_authorization.webbrowser.open',side_effect=browser):
            self.assertEqual(_prepare_folder(5),'folder-123')
        browser_threads[0].join(timeout=3)
        self.assertFalse(failures)
        self.assertEqual(len(pages),3)
        self.assertIn('Continue to Google',pages[1])
        self.assertIn('folder-123',pages[2])

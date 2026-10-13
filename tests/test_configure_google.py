import contextlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
import configure_google


class GoogleOnboardingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.owner = self.root/'Casey'
        self.owner.mkdir()
        self.credential = self.owner/'google-authorized-user.json'
        self.credential.write_text('original'); self.credential.chmod(0o600)
        self.config = self.owner/'drive.json'
        self.config.write_text(json.dumps({'owner':'Casey','google_account_email':'owner@example.invalid',
                                           'folder_id':'folder','retained':'binding'}))
        self.config.chmod(0o600)
        self.original_config = self.config.read_bytes()
        self.credentials = types.SimpleNamespace(to_json=lambda: json.dumps({'refresh_token':'test-refresh'}))
        self.metadata = {'id':'folder','shared':False,'trashed':False,
                         'mimeType':'application/vnd.google-apps.folder',
                         'parents':['my-drive-root'],
                         'owners':[{'emailAddress':'owner@example.invalid'}],'capabilities':{'canEdit':True}}

    def run_connect(self, email='owner@example.invalid', folder='folder', auth_error=None):
        def request(method,url,*args):
            self.assertEqual(method,'GET')
            if '/about?' in url: return {'user':{'emailAddress':email}}
            return self.metadata
        auth=Mock();auth.token.return_value='refreshed-token'
        if auth_error:auth.token.side_effect=auth_error
        with patch('configure_google.authorize_folder',return_value=(self.credentials,folder)), \
             patch('configure_google.GoogleAuth',return_value=auth) as factory, \
             patch('configure_google._http_request',side_effect=request) as http, \
             contextlib.redirect_stdout(io.StringIO()):
            configure_google.main(['client.json','--owner','Casey','--config-dir',str(self.root)])
            self.assertEqual(factory.call_args.kwargs['scopes'],configure_google.SCOPES)
            self.assertTrue(all(c.args[3]['Authorization']=='Bearer refreshed-token' for c in http.call_args_list))
            return http

    def assert_preserved(self):
        self.assertEqual(self.credential.read_text(),'original')
        self.assertEqual(self.config.read_bytes(),self.original_config)
        self.assertFalse(list(self.owner.glob('.google-*')))

    def test_owner_binding_and_idempotent_folder(self):
        with self.assertRaisesRegex(ValueError,'account mismatch'):self.run_connect(email='wrong@example.invalid')
        self.assert_preserved()
        self.run_connect()
        config=json.loads(self.config.read_text())
        self.assertEqual(config['google_scopes'],['https://www.googleapis.com/auth/drive.file'])
        self.assertEqual(config['archive_root_folder_id'],'folder')
        self.assertEqual(config['folder_access'],'selected_folder')
        self.assertEqual(config['retained'],'binding')
        self.assertEqual(self.credential.stat().st_mode & 0o777,0o600)

    def test_different_selection_preserves_existing(self):
        with self.assertRaisesRegex(ValueError,'folder mismatch'):self.run_connect(folder='different')
        self.assert_preserved()

    def test_refreshed_scope_failure_preserves_existing(self):
        with self.assertRaisesRegex(ValueError,'scope mismatch'):
            self.run_connect(auth_error=ValueError('scope mismatch'))
        self.assert_preserved()

    def test_invalid_folder_preserves_existing(self):
        for key,value in [('shared',True),('trashed',True),('driveId','shared-drive'),
                          ('mimeType','text/plain'),('capabilities',{'canEdit':False}),
                          ('owners',[{'emailAddress':'another@example.invalid'}]),('id','wrong'),('parents',[])]:
            with self.subTest(key=key):
                original=self.metadata.copy();self.metadata[key]=value
                with self.assertRaisesRegex(ValueError,'private, editable'):self.run_connect()
                self.assert_preserved();self.metadata=original

    def test_new_owner_selects_existing_folder_without_creating_or_renaming(self):
        self.config.unlink();self.credential.unlink()
        self.run_connect()
        self.assertEqual(json.loads(self.config.read_text())['folder_id'],'folder')

    def test_replacement_failure_rolls_back_both_files(self):
        replace=configure_google.os.replace
        def fail(source,target):
            if target==self.config:raise OSError('disk failure')
            return replace(source,target)
        with patch('configure_google.os.replace',side_effect=fail):
            with self.assertRaises(OSError):self.run_connect()
        self.assert_preserved()

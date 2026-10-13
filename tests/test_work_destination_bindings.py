import copy
import unittest
from urllib.parse import urlparse
from archive_publish_cli import verify_destinations


class WorkBindings(unittest.TestCase):
    def setUp(self):
        self.config = {'folder_id':'work-folder', 'corrections_folder_id':'owner-folder',
            'documents':{'messages':'messages', 'corrections':'corrections'}}
        self.items = {}
        for identifier in ('work-folder', 'owner-folder', 'messages', 'corrections'):
            folder = identifier.endswith('folder')
            self.items[identifier] = {'id':identifier,'mimeType':'application/vnd.google-apps.' + ('folder' if folder else 'document'),
                'shared':False, 'trashed':False, 'capabilities':{'canEdit':True},
                'owners':[{'emailAddress':'synthetic@example.invalid'}],
                'parents':[] if folder else ['owner-folder' if identifier=='corrections' else 'work-folder']}

    def get(self, url):
        return self.items[urlparse(url).path.rsplit('/',1)[-1]]

    def test_shared_input_binding_preserves_output_folder_boundary(self):
        verify_destinations(self.config, 'synthetic@example.invalid', self.get)
        self.items['messages']['parents'] = ['owner-folder']
        with self.assertRaises(ValueError):
            verify_destinations(self.config, 'synthetic@example.invalid', self.get)

    def test_legacy_same_folder_and_wrong_private_binding(self):
        config = copy.deepcopy(self.config)
        del config['corrections_folder_id']
        with self.assertRaises(ValueError):
            verify_destinations(config, 'synthetic@example.invalid', self.get)
        self.items['corrections']['parents'] = ['work-folder']
        verify_destinations(config, 'synthetic@example.invalid', self.get)

    def test_shared_trashed_foreign_folders_or_docs_fail_closed(self):
        for identifier, field, value in [('owner-folder','shared',True), ('work-folder','trashed',True),
                ('owner-folder','owners',[]), ('corrections','shared',True), ('messages','trashed',True)]:
            before = copy.deepcopy(self.items[identifier])
            self.items[identifier][field] = value
            with self.assertRaises(ValueError):
                verify_destinations(self.config, 'synthetic@example.invalid', self.get)
            self.items[identifier] = before

    def test_selected_root_moved_work_folder_rejected_before_doc_reads(self):
        self.config.update(folder_access='selected_folder',
            google_scopes=['https://www.googleapis.com/auth/drive.file'], archive_root_folder_id='owner-folder')
        self.items['work-folder']['parents'] = ['owner-folder']
        verify_destinations(self.config, 'synthetic@example.invalid', self.get)
        self.items['work-folder']['parents'] = ['outside']
        requested = []
        def get(url):
            requested.append(urlparse(url).path.rsplit('/', 1)[-1])
            return self.get(url)
        with self.assertRaises(ValueError):
            verify_destinations(self.config, 'synthetic@example.invalid', get)
        self.assertFalse(set(requested) & set(self.config['documents'].values()))
        self.assertNotIn('outside', requested)

    def test_marked_broad_scope_rejected_and_explicit_legacy_scope_preserved(self):
        self.config['google_scopes'] = ['https://www.googleapis.com/auth/drive',
                                       'https://www.googleapis.com/auth/spreadsheets']
        verify_destinations(self.config, 'synthetic@example.invalid', self.get)
        self.config.update(folder_access='selected_folder', archive_root_folder_id='owner-folder')
        with self.assertRaises(ValueError):
            verify_destinations(self.config, 'synthetic@example.invalid', self.get)

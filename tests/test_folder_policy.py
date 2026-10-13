import copy
import unittest

from folder_policy import FILE_SCOPE, verify_selected_folders


class SelectedFolderPolicy(unittest.TestCase):
    def setUp(self):
        self.config = dict(folder_access='selected_folder', google_scopes=[FILE_SCOPE],
                           archive_root_folder_id='root', folder_id='work', corrections_folder_id='root')
        self.items = {identifier: dict(id=identifier, name='Any owner-selected name',
            mimeType='application/vnd.google-apps.folder', shared=False, trashed=False,
            capabilities={'canEdit': True}, owners=[{'emailAddress': 'owner@example.invalid'}],
            parents=['outside'] if identifier == 'root' else ['root']) for identifier in ('root', 'work')}
        self.reads = []

    def metadata(self, identifier):
        self.reads.append(identifier)
        return self.items[identifier]

    def verify(self):
        return verify_selected_folders(self.config, 'owner@example.invalid', self.metadata)

    def test_root_arbitrary_location_and_name_are_preserved(self):
        before = copy.deepcopy(self.items)
        self.assertTrue(self.verify())
        self.assertEqual(self.items, before)
        self.assertEqual(set(self.reads), {'root', 'work'})
        self.config['folder_id'] = 'root'
        self.reads.clear()
        self.verify()
        self.assertEqual(self.reads, ['root'])

    def test_moved_output_and_corrections_fail_without_unknown_parent_reads(self):
        self.items['work']['parents'] = ['outside']
        with self.assertRaises(ValueError):
            self.verify()
        self.assertNotIn('outside', self.reads)
        self.items['work']['parents'] = ['root']
        self.config['corrections_folder_id'] = 'outside'
        self.items['outside'] = copy.deepcopy(self.items['work'])
        self.items['outside']['parents'] = ['other']
        with self.assertRaises(ValueError):
            self.verify()
        self.assertNotIn('other', self.reads)

    def test_known_nested_chain_and_moved_ancestor(self):
        self.config['managed_folder_parents'] = {'work': 'middle', 'middle': 'root'}
        self.items['middle'] = copy.deepcopy(self.items['work'])
        self.items['middle']['id'] = 'middle'
        self.items['work']['parents'] = ['middle']
        self.verify()
        self.assertEqual(set(self.reads), {'root', 'middle', 'work'})
        self.items['middle']['parents'] = ['unknown']
        with self.assertRaises(ValueError):
            self.verify()
        self.assertNotIn('unknown', self.reads)

    def test_unknown_parent_cycle_or_invalid_mapping_rejected_before_drive(self):
        for parents in ({'work': 'unknown'}, {'work': 'middle', 'middle': 'work'},
                        {'root': 'work'}, [], {'work': '../root'}):
            self.config['managed_folder_parents'] = parents
            with self.assertRaises(ValueError):
                self.verify()
            self.assertEqual(self.reads, [])

    def test_malformed_or_broad_marked_bindings_fail_before_drive(self):
        for key, value in [('google_scopes', [FILE_SCOPE, 'https://www.googleapis.com/auth/drive']),
                           ('google_scopes', ['https://www.googleapis.com/auth/drive']),
                           ('google_scopes', None), ('archive_root_folder_id', None),
                           ('folder_access', 'other'), ('folder_id', '')]:
            config = copy.deepcopy(self.config)
            config[key] = value
            with self.assertRaises(ValueError):
                verify_selected_folders(config, 'owner@example.invalid', self.metadata)
            self.assertEqual(self.reads, [])

    def test_root_must_remain_private_editable_owned_and_untrashed(self):
        for key, value in [('shared', True), ('trashed', True), ('owners', []),
                           ('capabilities', {'canEdit': False}), ('mimeType', 'other')]:
            before = copy.deepcopy(self.items['root'])
            self.items['root'][key] = value
            with self.assertRaises(ValueError):
                self.verify()
            self.items['root'] = before

    def test_legacy_and_synthetic_bindings_unchanged_but_file_scope_needs_root(self):
        for config in ({'folder_id': 'legacy'}, {'google_scopes': [
                'https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']}):
            self.assertFalse(verify_selected_folders(config, 'owner@example.invalid', self.metadata))
        with self.assertRaises(ValueError):
            verify_selected_folders({'google_scopes': [FILE_SCOPE]}, 'owner@example.invalid', self.metadata)
        self.assertEqual(self.reads, [])

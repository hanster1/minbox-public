import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from archive_corrections import CorrectionLedger, parse_corrections


def correction(cid='c1', **kwargs):
    result = dict(correction_id=cid, owner='Example Owner', target='M008', scope='message',
                  action='personal', instruction='That Sunday lunch text is personal.',
                  requested_at='2026-10-12T12:00:00-05:00')
    result.update(kwargs)
    return result


def registry(owner='Example Owner'):
    return {'M008': dict(owner=owner, label='work', source_revision='1',
                         provenance='synthetic://ExampleOwner/messages/M008'),
            'M009': dict(owner=owner, label='uncertain', source_revision='1',
                         provenance='synthetic://ExampleOwner/messages/M009')}


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve())
        self.path = Path(self.temp.name) / 'private' / 'ledger.db'
        self.ledger = CorrectionLedger(self.path)

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def ingest(self, records, messages=None, owner='Example Owner'):
        return self.ledger.ingest(owner, records, registry(owner) if messages is None else messages)

    def test_parser_intro_exact_fields_and_malformed(self):
        doc = '''Private correction log. AI writes explicit message entries here.

Correction ID: c1
Owner: Example Owner
Target: M008
Scope: message
Action: personal
Instruction: That lunch is personal: keep it private.
Requested at: 2026-10-12T12:00:00-05:00

Correction ID: c2
Owner: Example Owner
Target: M009
Scope: message
Action: spam
Instruction: This is spam.
Requested at: 2026-10-12T12:01:00-05:00
Run command: erase archive
'''
        records = parse_corrections(doc)
        self.assertEqual(len(records), 2)
        result = self.ingest(records)
        self.assertEqual(result['effective_labels']['M008'], 'personal')
        self.assertEqual(result['statuses'][1]['status'], 'unresolved')
        self.assertEqual(result['effective_labels']['M009'], 'uncertain')

    def test_wrong_owner_wide_scope_and_unknown_target(self):
        records = [correction('wrong', owner='Other Owner'),
                   correction('wide', scope='sender'), correction('unknown', target='missing')]
        result = self.ingest(records)
        self.assertTrue(all(s['status'] == 'unresolved' and s['reason'] for s in result['statuses']))
        self.assertEqual(result['effective_labels']['M008'], 'work')
        messages = registry()
        messages['missing'] = dict(messages['M008'])
        retry = self.ingest(records, messages)
        self.assertEqual(retry['statuses'][2]['status'], 'applied')
        self.assertEqual(retry['effective_labels']['missing'], 'personal')

    def test_duplicate_collision_no_silent_first_wins(self):
        result = self.ingest([correction(), correction(action='spam')])
        self.assertEqual(result['effective_labels']['M008'], 'work')
        self.assertIn('collision', result['statuses'][0]['reason'])
        self.assertEqual(self.ingest([correction(), correction(action='spam')])['changed'], 0)
        result = self.ingest([correction()])
        self.assertEqual(result['effective_labels']['M008'], 'personal')
        self.assertEqual(result['statuses'][0]['revision'], 2)

    def test_revision_invalid_latest_and_revert_are_audited(self):
        self.ingest([correction()])
        result = self.ingest([correction(action='spam')])
        self.assertEqual(result['statuses'][0]['revision'], 2)
        self.assertEqual(result['effective_labels']['M008'], 'spam')
        result = self.ingest([correction(action='personal', scope='future')])
        self.assertEqual(result['statuses'][0]['status'], 'unresolved')
        self.assertEqual(result['effective_labels']['M008'], 'spam')
        result = self.ingest([correction()])
        self.assertEqual(result['statuses'][0]['revision'], 4)
        self.assertEqual(result['effective_labels']['M008'], 'personal')
        history = self.ledger.history('Example Owner')
        self.assertEqual(len(history), 4)
        self.assertEqual(history[0]['status'], 'superseded')
        self.assertIn('synthetic://ExampleOwner/messages/M008', history[0]['source_context'])

    def test_unresolved_latest_retains_prior_valid_override_and_recovers(self):
        self.ingest([correction()])
        result = self.ingest([correction(target='missing', action='spam')])
        self.assertEqual(result['statuses'][0]['status'], 'unresolved')
        self.assertEqual(result['effective_labels']['M008'], 'personal')
        messages = registry()
        messages['missing'] = dict(messages['M008'])
        result = self.ingest([correction(target='missing', action='spam')], messages)
        self.assertEqual(result['effective_labels']['M008'], 'work')
        self.assertEqual(result['effective_labels']['missing'], 'spam')

    def test_revised_earlier_entry_retains_order_and_explicit_undo(self):
        self.ingest([correction('earlier'), correction('later', action='work')])
        result = self.ingest([correction('earlier', action='spam'), correction('later', action='work')])
        self.assertEqual(result['effective_labels']['M008'], 'work')
        result = self.ingest([correction('undo', action='undo', undo_correction='later')])
        self.assertEqual(result['effective_labels']['M008'], 'spam')

    def test_uncertain_retained_spam_excluded_and_mixed_private(self):
        result = self.ingest([correction(action='spam')])
        self.assertEqual(result['views'], {'private': ['M009'], 'work': [], 'personal': []})
        result = self.ingest([correction(action='mixed')])
        self.assertEqual(result['views']['private'], ['M008', 'M009'])
        self.assertEqual(result['views']['work'], [])

    def test_undo_previous_override_without_moving_other_message(self):
        records = [correction('personal'), correction('spam', action='spam'),
                   correction('other', target='M009', action='work')]
        self.ingest(records)
        records.append(correction('undo', action='undo', undo_correction='spam'))
        result = self.ingest(records)
        self.assertEqual(result['effective_labels'], {'M008': 'personal', 'M009': 'work'})
        self.assertEqual(result['statuses'][1]['status'], 'undone')
        self.assertEqual(self.ingest(records)['changed'], 0)
        records.append(correction('badundo', action='undo', undo_correction='other'))
        result = self.ingest(records)
        self.assertEqual(result['statuses'][-1]['status'], 'unresolved')
        records.append(correction('undo2', action='undo', undo_correction='personal'))
        self.assertEqual(self.ingest(records)['effective_labels']['M008'], 'work')

    def test_same_ids_two_owners_and_no_cross_owner_undo(self):
        self.ingest([correction()])
        result = self.ingest([correction(owner='Other Owner', action='spam')], owner='Other Owner')
        self.assertEqual(result['effective_labels']['M008'], 'spam')
        self.assertEqual(self.ingest([correction()])['effective_labels']['M008'], 'personal')
        result = self.ingest([correction('undo', owner='Third Owner', action='undo', undo_correction='c1')],
                             owner='Third Owner')
        self.assertEqual(result['statuses'][0]['status'], 'unresolved')

    def test_restart_idempotent_source_revision_preserves_override(self):
        first = self.ingest([correction()])
        self.assertGreater(first['changed'], 0)
        self.ledger.close()
        self.ledger = CorrectionLedger(self.path)
        self.assertEqual(self.ingest([correction()])['changed'], 0)
        messages = registry()
        messages['M008']['source_revision'] = '2'
        result = self.ingest([correction()], messages)
        self.assertEqual(result['effective_labels']['M008'], 'personal')
        self.assertEqual(result['statuses'][0]['source_context']['source_revision'], '2')
        self.assertEqual(self.ingest([correction()], messages)['changed'], 0)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_transaction_failure_rolls_back_registry_and_records(self):
        with patch.object(self.ledger, '_rebuild', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):
                self.ingest([correction()])
        self.assertEqual(self.ledger.history('Example Owner'), [])
        self.assertEqual(self.ledger.db.execute('SELECT count(*) FROM messages').fetchone()[0], 0)
        self.assertEqual(self.ingest([correction()])['effective_labels']['M008'], 'personal')

    def test_registry_owner_provenance_bounds_timezone_and_unknown_field(self):
        messages = registry()
        messages['M008']['owner'] = 'Other Owner'
        with self.assertRaises(ValueError):
            self.ingest([], messages)
        messages = registry()
        del messages['M008']['provenance']
        with self.assertRaises(ValueError):
            self.ingest([], messages)
        result = self.ingest([correction(requested_at='2026-10-12T12:00:00')])
        self.assertIn('timezone', result['statuses'][0]['reason'])
        result = self.ingest([correction(command='delete')])
        self.assertEqual(result['statuses'][0]['status'], 'unresolved')
        with self.assertRaises(ValueError):
            parse_corrections('a' * 1_000_001)


if __name__ == '__main__':
    unittest.main()

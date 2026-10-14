from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from archive_analysis import ArchiveAnalyzer
from archive_io import AdapterError, JsonCodexAnalyzer
from archive_incremental import IncrementalArchive


def source(sid, text='Synthetic work request', context=None):
    return {'source_id': sid, 'revision': 'r1', 'kind': 'message',
            'timestamp': '2026-10-13T10:00:00Z', 'text': text,
            'conversation_id': 'selected', 'origin_ids': [],
            'context': context or []}


def context(item):
    return {field: item[field] for field in
            ('source_id', 'revision', 'kind', 'timestamp', 'text')}


def fixture():
    first = source('first', 'LARGE MAIN EVIDENCE ' + 'm' * 6000)
    shared = context(source('shared', 'LARGE CONTEXT EVIDENCE ' + 'c' * 6000))
    return {'owner': 'Synthetic Owner', 'policy': 'archive-work-v1:test-model',
            'sources': [first] + [source('target-' + str(i),
                context=[context(first), deepcopy(shared)]) for i in range(3)]}


class ArchiveAnalysisTests(unittest.TestCase):
    def test_shares_context_and_main_evidence_preserving_references_and_input(self):
        payload = fixture()
        original = deepcopy(payload)
        decisions = [{'source_id': item['source_id'], 'label': 'work', 'facts': []}
                     for item in payload['sources']]
        response = {'decisions': decisions,
                    'usage': {'input_tokens': 100, 'output_tokens': 20}}
        with patch.object(JsonCodexAnalyzer, 'analyze', return_value=response) as transport:
            self.assertEqual(ArchiveAnalyzer().analyze(payload), response)
        compact = transport.call_args.args[0]
        self.assertEqual(payload, original)
        self.assertEqual(compact['owner'], payload['owner'])
        self.assertEqual(compact['policy'], payload['policy'])
        self.assertEqual(set(compact['context_sources']), {'shared'})
        self.assertEqual(compact['context_sources']['shared'],
                         payload['sources'][1]['context'][1])
        self.assertEqual(compact['sources'][0]['context_refs'], [])
        for item in compact['sources'][1:]:
            self.assertEqual(item['context_refs'], ['first', 'shared'])
            self.assertNotIn('context', item)
        serialized = json.dumps(compact, ensure_ascii=False)
        self.assertEqual(serialized.count('LARGE MAIN EVIDENCE'), 1)
        self.assertEqual(serialized.count('LARGE CONTEXT EVIDENCE'), 1)
        self.assertLess(len(serialized.encode()), len(json.dumps(payload).encode()) // 2)

    def test_conflicting_context_fails_before_transport(self):
        for conflicting_id in ('first', 'shared'):
            with self.subTest(source_id=conflicting_id):
                payload = fixture()
                index = 0 if conflicting_id == 'first' else 1
                payload['sources'][2]['context'][index]['revision'] = 'changed'
                with patch.object(JsonCodexAnalyzer, 'analyze') as transport:
                    with self.assertRaisesRegex(AdapterError, 'Conflicting'):
                        ArchiveAnalyzer().analyze(payload)
                transport.assert_not_called()

    def test_only_supplied_eligible_context_is_forwarded(self):
        payload = {'owner': 'Synthetic Owner', 'policy': 'test',
                   'sources': [source('target', context=[context(source('approved'))])]}
        compact = ArchiveAnalyzer._compact_payload(payload)
        self.assertEqual(set(compact['context_sources']), {'approved'})
        self.assertEqual(compact['sources'][0]['context_refs'], ['approved'])
        # The adapter has no archive lookup or ability to introduce other context.
        self.assertEqual(set(compact), {'owner', 'policy', 'sources', 'context_sources'})

    def test_incremental_security_and_personal_context_gates_survive_compaction(self):
        items = [source('code', 'Your login verification code is 123456.'),
                 source('personal', 'PRIVATE FAMILY CONTEXT'), source('approved'),
                 source('target', context=['code', 'personal', 'approved'])]
        for item in items:
            item['owner'] = 'Synthetic Owner'
        with tempfile.TemporaryDirectory() as directory:
            cache = IncrementalArchive(Path(directory) / 'analysis.sqlite3')
            try:
                cache.seed('Synthetic Owner', items[:3], [
                    {'source_id': item['source_id'],
                     'label': 'personal' if item['source_id'] == 'personal' else 'work',
                     'facts': []} for item in items[:3]])
                response = {'decisions': [{'source_id': 'target', 'label': 'work', 'facts': []}],
                            'usage': {'input_tokens': 100, 'output_tokens': 20}}
                with patch.object(JsonCodexAnalyzer, 'analyze', return_value=response) as transport:
                    result = cache.analyze('Synthetic Owner', items, ArchiveAnalyzer())
                compact = transport.call_args.args[0]
                self.assertEqual(result['analyzed'], 1)
                self.assertEqual(compact['sources'][0]['context_refs'], ['approved'])
                self.assertEqual(set(compact['context_sources']), {'approved'})
                self.assertNotIn('123456', json.dumps(compact))
                self.assertNotIn('PRIVATE FAMILY CONTEXT', json.dumps(compact))
            finally:
                cache.close()

    def test_requires_every_target_once_and_no_context_only_decisions(self):
        payload = fixture()
        ids = [item['source_id'] for item in payload['sources']]
        invalid = [ids[:-1], ids + ['shared'], [ids[0]] * len(ids),
                   ids[:-1] + ['shared']]
        for selected in invalid:
            with self.subTest(ids=selected):
                response = {'decisions': [{'source_id': sid, 'label': 'work', 'facts': []}
                                         for sid in selected],
                            'usage': {'input_tokens': 100, 'output_tokens': 20}}
                with patch.object(JsonCodexAnalyzer, 'analyze', return_value=response):
                    with self.assertRaises(AdapterError) as raised:
                        ArchiveAnalyzer().analyze(payload)
                self.assertEqual(raised.exception.reported_usage, response['usage'])


if __name__ == '__main__':
    unittest.main()

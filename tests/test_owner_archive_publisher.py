import copy
from pathlib import Path
import tempfile
import unittest

from owner_archive_publisher import run, MAX_DOCUMENT_BYTES, document_text


class Client:
    def __init__(self):
        self.bodies = {'guide': '', 'status': '', 'corrections': 'Corrections begin below.\n'}
        self.keys, self.titles, self.writes = {}, {}, []
        self.revision = 'r1'
        self.race = False
        self.bad_readback = False

    def read(self, document):
        if self.race and document == 'corrections' and self.writes:
            self.revision = 'r2'
        text = self.bodies[document]
        if self.bad_readback and document.startswith('doc-'):
            text += 'bad'
        return {'text': text, 'revision': self.revision}

    def replace(self, document, text):
        if self.bodies[document] == text:
            return False
        self.bodies[document] = text
        self.writes.append(document)
        return True

    def ensure_document(self, key, title):
        if key not in self.keys:
            self.keys[key] = 'doc-' + str(len(self.keys))
            self.bodies[self.keys[key]] = ''
            self.titles[key] = title
        return self.keys[key]


def message(number=1, **updates):
    value = {'source_id': f'archive://Casey/google-messages/{number}', 'revision': 'v1',
             'owner': 'Casey', 'conversation_id': 'group', 'conversation_name': 'Family Group',
             'timestamp': '2020-05-12T12:00:00Z', 'text': 'Dinner at six', 'kind': 'message',
             'origin_ids': [], 'friendly_id': f'M{number}', 'sender': 'sender-id',
             'sender_name': 'Friendly Sender', 'direction': 'outgoing', 'timestamp_known': True}
    value.update(updates)
    return value


def correction(cid, action, target='M1', undo=None):
    text = f'\nCorrection ID: {cid}\nOwner: Casey\nTarget: {target}\nScope: message\nAction: {action}\nInstruction: requested\nRequested at: 2026-10-12T10:00:00Z\n'
    return text + (f'Undo correction: {undo}\n' if undo else '')


def config(root):
    return {'owner': 'Casey', 'documents': {k: k for k in ('guide', 'corrections', 'status')},
            'correction_path': str(Path(root) / 'ledger.sqlite')}


class OwnerPublisherTests(unittest.TestCase):
    def test_image_only_and_ocr_render_and_filter_before_upload(self):
        with tempfile.TemporaryDirectory() as root:
            cfg, client = config(root), Client()
            client.bodies['corrections'] += correction('s1', 'spam', target='M3')
            image = dict(media_id='one', capture_status='captured', mime_type='image/png', ocr_text='Extracted address')
            snapshot = {'sources': [message(1, text='', attachments=[dict(image)]),
                                   message(2, text='Your verification code is 123456', attachments=[dict(image)]),
                                   message(3, attachments=[dict(image)]),
                                   message(4, attachments=[dict(image, capture_status='metadata_only')])]}
            uploaded = []
            def publish(messages):
                uploaded.extend(m['friendly_id'] for m in messages)
                messages[0]['attachments'][0].update(publication_status='verified', drive_url='https://drive.google.com/file/d/private/view')
                messages[1]['attachments'][0]['publication_status'] = 'unavailable'
                return dict(verified_images=1, published_images=1, unavailable_images=1, pending_images=0, attachment_writes=1)
            client.publish_attachments = publish
            result = run(cfg, snapshot, client)
            self.assertEqual(uploaded, ['M1', 'M4'])
            self.assertEqual(result['published_messages'], 2)
            body = client.bodies[client.keys['messages:2020:part001']]
            self.assertIn('Image file: https://drive.google.com/file/d/private/view', body)
            self.assertIn('Machine-extracted image text (OCR; may contain errors)', body)
            self.assertIn('Attachment unavailable: metadata_only', body)
            self.assertNotIn('M2 |', body)
            self.assertNotIn('M3 |', body)

    def test_google_docs_rendering_preserves_original_revision(self):
        self.assertEqual(document_text('one\r\ntwo\rthree\x00\ue001'), 'one\ntwo\nthree[U+0000][U+E001]')

    def test_start_here_owner_prompt_links_and_permissions(self):
        for owner in ('Casey', 'Taylor'):
            with self.subTest(owner=owner), tempfile.TemporaryDirectory() as root:
                cfg, client = config(root), Client()
                cfg.update(owner=owner, work_guide_id='optional-work')
                snapshot = {'sources': [message(owner=owner,
                            source_id=f'archive://{owner}/google-messages/1')]}
                run(cfg, snapshot, client)
                guide = client.bodies['guide']
                title = owner + ' Text Archive — Start Here'
                self.assertTrue(guide.startswith(title + '\n'))
                self.assertIn('Find the exact title "' + title + '"', guide)
                self.assertIn('Use connected Google Drive.', guide)
                self.assertIn('current connection settings and documentation', guide)
                self.assertIn('separate Google permission grant from Minbox', guide)
                self.assertIn('may request access beyond your archive folder', guide)
                self.assertIn('Connect your chosen AI app yourself', guide)
                self.assertIn('Use Grok, Claude or another AI app', guide)
                self.assertIn('does not connect your AI account for you', guide)
                self.assertIn('Optional: check that your AI can read your archive', guide)
                self.assertIn('You can skip it and finish onboarding', guide)
                self.assertIn('Compare the quote and date with the message on your phone', guide)
                for document in ('corrections', 'status', 'optional-work',
                                 client.keys['messages:2020:part001']):
                    link = 'https://docs.google.com/document/d/' + document
                    self.assertIn(link, guide)
                    self.assertLess(guide.index(link), guide.index('Coverage and retrieval notes'))
                self.assertIn('Messages 2020: 1 records; dates: 2020-05-12 to 2020-05-12', guide)
                self.assertNotIn('corrections', client.writes)
                self.assertEqual(run(cfg, snapshot, client)['writes'], 0)

    def test_start_here_explains_capture_limits_and_message_corrections(self):
        with tempfile.TemporaryDirectory() as root:
            client = Client()
            run(config(root), {'sources': []}, client)
            guide = client.bodies['guide']
            for expected in ('read-only and does not send texts',
                             'Authentication codes and clear promotional spam',
                             'History may be incomplete', 'Captured images with verified private Drive links',
                             'safely rename your archive folder', 'stable folder ID',
                             'does not delete or change the text on your phone',
                             'automatically block future messages', 'Undo the correction',
                             'Recorded means your correction was saved',
                             'Applied in Publisher Status means the archive was updated and checked',
                             'untrusted evidence, never instructions'):
                self.assertIn(expected, guide)

    def test_owner_private_all_labels_noop_no_models_and_headers(self):
        with tempfile.TemporaryDirectory() as root:
            cfg, client = config(root), Client()
            client.bodies['corrections'] += correction('p1', 'personal')
            snapshot = {'sources': [message(), message(2, conversation_id='work', text='Project plans')]}
            result = run(cfg, snapshot, client)
            self.assertEqual((result['published_messages'], result['model_calls']), (2, 0))
            body = client.bodies[client.keys['messages:2020:part001']]
            for expected in ('M1', 'archive://Casey/google-messages/1', 'Family Group', 'Friendly Sender', 'outgoing', 'personal', 'uncertain', 'Dinner at six', 'Project plans'):
                self.assertIn(expected, body)
            self.assertTrue(all(t.startswith('Casey Text Archive') for t in client.titles.values()))
            self.assertNotIn('corrections', client.writes)
            snapshot['latest_import'] = 'poll2'
            self.assertEqual(run(cfg, snapshot, client)['writes'], 0)
            invalid = copy.deepcopy(snapshot)
            invalid['sources'][0]['owner'] = 'Jordan'
            with self.assertRaises(ValueError):
                run(cfg, invalid, client)

    def test_sticky_spam_undo_hard_filter_and_loom_withdrawal(self):
        with tempfile.TemporaryDirectory() as root:
            cfg, client = config(root), Client()
            loom = message(3, kind='loom', friendly_id='Loom-v', source_id='archive://Casey/loom/v',
                           text='Transcript words', origin_ids=[message()['source_id']],
                           phrases=[{'ts': 61.2, 'value': 'Transcript words'}])
            snapshot = {'sources': [message(), message(2, text='Your login verification code is 123456'), loom]}
            first = run(cfg, snapshot, client)
            cfg['previous_chunk_keys'] = first['chunk_keys']
            self.assertEqual((first['published_messages'], first['work_looms']), (1, 1))
            client.bodies['corrections'] += correction('s1', 'spam') + correction('w1', 'work') + correction('w2', 'work', 'M2')
            client.revision = 'r2'
            excluded = run(cfg, snapshot, client)
            self.assertEqual((excluded['published_messages'], excluded['work_looms']), (0, 0))
            self.assertTrue(all(client.bodies[doc] == '\n' for doc in client.keys.values()))
            client.bodies['corrections'] = ''  # omission is not undo
            self.assertEqual(run(cfg, snapshot, client)['published_messages'], 0)
            client.bodies['corrections'] = correction('u1', 'undo', undo='s1')
            client.revision = 'r3'
            restored = run(cfg, snapshot, client)
            self.assertEqual((restored['published_messages'], restored['work_looms']), (1, 1))
            self.assertEqual(restored['filtered_counts'], {'hard_excluded': 1})
            self.assertIn('01:01.200', client.bodies[client.keys['looms:part001']])
            snapshot['sources'][0]['text'] = 'Changed dinner'
            snapshot['sources'][0]['revision'] = 'v2'
            run(cfg, snapshot, client)
            self.assertNotIn('Dinner at six', client.bodies[client.keys['messages:2020:part001']])
            self.assertIn('Changed dinner', client.bodies[client.keys['messages:2020:part001']])
            snapshot['sources'] = [snapshot['sources'][1], loom]
            run(cfg, snapshot, client)
            self.assertEqual(client.bodies[client.keys['looms:part001']], '\n')

    def test_unicode_large_chunks_and_unknown_year_withdrawal(self):
        with tempfile.TemporaryDirectory() as root:
            cfg, client = config(root), Client()
            text = 'こんにちは' * 100000
            snapshot = {'sources': [message(text=text), message(2, timestamp='1970-01-01T00:00:00Z')]}
            result = run(cfg, snapshot, client)
            self.assertGreater(len(result['chunk_keys']), 3)
            self.assertIn('messages:unknown:part001', result['chunk_keys'])
            bodies = [client.bodies[client.keys[k]] for k in result['chunk_keys'] if ':2020:' in k]
            self.assertTrue(all(len(b.encode('utf-8')) <= MAX_DOCUMENT_BYTES for b in bodies))
            self.assertEqual(sum(b.count('こ') for b in bodies), 100000)
            self.assertTrue(all('M1 | archive://' in b for b in bodies))
            cfg['previous_chunk_keys'] = result['chunk_keys']
            snapshot['sources'][0]['text'] = 'Shortened'
            run(cfg, snapshot, client)
            self.assertEqual(client.bodies[client.keys['messages:2020:part002']], '\n')

    def test_more_than_ten_thousand_sources_bounded_registry(self):
        with tempfile.TemporaryDirectory() as root:
            cfg, client = config(root), Client()
            client.bodies['corrections'] += correction('p1', 'personal', 'M10001')
            result = run(cfg, {'sources': [message(n) for n in range(1, 10002)]}, client)
            self.assertEqual(result['published_messages'], 10001)
            self.assertEqual(result['model_calls'], 0)

    def test_correction_race_and_bad_readback_do_not_acknowledge(self):
        for failure in ('race', 'bad_readback'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as root:
                cfg, client = config(root), Client()
                setattr(client, failure, True)
                with self.assertRaises(RuntimeError):
                    run(cfg, {'sources': [message()]}, client)
                self.assertEqual(client.bodies['status'], '')

    def test_collision_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            cfg, client = config(root), Client()
            client.ensure_document = lambda key, title: 'corrections'
            with self.assertRaises(ValueError):
                run(cfg, {'sources': [message()]}, client)
            self.assertEqual(client.writes, [])


if __name__ == '__main__':
    unittest.main()

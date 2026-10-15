import copy
from pathlib import Path
import tempfile
import time
import unittest

from owner_archive_publisher import run, MAX_DOCUMENT_BYTES, document_text
from archive_drive import canonical_hash


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
    def test_revision_prefetch_optin_uses_exact_chunk_hashes_and_fixed_progress(self):
        self_test = self
        class PrefetchClient(Client):
            def prefetch_revisions(self, candidates, *, workers, progress):
                self_test.assertEqual(set(candidates), set(self.keys.values()))
                self_test.assertNotIn('corrections', candidates)
                self_test.assertNotIn('guide', candidates)
                self_test.assertNotIn('status', candidates)
                self_test.assertEqual(self.writes, [])
                self.prefetched = candidates
                self.workers = workers
                progress()
                progress()
            def replace(self, document, text):
                if document in self.keys.values():
                    self_test.assertEqual(self.prefetched[document], canonical_hash(text))
                return super().replace(document, text)
        for workers in (2, 3):
            with self.subTest(workers=workers), tempfile.TemporaryDirectory() as root:
                cfg, client, phases = config(root), PrefetchClient(), []
                cfg['revision_probe_workers'] = workers
                run(cfg, {'sources': [message(text='Control\x00\r\nline'),
                                     message(2, timestamp='2021-01-01T12:00:00Z')]},
                    client, progress=phases.append)
                self.assertEqual(client.workers, workers)
                self.assertEqual(phases.count('revision_prefetch'), 3)
                self.assertLess(phases.index('revision_prefetch'), phases.index('output_verification'))
                self.assertEqual(client.bodies['corrections'], 'Corrections begin below.\n')
                self.assertTrue(all('doc-' not in phase and 'archive://' not in phase for phase in phases))

    def test_revision_prefetch_defaults_to_sequential(self):
        self_test = self
        class SequentialClient(Client):
            def prefetch_revisions(self, candidates, *, workers):
                self_test.assertEqual(candidates, {})
                self_test.assertEqual(workers, 1)
                self.cleared = True
        for explicit in (False, True):
            with self.subTest(explicit=explicit), tempfile.TemporaryDirectory() as root:
                cfg, client = config(root), SequentialClient()
                if explicit:
                    cfg['revision_probe_workers'] = 1
                result = run(cfg, {'sources': [message()]}, client)
                self.assertEqual(result['published_messages'], 1)
                self.assertTrue(client.cleared)

    def test_invalid_revision_prefetch_config_fails_before_corrections_or_outputs(self):
        class NoReadsClient(Client):
            def read(self, document):
                raise AssertionError('invalid worker configuration must fail first')
        for invalid in (0, 4, -1, True, False, None, 3.0, '3'):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as root:
                cfg, client = config(root), NoReadsClient()
                cfg['revision_probe_workers'] = invalid
                with self.assertRaisesRegex(ValueError, 'worker bound'):
                    run(cfg, {'sources': [message()]}, client)
                self.assertEqual(client.writes, [])

    def test_private_progress_uses_fixed_stages_before_operations(self):
        phases = []
        class ProgressClient(Client):
            def read(self, document):
                if document == 'corrections':
                    self_stage = 'corrections_check' if self.writes else 'corrections_read'
                    self_test.assertEqual(phases[-1], self_stage)
                return super().read(document)
            def ensure_document(self, key, title):
                self_test.assertEqual(phases[-1], 'documents')
                return super().ensure_document(key, title)
            def replace(self, document, text):
                expected = {'guide': 'guide_verification', 'status': 'final_status'}
                self_test.assertEqual(phases[-1], expected.get(document, 'output_verification'))
                return super().replace(document, text)
            def publish_attachments(self, messages):
                self_test.assertEqual(phases[-1], 'image_publication')
                return dict(verified_images=0, unavailable_images=0, published_images=0,
                            pending_images=0, attachment_writes=0)
            def withdraw_phone_spam(self, source_ids, images):
                self_test.assertEqual(phases[-1], 'phone_spam_withdrawal')
                return dict(withdrawn_images=0, pending_image_deletions=0)
        self_test = self
        with tempfile.TemporaryDirectory() as root:
            current = {'sources': [message(), message(2, timestamp='2021-01-01T12:00:00Z')],
                       'phone_spam_source_ids': ['private-source-identity']}
            client = ProgressClient()
            run(config(root), current, client, progress=phases.append)
            self.assertEqual(phases, ['corrections_read', 'image_publication', 'rendering',
                'documents', 'output_verification', 'output_verification', 'guide_verification',
                'phone_spam_withdrawal', 'corrections_check', 'final_status'])
            self.assertNotIn('private-source-identity', str(phases))
            self.assertNotIn('archive://', str(phases))
            self.assertNotIn('doc-', str(phases))

    def test_progress_failure_stops_before_publication(self):
        def fail(stage):
            if stage == 'output_verification':
                raise OSError('synthetic private status write failure')
        with tempfile.TemporaryDirectory() as root:
            client = Client()
            with self.assertRaisesRegex(OSError, 'status write failure'):
                run(config(root), {'sources': [message()]}, client, progress=fail)
            self.assertEqual(client.writes, [])
            self.assertEqual(client.bodies['status'], '')

    def test_explicit_verification_avoids_output_reads_and_keeps_corrections_fresh(self):
        class VerifiedClient(Client):
            def __init__(self):
                super().__init__()
                self.reads = []
            def read(self, document):
                self.reads.append(document)
                if document != 'corrections':
                    raise AssertionError('verified output must not be read again')
                return super().read(document)
            def replace_verified(self, document, text):
                changed = super().replace(document, text)
                return {'changed': changed, 'hash': canonical_hash(text), 'revision': 'verified',
                        'verified_at': time.time(),
                        'verification': 'full_readback' if changed else 'revision_probe'}
        with tempfile.TemporaryDirectory() as root:
            cfg, client = config(root), VerifiedClient()
            current = {'sources': [message()]}
            first = run(cfg, current, client)
            self.assertGreater(first['writes'], 0)
            self.assertEqual(client.reads, ['corrections', 'corrections'])
            self.assertEqual(run(cfg, current, client)['writes'], 0)
            self.assertEqual(client.reads, ['corrections'] * 4)
            client.race = True
            client.writes.clear()
            current['sources'][0]['text'] = 'changed captured text'
            with self.assertRaisesRegex(RuntimeError, 'corrections changed'):
                run(cfg, current, client)

    def test_invalid_verification_proofs_cannot_acknowledge_publication(self):
        class InvalidClient(Client):
            def replace_verified(self, document, text):
                return {**{'changed': False, 'hash': canonical_hash(text), 'revision': 'verified',
                           'verified_at': time.time(), 'verification': 'revision_probe'}, **self.invalid}
        for invalid in ({'hash': '0' * 64}, {'changed': 1}, {'revision': ''},
                        {'verified_at': time.time() + 3600}, {'verification': 'unverified'},
                        {'changed': True}, {'verified_at': 0}):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as root:
                client = InvalidClient()
                client.invalid = invalid
                phases = []
                with self.assertRaisesRegex(RuntimeError, 'proof mismatch'):
                    run(config(root), {'sources': [message()]}, client, progress=phases.append)
                self.assertEqual(phases[-1], 'output_verification')
                self.assertNotIn('final_status', phases)
                self.assertEqual(client.bodies['status'], '')

    def test_phone_spam_withdraws_all_years_before_image_deletion_and_stays_absent(self):
        with tempfile.TemporaryDirectory() as root:
            cfg, client = config(root), Client()
            junk = message(1, conversation_id='junk', text='Synthetic discarded conversation',
                           timestamp='2025-01-01T10:00:00Z')
            reply = message(2, conversation_id='junk', text='Synthetic discarded reply')
            keep = message(3, conversation_id='ordinary', text='Synthetic retained message')
            run(cfg, {'sources': [junk, reply, keep]}, client)
            cfg['previous_chunk_keys'] = list(client.keys)
            withdrawals = []
            def withdraw(ids, images):
                self.assertTrue(all('Synthetic discarded' not in body for body in client.bodies.values()))
                withdrawals.append(set(ids))
                return {'withdrawn_images': 0, 'pending_image_deletions': 0}
            client.withdraw_phone_spam = withdraw
            cfg['phone_spam_policy'] = 'spam_and_blocked'
            current = {'sources': [keep], 'phone_spam_source_ids': [junk['source_id'],reply['source_id']],
                       'phone_spam_conversations': 1, 'phone_spam_images': []}
            result = run(cfg,current,client)
            self.assertEqual(result['published_messages'],1)
            self.assertIn('Whole conversations observed in Google Messages Spam & blocked',client.bodies['guide'])
            self.assertEqual(result['filtered_counts']['phone_spam'],2)
            self.assertEqual(withdrawals,[{junk['source_id'],reply['source_id']}])
            self.assertTrue(any('Synthetic retained message' in body for body in client.bodies.values()))
            self.assertFalse(client.bodies[client.keys['messages:2025:part001']].strip())
            cfg['previous_chunk_keys'] = list(client.keys)
            self.assertEqual(run(cfg,current,client)['writes'],0)
            # A confirmed phone restoration returns both years, without new Doc IDs.
            keys_before = dict(client.keys)
            client.withdraw_phone_spam = lambda ids, images: {'withdrawn_images': 0, 'pending_image_deletions': 0}
            restored = {'sources': [junk, reply, keep], 'phone_spam_source_ids': [],
                        'phone_spam_conversations': 0, 'phone_spam_images': []}
            result = run(cfg, restored, client)
            self.assertEqual(result['published_messages'], 3)
            self.assertEqual(client.keys, keys_before)
            self.assertIn('Synthetic discarded conversation', client.bodies[client.keys['messages:2025:part001']])
            self.assertTrue(any('Synthetic discarded reply' in body for body in client.bodies.values()))
            self.assertEqual(run(cfg, restored, client)['writes'], 0)

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
                self.assertIn('current settings and documentation', guide)
                self.assertIn('Google grant is separate from Minbox', guide)
                self.assertIn('can extend beyond this archive', guide)
                self.assertIn('Connect your chosen AI app yourself', guide)
                self.assertIn('Use ChatGPT, Grok, Claude or another app', guide)
                self.assertIn('You handle sign-in and access consent', guide)
                self.assertIn('Ask a useful question from your phone', guide)
                self.assertNotIn('You can skip it and finish onboarding', guide)
                self.assertIn('Check one useful answer and its source', guide)
                self.assertIn('Compare the answer and its source with the messages you recognize', guide)
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
                             'authentication codes, recognizable password-reset links, and clear promotional spam',
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

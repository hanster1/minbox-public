import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / 'scripts/build_gmkit_media.py'
spec = importlib.util.spec_from_file_location('gmkit_media_builder', MODULE)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class GmkitMediaPatchTests(unittest.TestCase):
    def test_source_pin_cleanliness_and_official_origin_required(self):
        with patch.object(builder, 'run', side_effect=[builder.COMMIT, '', builder.UPSTREAM]):
            builder.validate_source(Path('/fixture'))
        for output in [['other-commit'], [builder.COMMIT, 'dirty'], [builder.COMMIT, '', 'https://untrusted.example/gmkit.git']]:
            with patch.object(builder, 'run', side_effect=output):
                with self.assertRaises(ValueError): builder.validate_source(Path('/fixture'))

    def test_output_must_be_private_outside_git_and_empty(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / '.git').mkdir()
            (root / '.git' / 'HEAD').write_text('ref: refs/heads/main')
            with self.assertRaises(ValueError): builder.build(root / 'output')
            (root / '.git' / 'HEAD').unlink()
            (root / '.git').rmdir()
            (root / 'output').mkdir()
            (root / 'output' / 'keep').write_text('existing artifact')
            with self.assertRaises(ValueError): builder.build(root / 'output')
            (root / 'link').symlink_to(root / 'output')
            with self.assertRaises(ValueError): builder.build(root / 'link')

    def test_patch_contains_offline_regressions_and_public_provenance(self):
        source = builder.PATCH.read_text()
        for name in ['internal/media/media.go', 'internal/media/media_test.go',
                     'internal/gm/media_request_test.go', 'internal/sync/media_test.go',
                     'TestMediaDownloadRequiresExistingDaemonWithoutAutoStart',
                     'cmd/minbox-refresh-session/main.go',
                     'TestStrippedHistoryPreservesFullMediaWithoutMixingChangedKeys',
                     'internal/cmd/phone_spam.go', 'internal/cmd/phone_spam_test.go',
                     'TestPhoneSpamMetadataOnlyReconciliationReportsCoverage',
                     'TestPhoneSpamPendingRequestIsBoundedWithoutConcurrentRetry',
                     'TestPhoneSpamMigrationPreservesExistingArchive',
                     'TestPhoneSpamStatusDistinguishesArchiveDeleteUnknownAndStaysSticky',
                     'TestPhoneFolderRestoreRequiresFreshSuccessfulTargetedRead',
                     'TestPhoneFolderRestorationRevisionAndStaleResponseGuard',
                     'TestPhoneFolderRestorationBatchFailureKeepsAllExclusions',
                     'TestPhoneFolderMigrationRetainsV4SpamEvidence',
                     'TestPhoneTargetedPendingRequestRetainsStartAndDoesNotClearReblock',
                     'TestPhoneTargetedLookupRotatesBeyondDiscoveryAndLookupCaps']:
            self.assertIn(name, source)
        self.assertIn('GNU Affero General Public License', builder.NOTICE)
        self.assertIn(builder.COMMIT, builder.NOTICE)

    def test_spam_paging_patch_escalates_capped_folder_with_regression(self):
        self.assertEqual(builder.PATCHES[0], builder.PATCH)
        source = builder.PATCHES[1].read_text()
        for name in ['internal/cmd/phone_spam.go', 'phoneSpamMaxLimit', 'next_limit',
                     'TestPhoneSpamCappedFolderEscalatesRequestSize']:
            self.assertIn(name, source)
        self.assertIn('gmkit-spam-paging.patch', builder.NOTICE)

    @unittest.skipUnless(os.environ.get('GMKIT_TEST_SOURCE') and os.environ.get('GMKIT_TEST_GO'),
                         'requires clean pinned upstream checkout and local Go toolchain')
    def test_pinned_patch_applies_tests_and_builds_offline_account_free(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'build'
            metadata = builder.build(output, source=os.environ['GMKIT_TEST_SOURCE'], go=os.environ['GMKIT_TEST_GO'])
            self.assertEqual(metadata['commit'], builder.COMMIT)
            self.assertEqual(metadata['artifacts']['gmcli'], builder.digest(output / 'gmcli'))
            self.assertTrue((output / 'gmkit-media-source.tar.gz').is_file())
            self.assertEqual((output / 'gmcli').stat().st_mode & 0o777, 0o700)
            self.assertEqual((output / 'minbox-refresh-session').stat().st_mode & 0o777, 0o700)
            self.assertFalse(metadata['installed'])


if __name__ == '__main__': unittest.main()

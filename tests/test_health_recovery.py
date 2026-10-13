import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import health_recovery as recovery


class RecoveryController(unittest.TestCase):
    def setUp(self):
        self.state, self.actions, self.sent = {}, [], []
        self.config = {'owners': ['Owner'], 'publishers': [
            {'name': 'owner', 'kind': 'owner_all'}, {'name': 'work'}]}
        self.worker = {'ActiveState': 'failed', 'Result': 'exit-code', 'UnitFileState': 'enabled'}

    def props(self, unit):
        return {'ActiveState': 'active', 'UnitFileState': 'enabled'} if unit.endswith('.timer') else self.worker

    def run_check(self, now, issues=(), **extra):
        return recovery.supervise(self.state, {'issues': issues, **extra}, self.config, now,
            properties=self.props, action=lambda *args: self.actions.append(args), deliver=self.sent.append)

    def test_transient_failure_is_repaired_and_verified_without_any_email(self):
        self.run_check(0, ['publisher_1.worker_failure'])
        report = self.run_check(60, ['publisher_1.worker_failure'])
        self.assertEqual(self.actions, [('start', 'minbox-owner-archive@owner.service')])
        self.assertEqual(report['components']['publisher_1']['state'], 'recovering')
        self.assertFalse(self.sent)
        self.worker['ActiveState'] = 'active'
        self.run_check(120, [], deferred_recoveries=['publisher_1.worker_failure'])
        self.assertNotIn('healthy_since', self.state['recovery']['publisher_1'])
        self.worker['ActiveState'] = 'inactive'
        self.run_check(180)
        self.assertEqual(self.state['recovery']['publisher_1']['state'], 'healthy')
        self.assertFalse(self.sent)

    def test_long_outage_retries_three_times_then_one_email_not_reminders_or_recoveries(self):
        bad = ['publisher_1.worker_failure', 'publisher_1.worker_stale']
        for now in (0, 60, 120, 420, 1320, 1800, 24000):
            self.run_check(now, bad)
        self.assertEqual(len(self.actions), 3)
        self.assertEqual(len(self.sent), 1)
        self.assertIn('Recovery attempts: 3', self.sent[0])
        self.run_check(24100)
        self.run_check(24200, bad)
        self.assertEqual(len(self.sent), 1)
        # A relapse gets repairs but retains the human notice dedupe.
        self.run_check(24260, bad)
        self.assertEqual(len(self.actions), 4)

    def test_recovery_budget_survives_controller_restart(self):
        bad = ['publisher_1.worker_failure']
        for now in (0, 60, 120, 420):
            self.run_check(now, bad)
        self.state = copy.deepcopy(self.state)
        self.run_check(1320, bad)
        self.assertEqual(len(self.actions), 3)
        self.run_check(1800, bad)
        self.assertEqual(len(self.sent), 1)

    def test_active_worker_not_restarted_or_escalated_mid_retry(self):
        bad = ['publisher_1.worker_stale']
        self.run_check(0, bad)
        self.worker['ActiveState'] = 'activating'
        self.run_check(3600, bad)
        self.assertFalse(self.actions)
        self.assertFalse(self.sent)

    def test_stuck_active_worker_escalates_without_blind_restart(self):
        self.worker['ActiveState'] = 'activating'
        for now in (0, 100, 601, 1800, 24000):
            self.run_check(now, ['publisher_1.worker_stale'])
        self.assertFalse(self.actions)
        self.assertEqual(len(self.sent), 1)

    def test_auth_and_privacy_require_one_human_notice_without_mutation(self):
        for i in range(3):
            self.run_check(i * 60, ['collector_1.authentication'])
        self.assertEqual(len(self.sent), 1)
        self.assertFalse(self.actions)
        self.run_check(200, ['publisher_1.human_required'],
                       components={'publisher_1': {'failure_kind': 'privacy'}})
        self.assertEqual(len(self.sent), 2)
        self.assertNotIn('private-message', ''.join(self.sent))

    def test_optional_analysis_and_history_never_email_when_primary_available(self):
        self.config['backfills'] = [{'owner': 'Owner'}]
        bad = ['publisher_2.analysis_paused', 'publisher_2.input_limit', 'backfill_1.paused']
        for now in (0, 1800, 24000):
            self.run_check(now, bad)
        self.assertFalse(self.sent)
        self.assertFalse(self.actions)
        self.assertEqual(self.state['recovery']['publisher_2']['state'], 'maintenance_pending')

    def test_disabled_timer_and_explicit_pause_never_reenabled(self):
        bad = ['publisher_1.timer']
        with patch.object(self, 'props', return_value={'ActiveState': 'inactive', 'UnitFileState': 'disabled'}):
            self.run_check(0, bad)
            self.run_check(1800, bad)
        self.assertFalse(self.actions)
        self.assertEqual(len(self.sent), 1)
        self.config['recovery'] = {'paused_components': ['publisher_1']}
        self.state, self.sent = {}, []
        self.run_check(0, bad)
        self.run_check(1800, bad)
        self.assertFalse(self.sent)

    def test_disabled_recovery_still_escalates_unresolved_essential_outage(self):
        self.config['recovery'] = {'enabled': False}
        self.run_check(0, ['publisher_1.worker_stale'])
        self.run_check(1800, ['publisher_1.worker_stale'])
        self.assertFalse(self.actions)
        self.assertEqual(len(self.sent), 1)

    def test_failed_notification_retries_without_claiming_delivery(self):
        def failed(_):
            raise RuntimeError('PRIVATE')
        observed = {'issues': ['collector_1.authentication']}
        report = recovery.supervise(self.state, observed, self.config, 0,
            properties=self.props, deliver=failed)
        self.assertEqual(report['delivery'], 'failed')
        self.assertFalse(self.state['recovery']['collector_1']['notified'])
        self.run_check(60, observed['issues'])
        self.assertEqual(len(self.sent), 1)

    def test_integrity_prevents_recovery_writes(self):
        bad = ['archive.integrity', 'publisher_1.worker_failure']
        self.run_check(0, bad)
        self.run_check(1800, bad)
        self.assertFalse(self.actions)
        self.assertEqual(len(self.sent), 1)

    def test_collector_reconnect_bounded_and_import_backlog_runs_import(self):
        bad = ['collector_1.disconnected']
        self.worker['ActiveState'] = 'active'
        self.run_check(0, bad)
        self.run_check(299, bad)
        self.assertFalse(self.actions)
        self.run_check(300, bad)
        self.assertEqual(self.actions[-1], ('restart', 'minbox-text-collector@Owner.service'))
        self.run_check(310)
        self.worker['ActiveState'] = 'inactive'
        self.run_check(400, ['collector_1.archive_backlog'])
        self.run_check(460, ['collector_1.archive_backlog'])
        self.assertEqual(self.actions[-1], ('start', 'minbox-text-import@Owner.service'))

    def test_persistent_disconnected_running_collector_still_escalates(self):
        self.worker['ActiveState'] = 'active'
        for now in (0, 300, 360, 660, 1800):
            self.run_check(now, ['collector_1.disconnected'])
        self.assertEqual(len(self.actions), 3)
        self.assertEqual(len(self.sent), 1)

    def test_unsafe_send_mode_is_quarantined_once_and_needs_human(self):
        self.run_check(0, ['collector_1.send_mode'])
        self.run_check(60, ['collector_1.send_mode'])
        self.assertEqual(self.actions, [('stop', 'minbox-text-collector@Owner.service')])
        self.assertEqual(len(self.sent), 1)
        self.run_check(120)
        self.run_check(180, ['collector_1.send_mode'])
        self.assertEqual(len(self.actions), 2)
        self.assertEqual(len(self.sent), 1)

    def test_distinct_new_safety_emergency_is_not_hidden_by_prior_notice(self):
        self.run_check(0, ['collector_1.authentication'])
        self.run_check(60)
        self.run_check(120, ['collector_1.source_integrity'])
        self.run_check(180, ['collector_1.source_integrity'])
        self.assertEqual(len(self.sent), 2)
        self.run_check(200, ['collector_1.authentication'])
        self.assertEqual(len(self.sent), 2)

    def test_untrusted_actions_and_names_are_rejected(self):
        for action, unit in [('restart', 'ssh.service'), ('enable', 'minbox-text-loom.service'),
                             ('start', 'minbox-owner-archive@bad/name.service')]:
            with self.assertRaises(ValueError):
                recovery.service_action(action, unit)
        self.config['publishers'][0]['name'] = 'unsafe/name'
        self.run_check(0, ['publisher_1.configuration'])
        self.assertFalse(self.actions)

    def test_enabled_stopped_timer_is_started_without_enabling_disabled_jobs(self):
        def properties(unit):
            return {'ActiveState': 'inactive', 'UnitFileState': 'enabled'}
        with patch.object(self, 'props', side_effect=properties):
            self.run_check(0, ['publisher_1.timer'])
            self.run_check(60, ['publisher_1.timer'])
        self.assertEqual(self.actions, [('start', 'minbox-owner-archive@owner.timer')])

    def test_monitor_cli_never_sends_legacy_recovery_and_check_only_has_no_actions(self):
        import health_monitor as health
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'config.json'
            config.write_text(json.dumps({'owners': [], 'state_dir': str(root / 'state'),
                                         'delivery': {'type': 'smtp'}}))
            config.chmod(0o600)
            observed = {'issues': {'publisher_1.analysis_paused': 0}, 'missing': {}, 'check_failed': False}
            with patch.object(health, 'observe', return_value=observed), patch.object(recovery, 'service_action') as action, patch.object(health, 'send_notification') as send, patch('builtins.print'):
                self.assertEqual(health.main(['--config', str(config), '--check-only']), 1)
                self.assertFalse((root / 'state/state.json').exists())
                self.assertEqual(health.main(['--config', str(config)]), 1)
                observed['issues'] = {}
                self.assertEqual(health.main(['--config', str(config)]), 0)
                send.assert_not_called()
                action.assert_not_called()


if __name__ == '__main__':
    unittest.main()

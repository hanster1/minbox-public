import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from activate_owner import activate


class ActivateOwner(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.publisher = self.home / '.config/minbox-text-archive/publishers/Taylor-full.json'
        self.publisher.parent.mkdir(parents=True)
        self.publisher.write_text(json.dumps({'owner':'Taylor','scope':'owner_all',
            'archive_root':str(self.home / '.local/share/minbox-text-archive'), 'status_file':str(self.home / 'Taylor-status.json')}))
        self.publisher.chmod(0o600)
        self.health = self.home / '.config/minbox-text-archive/health.json'
        self.health.write_text(json.dumps({'owners':['Casey','Taylor'], 'publishers':[],
            'delivery':{'type':'none'}, 'private_delivery_test':'preserve'}))
        self.health.chmod(0o600)
        session = self.home / '.local/state/minbox-text-archive-collectors/Taylor/session.json'
        session.parent.mkdir(parents=True)
        session.write_text('{}');session.chmod(0o600)
        units = self.home / '.config/systemd/user'
        units.mkdir(parents=True)
        for name in ('minbox-text-collector@.service','minbox-text-import@.timer',
                     'minbox-text-backfill@.timer','minbox-owner-archive@.timer'):
            (units / name).write_text('fixture')
        self.calls = []

    def publication(self, args):
        print(json.dumps({'published_messages':2,'excluded_messages':1,'model_calls':0}))
        return 0

    def success(self, **overrides):
        kwargs = dict(home=self.home, run=self.calls.append, validate=lambda config:None,
            status=lambda path:{'connected':True,'auth_expired':False,'offline':False,'send_mode':'off'},
            publish=self.publication, importer=lambda *args:{'imported':2},
            history_check=lambda *args,**kwargs:{'outcome':'check_only','source_messages':2})
        kwargs.update(overrides)
        with patch('activate_owner.platform.system', return_value='Linux'):
            return activate('Taylor', **kwargs)

    def test_owned_units_only_idempotent_health_and_pause_preservation(self):
        self.assertTrue(self.success()['activated'])
        self.success()
        self.assertTrue(all('Taylor' in unit for call in self.calls for unit in call[2:]))
        self.assertFalse(any('minbox-text-health' in unit for call in self.calls for unit in call))
        health = json.loads(self.health.read_text())
        self.assertEqual(health['delivery'], {'type':'none'})
        self.assertEqual(health['private_delivery_test'], 'preserve')
        self.assertEqual(len(health['publishers']), 1)
        self.assertEqual(len(health['backfills']), 1)

    def test_settings_and_other_enrollment_changed_during_publish_survive(self):
        def publication(args):
            data = json.loads(self.health.read_text())
            data['delivery'] = {'type':'changed-during-setup'}
            data['owners'].append('Morgan')
            data['publishers'].append({'name':'Morgan','kind':'owner_all','status_file':'/private/morgan.json'})
            self.health.write_text(json.dumps(data))
            return self.publication(args)
        self.success(publish=publication)
        data = json.loads(self.health.read_text())
        self.assertEqual(data['delivery'], {'type':'changed-during-setup'})
        self.assertEqual({p['name'] for p in data['publishers']}, {'Taylor','Morgan'})

    def test_wrong_account_validation_prevents_unit_changes(self):
        def reject(config):raise ValueError('wrong account')
        with self.assertRaises(ValueError):self.success(validate=reject)
        self.assertFalse(self.calls)

    def test_first_publish_failure_leaves_publisher_unenabled(self):
        with self.assertRaises(RuntimeError):self.success(publish=lambda args:1)
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn('minbox-owner-archive@Taylor.timer', self.calls[0])
        self.assertFalse(json.loads(self.health.read_text())['publishers'])

    def test_send_enabled_never_claims_activation(self):
        stamps = iter([0, 31])
        with self.assertRaises(RuntimeError):
            self.success(clock=lambda:next(stamps), sleep=lambda _:None,
                status=lambda path:{'connected':True,'auth_expired':False,'offline':False,'send_mode':'direct'})
        self.assertEqual(len(self.calls), 1)

    def test_custom_root_rejected_before_enabling_default_import_timer(self):
        config = json.loads(self.publisher.read_text())
        config['archive_root'] = str(self.home / 'different archive')
        self.publisher.write_text(json.dumps(config))
        with self.assertRaises(ValueError):self.success()
        self.assertFalse(self.calls)

    def test_unpaired_owner_and_wrong_scope_fail_before_services(self):
        (self.home / '.local/state/minbox-text-archive-collectors/Taylor/session.json').unlink()
        with self.assertRaises(FileNotFoundError):self.success()
        self.assertFalse(self.calls)

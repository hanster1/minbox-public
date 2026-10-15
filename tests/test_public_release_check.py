import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    'check_public_release', Path(__file__).resolve().parents[1] / 'scripts' / 'check_public_release.py')
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


class PrivateDetailPatterns(unittest.TestCase):
    def test_fictional_numbers_pass_and_real_shapes_fail(self):
        self.assertIsNone(check.PHONE.search(b'+15555550101 and 555-0101'))
        self.assertIsNotNone(check.PHONE.search(b'call 312-' + b'867-5309'))
        self.assertIsNotNone(check.PHONE.search(b'+1312' + b'8675309'))

    def test_home_paths(self):
        self.assertIsNone(check.HOME_PATH.search(b'/home/user/Minbox/Casey/Filtered'))
        self.assertIsNotNone(check.HOME_PATH.search(b'/home/' + b'realperson/archive'))

    def test_personal_email(self):
        self.assertIsNone(check.PRIVATE_EMAIL.search(b'person@gmail.com'))
        self.assertIsNotNone(check.PRIVATE_EMAIL.search(b'jo.doe' + b'@gmail.com'))

    def test_placeholder_names_are_not_private(self):
        self.assertFalse(check.private_word_hits(b'Casey and Jordan share a computer'))


if __name__ == '__main__':
    unittest.main()

import chi
import unittest

class Context(unittest.TestCase):

    def test_fetch(self):
        value = 'KEYNAME'
        chi.set('key_name', value)
        self.assertEqual(chi.get('key_name'), value)

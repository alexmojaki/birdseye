import unittest

from birdseye.db import Database


class TestDatabase(unittest.TestCase):
    def test_key_value_store(self):
        kv = Database().key_value_store

        self.assertIsNone(kv.thing)

        kv.thing = 'foo'
        self.assertEqual(kv.thing, 'foo')

        kv.thing = 'bar'
        self.assertEqual(kv.thing, 'bar')


if __name__ == '__main__':
    unittest.main()

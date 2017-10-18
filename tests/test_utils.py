import unittest
from birdseye.utils import iter_get, common_ancestor, short_path
from random import shuffle


class TestUtils(unittest.TestCase):
    def test_iter_get(self):
        lst = list(range(100))
        shuffle(lst)
        for i in range(-100, 100):
            self.assertEqual(iter_get(lst, i),
                             lst[i])

    def test_common_ancestor(self):
        self.assertEqual(
            common_ancestor(['/123/456', '/123/457', '/123/abc/def']),
            '/123/'
        )
        self.assertEqual(
            common_ancestor(['\\123\\456', '\\123\\457', '\\123\\abc\\def']),
            '\\123\\'
        )

    def test_short_path(self):
        def check(paths, result):
            self.assertEqual(result, [short_path(path, paths) for path in paths])

        check(['/123/456', '/123/457', '/123/abc/def'], ['456', '457', 'abc/def'])
        check(['/123/456'], ['456'])
        check(['/123'], ['/123'])
        check(['/123/456', '/abc/def'], ['/123/456', '/abc/def'])
        check(['\\123\\456', '\\123\\457', '\\123\\abc\\def'], ['456', '457', 'abc\\def'])
        check(['\\123\\456'], ['456'])
        check(['\\123'], ['\\123'])
        check(['\\123\\456', '\\abc\\def'], ['\\123\\456', '\\abc\\def'])


if __name__ == '__main__':
    unittest.main()

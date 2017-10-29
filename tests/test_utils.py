import unittest
from birdseye.utils import iter_get, common_ancestor, short_path, flatten_list
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

    def test_flatten_list(self):
        def check(inp, out):
            self.assertEqual(flatten_list(inp), out)

        check([], [])
        check(['abc'], ['abc'])
        check(['ab', 'cd'], ['ab', 'cd'])
        check(['ab', ['cd', 'ef']], ['ab', 'cd', 'ef'])
        check([['x', 'y'], 'ab', [['0', '1'], [[], 'cd', 'ef', ['ghi', [[['jkl']]]]]]],
              ['x', 'y', 'ab', '0', '1', 'cd', 'ef', 'ghi', 'jkl'])


if __name__ == '__main__':
    unittest.main()

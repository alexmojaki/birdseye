import unittest
from birdseye.utils import common_ancestor, short_path, flatten_list, is_lambda


class TestUtils(unittest.TestCase):
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

    def test_is_lambda(self):
        self.assertTrue(is_lambda(lambda: 0))
        self.assertTrue(is_lambda(lambda x, y: x + y))
        self.assertFalse(is_lambda(min))
        self.assertFalse(is_lambda(flatten_list))
        self.assertFalse(is_lambda(self.test_is_lambda))


if __name__ == '__main__':
    unittest.main()

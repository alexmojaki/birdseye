# coding=utf8

import ast
import unittest
from tempfile import mkstemp

import asttokens
import numpy as np
import pandas as pd
from cheap_repr import cheap_repr

from birdseye.utils import common_ancestor, short_path, flatten_list, is_lambda, source_without_decorators, PY3, \
    read_source_file


def def_decorator(_):
    def actual_decorator(f):
        return f

    return actual_decorator


def eye(f):
    return f


@def_decorator('def')
@eye
def define(defx, defy):
    """
def def def

@eye
def define(defx, defy):
    """
    def inner():
        pass
    return defx + defy + inner


define_source = '''\
def define(defx, defy):
    """
def def def

@eye
def define(defx, defy):
    """
    def inner():
        pass
    return defx + defy + inner'''


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

    def test_open_with_encoding_check(self):
        filename = mkstemp()[1]

        def write(stuff):
            with open(filename, 'wb') as f:
                f.write(stuff)

        def read():
            return read_source_file(filename).strip()

        # Correctly declared encodings

        write(u'# coding=utf8\né'.encode('utf8'))
        self.assertEqual(u'é', read())

        write(u'# coding=gbk\né'.encode('gbk'))
        self.assertEqual(u'é', read())

        # Wrong encodings

        write(u'# coding=utf8\né'.encode('gbk'))
        self.assertRaises(UnicodeDecodeError, read)

        write(u'# coding=gbk\né'.encode('utf8'))
        self.assertFalse(u'é' in read())

        # In Python 3 the default encoding is assumed to be UTF8
        if PY3:
            write(u'é'.encode('utf8'))
            self.assertEqual(u'é', read())

            write(u'é'.encode('gbk'))

            # The lack of an encoding when one is needed
            # ultimately raises a SyntaxError
            self.assertRaises(SyntaxError, read)

    def test_source_without_decorators(self):
        source = read_source_file(__file__)
        tokens = asttokens.ASTTokens(source, parse=True)
        function_def_node = next(n for n in ast.walk(tokens.tree)
                                 if isinstance(n, ast.FunctionDef) and
                                 n.name == 'define')
        self.assertEqual(define_source,
                         source_without_decorators(tokens, function_def_node)[1])

    def test_cheap_repr(self):
        arr = np.arange(10000)
        arr = arr.reshape((100, 100))
        df = pd.DataFrame(arr)
        series = df[0]
        self.assertEqual(cheap_repr(series), "0 = 0; 1 = 100; 2 = 200; ...; 97 = 9700; 98 = 9800; 99 = 9900")


if __name__ == '__main__':
    unittest.main()

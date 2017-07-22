import unittest
import sys
from collections import OrderedDict

from birdseye.cheap_repr import basic_repr, register_repr, cheap_repr

try:
    from unittest import skipUnless
except ImportError:
    def skipUnless(condition, _):
        if condition:
            return lambda x: x
        else:
            return lambda x: None


def requires_python_version(version):
    version_tuple = tuple(map(int, str(version).split('.')))
    return skipUnless(sys.version_info >= version_tuple,
                      'Requires python version %s' % version)


class FakeExpensiveReprClass:
    def __repr__(self):
        return 'bad'


register_repr(FakeExpensiveReprClass)(basic_repr)


class TestCheapRepr(unittest.TestCase):
    def assert_usual_repr(self, x):
        self.assert_cheap_repr(x, repr(x))

    def assert_cheap_repr(self, x, expected_repr):
        self.assertEqual(cheap_repr(x), expected_repr)

    def test_numpy_array(self):
        try:
            import numpy
        except ImportError:
            return
        self.assert_usual_repr(numpy.array([1, 2, 3]))
        self.assert_cheap_repr(numpy.array(range(9)),
                               'array([0, 1, 2, 3, 4, 5, ...])')

    def test_registered_default_repr(self):
        x = FakeExpensiveReprClass()
        self.assertEqual(repr(x), 'bad')
        self.assertRegex(cheap_repr(x), '<FakeExpensiveReprClass instance at 0x(.+)>')

    @requires_python_version(3.3)
    def test_chain_map(self):
        from collections import ChainMap
        self.assert_usual_repr(ChainMap({1: 2, 3: 4}, dict.fromkeys('abcd')))

        ex = ("ChainMap(["
              "OrderedDict(('1', 0), ('2', 0), ('3', 0), ('4', 0), ...), "
              "OrderedDict(('1', 0), ('2', 0), ('3', 0), ('4', 0), ...), "
              "OrderedDict(('1', 0), ('2', 0), ('3', 0), ('4', 0), ...), "
              "OrderedDict(('1', 0), ('2', 0), ('3', 0), ('4', 0), ...), "
              "OrderedDict(('1', 0), ('2', 0), ('3', 0), ('4', 0), ...), "
              "OrderedDict(('1', 0), ('2', 0), ('3', 0), ('4', 0), ...), "
              "...])")
        self.assert_cheap_repr(ChainMap([OrderedDict.fromkeys('1234567890', 0) for _ in range(10)]),
                               ex)


if __name__ == '__main__':
    unittest.main()

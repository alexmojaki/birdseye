import re
import unittest
from collections import OrderedDict

from birdseye.cheap_repr import basic_repr, register_repr, cheap_repr
from tests.utils import requires_python_version


class FakeExpensiveReprClass:
    def __repr__(self):
        return 'bad'


register_repr(FakeExpensiveReprClass)(basic_repr)


class TestCheapRepr(unittest.TestCase):
    def assert_usual_repr(self, x):
        self.assert_cheap_repr(x, repr(x))

    def assert_cheap_repr(self, x, expected_repr):
        self.assertEqual(cheap_repr(x), expected_repr)

    def test_registered_default_repr(self):
        x = FakeExpensiveReprClass()
        self.assertEqual(repr(x), 'bad')
        self.assertTrue(re.match(r'<FakeExpensiveReprClass instance at 0x(.+)>', cheap_repr(x)))

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

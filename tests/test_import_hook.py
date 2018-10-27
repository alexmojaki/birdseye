# coding=utf8
import unittest

from tests.utils import requires_python_version


class TestImportHook(unittest.TestCase):
    @requires_python_version(3.5)
    def test_should_trace(self):
        from birdseye.import_hook import should_trace
        deep, trace_stmt = should_trace('import birdseye.trace_module')
        self.assertFalse(deep)
        self.assertIsNotNone(trace_stmt)

        deep, trace_stmt = should_trace('import birdseye.trace_module_deep')
        self.assertTrue(deep)
        self.assertIsNotNone(trace_stmt)

        deep, trace_stmt = should_trace('from birdseye import trace_module_deep, eye')
        self.assertTrue(deep)
        self.assertIsNotNone(trace_stmt)

        deep, trace_stmt = should_trace('from birdseye import trace_module, eye')
        self.assertFalse(deep)
        self.assertIsNotNone(trace_stmt)

        deep, trace_stmt = should_trace('from birdseye import eye')
        self.assertFalse(deep)
        self.assertIsNone(trace_stmt)


if __name__ == '__main__':
    unittest.main()

import sys
import unittest

from tests.utils import requires_python_version


class TestTreeTrace(unittest.TestCase):
    maxDiff = None

    @requires_python_version(3.5)
    def test_async_forbidden(self):
        from birdseye.tracer import TreeTracerBase
        tracer = TreeTracerBase()
        with self.assertRaises(ValueError):
            exec("""
@tracer
async def f(): pass""")

        if sys.version_info >= (3, 6):
            with self.assertRaises(ValueError):
                exec("""
@tracer
async def f(): yield 1""")

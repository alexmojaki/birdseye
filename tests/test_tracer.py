import unittest

import sys

from tests.utils import requires_python_version


class TestTreeTrace(unittest.TestCase):
    maxDiff = None

    @requires_python_version(3.5)
    def test_async_forbidden(self):
        def check(body):
            with self.assertRaises(ValueError):
                exec("""
from birdseye.tracer import TreeTracerBase
@TreeTracerBase()
async def f(): """ + body)

        check('pass')

        if sys.version_info >= (3, 6):
            check('yield 1')

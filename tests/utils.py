import multiprocessing
import sys
from unittest import skipUnless


def requires_python_version(version):
    version_tuple = tuple(map(int, str(version).split('.')))
    return skipUnless(sys.version_info >= version_tuple,
                      'Requires python version %s' % version)


class SharedCounter(object):
    def __init__(self):
        self._val = multiprocessing.Value('i', 0)

    def increment(self, n=1):
        with self._val.get_lock():
            self._val.value += n
            return self._val.value

    @property
    def value(self):
        return self._val.value

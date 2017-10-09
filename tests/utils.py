import sys
from unittest import skipUnless


def requires_python_version(version):
    version_tuple = tuple(map(int, str(version).split('.')))
    return skipUnless(sys.version_info >= version_tuple,
                      'Requires python version %s' % version)

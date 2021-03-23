import sys
from importlib import import_module

try:
    from .version import __version__
except ImportError:  # pragma: no cover
    # version.py is auto-generated with the git tag when building
    __version__ = "???"


# birdseye has so many dependencies that simply importing them can be quite slow
# Sometimes you just want to leave an import sitting around without actually using it
# These proxies ensure that if you do, program startup won't be slowed down
# In a nutshell:
#     from birdseye import eye
# is a lazy version of
#     from birdseye.bird import eye

class _SimpleProxy(object):
    def __init__(self, val):
        object.__setattr__(self, '_SimpleProxy__val', val)

    def __call__(self, *args, **kwargs):
        return self.__val()(*args, **kwargs)

    def __getattr__(self, item):
        return getattr(self.__val(), item)

    def __setattr__(self, key, value):
        setattr(self.__val(), key, value)


eye = _SimpleProxy(lambda: import_module('birdseye.bird').eye)
BirdsEye = _SimpleProxy(lambda: import_module('birdseye.bird').BirdsEye)


def load_ipython_extension(ipython_shell):
    from birdseye.ipython import BirdsEyeMagics
    ipython_shell.register_magics(BirdsEyeMagics)


if sys.version_info.major == 3:
    from birdseye.import_hook import BirdsEyeFinder

    sys.meta_path.insert(0, BirdsEyeFinder())

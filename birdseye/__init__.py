import sys


__version__ = '0.7.2'


def eye(*args, **kwargs):
    from birdseye.bird import eye
    return eye(*args, **kwargs)


def BirdsEye(*args, **kwargs):
    from birdseye.bird import BirdsEye
    return BirdsEye(*args, **kwargs)


def load_ipython_extension(ipython_shell):
    from birdseye.ipython import BirdsEyeMagics
    ipython_shell.register_magics(BirdsEyeMagics)


if sys.version_info.major == 3:
    from birdseye.import_hook import BirdsEyeFinder

    sys.meta_path.insert(0, BirdsEyeFinder())

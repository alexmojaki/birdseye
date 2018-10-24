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

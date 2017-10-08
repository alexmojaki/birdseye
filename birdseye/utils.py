from __future__ import print_function, division, absolute_import

from future import standard_library

standard_library.install_aliases()
from future.utils import raise_from
import atexit
import ntpath
import os
import traceback
import types
from queue import Queue
from threading import Thread
from sys import version_info

from littleutils import strip_required_prefix
from qualname import qualname

PY2 = version_info.major == 2
PY3 = not PY2


def path_leaf(path):
    # http://stackoverflow.com/a/8384788/2482744
    head, tail = ntpath.split(path)
    return tail or ntpath.basename(head)


def all_file_paths():
    from birdseye.db import Function, Session
    return [f[0] for f in Session().query(Function.file).distinct()]


def short_path(path):
    return strip_required_prefix(path, os.path.commonprefix(all_file_paths())) or path_leaf(path)


def safe_qualname(obj):
    result = safe_qualname._cache.get(obj)
    if not result:
        try:
            result = qualname(obj)
        except AttributeError:
            result = obj.__name__
        if '<locals>' not in result:
            safe_qualname._cache[obj] = result
    return result


safe_qualname._cache = {}


def correct_type(obj):
    # TODO handle case where __class__ has been assigned
    t = type(obj)
    if t is getattr(types, 'InstanceType', None):
        t = obj.__class__
    return t


def iter_get(it, n):
    n_original = n
    if n < 0:
        n = -n - 1
        it = reversed(it)
    else:
        it = iter(it)
    try:
        while n > 0:
            next(it)
            n -= 1
        return next(it)
    except StopIteration as e:
        raise_from(IndexError(n_original), e)


def exception_string(exc):
    assert isinstance(exc, BaseException)
    return ''.join(traceback.format_exception_only(type(exc), exc))


class Consumer(object):
    def __init__(self):
        self.queue = Queue()
        self.error = ValueError('There should be an error raised by a consumed task here')
        self.exiting = False
        self._run_thread()
        atexit.register(self._exit)

    def _run_thread(self):
        def run():
            while True:
                func = self.queue.get()
                try:
                    func()
                except BaseException as e:
                    self.queue = None
                    self.error = e
                    if not self.exiting:
                        raise
                finally:
                    self.queue.task_done()

        self.thread = Thread(target=run, name='Consumer thread')
        self.thread.daemon = True
        self.thread.start()

    def _exit(self):
        self.exiting = True
        if self.queue:
            self._run_thread()  # just for good measure
            self.queue.join()

    def __call__(self, func):
        if self.queue:
            self.queue.put(func)
        else:
            raise self.error  # error raised by task in consumer thread

    def wait(self, func):
        self(func)
        self.queue.join()


class SimpleNamespace(object):
    pass


dummy_namespace = SimpleNamespace()


def of_type(type_or_tuple, iterable):
    return (x for x in iterable if isinstance(x, type_or_tuple))


def safe_next(it):
    """
    next() can raise a StopIteration which can cause strange bugs inside generators.
    """
    try:
        return next(it)
    except StopIteration as e:
        raise_from(RuntimeError, e)


def one_or_none(expression):
    """Performs a one_or_none on a sqlalchemy expression."""
    if hasattr(expression, 'one_or_none'):
        return expression.one_or_none()
    result = expression.all()
    if len(result) == 0:
        return None
    elif len(result) == 1:
        return result[0]
    else:
        raise Exception("There is more than one item returned for the supplied filter")

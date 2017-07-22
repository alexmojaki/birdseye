import ntpath
import os
import traceback
import types

from littleutils import strip_required_prefix
from qualname import qualname


def path_leaf(path):
    # http://stackoverflow.com/a/8384788/2482744
    head, tail = ntpath.split(path)
    return tail or ntpath.basename(head)


def all_file_paths():
    from birdseye.app import db, Function
    return [f[0] for f in db.session.query(Function.file).distinct()]


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
        raise IndexError(n_original) from e


def exception_string(exc):
    return ''.join(traceback.format_exception_only(type(exc), exc))

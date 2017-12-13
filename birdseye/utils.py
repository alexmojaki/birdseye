from __future__ import print_function, division, absolute_import

import json

from future import standard_library

standard_library.install_aliases()
import inspect
from future.utils import raise_from, iteritems
import ntpath
import os
import types
from sys import version_info
from typing import TypeVar, Union, List, Any, Iterator, Tuple, Iterable, Callable

try:
    from typing import Type
except ImportError:
    Type = type

try:
    from typing import Deque
except ImportError:
    from collections import deque as Deque

try:
    from functools import lru_cache
except ImportError:
    from backports.functools_lru_cache import lru_cache

from littleutils import strip_required_prefix

PY2 = version_info.major == 2
PY3 = not PY2
T = TypeVar('T')
RT = TypeVar('RT')

if PY2:
    Text = unicode
else:
    Text = str


def path_leaf(path):
    # type: (str) -> str
    # http://stackoverflow.com/a/8384788/2482744
    head, tail = ntpath.split(path)
    return tail or ntpath.basename(head)


def all_file_paths():
    # type: () -> List[str]
    from birdseye.db import Function, Session
    return [f[0] for f in Session().query(Function.file).distinct()]


def common_ancestor(paths):
    # type: (List[str]) -> str
    """
    Returns a path to a directory that contains all the given absolute paths
    """
    prefix = os.path.commonprefix(paths)

    # Ensure that the prefix doesn't end in part of the name of a file/directory
    prefix = ntpath.split(prefix)[0]

    # Ensure that it ends with a slash
    first_char_after = paths[0][len(prefix)]
    if first_char_after in r'\/':
        prefix += first_char_after

    return prefix


def short_path(path, all_paths=None):
    # type: (str, List[str]) -> str
    prefix = common_ancestor(all_paths or all_file_paths())
    if prefix in r'\/':
        prefix = ''
    return strip_required_prefix(path, prefix) or path_leaf(path)


if PY2:
    def correct_type(obj):
        """
        Returns the correct type of obj, regardless of __class__ assignment
        or old-style classes:

        >>> class A:
        ...     pass
        ...
        ...
        ... class B(object):
        ...     pass
        ...
        ...
        ... class C(object):
        ...     __class__ = A
        ...
        >>> correct_type(A()) is A
        True
        >>> correct_type(B()) is B
        True
        >>> correct_type(C()) is C
        True
        """
        t = type(obj)
        # noinspection PyUnresolvedReferences
        if t is types.InstanceType:
            return obj.__class__
        return t
else:
    correct_type = type


def of_type(type_or_tuple, iterable):
    # type: (Union[type, Tuple[Union[type, tuple], ...]], Iterable[Any]) -> Iterator[Any]
    return (x for x in iterable if isinstance(x, type_or_tuple))


def safe_next(it):
    # type: (Iterator[T]) -> T
    """
    next() can raise a StopIteration which can cause strange bugs inside generators.
    """
    try:
        return next(it)
    except StopIteration as e:
        raise_from(RuntimeError, e)
        raise  # isn't reached


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


def flatten_list(lst):
    result = []
    for x in lst:
        if isinstance(x, list):
            result.extend(flatten_list(x))
        else:
            result.append(x)
    return result


def is_lambda(f):
    try:
        code = f.__code__
    except AttributeError:
        return False
    return code.co_name == (lambda: 0).__code__.co_name


def decorate_methods(cls, decorator):
    # type: (type, Callable[[Callable], Callable]) -> type
    """
    Apply `decorator` to every method of `cls`.
    """
    for name, meth in iteritems(cls.__dict__):  # type: str, Callable
        if inspect.ismethod(meth) or inspect.isfunction(meth):
            setattr(cls, name, decorator(meth))
    return cls


class ProtocolEncoder(json.JSONEncoder):
    def default(self, o):
        try:
            method = o.as_json
        except AttributeError:
            return super(ProtocolEncoder, self).default(o)
        else:
            return method()

from __future__ import print_function, division, absolute_import

from future import standard_library

standard_library.install_aliases()
from future.utils import raise_from
import ntpath
import os
import traceback
import types
from sys import version_info
from typing import TypeVar, Union, List, Any, Iterator, Tuple, Iterable, Dict
from types import FunctionType

try:
    from typing import Type
except ImportError:
    Type = type

try:
    from typing import Deque
except ImportError:
    from collections import deque as Deque

from littleutils import strip_required_prefix
from qualname import qualname

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


def safe_qualname(obj):
    # type: (Union[Type, FunctionType]) -> str
    result = _safe_qualname_cache.get(obj)
    if not result:
        try:
            result = qualname(obj)
        except AttributeError:
            result = obj.__name__
        if '<locals>' not in result:
            _safe_qualname_cache[obj] = result
    return result


_safe_qualname_cache = {}  # type: Dict[Union[Type, FunctionType], str]


def correct_type(obj):
    # type: (Any) -> type
    # TODO handle case where __class__ has been assigned
    t = type(obj)
    if t is getattr(types, 'InstanceType', None):
        t = obj.__class__
    return t


def exception_string(exc):
    # type: (BaseException) -> Text
    assert isinstance(exc, BaseException)
    return ''.join(traceback.format_exception_only(type(exc), exc))


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

import ast
import io
import json
import linecache
import ntpath
import os
import sys
import token
import types
from sys import version_info

from littleutils import strip_required_prefix

# noinspection PyUnreachableCode
if False:
    from typing import Union, List, Any, Iterator, Tuple, Iterable

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


PY2 = version_info.major == 2
PY3 = not PY2
PYPY = 'pypy' in sys.version.lower()
IPYTHON_FILE_PATH = 'IPython notebook or shell'
FILE_SENTINEL_NAME = '$$__FILE__$$'

if PY2:
    Text = unicode
else:
    Text = str


def path_leaf(path):
    # type: (str) -> str
    # http://stackoverflow.com/a/8384788/2482744
    head, tail = ntpath.split(path)
    return tail or ntpath.basename(head)


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


def short_path(path, all_paths):
    # type: (str, List[str]) -> str
    if path == IPYTHON_FILE_PATH:
        return path

    all_paths = [f for f in all_paths
                 if f != IPYTHON_FILE_PATH]
    prefix = common_ancestor(all_paths)
    if prefix in r'\/':
        prefix = ''
    return strip_required_prefix(path, prefix) or path_leaf(path)


def fix_abs_path(path):
    if path == IPYTHON_FILE_PATH:
        return path
    if os.path.sep == '/' and not path.startswith('/'):
        path = '/' + path
    return path


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


class ProtocolEncoder(json.JSONEncoder):
    def default(self, o):
        try:
            method = o.as_json
        except AttributeError:
            return super(ProtocolEncoder, self).default(o)
        else:
            return method()


def read_source_file(filename):
    if PY3:
        from tokenize import detect_encoding, cookie_re
    else:
        from lib2to3.pgen2.tokenize import detect_encoding, cookie_re

    lines = linecache.getlines(filename)
    text = ''.join(lines)

    if not isinstance(text, Text):
        encoding = detect_encoding(io.BytesIO(text).readline)[0]
        text = text.decode(encoding)  # noqa
        lines = [line.decode(encoding) for line in lines]

    # In python 2 it's a syntax error to parse unicode
    # with an encoding declaration, so we remove it but
    # leave empty lines in its place to keep line numbers the same
    return ''.join([
        '\n' if i < 2 and cookie_re.match(line)
        else line
        for i, line in enumerate(lines)
    ])


def source_without_decorators(tokens, function_node):
    def_token = tokens.find_token(function_node.first_token, token.NAME, 'def')
    startpos = def_token.startpos
    source = tokens.text[startpos:function_node.last_token.endpos].rstrip()
    assert source.startswith('def')

    return startpos, source


def prn(*args):
    for arg in args:
        print(arg)
    if len(args) == 1:
        return args[0]
    return args


def is_ipython_cell(filename):
    return filename.startswith('<ipython-input-')


def is_future_import(node):
    return isinstance(node, ast.ImportFrom) and node.module == "__future__"


def get_unfrozen_datetime():
    try:
        # if freezegun could be active, we need to use real_datetime to ensure we use the actual time instead of the
        # time set by freezegun.
        # we have to import this at the last possible moment because birdeye is very likely to be imported before
        # freezegun is activated.
        from freezegun.api import real_datetime
    except ImportError:
        from datetime import datetime as real_datetime

    return real_datetime.now()


html_escape_table = {
    "&": "&amp;",
    '"': "&quot;",
    "'": "&#x27;",
    ">": "&gt;",
    "<": "&lt;",
}


def html_escape(text):
    return "".join(html_escape_table.get(c, c) for c in text)


def format_pandas_index(index):
    """
    Supports different versions of pandas
    """
    try:
        return index.format(sparsify=False)
    except TypeError:
        return index.format()

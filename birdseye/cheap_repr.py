from __future__ import print_function, division, absolute_import
from future import standard_library
from future.utils import iteritems

standard_library.install_aliases()
import inspect
import warnings
from array import array
from collections import defaultdict, deque
from importlib import import_module
from itertools import islice

from birdseye.utils import safe_qualname, correct_type, PY2, PY3

repr_registry = {}


def try_register_repr(module_name, class_name):
    try:
        cls = getattr(import_module(module_name), class_name)
    except (ImportError, AttributeError):
        return lambda x: x
    else:
        if inspect.isclass(cls):
            return register_repr(cls)


def register_repr(cls):
    def decorator(func):
        repr_registry[cls] = func
        return func

    return decorator


def maxparts(num):
    def decorator(func):
        func.maxparts = num
        return func

    return decorator


def basic_repr(x, *_):
    return '<%s instance at %#x>' % (type_name(x), id(x))


def type_name(x):
    return safe_qualname(correct_type(x))


"""
If a class has a __repr__ that returns a value longer than the threshold
below it will be noted as suppressed and not used again, and a warning
will be emitted.
"""
suppression_threshold = 300
supressed_classes = set()


class ReprSupressedWarning(Warning):
    pass


@register_repr(object)
@maxparts(60)
def repr_object(x, helper):
    try:
        s = repr(x)
        # Bugs in x.__repr__() can cause arbitrary
        # exceptions -- then make up something
    except Exception:
        return basic_repr(x)
    if len(s) > suppression_threshold:
        cls = correct_type(x)
        supressed_classes.add(cls)
        warnings.warn('%s.__repr__ is too long and has been supressed. '
                      'Register a cheap repr for the class to avoid this warning '
                      'and see an informative repr again.' % safe_qualname(cls))
    return helper.truncate(s)


class Repr(object):
    def __init__(self):
        self.maxlevel = 3

    def repr(self, x, level=None):
        if level is None:
            level = self.maxlevel
        for cls in inspect.getmro(correct_type(x)):
            if cls in supressed_classes:
                return basic_repr(x)[:-1] + ' (expensive repr suppressed)>'
            func = repr_registry.get(cls)
            if func:
                return func(x, ReprHelper(self, level, func))
        return repr(x)



aRepr = Repr()
cheap_repr = aRepr.repr


class ReprHelper(object):
    def __init__(self, repr_instance, level, func):
        self.repr_instance = repr_instance
        self.level = level
        self.func = func

    def repr_iterable(self, iterable, left, right, trail='', length=None):
        if length is None:
            length = len(iterable)
        if self.level <= 0 and length:
            s = '...'
        else:
            newlevel = self.level - 1
            repr1 = self.repr_instance.repr
            max_parts = self.maxparts
            pieces = [repr1(elem, newlevel) for elem in islice(iterable, max_parts)]
            if length > max_parts:
                pieces.append('...')
            s = ', '.join(pieces)
            if length == 1 and trail:
                right = trail + right
        return left + s + right

    @property
    def maxparts(self):
        return getattr(self.func, 'maxparts', 6)

    def truncate(self, s):
        max_parts = self.maxparts
        if len(s) > max_parts:
            i = max(0, (max_parts - 3) // 2)
            j = max(0, max_parts - 3 - i)
            s = s[:i] + '...' + s[len(s) - j:]
        return s


@register_repr(tuple)
def repr_tuple(x, helper):
    return helper.repr_iterable(x, '(', ')', trail=',')


@register_repr(list)
@try_register_repr('UserList', 'UserList')
@try_register_repr('collections', 'UserList')
def repr_list(x, helper):
    return helper.repr_iterable(x, '[', ']')


@register_repr(array)
@maxparts(5)
def repr_array(x, helper):
    if not x:
        return repr(x)
    return helper.repr_iterable(x, "array('%s', [" % x.typecode, '])')


@register_repr(set)
def repr_set(x, helper):
    if not x:
        return repr(x)
    if PY2:
        return helper.repr_iterable(x, 'set([', '])')
    else:
        return helper.repr_iterable(x, '{', '}')


@register_repr(frozenset)
def repr_frozenset(x, helper):
    if not x:
        return repr(x)
    if PY2:
        return helper.repr_iterable(x, 'frozenset([', '])')
    else:
        return helper.repr_iterable(x, 'frozenset({', '})')


@register_repr(deque)
def repr_deque(x, helper):
    return helper.repr_iterable(x, 'deque([', '])')


@register_repr(dict)
@try_register_repr('UserDict', 'UserDict')
@try_register_repr('collections', 'UserDict')
@maxparts(4)
def repr_dict(x, helper):
    n = len(x)
    if n == 0:
        return '{}'
    if helper.level <= 0:
        return '{...}'
    newlevel = helper.level - 1
    repr1 = helper.repr_instance.repr
    pieces = []
    for key in islice(x, helper.maxparts):
        keyrepr = repr1(key, newlevel)
        valrepr = repr1(x[key], newlevel)
        pieces.append('%s: %s' % (keyrepr, valrepr))
    if n > helper.maxparts:
        pieces.append('...')
    s = ', '.join(pieces)
    return '{%s}' % (s,)


@try_register_repr('__builtin__', 'unicode')
@register_repr(str)
@maxparts(30)
def repr_str(x, helper):
    return repr(helper.truncate(x))


@try_register_repr('builtins', 'int')
@try_register_repr('__builtin__', 'long')
@maxparts(40)
def repr_int(x, helper):
    return helper.truncate(repr(x))


@try_register_repr('numpy.core.multiarray', 'ndarray')
def repr_ndarray(x, helper):
    if len(x) == 0:
        return repr(x)
    return helper.repr_iterable(x, 'array([', '])')


@try_register_repr('django.db.models', 'QuerySet')
def repr_QuerySet(x, _):
    try:
        model_name = x.model._meta.object_name
    except AttributeError:
        model_name = type_name(x.model)
    return '<%s instance of %s at %#x>' % (type_name(x), model_name, id(x))


@try_register_repr('collections', 'ChainMap')
@try_register_repr('chainmap', 'ChainMap')
@maxparts(4)
def repr_ChainMap(x, helper):
    return helper.repr_iterable(x.maps, type_name(x) + '(', ')')


@try_register_repr('collections', 'OrderedDict')
@try_register_repr('ordereddict', 'OrderedDict')
@try_register_repr('backport_collections', 'OrderedDict')
@maxparts(4)
def repr_OrderedDict(x, helper):
    helper.level += 1
    return helper.repr_iterable(iteritems(x), type_name(x) + '(', ')', length=len(x))


@try_register_repr('collections', 'Counter')
@try_register_repr('counter', 'Counter')
@try_register_repr('backport_collections', 'Counter')
@maxparts(5)
def repr_Counter(x, helper):
    typename = type_name(x)
    if not x:
        return '%s()' % typename
    return '{0}({1})'.format(typename, repr_dict(x, helper))


@register_repr(defaultdict)
@maxparts(4)
def repr_defaultdict(x, helper):
    return '{0}({1}, {2})'.format(type_name(x),
                                  x.default_factory,
                                  repr_dict(x, helper))

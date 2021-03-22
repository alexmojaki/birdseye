# coding=utf8

"""
Module docstrings before __future__ imports can break things...
"""

from __future__ import division

import ast
import json
import os
import random
import re
import sys
import unittest
import weakref
from collections import namedtuple
from copy import copy
from functools import partial
from importlib import import_module
from multiprocessing.dummy import Pool as ThreadPool
from time import sleep
from unittest import skipUnless

from bs4 import BeautifulSoup
from cheap_repr import register_repr
from littleutils import file_to_json, string_to_file, only

from birdseye import eye
from birdseye.bird import NodeValue, is_interesting_expression, is_obvious_builtin
from birdseye.utils import PY2, PY3, PYPY
from tests.utils import SharedCounter

Session = eye.db.Session
Call = eye.db.Call

try:
    from collections.abc import Set, Mapping
except ImportError:
    from collections import Set, Mapping


@eye
def bar():
    pass


# noinspection PyStatementEffect
@eye()
def foo():
    x = 1
    y = 2
    if x + y > 5:
        1 / 0
    else:
        x * y
    try:
        bar(x + x, 2 / 0, y + y)
        foo
    except ZeroDivisionError:
        x - y
    for i in [1, 2]:
        for j in [3, 4]:
            i + j
        for k in [5]:
            k
    z = 0
    while z < 2:
        z += 1
        z ** z
    bar()
    {'list': [n for n in [1, 2]]}

    try:
        error()
    except ValueError:
        pass

    [1, 2, 3][:2]


@eye
def error():
    raise ValueError()


class NormalClass(object):
    def __init__(self):
        self.x = 1

    def __repr__(self):
        return '<A>'


class SlotClass(object):
    __slots__ = ('slot1',)

    def __init__(self):
        self.slot1 = 3

    def __repr__(self):
        return '<B>'


call_id = SharedCounter()


def call_id_mock(*_):
    return 'test_id_%s' % call_id.increment()


eye._call_id = call_id_mock


def get_call_ids(func):
    start_id = call_id.value + 1
    func()
    end_id = call_id.value + 1
    return ['test_id_%s' % i for i in range(start_id, end_id)]


def hydrate(call):
    str(call.function.name)
    return copy(call)


# Do this here to make call ids consistent
golden_calls = {
    name: [hydrate(Session().query(Call).filter_by(id=c_id).one())
           for c_id in get_call_ids(lambda: import_module('test_scripts.' + name))]
    for name in ('gold', 'traced')
}

CallStuff = namedtuple('CallStuff', 'call, soup, call_data, func_data')


@eye.db.provide_session
def get_call_stuff(sess, c_id):
    call = sess.query(Call).filter_by(id=c_id).one()

    # <pre> makes it preserve whitespace
    soup = BeautifulSoup('<pre>' + call.function.html_body + '</pre>', 'html.parser')

    call_data = normalise_call_data(call.data)
    func_data = json.loads(call.function.data)
    return CallStuff(copy(call), soup, call_data, func_data)


def byteify(x):
    """
    This converts unicode objects to plain str so that the diffs in test failures
    aren't filled with false differences where there's a u prefix.
    """
    if PY3:
        return x

    # noinspection PyUnresolvedReferences
    if isinstance(x, dict):
        return dict((byteify(key), byteify(value)) for key, value in x.items())
    elif isinstance(x, list):
        return [byteify(element) for element in x]
    elif isinstance(x, unicode):
        return x.encode('utf-8')
    else:
        return x


def normalise_call_data(call_data):
    """
    Replace type indices with type names.
    Sort type_names.
    :type call_data: str
    :rtype: dict
    """
    data = byteify(json.loads(call_data))
    types = data['type_names']

    def fix(x):
        if isinstance(x, dict):
            return dict((key, fix(value)) for key, value in x.items())
        elif isinstance(x, list):
            result = [x[0]]
            type_index = x[1]
            if type_index < 0:
                assert type_index in (-1, -2)
                result.append(type_index)
            else:
                result.append(types[type_index])
            result.append(x[2])

            for y in x[3:]:
                y[1] = fix(y[1])
                result.append(y)
            return result
        else:
            return x

    data['node_values'] = fix(data['node_values'], )
    data['type_names'].sort()
    return data


class TestBirdsEye(unittest.TestCase):
    maxDiff = None

    def test_stuff(self):
        call_ids = get_call_ids(foo)
        call, soup, call_data, func_data = get_call_stuff(call_ids[0])

        node_values = call_data['node_values']
        actual_values = {'expr': {}, 'stmt': {}, 'loop': {}}
        loops = {}
        actual_node_loops = {}
        for span in soup('span'):
            index = span['data-index']
            if index not in node_values:
                continue

            if 'loop' in span['class']:
                data_type = 'loop'
            elif 'stmt' in span['class']:
                data_type = 'stmt'
            else:
                data_type = 'expr'

            text = span.text.strip()
            actual_values[data_type][text] = node_values[index]
            if data_type == 'loop':
                loops[text.split()[1]] = index
            this_node_loops = func_data['node_loops'].get(index)
            if this_node_loops:
                actual_node_loops[text] = [str(x) for x in this_node_loops]

        def func_value(f):
            result = [repr(f), 'function', {}]  # type: list
            if PY3:
                result.append(['__wrapped__', [repr(f.__wrapped__), 'function', {}]])
            return result

        s = ['', -2, {}]

        expected_values = {
            'expr': {
                'x': ['1', 'int', {}],
                'y': ['2', 'int', {}],
                'x + y': ['3', 'int', {}],
                'x + y > 5': ['False', 'bool', {}],
                'x * y': ['2', 'int', {}],
                '2 / 0': ['ZeroDivisionError: division by zero', -1, {}],
                'bar': func_value(bar),
                'error': func_value(error),
                'bar()': ['None', 'NoneType', {'inner_calls': [call_ids[1]]}],
                'x + x': ['2', 'int', {}],
                'x - y': ['-1', 'int', {}],
                'i': {'0': {'0': ['1', 'int', {}],
                            '1': ['1', 'int', {}]},
                      '1': {'0': ['2', 'int', {}],
                            '1': ['2', 'int', {}]}},
                'i + j': {'0': {'0': ['4', 'int', {}],
                                '1': ['5', 'int', {}]},
                          '1': {'0': ['5', 'int', {}],
                                '1': ['6', 'int', {}]}},
                'j': {'0': {'0': ['3', 'int', {}],
                            '1': ['4', 'int', {}]},
                      '1': {'0': ['3', 'int', {}],
                            '1': ['4', 'int', {}]}},
                'k': {'0': {'0': ['5', 'int', {}]},
                      '1': {'0': ['5', 'int', {}]}},

                '[1, 2, 3][:2]': ['[1, 2]',
                                  'list',
                                  {'len': 2},
                                  ['0', ['1', 'int', {}]],
                                  ['1', ['2', 'int', {}]]],

                # These are the values of z as in z ** z, not z < 2
                'z': {'0': ['1', 'int', {}],
                      '1': ['2', 'int', {}]},

                'z ** z': {'0': ['1', 'int', {}],
                           '1': ['4', 'int', {}]},
                'z < 2': {'0': ['True', 'bool', {}],
                          '1': ['True', 'bool', {}],
                          '2': ['False', 'bool', {}]},
                '[n for n in [1, 2]]': ['[1, 2]', 'list',
                                        {'len': 2},
                                        ['0', ['1', 'int', {}]],
                                        ['1', ['2', 'int', {}]]],
                'n': {'0': ['1', 'int', {}],
                      '1': ['2', 'int', {}]},
                "{'list': [n for n in [1, 2]]}":
                    ["{'list': [1, 2]}", 'dict',
                     {'len': 1},
                     ["'list'",
                      ['[1, 2]', 'list',
                       {'len': 2},
                       ['0', ['1', 'int', {}]],
                       ['1', ['2', 'int', {}]]]]],
                'error()': ['ValueError', -1, {'inner_calls': [call_ids[2]]}],
            },
            'stmt': {
                'x = 1': s,
                'y = 2': s,
                '[1, 2, 3][:2]': s,
                '''
    if x + y > 5:
        1 / 0
    else:
        x * y
                '''.strip(): s,
                'x * y': s,
                '''
    try:
        bar(x + x, 2 / 0, y + y)
        foo
    except ZeroDivisionError:
        x - y
                '''.strip(): s,
                'bar(x + x, 2 / 0, y + y)': s,
                'x - y': s,
                'i + j': {'0': {'0': s, '1': s}, '1': {'0': s, '1': s}},
                'k': {'0': {'0': s}, '1': {'0': s}},
                'bar()': s,
                "{'list': [n for n in [1, 2]]}": s,
                'error()': s,
                '''
    try:
        error()
    except ValueError:
        pass
                '''.strip(): s,
                'pass': s,
                'z ** z': {'0': s, '1': s},
                'z += 1': {'0': s, '1': s},
                'z = 0': s,
            },
            'loop': {
                '''
    for i in [1, 2]:
        for j in [3, 4]:
            i + j
        for k in [5]:
            k
                '''.strip(): s,
                '''
        for j in [3, 4]:
            i + j
                '''.strip(): {'0': s, '1': s},
                '''
        for k in [5]:
            k
                '''.strip(): {'0': s, '1': s},
                'for n in [1, 2]': s,
                '''
    while z < 2:
        z += 1
        z ** z
                '''.strip(): s,
            }
        }
        self.assertEqual(byteify(actual_values), expected_values)

        expected_node_loops = {
            'z': [loops['z']],
            'z ** z': [loops['z']],
            'z += 1': [loops['z']],
            'z < 2': [loops['z']],
            'i + j': [loops['i'], loops['j']],
            'i': [loops['i'], loops['j']],
            'j': [loops['i'], loops['j']],
            'k': [loops['i'], loops['k']],
            '''
        for j in [3, 4]:
            i + j
            '''.strip(): [loops['i']],
            '''
        for k in [5]:
            k
            '''.strip(): [loops['i']],
            'n': [loops['n']]
        }
        self.assertEqual(actual_node_loops, expected_node_loops)

    def test_comprehension_loops(self):
        # noinspection PyUnusedLocal
        @eye
        def f():
            # @formatter:off
            for i in ([([x for x in [] for y in []], [x for x in [] for y in []]) for x in [x for x in [] for y in []] for y in [x for x in [] for y in []]], [([x for x in [] for y in []], [x for x in [] for y in []]) for x in [x for x in [] for y in []] for y in [x for x in [] for y in []]]):
                pass
            # @formatter:on

        soup = get_call_stuff(get_call_ids(f)[0]).soup
        for line in str(soup).splitlines():
            self.assertTrue(line.count('for') in (0, 1))

    def test_expansion(self):
        @eye
        def f():
            x = {'t': [(7, 8, [9, 10]), NormalClass(), SlotClass(), "Hello World!" * 50]}
            len(x)

        stuff = get_call_stuff(get_call_ids(f)[0])
        value = [x for x in stuff.call_data['node_values'].values()
                 if isinstance(x, list) and
                 "'t': " in x[0]
                 ][0]
        self.assertEqual(
            value,
            ["{'t': [(7, 8, [...]), <A>, <B>, 'Hello World!H...d!Hello World!']}",
             'dict', {'len': 1},
             ["'t'", ["[(7, 8, [9, 10]), <A>, <B>, 'Hello World!H...d!Hello World!']",
                      'list', {'len': 4},
                      ['0', ['(7, 8, [9, 10])',
                             'tuple', {'len': 3},
                             ['0', ['7', 'int', {}]],
                             ['1', ['8', 'int', {}]],
                             ['2', ['[9, 10]', 'list', {'len': 2}]]]],
                      ['1', ['<A>', 'NormalClass', {},
                             ['x', ['1', 'int', {}]]]],
                      ['2', ['<B>', 'SlotClass', {},
                             ['slot1', ['3', 'int', {}]]]],
                      ['3', ["'Hello World!H...d!Hello World!'",
                             'str', {'len': 600}]]]]])

    def test_against_files(self):

        @register_repr(weakref.ref)
        def repr_weakref(*_):
            return '<weakref>'

        def normalise_addresses(string):
            return re.sub(r'at 0x\w+>', 'at 0xABC>', string)

        for name, calls in golden_calls.items():
            data = [dict(
                arguments=byteify(json.loads(normalise_addresses(call.arguments))),
                return_value=byteify(normalise_addresses(str(call.return_value))),
                exception=call.exception,
                traceback=call.traceback,
                data=normalise_call_data(normalise_addresses(call.data)),
                function=dict(
                    name=byteify(call.function.name),
                    html_body=byteify(call.function.html_body),
                    lineno=call.function.lineno,
                    data=byteify(json.loads(call.function.data)),
                ),
            ) for call in calls]
            version = PYPY * 'pypy' + sys.version[:3]
            path = os.path.join(os.path.dirname(__file__), 'golden-files', version, name + '.json')

            if os.getenv("FIX_TESTS"):
                with open(path, 'w') as f:
                    json.dump(data, f, indent=2, sort_keys=True)
            else:
                self.assertEqual(data, byteify(file_to_json(path)))

    def test_decorate_class(self):
        with self.assertRaises(TypeError) as e:
            # noinspection PyUnusedLocal
            @eye
            class Testclass(object):
                def barz(self):
                    return 'class decorator test'

        self.assertEqual(str(e.exception),
                         'Decorating classes is no longer supported')

    @skipUnless(PY2, 'Nested arguments are only possible in Python 2')
    def test_nested_arguments(self):
        # Python 3 sees nested arguments as a syntax error, so I can't
        # define the function here normally
        # birdseye requires a source file so I can't just use exec
        # The file can't just live there because then the test runner imports it
        path = os.path.join(os.path.dirname(__file__),
                            'nested_arguments.py')
        string_to_file(
            """
def f((x, y), z):
    return x, y, z
""",
            path)

        try:
            from tests.nested_arguments import f
            f = eye(f)
            call = get_call_stuff(get_call_ids(lambda: f((1, 2), 3))[0]).call
            self.assertEqual(call.arguments, '[["x", "1"], ["y", "2"], ["z", "3"]]')
            self.assertEqual(call.result, "(1, 2, 3)")
        finally:
            os.remove(path)

    @skipUnless(PY2, 'Division future import only changes things in Python 2')
    def test_future_imports(self):
        from tests.future_tests import with_future, without_future
        self.assertEqual(with_future.foo(), eye(with_future.foo)())
        self.assertEqual(without_future.foo(), eye(without_future.foo)())

    def test_expand_exceptions(self):
        expand = partial(NodeValue.expression, eye.num_samples)

        class A(object):
            def __len__(self):
                assert 0

        with self.assertRaises(AssertionError):
            len(A())

        self.assertIsNone(expand(A(), 1).meta)
        self.assertEqual(expand([4, 4, 4], 1).meta['len'], 3)

        class FakeSet(Set):
            def __len__(self):
                return 0

            def __iter__(self):
                pass

            def __contains__(self, x):
                pass

        class B(FakeSet):
            def __iter__(self):
                assert 0

        with self.assertRaises(AssertionError):
            list(B())

        self.assertIsNone(expand(B(), 1).children)

        class C(FakeSet):
            def __iter__(self):
                yield 1
                yield 2
                assert 0

        def children_keys(cls):
            return [k for k, _ in expand(cls(), 1).children]

        with self.assertRaises(AssertionError):
            list(C())

        self.assertEqual(children_keys(C), ['<0>', '<1>'])

        class D(object):
            def __init__(self):
                self.x = 3
                self.y = 4

            def __getattribute__(self, item):
                assert item not in ['x', 'y']
                return object.__getattribute__(self, item)

        with self.assertRaises(AssertionError):
            str(D().x)

        # expand goes through __dict__ so x and y are reachable
        self.assertEqual(sorted(children_keys(D)), ['x', 'y'])

        class E(Mapping):
            def __len__(self):
                return 0

            def __getitem__(self, key):
                assert 0

            def __iter__(self):
                yield 4

        with self.assertRaises(AssertionError):
            list(E().items())

        self.assertIsNone(expand(E(), 1).children)

    def test_is_interesting_expression(self):
        def check(s):
            return is_interesting_expression(ast.parse(s, mode='eval').body)

        self.assertFalse(check('1'))
        self.assertFalse(check('-1'))
        self.assertTrue(check('-1-3'))
        self.assertFalse(check('"abc"'))
        self.assertTrue(check('abc'))
        self.assertFalse(check('[]'))
        self.assertFalse(check('[1, 2]'))
        self.assertFalse(check('[1, 2, "abc"]'))
        self.assertFalse(check('[[[]]]'))
        self.assertFalse(check('{}'))
        self.assertFalse(check('{1:2}'))
        self.assertFalse(check('["abc", 1, [2, {7:3}, {}, {3:[5, ["lkj"]]}]]'))
        self.assertTrue(check('["abc", 1+3, [2, {7:3}, {}, {3:[5, ["lkj"]]}]]'))

    def test_is_obvious_builtin(self):
        def check(s, value):
            return is_obvious_builtin(ast.parse(s, mode='eval').body, value)

        self.assertTrue(check('len', len))
        self.assertTrue(check('max', max))
        self.assertTrue(check('True', True))
        self.assertTrue(check('False', False))
        self.assertTrue(check('None', None))
        self.assertFalse(check('len', max))
        self.assertFalse(check('max', len))
        self.assertFalse(check('0', False))
        self.assertFalse(check('not True', False))
        if PY2:
            self.assertFalse(check('None', False))

    def test_tracing_magic_methods(self):
        class A(object):
            @eye
            def __repr__(self):
                return '%s(label=%r)' % (self.__class__.__name__, self.label)

            @eye
            def __getattr__(self, item):
                return item

            @eye
            def __getattribute__(self, item):
                return object.__getattribute__(self, item)

            @eye
            def __len__(self):
                return self.length

        a = A()
        a.label = 'hello'
        a.length = 3

        @eye
        def test_A():
            self.assertEqual(a.label, 'hello')
            self.assertEqual(a.length, 3)
            self.assertEqual(a.thing, 'thing')
            self.assertEqual(repr(a), "A(label='hello')")

        test_A()

    def test_unicode(self):
        @eye
        def f():
            return u'é'

        self.assertEqual(f(), u'é')

    def test_optional_eye(self):
        @eye(optional=True)
        def f(x):
            return x * 3

        call_stuff = get_call_stuff(get_call_ids(lambda: f(2, trace_call=True))[0])
        self.assertEqual(call_stuff.call.result, '6')

        call = eye.enter_call
        eye.enter_call = lambda *args, **kwargs: 1 / 0
        try:
            self.assertEqual(f(3, trace_call=False), 9)
            self.assertEqual(f(4), 12)
        finally:
            eye.enter_call = call

    def test_first_check(self):
        def deco(f):
            f.attr = 3
            return f

        # Correct order, everything fine
        @deco
        @eye
        def baz():
            pass

        with self.assertRaises(ValueError):
            # @eye should notice it was applied second
            # because of __wrapped__ attribute
            @eye
            @deco
            def baz():
                pass

    def test_concurrency(self):
        ids = get_call_ids(lambda: ThreadPool(5).map(sleepy, range(25)))
        results = [int(get_call_stuff(i).call.result) for i in ids]
        self.assertEqual(sorted(results), list(range(0, 50, 2)))

    def test_middle_iterations(self):
        @eye
        def f():
            for i in range(20):
                for j in range(20):
                    if i == 10 and j >= 12:
                        str(i + 1)

        stuff = get_call_stuff(get_call_ids(f)[0])

        iteration_list = only(stuff.call_data['loop_iterations'].values())
        indexes = [i['index'] for i in iteration_list]
        self.assertEqual(indexes, [0, 1, 2, 10, 17, 18, 19])

        iteration_list = only(iteration_list[3]['loops'].values())
        indexes = [i['index'] for i in iteration_list]
        self.assertEqual(indexes, [0, 1, 2, 12, 13, 17, 18, 19])

    @classmethod
    def tearDownClass(cls):
        assert not eye.stack, eye.stack
        assert not eye.main_to_secondary_frames, eye.main_to_secondary_frames
        assert not eye.secondary_to_main_frames, eye.secondary_to_main_frames


@eye
def sleepy(x):
    sleep(random.random())
    return x * 2


if __name__ == '__main__':
    unittest.main()

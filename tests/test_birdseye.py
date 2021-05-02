# coding=utf8

"""
Module docstrings before __future__ imports can break things...
"""

from __future__ import division

import ast
import json
import os
import re
import sys
import unittest
import weakref
from collections import namedtuple
from collections.abc import Set, Mapping
from copy import copy
from functools import partial
from pathlib import Path
from textwrap import dedent

from bs4 import BeautifulSoup
from cheap_repr import register_repr
from littleutils import only, file_to_json

from birdseye.bird import (
    NodeValue,
    is_interesting_expression,
    is_obvious_builtin,
    BirdsEye,
)

foo_source = """
def bar():
    pass


# noinspection PyStatementEffect
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


def error():
    raise ValueError()
"""


CallStuff = namedtuple("CallStuff", "call, soup, call_data, func_data, globs, eye")


def get_call_stuff(source, func_name):
    source = dedent(source)
    eye, globs = run_traced(source, func_name)

    call = eye.store["calls"][eye._last_call_id]
    function = eye.store["functions"][call["function_id"]]

    # <pre> makes it preserve whitespace
    soup = BeautifulSoup("<pre>" + function["html_body"] + "</pre>", "html.parser")

    call_data = json.loads(json.dumps(normalise_call_data(call["data"])))
    func_data = json.loads(json.dumps(function["data"]))
    return CallStuff(copy(call), soup, call_data, func_data, globs, eye)


def run_traced(source, func_name):
    eye = BirdsEye()
    eye.num_samples["big"]["list"] = 10
    traced_file = eye.trace_string_deep("filename", source)
    globs = eye._trace_methods_dict(traced_file).copy()
    exec(traced_file.code, globs)
    globs[func_name]()
    assert not eye.stack, eye.stack
    assert not eye.main_to_secondary_frames, eye.main_to_secondary_frames
    assert not eye.secondary_to_main_frames, eye.secondary_to_main_frames
    return eye, globs


def normalise_call_data(data):
    """
    Replace type indices with type names.
    Sort type_names.
    :rtype: dict
    """
    types = data['type_names']

    def fix(x):
        if isinstance(x, dict):
            return dict((key, fix(value)) for key, value in x.items())
        elif isinstance(x, list):
            value, type_index, meta, *children = x
            x[0] = fix(value)

            if type_index < 0:
                assert type_index in (-1, -2)
            else:
                x[1] = types[type_index]

            if "inner_calls" in meta:
                meta["inner_calls"] = len(meta["inner_calls"])

            for y in children:
                y[1] = fix(y[1])
            return x
        elif isinstance(x, str):
            return re.sub(r"at 0x\w+>", "at 0xABC>", x)
        else:
            return x

    data['node_values'] = fix(data['node_values'], )
    data['type_names'].sort()
    return data


class TestBirdsEye(unittest.TestCase):
    maxDiff = None

    def test_stuff(self):
        stuff = get_call_stuff(foo_source, "foo")

        node_values = stuff.call_data["node_values"]
        actual_values = {"expr": {}, "stmt": {}, "loop": {}}
        loops = {}
        actual_node_loops = {}
        for span in stuff.soup("span"):
            index = span["data-index"]
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
            this_node_loops = stuff.func_data["node_loops"].get(index)
            if this_node_loops:
                actual_node_loops[text] = [str(x) for x in this_node_loops]

        s = ['', -2, {}]

        call_ids = list(stuff.eye.store["calls"])
        expected_values = {
            "expr": {
                "x": ["1", "int", {}],
                "y": ["2", "int", {}],
                "x + y": ["3", "int", {}],
                "x + y > 5": ["False", "bool", {}],
                "x * y": ["2", "int", {}],
                "2 / 0": ["ZeroDivisionError: division by zero", -1, {}],
                "bar": ['<function bar at 0xABC>', 'function', {}],
                "error": ['<function error at 0xABC>', 'function', {}],
                "bar()": ["None", "NoneType", {"inner_calls": 1}],
                "x + x": ["2", "int", {}],
                "x - y": ["-1", "int", {}],
                "i": {
                    "0": {"0": ["1", "int", {}], "1": ["1", "int", {}]},
                    "1": {"0": ["2", "int", {}], "1": ["2", "int", {}]},
                },
                "i + j": {
                    "0": {"0": ["4", "int", {}], "1": ["5", "int", {}]},
                    "1": {"0": ["5", "int", {}], "1": ["6", "int", {}]},
                },
                "j": {
                    "0": {"0": ["3", "int", {}], "1": ["4", "int", {}]},
                    "1": {"0": ["3", "int", {}], "1": ["4", "int", {}]},
                },
                "k": {"0": {"0": ["5", "int", {}]}, "1": {"0": ["5", "int", {}]}},
                "[1, 2, 3][:2]": [
                    "[1, 2]",
                    "list",
                    {"len": 2},
                    ["0", ["1", "int", {}]],
                    ["1", ["2", "int", {}]],
                ],
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
                'error()': ['ValueError', -1, {'inner_calls': 1}],
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
        self.assertEqual(actual_values, expected_values)

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
        soup = get_call_stuff(
            """
            def f():
                for i in ([([x for x in [] for y in []], [x for x in [] for y in []]) for x in [x for x in [] for y in []] for y in [x for x in [] for y in []]], [([x for x in [] for y in []], [x for x in [] for y in []]) for x in [x for x in [] for y in []] for y in [x for x in [] for y in []]]):
                    pass
            """,
            "f",
        ).soup
        for line in str(soup).splitlines():
            self.assertTrue(line.count('for') in (0, 1))

    def test_expansion(self):
        source = """
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
        
        def f():
            x = {'t': [(7, 8, [9, 10]), NormalClass(), SlotClass(), "Hello World!" * 50]}
            len(x)
        """

        stuff = get_call_stuff(source, "f")
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

        for name in ("gold", "traced"):
            source = (
                Path(__file__).parent.parent / "test_scripts" / f"{name}.py"
            ).read_text()
            eye, globs = run_traced(source, "main")
            store = eye.store

            data = [
                dict(
                    data=normalise_call_data(call["data"]),
                    function=store["functions"][call["function_id"]],
                )
                for call in store["calls"].values()
            ]
            version = sys.version[:3]
            path = os.path.join(os.path.dirname(__file__), 'golden-files', version, name + '.json')

            if os.getenv("FIX_TESTS"):
                with open(path, 'w') as f:
                    json.dump(data, f, indent=2, sort_keys=True)
            else:
                assert data == file_to_json(path)

    def test_expand_exceptions(self):
        expand = partial(NodeValue.expression, BirdsEye().num_samples)

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

    def test_middle_iterations(self):
        source = """
        def f():
            for i in range(20):
                for j in range(20):
                    if i == 10 and j >= 12:
                        str(i + 1)
        """

        stuff = get_call_stuff(source, "f")

        iteration_list = only(stuff.call_data['loop_iterations'].values())
        indexes = [i['index'] for i in iteration_list]
        self.assertEqual(indexes, [0, 1, 2, 10, 17, 18, 19])

        iteration_list = only(iteration_list[3]['loops'].values())
        indexes = [i['index'] for i in iteration_list]
        self.assertEqual(indexes, [0, 1, 2, 12, 13, 17, 18, 19])


if __name__ == '__main__':
    unittest.main()

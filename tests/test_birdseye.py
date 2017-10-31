import json
import os
import re
import sys
import unittest
import weakref
from collections import namedtuple
from unittest import skipUnless

from birdseye import eye
from birdseye.cheap_repr import register_repr
from birdseye.db import Call, Session
from birdseye.utils import PY2, PY3
from bs4 import BeautifulSoup
from littleutils import json_to_file, file_to_json, string_to_file
from tests import golden_script

session = Session()


@eye
def bar():
    pass


@eye
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
    bar()
    {'list': [n for n in [1, 2]]}


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


call_id = 0


def call_id_mock(*_):
    global call_id
    call_id += 1
    return 'test_id_%s' % call_id


eye._call_id = call_id_mock


def get_call_ids(func):
    start_id = call_id + 1
    func()
    end_id = call_id + 1
    return ['test_id_%s' % i for i in range(start_id, end_id)]


# Do this here to make call ids consistent
golden_calls = [session.query(Call).filter_by(id=c_id).one()
                for c_id in get_call_ids(golden_script.main)]

CallStuff = namedtuple('CallStuff', 'call, soup, call_data, func_data')


def get_call_stuff(c_id):
    call = session.query(Call).filter_by(id=c_id).one()

    # <pre> makes it preserve whitespace
    soup = BeautifulSoup('<pre>' + call.function.html_body + '</pre>', 'html.parser')

    call_data = normalise_call_data(call.data)
    func_data = json.loads(call.function.data)
    return CallStuff(call, soup, call_data, func_data)


def byteify(x):
    """
    This converts unicode objects to plain str so that the diffs in test failures
    aren't filled with false differences where there's a u prefix.
    """
    if PY3:
        return x

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
    Sort non-numeric attributes and dict items inside expanded values.
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
            if type_index == -1:
                result.append(-1)
            else:
                result.append(types[type_index])

            non_numeric = []
            for y in x[2:]:
                if isinstance(y, list):
                    y = [y[0], fix(y[1])]
                    if y[0].isdigit():
                        result.append(y)
                    else:
                        non_numeric.append(y)
                else:
                    result.append(y)
            non_numeric.sort()
            result.extend(non_numeric)
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
            data_type = span['data-type']
            text = span.text.strip()
            actual_values[data_type][text] = node_values[index]
            if data_type == 'loop':
                loops[text.split()[1]] = index
            this_node_loops = func_data['node_loops'].get(index)
            if this_node_loops:
                actual_node_loops[text] = [str(x) for x in this_node_loops]

        bar_value = [repr(bar), 'function', {}]
        if PY3:
            bar_value.append(['__wrapped__', [repr(bar.__wrapped__), 'function', {}]])

        expected_values = {
            'expr': {
                'x': ['1', 'int', {}],
                'y': ['2', 'int', {}],
                'x + y': ['3', 'int', {}],
                'x + y > 5': ['False', 'bool', {}],
                'x * y': ['2', 'int', {}],
                '2 / 0': ['ZeroDivisionError: division by zero\n', -1, {}],
                'bar': bar_value,
                'bar()': ['None', 'NoneType', {'inner_call': call_ids[1]}],
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
            },
            'stmt': {
                'x = 1': True,
                'y = 2': True,
                '''
    if x + y > 5:
        1 / 0
    else:
        x * y
                '''.strip(): True,
                'x * y': True,
                '''
    try:
        bar(x + x, 2 / 0, y + y)
        foo
    except ZeroDivisionError:
        x - y
                '''.strip(): True,
                'bar(x + x, 2 / 0, y + y)': True,
                'x - y': True,
                'i + j': {'0': {'0': True, '1': True}, '1': {'0': True, '1': True}},
                'k': {'0': {'0': True}, '1': {'0': True}},
                'bar()': True,
                "{'list': [n for n in [1, 2]]}": True,
            },
            'loop': {
                '''
    for i in [1, 2]:
        for j in [3, 4]:
            i + j
        for k in [5]:
            k            
                '''.strip(): True,
                '''
        for j in [3, 4]:
            i + j
                '''.strip(): {'0': True, '1': True},
                '''
        for k in [5]:
            k            
                '''.strip(): {'0': True, '1': True},
                'for n in [1, 2]': True,
            }
        }
        self.assertEqual(byteify(actual_values), expected_values)

        expected_node_loops = {
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
            len(([([x for x in [] for y in []], [x for x in [] for y in []]) for x in [x for x in [] for y in []] for y in [x for x in [] for y in []]], [([x for x in [] for y in []], [x for x in [] for y in []]) for x in [x for x in [] for y in []] for y in [x for x in [] for y in []]]))
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

        data = [dict(
            arguments=byteify(json.loads(normalise_addresses(call.arguments))),
            return_value=byteify(normalise_addresses(call.return_value)),
            exception=call.exception,
            traceback=call.traceback,
            data=normalise_call_data(normalise_addresses(call.data)),
            function=dict(
                name=byteify(call.function.name),
                html_body=byteify(call.function.html_body),
                lineno=call.function.lineno,
                data=byteify(json.loads(call.function.data)),
            ),
        ) for call in golden_calls]
        version = re.match(r'\d\.\d', sys.version).group()
        path = os.path.join(os.path.dirname(__file__), 'golden-files', version, 'calls.json')

        if 1:  # change to 0 to write new data instead of reading and testing
            self.assertEqual(data, byteify(file_to_json(path)))
        else:
            json_to_file(data, path)

    def test_decorate_class(self):
        def fooz(_):
            return 'method outside class'

        @eye
        class Testclass(object):
            call_meth = fooz

            def barz(self):
                return 'class decorator test'

        def check(method, expected_value):
            call = get_call_stuff(get_call_ids(method)[0]).call
            self.assertEqual(expected_value, call.return_value)

        x = Testclass()
        check(x.barz, "'class decorator test'")
        check(x.call_meth, "'method outside class'")

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
            from .nested_arguments import f
            f = eye(f)
            call = get_call_stuff(get_call_ids(lambda: f((1, 2), 3))[0]).call
            self.assertEqual(call.arguments, '[["x", "1"], ["y", "2"], ["z", "3"]]')
            self.assertEqual(call.result, "(1, 2, 3)")
        finally:
            os.remove(path)


if __name__ == '__main__':
    unittest.main()

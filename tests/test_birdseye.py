import json
import unittest
from collections import namedtuple

from birdseye.utils import PY3, PY2
from birdseye import eye
from birdseye.db import Call, Session
from bs4 import BeautifulSoup

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


CallStuff = namedtuple('CallStuff', 'call, soup, call_data, func_data, types')


def get_call_stuff(c_id):
    call = session.query(Call).filter_by(id=c_id).one()

    # <pre> makes it preserve whitespace
    soup = BeautifulSoup('<pre>' + call.function.html_body + '</pre>', 'html.parser')

    call_data = json.loads(call.data)
    func_data = json.loads(call.function.data)
    types = dict((name, i) for i, name in enumerate(call_data['type_names']))
    return CallStuff(call, soup, call_data, func_data, types)


def byteify(x):
    if isinstance(x, dict):
        return dict((byteify(key), byteify(value)) for key, value in x.items())
    elif isinstance(x, list):
        return [byteify(element) for element in x]
    elif isinstance(x, unicode):
        return x.encode('utf-8')
    else:
        return x


class TestBirdsEye(unittest.TestCase):
    maxDiff = None

    def test_stuff(self):
        call_ids = get_call_ids(foo)
        call, soup, call_data, func_data, t = get_call_stuff(call_ids[0])

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

        bar_value = [repr(bar), t['function']]
        if PY3:
            bar_value.append(['__wrapped__', [repr(bar.__wrapped__), t['function']]])

        expected_values = {
            'expr': {
                'x': ['1', t['int']],
                'y': ['2', t['int']],
                'x + y': ['3', t['int']],
                'x + y > 5': ['False', t['bool']],
                'x * y': ['2', t['int']],
                '2 / 0': ['ZeroDivisionError: division by zero\n', -1],
                'bar': bar_value,
                'bar()': ['None', t['NoneType'], {'inner_call': call_ids[1]}],
                'x + x': ['2', t['int']],
                'x - y': ['-1', t['int']],
                'i': {'0': {'0': ['1', t['int']],
                            '1': ['1', t['int']]},
                      '1': {'0': ['2', t['int']],
                            '1': ['2', t['int']]}},
                'i + j': {'0': {'0': ['4', t['int']],
                                '1': ['5', t['int']]},
                          '1': {'0': ['5', t['int']],
                                '1': ['6', t['int']]}},
                'j': {'0': {'0': ['3', t['int']],
                            '1': ['4', t['int']]},
                      '1': {'0': ['3', t['int']],
                            '1': ['4', t['int']]}},
                'k': {'0': {'0': ['5', t['int']]},
                      '1': {'0': ['5', t['int']]}},
                '[n for n in [1, 2]]': ['[1, 2]', t['list'],
                                        'len() = 2',
                                        ['0', ['1', t['int']]],
                                        ['1', ['2', t['int']]]],
                'n': {'0': ['1', t['int']],
                      '1': ['2', t['int']]},
                "{'list': [n for n in [1, 2]]}":
                    ["{'list': [1, 2]}", t['dict'],
                     'len() = 1',
                     ["'list'",
                      ['[1, 2]', t['list'],
                       'len() = 2',
                       ['0', ['1', t['int']]],
                       ['1', ['2', t['int']]]]]],
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
        if PY2:
            actual_values = byteify(actual_values)
        self.assertEqual(actual_values, expected_values)

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
        t = stuff.types
        self.assertEqual(
            value,
            ["{'t': [(7, 8, [...]), <A>, <B>, 'Hello World!H...d!Hello World!']}",
             t['dict'], 'len() = 1',
             ["'t'", ["[(7, 8, [9, 10]), <A>, <B>, 'Hello World!H...d!Hello World!']",
                      t['list'], 'len() = 4',
                      ['0', ['(7, 8, [9, 10])',
                             t['tuple'], 'len() = 3',
                             ['0', ['7', t['int']]],
                             ['1', ['8', t['int']]],
                             ['2', ['[9, 10]', t['list']]]]],
                      ['1', ['<A>', t['NormalClass'],
                             ['x', ['1', t['int']]]]],
                      ['2', ['<B>', t['SlotClass'],
                             ['slot1', ['3', t['int']]]]],
                      ['3', ["'Hello World!H...d!Hello World!'",
                             t['str'], 'len() = 600']]]]])

    def test_decorate_class(self):
        def fooz(self):
            return 'method outside class'

        @eye
        class Testclass(object):

            call_meth = fooz
            def barz(self):
                return 'class decorator test'

        def get_stuff(method):
            return get_call_stuff(get_call_ids(method)[0]).call

        x = Testclass()
        call = get_stuff(x.barz)
        self.assertEqual("'class decorator test'", call.return_value)
        
        call = get_stuff(x.call_meth)
        self.assertEqual("'method outside class'", call.return_value)

if __name__ == '__main__':
    unittest.main()

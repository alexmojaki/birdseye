import json
import os
import unittest

os.environ['BIRDSEYE_DB'] = 'sqlite:///:memory:'
os.environ['BIRDSEYE_TESTING_IN_MEMORY'] = 'true'

from birdseye import BirdsEye
from birdseye.db import Call, Session, db_consumer
from bs4 import BeautifulSoup

eye = BirdsEye()
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


class SlotClass:
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
    db_consumer.queue.join()
    end_id = call_id + 1
    return ['test_id_%s' % i for i in range(start_id, end_id)]


def get_call_stuff(c_id):
    call = session.query(Call).filter_by(id=c_id).one()

    # <pre> makes it preserve whitespace
    soup = BeautifulSoup('<pre>' + call.function.html_body + '</pre>', 'lxml')

    call_data = json.loads(call.data)
    func_data = json.loads(call.function.data)
    return call, soup, call_data, func_data


class TestBirdsEye(unittest.TestCase):
    maxDiff = None

    def test_stuff(self):
        call_ids = get_call_ids(foo)
        call, soup, call_data, func_data = get_call_stuff(call_ids[0])

        node_values = call_data['node_values']
        t = dict((name, i) for i, name in enumerate(call_data['type_names']))

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

        expected_values = {
            'expr': {
                'x': ['1', t['int']],
                'y': ['2', t['int']],
                'x + y': ['3', t['int']],
                'x + y > 5': ['False', t['bool']],
                'x * y': ['2', t['int']],
                '2 / 0': ['ZeroDivisionError: division by zero\n', -1],
                'bar': [repr(bar), t['function'], ['__wrapped__', [repr(bar.__wrapped__), t['function']]]],
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

        soup = get_call_stuff(get_call_ids(f)[0])[1]
        for line in str(soup).splitlines():
            self.assertIn(line.count('for'), (0, 1))

    def test_expansion(self):
        @eye
        def f():
            x = {'t': [(7, 8, [9, 10]), NormalClass(), SlotClass(), "Hello World!" * 50]}
            len(x)

        call_data = get_call_stuff(get_call_ids(f)[0])[2]
        value = [x for x in call_data['node_values'].values()
                 if isinstance(x, list) and
                 "'t': " in x[0]
                 ][0]
        self.assertEqual(
            value,
            ["{'t': [(7, 8, [...]), <A>, <B>, 'Hello World!H...d!Hello World!']}",
             6, 'len() = 1',
             ["'t'", ["[(7, 8, [9, 10]), <A>, <B>, 'Hello World!H...d!Hello World!']",
                      5, 'len() = 4',
                      ['0', ['(7, 8, [9, 10])',
                             7, 'len() = 3',
                             ['0', ['7', 2]],
                             ['1', ['8', 2]],
                             ['2', ['[9, 10]', 5]]]],
                      ['1', ['<A>', 15,
                             ['x', ['1', 2]]]],
                      ['2', ['<B>', 17,
                             ['slot1', ['3', 2]]]],
                      ['3', ["'Hello World!H...d!Hello World!'",
                             10, 'len() = 600']]]]])


if __name__ == '__main__':
    unittest.main()

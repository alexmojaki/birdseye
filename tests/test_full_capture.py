import enum
import json
import os
import unittest
import warnings
from array import array
from collections import Counter, OrderedDict, defaultdict, deque, namedtuple
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import PurePosixPath
from unittest import mock
from uuid import UUID

import numpy as np
from bs4 import BeautifulSoup

from birdseye.bird import BirdsEye, DEFAULT_CAPTURE_OPTIONS, NodeValue, eye, resolve_capture_options, type_registry
from birdseye.utils import ProtocolEncoder

Point = namedtuple('Point', 'x y')

CAPTURE_VARIABLES = ('BIRDSEYE_CAPTURE', 'BIRDSEYE_CAPTURE_MAX_BYTES')


def environment(**values):
    """
    Patch os.environ so that only the given capture variables are set.
    """
    environ = {k: v for k, v in os.environ.items() if k not in CAPTURE_VARIABLES}
    environ.update(values)
    return mock.patch.dict(os.environ, environ, clear=True)


class Tree(object):
    """
    Friendlier view of a stored node: [repr, type_index, meta, [key, child], ...]
    """

    def __init__(self, node, type_names):
        self.repr, self.type_index, self.meta = node[:3]
        self.type = type_names[self.type_index] if self.type_index >= 0 else None
        self.children = [(key, Tree(child, type_names)) for key, child in node[3:]]

    @property
    def keys(self):
        return [key for key, _ in self.children]

    @property
    def child_reprs(self):
        return [child.repr for _, child in self.children]

    @property
    def marker(self):
        return self.meta.get('marker')

    def __getitem__(self, key):
        return dict(self.children)[key]


def snapshot(value, **options):
    node = NodeValue.snapshot(value, dict(DEFAULT_CAPTURE_OPTIONS, **options), eye.num_samples)
    return Tree(json.loads(json.dumps(node, cls=ProtocolEncoder)), type_registry.names())


def last_call(tracer):
    """
    The arguments summary, argument snapshots, result snapshot, and data
    stored for the most recent call traced by tracer.
    """
    with tracer.db.session_scope() as session:
        call = session.query(tracer.db.Call).filter_by(id=tracer._last_call_id).one()
        summary, data = json.loads(call.arguments), json.loads(call.data)
    names = data['type_names']
    arguments = {name: Tree(node, names) for name, node in data.get('argument_snapshots', [])}
    result = Tree(data['result_snapshot'], names) if 'result_snapshot' in data else None
    return summary, arguments, result, data


def expression_values(tracer):
    """
    The expression values of the most recent call traced by tracer, keyed by source text.
    The values of expressions inside a loop are dicts from iteration index to value.
    """
    with tracer.db.session_scope() as session:
        call = session.query(tracer.db.Call).filter_by(id=tracer._last_call_id).one()
        data = json.loads(call.data)
        html_body = call.function.html_body
    names = data['type_names']
    result = {}
    for span in BeautifulSoup('<pre>' + html_body + '</pre>', 'html.parser')('span'):
        value = data['node_values'].get(span['data-index'])
        if isinstance(value, list):
            result[span.text] = Tree(value, names)
        elif isinstance(value, dict):
            result[span.text] = {i: Tree(v, names) for i, v in value.items() if isinstance(v, list)}
    return result


def items(tree):
    """
    Keys of the children that are items, not facts such as maxlen or typecode.
    """
    return [key for key in tree.keys if key not in ('maxlen', 'typecode', 'default_factory')]


class TestSnapshot(unittest.TestCase):
    def test_sequences_sets_and_arrays(self):
        numbers = [str(i) for i in range(20)]

        tree = snapshot(list(range(20)))
        self.assertEqual(tree.type, 'list')
        self.assertEqual(tree.meta['len'], 20)
        self.assertEqual(tree.keys, numbers)
        self.assertEqual(tree.child_reprs, numbers)

        self.assertEqual(snapshot(tuple(range(20))).child_reprs, numbers)
        self.assertEqual(sorted(snapshot(set(range(20))).child_reprs, key=int), numbers)
        self.assertEqual(sorted(snapshot(frozenset('ab')).child_reprs), ["'a'", "'b'"])

        tree = snapshot(array('i', range(20)))
        self.assertEqual(tree.type, 'array')
        self.assertEqual(tree.keys, ['typecode'] + numbers)
        self.assertEqual(tree['typecode'].repr, "'i'")

        tree = snapshot(deque(range(20), maxlen=50))
        self.assertEqual(tree.type, 'deque')
        self.assertEqual(tree['maxlen'].repr, '50')
        self.assertEqual(tree.child_reprs[1:], numbers)
        self.assertEqual(snapshot(deque([1])).keys, ['0'])

        tree = snapshot(Point(1, 2))
        self.assertEqual(tree.type, 'Point')
        self.assertEqual(tree.keys, ['x', 'y'])

    def test_mappings(self):
        tree = snapshot({'k%s' % i: i for i in range(10)})
        self.assertEqual(tree.keys, ["'k%s'" % i for i in range(10)])
        self.assertEqual(tree.child_reprs, [str(i) for i in range(10)])

        ordered = OrderedDict([('a', 1), ('b', 2), ('c', 3)])
        ordered.move_to_end('a')
        self.assertEqual(snapshot(ordered).keys, ["'b'", "'c'", "'a'"])

        tree = snapshot(defaultdict(list, x=[1]))
        self.assertEqual(tree.keys, ['default_factory', "'x'"])
        self.assertEqual(tree['default_factory'].repr, "<class 'list'>")
        self.assertEqual(tree["'x'"].child_reprs, ['1'])

        self.assertEqual(snapshot(Counter('aab')).child_reprs, ['2', '1'])
        self.assertEqual(snapshot({(1, 2): 'pair', None: 'none'}).keys, ['(1, 2)', 'None'])

    def test_full_leaf_values_and_nesting(self):
        text = 'x' * 1000
        self.assertEqual(snapshot(text).repr, repr(text))
        self.assertEqual(snapshot(b'\0' * 100).repr, repr(b'\0' * 100))
        self.assertEqual(snapshot(10 ** 100).repr, str(10 ** 100))

        tree = snapshot([[[[['deep']]]]])
        for _ in range(5):
            tree = tree['0']
        self.assertEqual(tree.repr, "'deep'")

    def test_labels(self):
        # Small values are labelled with their complete repr, unlike cheap_repr
        result = {'status': 'incomplete', 'episodes': {}, 'want_everything': True, 'total_seasons': 0, 'queued': 5}
        self.assertEqual(snapshot(result).repr, repr(result))
        self.assertEqual(snapshot(list(range(20))).repr, repr(list(range(20))))
        self.assertEqual(snapshot(deque(range(20), maxlen=25)).repr, repr(deque(range(20), maxlen=25)))

        # Large values keep the short summary, but their items are all there
        tree = snapshot(list(range(1000)))
        self.assertEqual(tree.repr, '[0, 1, 2, ..., 997, 998, 999]')
        self.assertEqual(len(tree.children), 1000)

    def test_objects(self):
        class Node(object):
            def __init__(self, child=None):
                self.child = child
                self.items = list(range(10))

        tree = snapshot(Node(Node(Node())))
        self.assertEqual(tree.keys, ['child', 'items'])
        self.assertEqual(tree['items'].child_reprs, [str(i) for i in range(10)])

        # Attributes are expanded object_depth (2) levels deep
        level_2 = tree['child']['child']
        self.assertEqual(level_2.keys, ['...'])
        self.assertEqual(level_2['...'].marker, 'object_depth')
        self.assertEqual(snapshot(Node(Node(Node())), object_depth=3)['child']['child'].keys, ['child', 'items'])

    def test_cycles(self):
        items = [1]
        items.append(items)
        tree = snapshot(items)
        self.assertEqual(tree['0'].repr, '1')
        self.assertEqual(tree['1'].marker, 'cycle')
        self.assertEqual(tree['1'].type_index, -1)

    def test_max_bytes(self):
        tree = snapshot(list(range(1000)), max_bytes=300)
        self.assertLess(len(tree.children), 100)
        self.assertEqual(tree.meta['truncated'], 'max_bytes')
        last = tree.children[-1][1]
        self.assertEqual(last.marker, 'max_bytes')
        self.assertIn('more items not captured', last.repr)

        tree = snapshot('y' * 1000, max_bytes=300)
        self.assertTrue(tree.repr.startswith("'yyy"))
        self.assertIn('more characters not captured: max_bytes reached', tree.repr)

        self.assertEqual(len(snapshot(list(range(5000)), max_bytes=None).children), 5000)

    def test_max_depth(self):
        tree = snapshot([[[[['deep']]]]], max_depth=3)
        tree = tree['0']['0']['0']
        self.assertEqual(tree.keys, ['...'])
        self.assertEqual(tree['...'].marker, 'max_depth')

        # Even without a useful limit, capturing never raises: the part that
        # couldn't be captured becomes an error marker and the rest is kept
        nested = []
        for _ in range(5000):
            nested = [nested]
        node = NodeValue.snapshot(nested, dict(DEFAULT_CAPTURE_OPTIONS, max_depth=10000), eye.num_samples)
        self.assertEqual(node.meta['len'], 1)
        while node.children:
            node = node.children[0][1]
        self.assertEqual(node.meta['marker'], 'error')

    def test_values_are_not_consumed_or_hidden(self):
        numbers = (i for i in range(3))
        self.assertEqual(snapshot(numbers).children, [])
        self.assertEqual(list(numbers), [0, 1, 2])

        class Sneaky(list):
            def __iter__(self):
                return iter(['fake'])

        self.assertEqual(snapshot(Sneaky([1, 2, 3])).child_reprs, ['1', '2', '3'])

    def test_repr_errors_become_markers(self):
        class BadRepr(str):
            def __repr__(self):
                raise ValueError('boom')

        tree = snapshot([BadRepr('x')])
        self.assertEqual(tree['0'].marker, 'error')
        self.assertIn('ValueError: boom', tree['0'].repr)

    def test_numpy_arrays_keep_sampled_rendering(self):
        tree = snapshot(np.arange(100))
        self.assertEqual(tree.type, 'ndarray')
        self.assertLess(len(tree.children), 100)


class TestCapturedCalls(unittest.TestCase):
    def tracer(self, **capture_options):
        with environment():
            tracer = BirdsEye(capture_options=capture_options)
        self.addCleanup(lambda: tracer.db.engine.dispose())
        return tracer

    def full_eye(self):
        return self.tracer(arguments='full', result='full')

    def test_default_stores_only_summaries(self):
        tracer = self.tracer()
        self.assertEqual(tracer.capture_options, DEFAULT_CAPTURE_OPTIONS)

        @tracer
        def f(items):
            return items

        f(list(range(20)))
        summary, arguments, result, data = last_call(tracer)
        self.assertEqual(summary, [['items', '[0, 1, 2, ..., 17, 18, 19]']])
        self.assertNotIn('argument_snapshots', data)
        self.assertNotIn('result_snapshot', data)

    def test_arguments_and_result(self):
        tracer = self.full_eye()

        @tracer
        def f(items, tags, window):
            items.append('added')
            return {'status': 'incomplete', 'episodes': {i: 'e%s' % i for i in range(10)}}

        f(list(range(20)), set(range(20)), deque(range(20)))
        summary, arguments, result, data = last_call(tracer)

        # The short summaries are still stored for lists of calls
        self.assertEqual(summary[0], ['items', '[0, 1, 2, ..., 17, 18, 19]'])

        # Arguments are copied when the call starts, before the function changes them
        self.assertEqual(arguments['items'].child_reprs, [str(i) for i in range(20)])
        self.assertEqual(len(arguments['tags'].children), 20)
        self.assertEqual(len(arguments['window'].children), 20)

        self.assertEqual(result.keys, ["'status'", "'episodes'"])
        self.assertEqual(result["'episodes'"].keys, [str(i) for i in range(10)])

    def test_no_result_snapshot_after_exception(self):
        tracer = self.full_eye()

        @tracer
        def f():
            raise ValueError('failed')

        with self.assertRaises(ValueError):
            f()
        summary, arguments, result, data = last_call(tracer)
        self.assertEqual(data['argument_snapshots'], [])
        self.assertIsNone(result)

    def test_expression_values(self):
        tracer = self.tracer(expressions='full')

        @tracer
        def f(items):
            doubled = [x * 2 for x in items]
            table = {i: list(range(i * 10, i * 10 + 10)) for i in range(3)}
            return doubled, table

        f(list(range(20)))
        values = expression_values(tracer)

        self.assertEqual(values['items'].child_reprs, [str(i) for i in range(20)])
        self.assertEqual(values['[x * 2 for x in items]'].child_reprs, [str(i * 2) for i in range(20)])

        # Values inside loops are complete in every iteration,
        # while sampling would show only part of them after the first
        rows = values['list(range(i * 10, i * 10 + 10))']
        self.assertEqual(sorted(rows), ['0', '1', '2'])
        for i, row in rows.items():
            start = int(i) * 10
            self.assertEqual(row.child_reprs, [str(n) for n in range(start, start + 10)])

    def test_expression_budget_is_shared_by_the_call(self):
        tracer = self.tracer(expressions='full', max_bytes=500)

        @tracer
        def f():
            first = list(range(100))
            second = list(range(200))
            return len(first) + len(second)

        self.assertEqual(f(), 300)
        values = expression_values(tracer)

        # The first value uses up the budget
        first = values['list(range(100))']
        self.assertEqual(first.children[-1][1].marker, 'max_bytes')

        # Later values are the usual samples, and say so
        second = values['list(range(200))']
        self.assertEqual(second.meta['sampled'], 'max_bytes')
        self.assertIn('only a sample', second.children[-1][1].repr)
        self.assertEqual(values['len(first) + len(second)'].repr, '300')

    def test_supported_data_structures(self):
        eye = self.tracer(arguments='full', result='full', expressions='full')

        class Color(enum.Enum):
            RED = 1

        class Plain(object):
            def __init__(self):
                self.values = set(range(10))

        class Slotted(object):
            __slots__ = ('items', 'name')

            def __init__(self):
                self.items = list(range(10))
                self.name = 'slotted'

        containers = dict(
            a_list=list(range(20)),
            a_tuple=tuple(range(20)),
            a_set=set(range(20)),
            a_frozenset=frozenset(range(20)),
            a_dict={'k%s' % i: i for i in range(20)},
            an_ordered_dict=OrderedDict(('k%s' % i, i) for i in range(20)),
            a_defaultdict=defaultdict(list, {i: [i] for i in range(20)}),
            a_counter=Counter({'k%s' % i: i + 1 for i in range(20)}),
            a_deque=deque(range(20), maxlen=30),
            an_array=array('d', [i / 2 for i in range(20)]),
        )
        leaves = dict(
            text='x' * 200,
            data=bytes(range(100)),
            number=10 ** 50,
            ratio=Fraction(1, 3),
            price=Decimal('19.99'),
            moment=datetime(2026, 9, 24, 21, 55),
            identifier=UUID(int=1),
            path=PurePosixPath('/tmp/example'),
            color=Color.RED,
        )
        nested = [{'level': 1, 'items': [{'level': 2, 'items': list(range(20))}]}]
        numbers = (i for i in range(3))

        @eye
        def process(a_list, a_tuple, a_set, a_frozenset, a_dict, an_ordered_dict, a_defaultdict,
                    a_counter, a_deque, an_array, point, nested, plain, slotted, leaves, numbers):
            everything = [a_list, a_tuple, a_set, a_frozenset, a_dict, an_ordered_dict,
                          a_defaultdict, a_counter, a_deque, an_array]
            return {'everything': everything, 'nested': nested, 'leaves': leaves}

        process(point=Point(1, 2), nested=nested, plain=Plain(), slotted=Slotted(),
                leaves=leaves, numbers=numbers, **containers)
        summary, arguments, result, data = last_call(eye)
        values = expression_values(eye)

        # Every item, as an argument, as a value inside the function, and in the result
        for i, name in enumerate(containers):
            self.assertEqual(len(items(arguments[name])), 20, name)
            self.assertEqual(len(items(values[name])), 20, name)
            self.assertEqual(len(items(result["'everything'"][str(i)])), 20, name)
        self.assertEqual(arguments['a_deque']['maxlen'].repr, '30')
        self.assertEqual(arguments['an_array']['typecode'].repr, "'d'")
        self.assertEqual(arguments['a_defaultdict']['default_factory'].repr, "<class 'list'>")

        # Nested values at every level
        deepest = arguments['nested']['0']["'items'"]['0']["'items'"]
        self.assertEqual(deepest.child_reprs, [str(i) for i in range(20)])
        self.assertEqual(result["'nested'"]['0']["'items'"]['0']["'items'"].child_reprs, deepest.child_reprs)

        # Complete simple values
        for key, value in leaves.items():
            self.assertEqual(arguments['leaves'][repr(key)].repr, repr(value))

        # Objects and named tuples
        self.assertEqual(sorted(arguments['plain']['values'].child_reprs, key=int), [str(i) for i in range(10)])
        self.assertEqual(arguments['slotted']['items'].child_reprs, [str(i) for i in range(10)])
        self.assertEqual(arguments['slotted']['name'].repr, "'slotted'")
        self.assertEqual(arguments['point'].keys, ['x', 'y'])

        # Generators are summarised, never consumed
        self.assertEqual(arguments['numbers'].children, [])
        self.assertEqual(list(numbers), [0, 1, 2])

    def test_unstorable_snapshots_are_dropped_with_a_warning(self):
        tracer = self.full_eye()
        unstorable = NodeValue('x', 0)
        unstorable.set_meta('bad', {1})

        @tracer
        def f(x):
            return x

        with mock.patch.object(NodeValue, 'snapshot', return_value=unstorable):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                self.assertEqual(f(1), 1)

        summary, arguments, result, data = last_call(tracer)
        self.assertEqual(summary, [['x', '1']])
        self.assertNotIn('argument_snapshots', data)
        self.assertNotIn('result_snapshot', data)
        self.assertTrue(any('could not store full values' in str(w.message) for w in caught))

    def test_environment_variables(self):
        def scopes(options):
            return options['arguments'], options['result'], options['expressions']

        with environment(BIRDSEYE_CAPTURE='arguments, result', BIRDSEYE_CAPTURE_MAX_BYTES='1234'):
            options = resolve_capture_options()
        self.assertEqual(scopes(options), ('full', 'full', 'sampled'))
        self.assertEqual(options['max_bytes'], 1234)

        with environment(BIRDSEYE_CAPTURE='expressions'):
            self.assertEqual(scopes(resolve_capture_options()), ('summary', 'summary', 'full'))

        with environment(BIRDSEYE_CAPTURE='full', BIRDSEYE_CAPTURE_MAX_BYTES='none'):
            options = BirdsEye().capture_options
        self.assertEqual(scopes(options), ('full', 'full', 'full'))
        self.assertIsNone(options['max_bytes'])

        # Options given in code take priority over the environment
        with environment(BIRDSEYE_CAPTURE='full'):
            options = resolve_capture_options(dict(result='summary'))
        self.assertEqual((options['arguments'], options['result']), ('full', 'summary'))

        # Invalid environment values only produce warnings
        with environment(BIRDSEYE_CAPTURE='everything', BIRDSEYE_CAPTURE_MAX_BYTES='lots'):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                options = resolve_capture_options()
        self.assertEqual(options, DEFAULT_CAPTURE_OPTIONS)
        self.assertEqual(len(caught), 2)

    def test_invalid_options_in_code_raise(self):
        with environment():
            with self.assertRaises(ValueError):
                resolve_capture_options(dict(arguments='everything'))
            with self.assertRaises(ValueError):
                resolve_capture_options(dict(argument='full'))


if __name__ == '__main__':
    unittest.main()

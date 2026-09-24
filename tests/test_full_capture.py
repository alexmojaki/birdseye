import json
import os
import unittest
import warnings
from array import array
from collections import Counter, OrderedDict, defaultdict, deque, namedtuple
from unittest import mock

import numpy as np

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
        with environment(BIRDSEYE_CAPTURE='arguments, result', BIRDSEYE_CAPTURE_MAX_BYTES='1234'):
            options = resolve_capture_options()
        self.assertEqual((options['arguments'], options['result'], options['max_bytes']), ('full', 'full', 1234))

        with environment(BIRDSEYE_CAPTURE='full', BIRDSEYE_CAPTURE_MAX_BYTES='none'):
            options = BirdsEye().capture_options
        self.assertEqual((options['arguments'], options['result'], options['max_bytes']), ('full', 'full', None))

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

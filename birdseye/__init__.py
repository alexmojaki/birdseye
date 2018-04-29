from __future__ import absolute_import, division, print_function

from future import standard_library

standard_library.install_aliases()
from future.utils import iteritems
from typing import List, Dict, Any, Optional, NamedTuple, Tuple, Iterator, Iterable, Union, cast
from types import FrameType, TracebackType, CodeType, FunctionType
import typing

import ast
import html
import inspect
import json
import os
import traceback
from collections import defaultdict, Sequence, Set, Mapping, deque
from datetime import datetime
from functools import partial
from itertools import chain, islice
from threading import Lock
from uuid import uuid4
import hashlib

from asttokens import ASTTokens
from littleutils import group_by_key_func
from outdated import warn_if_outdated

from cheap_repr import cheap_repr
from cheap_repr.utils import safe_qualname, exception_string
from birdseye.db import Function, Call, session
from birdseye.tracer import TreeTracerBase, TracedFile, EnterCallInfo, ExitCallInfo, FrameInfo, ChangeValue, Loop
from birdseye import tracer
from birdseye.utils import correct_type, PY3, PY2, one_or_none, \
    of_type, Deque, Text, flatten_list, lru_cache, ProtocolEncoder, IPYTHON_FILE_PATH


__version__ = '0.4.2'

warn_if_outdated('birdseye', __version__)


CodeInfo = NamedTuple('CodeInfo', [('db_func', Function),
                                   ('traced_file', TracedFile),
                                   ('arg_names', List[str])])


class BirdsEye(TreeTracerBase):
    def __init__(self):
        super(BirdsEye, self).__init__()
        self._code_infos = {}  # type: Dict[CodeType, CodeInfo]

    def parse_extra(self, root, source, filename):
        # type: (ast.Module, str, str) -> None
        for node in ast.walk(root):  # type: ast.AST
            node._loops = tracer.loops(node)
            if isinstance(node, ast.expr):
                node._is_interesting_expression = is_interesting_expression(node)

    @lru_cache()
    def compile(self, source, filename, flags=0):
        traced_file = super(BirdsEye, self).compile(source, filename, flags)
        traced_file.tokens = ASTTokens(source, tree=traced_file.root)
        return traced_file

    def before_stmt(self, node, frame):
        # type: (ast.stmt, FrameType) -> None
        if frame.f_code not in self._code_infos:
            return
        if isinstance(node.parent, ast.For) and node is node.parent.body[0]:
            self._add_iteration(node._loops, frame)

    def before_expr(self, node, frame):
        if isinstance(node.parent, ast.While) and node is node.parent.test:
            self._add_iteration(node._loops, frame)

    def _add_iteration(self, loops, frame):
        # type: (typing.Sequence[Loop], FrameType) -> None
        """
        Given one or more nested loops, add an iteration for the innermost
        loop (the last in the sequence).
        """
        iteration = self.stack[frame].iteration  # type: Iteration
        for i, loop_node in enumerate(loops):
            loop = iteration.loops[loop_node._tree_index]
            if i == len(loops) - 1:
                loop.append(Iteration())
            else:
                iteration = loop.last()

    def after_expr(self, node, frame, value, exc_value, exc_tb):
        # type: (ast.expr, FrameType, Any, Optional[BaseException], Optional[TracebackType]) -> Optional[ChangeValue]

        if _tracing_recursively(frame):
            return None

        if node._is_interesting_expression:

            # Find the frame corresponding to the function call if we're inside a comprehension
            original_frame = frame
            while frame.f_code.co_name in ('<listcomp>',
                                           '<dictcomp>',
                                           '<setcomp>'):
                frame = frame.f_back

            if frame.f_code not in self._code_infos:
                return None

            if is_obvious_builtin(node, self.stack[original_frame].expression_values[node]):
                return None

            frame_info = self.stack[frame]
            if exc_value:
                node_value = self._exception_value(node, frame, exc_value)
            else:
                node_value = NodeValue.expression(value, level=max(1, 3 - len(node._loops)))
                self._set_node_value(node, frame, node_value)
            self._check_inner_call(frame_info, node, node_value)

        # i.e. is `node` the `y` in `[f(x) for x in y]`, making `node.parent` the `for x in y`
        is_special_comprehension_iter = (
            isinstance(node.parent, ast.comprehension) and
            node is node.parent.iter and

            # Generators execute in their own time and aren't directly attached to the parent frame
            not isinstance(node.parent.parent, ast.GeneratorExp))

        if not is_special_comprehension_iter:
            return None

        # Mark `for x in y` as a bit that executed, so it doesn't show as grey
        self._set_node_value(node.parent, frame, NodeValue.covered())

        if exc_value:
            return None

        # Track each iteration over `y` so that the 'loop' can be stepped through
        loops = node._loops + (node.parent,)  # type: Tuple[Loop, ...]

        def comprehension_iter_proxy():
            for item in value:
                self._add_iteration(loops, frame)
                yield item

        # This effectively changes to code to `for x in comprehension_iter_proxy()`
        return ChangeValue(comprehension_iter_proxy())

    def _check_inner_call(self, frame_info, node, node_value):
        # type: (FrameInfo, Union[ast.stmt, ast.expr], NodeValue) -> None
        inner_calls = frame_info.inner_calls.pop(node, None)
        if inner_calls:
            node_value.set_meta('inner_calls', inner_calls)

    def _set_node_value(self, node, frame, value):
        # type: (ast.AST, FrameType, NodeValue) -> None
        iteration = self.stack[frame].iteration  # type: Iteration
        for i, loop_node in enumerate(node._loops):  # type: int, ast.AST
            loop = iteration.loops[loop_node._tree_index]
            iteration = loop.last()
        iteration.vals[node._tree_index] = value

    def _exception_value(self, node, frame, exc_value):
        # type: (Union[ast.expr, ast.stmt], FrameType, BaseException) -> NodeValue
        value = NodeValue.exception(exc_value)
        self._set_node_value(node, frame, value)
        return value

    def after_stmt(self, node, frame, exc_value, exc_traceback, exc_node):
        # type: (ast.stmt, FrameType, Optional[BaseException], Optional[TracebackType], Optional[ast.AST]) -> Optional[bool]
        if frame.f_code not in self._code_infos or _tracing_recursively(frame):
            return None
        if exc_value and node is exc_node:
            value = self._exception_value(node, frame, exc_value)
        else:
            value = NodeValue.covered()
            self._set_node_value(node, frame, value)
        self._check_inner_call(self.stack[frame], node, value)
        return None

    def enter_call(self, enter_info):
        # type: (EnterCallInfo) -> None
        frame = enter_info.current_frame  # type: FrameType
        if frame.f_code not in self._code_infos or _tracing_recursively(frame):
            return
        frame_info = self.stack[frame]
        frame_info.start_time = datetime.now()
        frame_info.iteration = Iteration()
        f_locals = frame.f_locals.copy()  # type: Dict[str, Any]
        arguments = [(name, f_locals.pop(name))
                     for name in self._code_infos[frame.f_code].arg_names
                     if name] + [

            # Local variables other than actual arguments. These are variables from
            # the enclosing scope. It's handy to treat them like arguments in the UI
            it for it in f_locals.items()
            if it[0][0] != '.'  # Appears when using nested tuple arguments
        ]
        frame_info.arguments = json.dumps([[k, cheap_repr(v)] for k, v in arguments])
        frame_info.call_id = self._call_id()
        frame_info.inner_calls = defaultdict(list)
        prev = self.stack.get(enter_info.caller_frame)
        if prev:
            prev.inner_calls[enter_info.call_node].append(frame_info.call_id)

    def _call_id(self):
        # type: () -> Text
        return uuid4().hex

    def exit_call(self, exit_info):
        # type: (ExitCallInfo) -> None
        """
        This is where all the data collected during the call is gathered up
        and sent to the database.
        """
        frame = exit_info.current_frame  # type: FrameType
        if frame.f_code not in self._code_infos or _tracing_recursively(frame):
            return
        frame_info = self.stack[frame]

        top_iteration = frame_info.iteration  # type: Iteration
        node_values = _deep_dict()
        self._extract_node_values(top_iteration, (), node_values)

        db_func = self._code_infos[frame.f_code].db_func  # type: Function
        exc = exit_info.exc_value  # type: Optional[Exception]
        if exc:
            traceback_str = ''.join(traceback.format_exception(type(exc), exc, exit_info.exc_tb))
            exception = exception_string(exc)
        else:
            traceback_str = exception = None

        call = Call(id=frame_info.call_id,
                    function=db_func,
                    arguments=frame_info.arguments,
                    return_value=cheap_repr(exit_info.return_value),
                    exception=exception,
                    traceback=traceback_str,
                    data=json.dumps(
                        dict(
                            node_values=node_values,
                            loop_iterations=top_iteration.extract_iterations()['loops'],
                            type_names=type_registry.names(),
                            num_special_types=type_registry.num_special_types,
                        ),
                        cls=ProtocolEncoder,
                        separators=(',', ':')
                    ),
                    start_time=frame_info.start_time)
        session.add(call)
        session.commit()

    def _extract_node_values(self, iteration, path, node_values):
        # type: (Iteration, Tuple[int, ...], dict) -> None
        """
        Populates node_values with values inside iteration.
        """
        # Each element of `path` is an index of a loop iteration
        # e.g. given the nested loops:
        #
        # for i in [0, 1, 2]:
        #     for j in [0, 1, 2, 3]:
        #
        # path may be (i, j) for each of the iterations
        for tree_index, node_value in iteration.vals.items():

            # So this `full_path` is a tuple of ints, but the first
            # int has a different meaning from the others
            full_path = (tree_index,) + path

            # Given a path (a, b, c) we're making node_values 'contain'
            # this structure:
            # {a: {b: {c: node_value}}}
            d = node_values
            for path_k in full_path[:-1]:
                d = d[path_k]
            d[full_path[-1]] = node_value

        for loop in iteration.loops.values():
            for i, iteration in enumerate(loop):
                self._extract_node_values(iteration, path + (i,), node_values)

    def trace_function(self, func):
        # type: (FunctionType) -> FunctionType
        new_func = super(BirdsEye, self).trace_function(func)
        code_info = self._code_infos.get(new_func.__code__)
        if code_info:
            return new_func

        lines, start_lineno = inspect.getsourcelines(func)  # type: List[Text], int
        end_lineno = start_lineno + len(lines)
        name = safe_qualname(func)
        source_file = inspect.getsourcefile(func)
        if source_file.startswith('<ipython-input'):
            filename = IPYTHON_FILE_PATH
        else:
            filename = os.path.abspath(source_file)
        nodes = list(self._nodes_of_interest(new_func.traced_file, start_lineno, end_lineno))
        html_body = self._nodes_html(nodes, start_lineno, end_lineno, new_func.traced_file)
        data = json.dumps(dict(
            node_loops={
                node._tree_index: [n._tree_index for n in node._loops]
                for node, _ in nodes
                if node._loops
            }),
            sort_keys=True)
        db_func = self._db_func(data, filename, html_body, name, start_lineno)
        arg_info = inspect.getargs(new_func.__code__)
        arg_names = list(chain(flatten_list(arg_info[0]), arg_info[1:]))  # type: List[str]
        self._code_infos[new_func.__code__] = CodeInfo(db_func, new_func.traced_file, arg_names)
        return new_func

    def _db_func(self, data, filename, html_body, name, start_lineno):
        """
        Retrieve the Function object from the database if one exists, or create one.
        """
        function_hash = hashlib.sha256((filename + name + html_body + data + str(start_lineno)
                                        ).encode('utf8')).hexdigest()
        db_func = one_or_none(session.query(Function).filter_by(hash=function_hash))  # type: Optional[Function]
        if not db_func:
            db_func = Function(file=filename,
                               name=name,
                               html_body=html_body,
                               lineno=start_lineno,
                               data=data,
                               hash=function_hash)
            session.add(db_func)
            session.commit()
        return db_func

    def _nodes_of_interest(self, traced_file, start_lineno, end_lineno):
        """
        Nodes that may have a value, show up as a box in the UI, and lie within the
        given line range.
        """
        for node in traced_file.nodes:
            classes = []

            if (isinstance(node, (ast.While, ast.For, ast.comprehension)) and
                    not isinstance(node.parent, ast.GeneratorExp)):
                classes.append('loop')
            if isinstance(node, ast.stmt):
                classes.append('stmt')

            if isinstance(node, ast.expr):
                if not node._is_interesting_expression:
                    continue
            elif not classes:
                continue

            assert isinstance(node, ast.AST)

            # In particular FormattedValue is missing this
            if not hasattr(node, 'first_token'):
                continue

            if not start_lineno <= node.first_token.start[0] <= end_lineno:
                continue

            start, end = traced_file.tokens.get_text_range(node)  # type: int, int
            if start == end == 0:
                continue

            yield node, (classes, start, end)

    def _nodes_html(self, nodes, start_lineno, end_lineno, traced_file):
        # type: (list, int, int, TracedFile) -> str
        """
        The algorithm for generating the HTML works as follows. We generate a list
        of HTMLPositions, which are essentially places to insert HTML into the source plus some
        metadata. The order of the fields of HTMLPosition ensure that when the list is sorted,
        the resulting HTML is valid and correct. Specifically, the fields are:
        
          1. index: the index in the source string where the HTML would be inserted
          2. is_start: Indicates if this piece of HTML is the start of a tag, rather than the end.
             Ends should appear first, so that the resulting HTML looks like:
                <span> ... </span><span> ... </span>
             rather than:
                <span> ... <span></span> ... </span>
             (I think this might actually be unnecessary, since I can't think of any cases of two
              expressions right next to each other with nothing in between)
          3. depth: the depth of the corresponding node in the AST. We want the start of a tag from
             a node to appear before the start of a tag nested within, e.g. `foo()` should become:
                <span [for foo()]><span [for foo]>foo</span>()</span>
             rather than:   
                <span [for foo]><span [for foo()]>foo</span>()</span>
          4. html: the actual HTML to insert. Not important for ordering.
          
        Mostly the list contains pairs of HTMLPositions corresponding to AST nodes, one for the
        start and one for the end.
        
        After the list is sorted, the HTML generated is essentially:
        
        source[0:positions[0].index] + positions[0].html + source[positions[0].index:positions[1].index] + positions[1].html + ...
        """

        traced_file.root._depth = 0
        for node in ast.walk(traced_file.root):  # type: ast.AST
            for child in ast.iter_child_nodes(node):
                child._depth = node._depth + 1

        positions = []  # type: List[HTMLPosition]

        for node, (classes, start, end) in nodes:
            # noinspection PyArgumentList
            positions.extend(map(
                HTMLPosition,
                [start, end],
                [True, False],  # is_start
                [node._depth, node._depth],
                ['<span data-index="%s" class="%s">' % (node._tree_index, ' '.join(classes)),
                 '</span>']))

        end_lineno = self._separate_comprehensions(end_lineno, positions, traced_file)

        # This just makes the loop below simpler
        positions.append(HTMLPosition(len(traced_file.source), False, 0, ''))

        positions.sort()

        html_parts = []
        start = 0
        for position in positions:
            html_parts.append(html.escape(traced_file.source[start:position.index]))
            html_parts.append(position.html)
            start = position.index
        html_body = ''.join(html_parts)
        html_body = '\n'.join(html_body.split('\n')[start_lineno - 1:end_lineno - 1])

        return html_body

    def _separate_comprehensions(self, end_lineno, positions, traced_file):
        # type: (int, List[HTMLPosition], TracedFile) -> int
        """
        Comprehensions (e.g. list comprehensions) are troublesome because they can
        be navigated like loops, and the buttons for these need to be on separate lines.
        This function inserts newlines to turn:

        [x + y for x in range(3) for y in range(5)] and
        [[x + y for x in range(3)] for y in range(5)]

        into

        [x + y for x in range(3)
         for y in range(5)] and
        [[x + y for x in range(3)]
         for y in range(5)]
        """

        comprehensions = group_by_key_func(of_type((ast.comprehension, ast.While, ast.For), traced_file.nodes),
                                           lambda c: c.first_token.start[0]
                                           )  # type: Dict[Any, Iterable[ast.comprehension]]

        def get_start(n):
            # type: (ast.AST) -> int
            return traced_file.tokens.get_text_range(n)[0]

        for comp_list in comprehensions.values():
            prev_start = None  # type: Optional[int]
            for comp in sorted(comp_list, key=lambda c: c.first_token.startpos):
                if isinstance(comp, ast.comprehension) and comp is comp.parent.generators[0]:
                    start = get_start(comp.parent)
                    if prev_start is not None and start < prev_start:
                        start = get_start(comp)
                else:
                    start = get_start(comp)
                if prev_start is not None:
                    positions.append(HTMLPosition(start, True, 0, '\n '))
                    end_lineno += 1
                prev_start = start

        return end_lineno


eye = BirdsEye()

HTMLPosition = NamedTuple('HTMLPosition', [
    ('index', int),
    ('is_start', bool),
    ('depth', int),
    ('html', str),
])


def _deep_dict():
    return defaultdict(_deep_dict)


_bad_codes = (eye.enter_call.__code__,
              eye.exit_call.__code__,
              eye.after_expr.__code__,
              eye.after_stmt.__code__)


def _tracing_recursively(frame):
    while frame:
        if frame.f_code in _bad_codes:
            return True
        frame = frame.f_back


class Iteration(object):
    """
    Corresponds to an iteration of a loop during a call, OR
    the call itself (FrameInfo.iteration).
    """
    def __init__(self):
        # Mapping of nodes (via node._tree_index) to the value of that
        # node in this iteration. Only contains nodes within the corresponding
        # loop or at the top of the function, but not in loops further within
        # (those will be somewhere within self.loops)
        # Therefore those nodes have at most one value.
        self.vals = {}  # type: Dict[int, NodeValue]

        # Mapping of loop nodes (via node._tree_index) to IterationLists
        # for loops that happened during this iteration
        self.loops = defaultdict(IterationList)  # type: Dict[int, IterationList]

        # 0-based index of this iteration
        self.index = None  # type: int

    def extract_iterations(self):
        # type: () -> Dict[str, Union[int, Dict]]
        return {
            'index': self.index,
            'loops': {
                tree_index: [iteration.extract_iterations()
                             for iteration in iteration_list]
                for tree_index, iteration_list in self.loops.items()
            }
        }


class IterationList(Iterable[Iteration]):
    """
    A list of Iterations, corresponding to a run of a loop.
    If the loop has many iterations, only contains the first and last few.
    """
    side_len = 3

    def __init__(self):
        self.start = []  # type: List[Iteration]
        self.end = deque(maxlen=self.side_len)  # type: Deque[Iteration]
        self.length = 0  # type: int

    def append(self, iteration):
        # type: (Iteration) -> None
        if self.length < self.side_len:
            self.start.append(iteration)
        else:
            self.end.append(iteration)
        iteration.index = self.length
        self.length += 1

    def __iter__(self):
        # type: () -> Iterator[Iteration]
        return chain(self.start, self.end)

    def last(self):
        # type: () -> Iteration
        if self.end:
            return self.end[-1]
        else:
            return self.start[-1]


class TypeRegistry(object):
    basic_types = (type(None), bool, int, float, complex)
    if PY2:
        basic_types += (long,)
    special_types = basic_types + (list, dict, tuple, set, frozenset, str)
    if PY2:
        special_types += (unicode if PY2 else bytes,)

    num_special_types = len(special_types)

    def __init__(self):
        self.lock = Lock()
        self.data = defaultdict(lambda: len(self.data))  # type: Dict[type, int]

        for t in self.special_types:
            _ = self.data[t]

    def __getitem__(self, item):
        t = correct_type(item)
        with self.lock:
            return self.data[t]

    def names(self):
        # type: () -> List[str]
        rev = dict((v, k) for k, v in self.data.items())
        return [safe_qualname(rev[i]) for i in range(len(rev))]


type_registry = TypeRegistry()


class NodeValue(object):
    """
    The 'value' of a node during a particular iteration.
    This can mean different things, see the classmethods.
    Can also contain some metadata, including links to other calls.
    """
    __slots__ = ('val_repr', 'type_index', 'meta', 'children')

    def __init__(self, val_repr, type_index):
        self.val_repr = val_repr  # type: str
        self.type_index = type_index  # type: int
        self.meta = None  # type: Optional[Dict[str, Any]]
        self.children = None  # type: Optional[List[Tuple[str, NodeValue]]]

    def set_meta(self, key, value):
        # type: (str, Any) -> None
        self.meta = self.meta or {}
        self.meta[key] = value

    def add_child(self, level, key, value):
        # type: (int, str, Any) -> None
        self.children = self.children or []
        self.children.append((key, NodeValue.expression(value, level)))

    def as_json(self):
        result = [self.val_repr, self.type_index, self.meta or {}]  # type: list
        if self.children:
            result.extend(self.children)
        return result

    @classmethod
    def covered(cls):
        """
        Represents a bit of code, usually a statement, that executed successfully but
        doesn't have an actual value.
        """
        return cls('', -2)

    @classmethod
    def exception(cls, exc_value):
        """
        Means that exc_value was raised by a node when executing, and not any inner node.
        """
        return cls(exception_string(exc_value), -1)

    @classmethod
    def expression(cls, val, level):
        # type: (Any, int) -> NodeValue
        """
        The value of an expression or one of its children, with attributes,
        dictionary items, etc as children. Has a max depth of `level` levels.
        """
        result = cls(cheap_repr(val), type_registry[val])
        if isinstance(val, TypeRegistry.basic_types):
            return result

        try:
            length = len(val)
        except:
            length = None
        else:
            result.set_meta('len', length)

        if (level == 0 or
                isinstance(val,
                           (str, bytes, range)
                           if PY3 else
                           (str, unicode, xrange))):
            return result

        add_child = partial(result.add_child, level - 1)

        if isinstance(val, Sequence) and length is not None:
            if length <= 8:
                indices = range(length)
            else:
                indices = chain(range(3), range(length - 3, length))
            for i in indices:
                try:
                    v = val[i]
                except:
                    pass
                else:
                    add_child(str(i), v)
        if isinstance(val, Mapping):
            for k, v in islice(_safe_iter(val, iteritems), 10):
                add_child(cheap_repr(k), v)
        if isinstance(val, Set):
            vals = _safe_iter(val)
            if length is None or length > 8:
                vals = islice(vals, 6)
            for i, v in enumerate(vals):
                add_child('<%s>' % i, v)

        d = getattr(val, '__dict__', None)
        if d:
            for k, v in islice(iteritems(d), 50):
                if isinstance(v, TracedFile):
                    continue
                add_child(str(k), v)
        else:
            for s in (getattr(val, '__slots__', None) or ()):
                try:
                    attr = getattr(val, s)
                except AttributeError:
                    pass
                else:
                    add_child(str(s), attr)
        return result


def _safe_iter(val, f=lambda x: x):
    try:
        for x in f(val):
            yield x
    except:
        pass


def is_interesting_expression(node):
    # type: (ast.AST) -> bool
    """
    If this expression has a value that may not be exactly what it looks like,
    return True. Put differently, return False if this is just a literal.
    """
    return (isinstance(node, ast.expr) and
            not (isinstance(node, (ast.Num, ast.Str, getattr(ast, 'NameConstant', ()))) or
                 isinstance(getattr(node, 'ctx', None),
                            (ast.Store, ast.Del)) or
                 (isinstance(node, ast.UnaryOp) and
                  isinstance(node.op, (ast.UAdd, ast.USub)) and
                  isinstance(node.operand, ast.Num)) or
                 (isinstance(node, (ast.List, ast.Tuple, ast.Dict)) and
                  not any(is_interesting_expression(n) for n in ast.iter_child_nodes(node)))))


def is_obvious_builtin(node, value):
    # type: (ast.expr, Any) -> bool
    """
    Return True if this node looks like a builtin and it really is
    (i.e. hasn't been shadowed).
    """
    # noinspection PyUnresolvedReferences
    builtins = cast(dict, __builtins__)
    return ((isinstance(node, ast.Name) and
             node.id in builtins and
             builtins[node.id] is value) or
            isinstance(node, getattr(ast, 'NameConstant', ())))

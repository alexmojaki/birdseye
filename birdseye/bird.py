import ast
import hashlib
import inspect
import json
import os
import sys
import traceback
from collections import defaultdict, deque, namedtuple, Counter
from functools import partial
from itertools import chain, islice
from threading import Lock
from types import FrameType, TracebackType, CodeType, FunctionType, ModuleType
from uuid import uuid4

from asttokens import ASTTokens
from cached_property import cached_property
from cheap_repr import cheap_repr, try_register_repr
from cheap_repr.utils import safe_qualname, exception_string
from littleutils import group_by_key_func, only

from birdseye import __version__
from birdseye import tracer
from birdseye.db import Database, retry_db
from birdseye.tracer import (
    TreeTracerBase,
    TracedFile,
    EnterCallInfo,
    ExitCallInfo,
    FrameInfo,
    ChangeValue,
)
from birdseye.utils import (
    correct_type,
    PY3,
    PY2,
    one_or_none,
    of_type,
    Deque,
    Text,
    flatten_list,
    lru_cache,
    ProtocolEncoder,
    IPYTHON_FILE_PATH,
    source_without_decorators,
    is_future_import,
    get_unfrozen_datetime,
    FILE_SENTINEL_NAME,
    read_source_file,
    html_escape,
)

try:
    from collections.abc import Sequence, Set, Mapping
except ImportError:
    from collections import Sequence, Set, Mapping

try:
    from numpy import ndarray
except Exception:
    class ndarray(object):
        pass

try:
    from pandas import DataFrame, Series
except Exception:
    class DataFrame(object):
        pass


    class Series(object):
        pass

try:
    from django.db.models import QuerySet
except Exception:
    class QuerySet(object):
        pass

try:
    from outdated import warn_if_outdated

    warn_if_outdated("birdseye", __version__)
except Exception:
    pass

# noinspection PyUnreachableCode
if False:
    from typing import (
        List,
        Dict,
        Any,
        Optional,
        Tuple,
        Iterator,
        Iterable,
        Union,
    )
    Loop = Union[ast.For, ast.While, ast.comprehension]


CodeInfo = namedtuple('CodeInfo', 'db_func traced_file arg_names')


class BirdsEye(TreeTracerBase):
    """
    Decorate functions with an instance of this class to debug them,
    or just use the existing instance `eye`.
    """

    def __init__(self, db_uri=None, num_samples=None):
        """
        Set db_uri to specify where the database lives, as an alternative to
        the environment variable BIRDSEYE_DB.
        """
        super(BirdsEye, self).__init__()
        self._db_uri = db_uri
        self._code_infos = {}  # type: Dict[CodeType, CodeInfo]
        self._last_call_id = None
        self._ipython_cell_value = None
        self.num_samples = num_samples or dict(
            big=dict(
                attributes=50,
                dict=50,
                list=30,
                set=30,
                pandas_rows=20,
                pandas_cols=100,
            ),
            small=dict(
                attributes=50,
                dict=10,
                list=6,
                set=6,
                pandas_rows=6,
                pandas_cols=10,
            ),
        )

    @cached_property
    def db(self):
        return Database(self._db_uri)

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
        # type: (Sequence[Loop], FrameType) -> None
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

        if frame.f_code not in self._code_infos:
            return None

        if node._is_interesting_expression:
            # If this is an expression statement and the last statement
            # in the body, the value is returned from the cell magic
            # to be displayed as usual
            if (self._code_infos[frame.f_code].traced_file.is_ipython_cell
                    and isinstance(node.parent, ast.Expr)
                    and node.parent is node.parent.parent.body[-1]):
                self._ipython_cell_value = value

            if is_obvious_builtin(node, self.stack[frame].expression_values[node]):
                return None

            frame_info = self.stack[frame]
            if exc_value:
                node_value = self._exception_value(node, frame, exc_value)
            else:
                node_value = NodeValue.expression(
                    self.num_samples,
                    value,
                    level=max(1, 3 - len(node._loops) * (not self._is_first_loop_iteration(node, frame))),
                )
                self._set_node_value(node, frame, node_value)
            self._check_inner_call(frame_info, node, node_value)

        # i.e. is `node` the `y` in `[f(x) for x in y]`, making `node.parent` the `for x in y`
        is_special_comprehension_iter = (
            isinstance(node.parent, ast.comprehension) and
            node is node.parent.iter
        )

        if not is_special_comprehension_iter:
            return None

        # Mark `for x in y` as a bit that executed, so it doesn't show as grey
        self._set_node_value(node.parent, frame, NodeValue.covered())

        if exc_value:
            return None

        # Track each iteration over `y` so that the 'loop' can be stepped through
        loops = node._loops + (node.parent,)  # type: Tuple[Loop, ...]

        is_genexpr = isinstance(node.parent.parent, ast.GeneratorExp)

        def comprehension_iter_proxy():
            for item in value:
                # Don't try to add an iteration if this is a generator
                # which has outlived its main frame
                # This way of doing things has the weird side effect
                # of grey values when the main frame is still alive
                # but the generator is evaluated elsewhere
                if not (is_genexpr and frame not in self.stack):
                    self._add_iteration(loops, frame)
                yield item

        # This effectively changes to code to `for x in comprehension_iter_proxy()`
        return ChangeValue(comprehension_iter_proxy())

    def _check_inner_call(self, frame_info, node, node_value):
        # type: (FrameInfo, Union[ast.stmt, ast.expr], NodeValue) -> None
        inner_calls = frame_info.inner_calls.pop(node, None)
        if inner_calls:
            node_value.set_meta('inner_calls', inner_calls)

    def _is_first_loop_iteration(self, node, frame):
        # type: (ast.AST, FrameType) -> bool
        iteration = self.stack[frame].iteration  # type: Iteration
        for loop_node in node._loops:  # type: ast.AST
            loop = iteration.loops[loop_node._tree_index]
            iteration = loop.last()
            if iteration.index > 0:
                return False
        return True

    def _set_node_value(self, node, frame, value):
        # type: (ast.AST, FrameType, NodeValue) -> None
        iteration = self.stack[frame].iteration  # type: Iteration
        for loop_node in node._loops:  # type: ast.AST
            loop = iteration.loops[loop_node._tree_index]
            loop.recorded_node(node)
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
        frame_info.start_time = get_unfrozen_datetime()
        frame_info.iteration = Iteration()

        code_info = self._code_infos[frame.f_code]
        if isinstance(enter_info.enter_node.parent, ast.Module):
            arguments = []
        else:
            f_locals = frame.f_locals.copy()  # type: Dict[str, Any]
            arguments = [(name, f_locals.pop(name))
                         for name in code_info.arg_names
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
            inner_calls = getattr(prev, 'inner_calls', None)
            if inner_calls is not None:
                inner_calls[enter_info.call_node].append(frame_info.call_id)

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

        db_func = self._code_infos[frame.f_code].db_func
        exc = exit_info.exc_value  # type: Optional[Exception]
        if exc:
            traceback_str = ''.join(traceback.format_exception(type(exc), exc, exit_info.exc_tb))
            exception = exception_string(exc)
        else:
            traceback_str = exception = None

        @retry_db
        def add_call():
            Call = self.db.Call
            call = Call(id=frame_info.call_id,
                        function_id=db_func,
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
            with self.db.session_scope() as session:
                session.add(call)

        add_call()

        self._last_call_id = frame_info.call_id

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
        traced_file = new_func.traced_file

        arg_info = inspect.getargs(new_func.__code__)
        arg_names = list(chain(flatten_list(arg_info[0]), arg_info[1:]))  # type: List[str]
        self._trace(name, filename, traced_file, new_func.__code__, typ='function',
                    start_lineno=start_lineno, end_lineno=end_lineno,
                    arg_names=arg_names)

        return new_func

    def exec_ipython_cell(self, source, callback):
        from IPython import get_ipython
        shell = get_ipython()
        filename = name = shell.compile.cache(source)
        flags = shell.compile.flags

        traced_file = self.compile(source, filename, flags)
        traced_file.is_ipython_cell = True

        for node in traced_file.root.body:
            if is_future_import(node):
                raise ValueError('from __future__ import ... statements '
                                 'are not allowed in cells traced with %%eye')

        shell.user_global_ns.update(self._trace_methods_dict(traced_file))

        self._trace(name, filename, traced_file, traced_file.code, 'module', source)

        try:
            shell.ex(traced_file.code)
            return self._ipython_cell_value
        finally:
            callback(self._last_call_id)
            self._ipython_cell_value = None

    def trace_this_module(self, context=0, deep=False):
        frame = inspect.currentframe()

        filename = None
        while context >= 0:
            frame = frame.f_back
            filename = inspect.getsourcefile(frame)
            if filename is not None:
                context -= 1
        filename = os.path.abspath(filename)

        if frame.f_globals.get('__name__') != '__main__':
            if PY3 and "_treetrace_hidden_" not in str(frame.f_globals.keys()):
                raise RuntimeError(
                    'To trace an imported module, you must import birdseye before '
                    'importing that module.')
            return

        lines = read_source_file(filename).splitlines()
        lines[:frame.f_lineno] = [''] * frame.f_lineno
        source = '\n'.join(lines)
        self.exec_string(source, filename, frame.f_globals, frame.f_locals, deep)
        sys.exit(0)

    def exec_string(self, source, filename, globs=None, locs=None, deep=False):
        globs = globs or {}
        locs = locs or {}

        traced_file = self.compile(source, filename)

        globs.update(self._trace_methods_dict(traced_file))

        self._trace(FILE_SENTINEL_NAME, filename, traced_file, traced_file.code, 'module', source)

        if deep:
            nodes_by_lineno = {
                node.lineno: node
                for node in traced_file.nodes
                if isinstance(node, ast.FunctionDef)
            }

            def find_code(root_code):
                # type: (CodeType) -> None
                for code in root_code.co_consts:  # type: CodeType
                    if not inspect.iscode(code) or code.co_name.startswith('<'):
                        continue

                    find_code(code)

                    lineno = code.co_firstlineno
                    node = nodes_by_lineno.get(lineno)
                    if not node:
                        continue

                    self._trace(
                        code.co_name, filename, traced_file, code,
                        typ='function',
                        source=source,
                        start_lineno=lineno,
                        end_lineno=node.last_token.end[0] + 1,
                    )

            find_code(traced_file.code)

        exec(traced_file.code, globs, locs)

    def _trace(
            self,
            name,
            filename,
            traced_file,
            code,
            typ,
            source='',
            start_lineno=1,
            end_lineno=None,
            arg_names=(),
    ):
        if not end_lineno:
            end_lineno = start_lineno + len(source.splitlines())
        nodes = list(self._nodes_of_interest(traced_file, start_lineno, end_lineno))
        html_body = self._nodes_html(nodes, start_lineno, end_lineno, traced_file)

        data_dict = dict(
            # This maps each node to the loops enclosing that node
            node_loops={
                node._tree_index: [n._tree_index for n in node._loops]
                for node, _ in nodes
                if node._loops
            },
        )
        if typ == 'function':
            tokens = traced_file.tokens
            func_node = only(node
                             for node, _ in nodes
                             if isinstance(node, ast.FunctionDef)
                             and node.first_token.start[0] == start_lineno)
            func_startpos, source = source_without_decorators(tokens, func_node)
            # These are for the PyCharm plugin
            data_dict.update(
                node_ranges=list(self._node_ranges(nodes, tokens, func_startpos)),
                loop_ranges=list(self._loop_ranges(nodes, tokens, func_startpos)),
            )

        data = json.dumps(data_dict, sort_keys=True)
        db_func = self._db_func(data, filename, html_body, name, start_lineno, source, typ)
        self._code_infos[code] = CodeInfo(db_func, traced_file, arg_names)

    def _loop_ranges(self, nodes, tokens, func_start):
        # For a for loop, e.g.
        #
        #     for x in y:
        #
        # this yields the range of the target 'x'.
        #
        # For a while loop, e.g.
        #
        #     while x < 10:
        #
        # this yields the range of the condition 'x < 10'.
        for node, (classes, _, __) in nodes:
            if 'loop' not in classes:
                continue

            try:
                target = node.target  # for loop
            except AttributeError:
                target = node.test  # while loop

            start, end = tokens.get_text_range(target)
            start -= func_start
            end -= func_start

            yield dict(
                tree_index=node._tree_index,
                start=start,
                end=end
            )

    def _node_ranges(self, nodes, tokens, func_start):
        for node, (classes, _, __) in nodes:
            start, end = tokens.get_text_range(node)
            start -= func_start
            end -= func_start

            if start < 0:
                assert (end < 0  # nodes before the def, i.e. decorators
                        or isinstance(node, ast.FunctionDef))
                continue

            yield dict(
                tree_index=node._tree_index,
                start=start,
                end=end,
                depth=node._depth,
                classes=classes,
            )

    @retry_db
    def _db_func(self, data, filename, html_body, name, start_lineno, source, typ):
        """
        Retrieve the Function object from the database if one exists, or create one.
        """
        def h(s):
            return hashlib.sha256(s.encode('utf8')).hexdigest()

        function_hash = h(filename + name + html_body + data + str(start_lineno))

        Function = self.db.Function

        with self.db.session_scope() as session:
            db_func = one_or_none(session.query(Function).filter_by(hash=function_hash))  # type: Optional[Function]
            if not db_func:
                db_func = Function(file=filename,
                                   name=name,
                                   type=typ,
                                   html_body=html_body,
                                   lineno=start_lineno,
                                   data=data,
                                   body_hash=h(source),
                                   hash=function_hash)
                session.add(db_func)
                session.commit()  # ensure .id exists
            assert isinstance(db_func.id, int)
            return db_func.id

    def _nodes_of_interest(self, traced_file, start_lineno, end_lineno):
        # type: (TracedFile, int, int) -> Iterator[Tuple[ast.AST, Tuple]]
        """
        Nodes that may have a value, show up as a box in the UI, and lie within the
        given line range.
        """
        for node in traced_file.nodes:
            classes = []

            if isinstance(node, (ast.While, ast.For, ast.comprehension)):
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

        end_lineno = self._separate_comprehensions(
            [n[0] for n in nodes],
            end_lineno, positions, traced_file)

        # This just makes the loop below simpler
        positions.append(HTMLPosition(len(traced_file.source), False, 0, ''))

        positions.sort()

        html_parts = []
        start = 0
        for position in positions:
            html_parts.append(html_escape(traced_file.source[start:position.index]))
            html_parts.append(position.html)
            start = position.index
        html_body = ''.join(html_parts)
        html_body = '\n'.join(html_body.split('\n')[start_lineno - 1:end_lineno - 1])

        return html_body.strip('\n')

    def _separate_comprehensions(self, nodes, end_lineno, positions, traced_file):
        # type: (list, int, List[HTMLPosition], TracedFile) -> int
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

        comprehensions = group_by_key_func(of_type((ast.comprehension, ast.While, ast.For), nodes),
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

HTMLPosition = namedtuple('HTMLPosition', 'index is_start depth html')


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
        self.keep = False

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


class IterationList:
    """
    A list of Iterations, corresponding to a run of a loop.
    If the loop has many iterations, only contains the first and last few
    and any in the middle where unique nodes had values, so that
    any node which appeared during this loop exists in at least some iterations.
    """
    side_len = 3

    def __init__(self):
        # Contains the first few iterations
        # and any after that have unique nodes in them
        self.start = []  # type: List[Iteration]

        # Contains the last few iterations
        self.end = deque(maxlen=self.side_len)  # type: Deque[Iteration]

        # Total number of iterations in the loop, not all of which
        # are kept
        self.length = 0  # type: int

        # Number of times each node has been recorded in this loop
        self.recorded = Counter()

    def append(self, iteration):
        # type: (Iteration) -> None
        if self.length < self.side_len:
            self.start.append(iteration)
        else:
            # If self.end is too long, the first element self.end[0]
            # is about to be dropped by the deque. If that iteration
            # should be kept because of some node that was recorded,
            # add it to self.start
            if len(self.end) >= self.side_len and self.end[0].keep:
                self.start.append(self.end[0])

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

    def recorded_node(self, node):
        # type: (ast.AST) -> None
        if self.recorded[node] >= 2:
            # We've already seen this node enough
            return

        # This node is new(ish), make sure we keep this iteration
        self.last().keep = True
        self.recorded[node] += 1


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

    def add_child(self, samples, level, key, value):
        # type: (dict, int, str, Any) -> None
        self.children = self.children or []
        self.children.append((key, NodeValue.expression(samples, value, level)))

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
    def expression(cls, samples, val, level):
        # type: (dict, Any, int) -> NodeValue
        """
        The value of an expression or one of its children, with attributes,
        dictionary items, etc as children. Has a max depth of `level` levels.
        """
        result = cls(cheap_repr(val), type_registry[val])
        if isinstance(val, (TypeRegistry.basic_types, BirdsEye)):
            return result

        length = None
        if not isinstance(val, QuerySet):  # len triggers a database query
            try:
                length = len(val)
            except:
                pass
            else:
                result.set_meta('len', length)

        if isinstance(val, ModuleType):
            level = min(level, 2)

        add_child = partial(result.add_child, samples, level - 1)

        if isinstance(val, (Series, ndarray)):
            attrs = ['dtype']
            if isinstance(val, ndarray):
                attrs.append('shape')
            for name in attrs:
                try:
                    attr = getattr(val, name)
                except AttributeError:
                    pass
                else:
                    add_child(name, attr)

        if level >= 3 or level >= 2 and isinstance(val, Series):
            sample_type = 'big'
        else:
            sample_type = 'small'

        samples = samples[sample_type]

        # Always expand DataFrames and Series regardless of level to
        # make the table view of DataFrames work

        if isinstance(val, DataFrame):
            meta = {}
            result.set_meta('dataframe', meta)

            max_rows = samples['pandas_rows']
            max_cols = samples['pandas_cols']

            if length > max_rows + 2:
                meta['row_break'] = max_rows // 2

            columns = val.columns
            num_cols = len(columns)
            if num_cols > max_cols + 2:
                meta['col_break'] = max_cols // 2

            indices = set(_sample_indices(num_cols, max_cols))
            for i, (formatted_name, label) in enumerate(zip(val.columns.format(sparsify=False),
                                                            val.columns)):
                if i in indices:
                    add_child(formatted_name, val.iloc[:, i])

            return result

        if isinstance(val, Series):
            for i in _sample_indices(length, samples['pandas_rows']):
                try:
                    k = val.index[i:i + 1].format(sparsify=False)[0]
                    v = val.iloc[i]
                except:
                    pass
                else:
                    add_child(k, v)
            return result

        if (level <= 0 or
                isinstance(val,
                           (str, bytes, range)
                           if PY3 else
                           (str, unicode, xrange))):
            return result

        if isinstance(val, (Sequence, ndarray)) and length is not None:
            for i in _sample_indices(length, samples['list']):
                try:
                    v = val[i]
                except:
                    pass
                else:
                    add_child(str(i), v)

        if isinstance(val, Mapping):
            for k, v in islice(_safe_iter(val, iteritems), samples['dict']):
                add_child(cheap_repr(k), v)

        if isinstance(val, Set):
            vals = _safe_iter(val)
            num_items = samples['set']
            if length is None or length > num_items + 2:
                vals = islice(vals, num_items)
            for i, v in enumerate(vals):
                add_child('<%s>' % i, v)

        d = getattr(val, '__dict__', None)
        if d:
            for k in sorted(islice(_safe_iter(d),
                                   samples['attributes']),
                            key=str):
                v = d[k]
                if isinstance(v, TracedFile):
                    continue
                add_child(str(k), v)
        else:
            for s in sorted(getattr(type(val), '__slots__', None) or ()):
                try:
                    attr = getattr(val, s)
                except AttributeError:
                    pass
                else:
                    add_child(str(s), attr)
        return result


def iteritems(obj):
    return getattr(obj, "iteritems", obj.items)()


def _safe_iter(val, f=lambda x: x):
    try:
        for x in f(val):
            yield x
    except:
        pass


def _sample_indices(length, max_length):
    if length <= max_length + 2:
        return range(length)
    else:
        return chain(range(max_length // 2),
                     range(length - max_length // 2,
                           length))


@try_register_repr('pandas', 'Series')
def _repr_series_one_line(x, helper):
    n = len(x)
    if n == 0:
        return repr(x)
    newlevel = helper.level - 1
    pieces = []
    maxparts = _repr_series_one_line.maxparts
    for i in _sample_indices(n, maxparts):
        try:
            k = x.index[i:i + 1].format(sparsify=False)[0]
        except TypeError:
            k = x.index[i:i + 1].format()[0]
        v = x.iloc[i]
        pieces.append('%s = %s' % (k, cheap_repr(v, newlevel)))
    if n > maxparts + 2:
        pieces.insert(maxparts // 2, '...')
    return '; '.join(pieces)


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


# noinspection PyUnresolvedReferences
builtins_dict = __builtins__
if not isinstance(builtins_dict, dict):
    builtins_dict = builtins_dict.__dict__


def is_obvious_builtin(node, value):
    # type: (ast.expr, Any) -> bool
    """
    Return True if this node looks like a builtin and it really is
    (i.e. hasn't been shadowed).
    """
    return ((isinstance(node, ast.Name) and
             node.id in builtins_dict and
             builtins_dict[node.id] is value) or
            isinstance(node, getattr(ast, 'NameConstant', ())))

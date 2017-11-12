from __future__ import print_function, division, absolute_import

from future import standard_library

standard_library.install_aliases()

import ast
import inspect
from collections import namedtuple
from copy import deepcopy
from functools import partial, update_wrapper
from itertools import takewhile
from typing import List, Dict, Any, Optional, NamedTuple, Tuple, Iterator, Callable, cast, Union
from types import FrameType, TracebackType, CodeType, FunctionType

try:
    from functools import lru_cache
except ImportError:
    from backports.functools_lru_cache import lru_cache
from littleutils import file_to_string

from birdseye.utils import of_type, safe_next, PY3, Type


class TracedFile(object):
    def __init__(self, tracer, source, filename):
        # type: (TreeTracerBase, str, str) -> None
        root = ast.parse(source, filename)  # type: ast.Module

        self.nodes = []  # type: List[ast.AST]

        def set_basic_node_attributes():
            self.nodes = []  # type: List[ast.AST]
            for node in ast.walk(root):  # type: ast.AST
                for child in ast.iter_child_nodes(node):
                    child.parent = node
                node.traced_file = self
                node._tree_index = len(self.nodes)
                self.nodes.append(node)

        set_basic_node_attributes()

        new_root = tracer.parse_extra(root, source, filename)
        if new_root is not None:
            root = new_root

        set_basic_node_attributes()

        new_root = deepcopy(root)
        new_root = _NodeVisitor().visit(new_root)

        self.code = compile(new_root, filename, "exec", dont_inherit=True)  # type: CodeType
        self.root = root
        self.tracer = tracer
        self.source = source
        self.filename = filename


class FrameInfo(object):
    def __init__(self):
        self.statement = None  # type: Optional[ast.stmt]
        self.expression_stack = []  # type: List[ast.expr]
        self.expression_values = {}  # type: Dict[ast.expr, Any]
        self.return_node = None  # type: Optional[ast.Return]
        self.comprehension_frames = {}  # type: Dict[ast.expr, FrameType]
        self.exc_value = None  # type: Optional[BaseException]


EnterCallInfo = NamedTuple('EnterCallInfo', [('call_node', Optional[ast.expr]),
                                             ('enter_node', ast.AST),
                                             ('caller_frame', FrameType),
                                             ('current_frame', FrameType)])
ExitCallInfo = NamedTuple('ExitCallInfo', [('call_node', Optional[ast.expr]),
                                           ('return_node', Optional[ast.Return]),
                                           ('caller_frame', FrameType),
                                           ('current_frame', FrameType),
                                           ('return_value', Any),
                                           ('exc_value', Optional[Exception]),
                                           ('exc_tb', Optional[TracebackType])])

ChangeValue = namedtuple('ChangeValue', 'value')


class TreeTracerBase(object):
    SPECIAL_COMPREHENSION_TYPES = (ast.DictComp, ast.SetComp)  # type: Tuple[Type[ast.expr], ...]
    if PY3:
        SPECIAL_COMPREHENSION_TYPES += (ast.ListComp,)

    def __init__(self):
        self.stack = {}  # type: Dict[FrameType, FrameInfo]

    @lru_cache()
    def compile(self, source, filename):
        # type: (str, str) -> TracedFile
        return TracedFile(self, source, filename)

    def exec_string(self, source, filename, globs=None, locs=None):
        # type: (str, str, dict, dict) -> None
        traced_file = self.compile(source, filename)
        globs = globs or {}
        locs = locs or {}
        globs = dict(globs, **self._trace_methods_dict(traced_file))
        exec (traced_file.code, globs, locs)

    def _trace_methods_dict(self, traced_file):
        # type: (TracedFile) -> Dict[str, Callable]
        return {f.__name__: partial(f, traced_file)
                for f in [
                    self._treetrace_hidden_with_stmt,
                    self._treetrace_hidden_before_expr,
                    self._treetrace_hidden_after_expr,
                ]}

    def __call__(self, func):
        # type: (FunctionType) -> FunctionType
        try:
            if inspect.iscoroutinefunction(func) or inspect.isasyncgenfunction(func):
                raise ValueError('You cannot trace async functions')
        except AttributeError:
            pass
        filename = inspect.getsourcefile(func)  # type: str
        source = file_to_string(filename)
        traced_file = self.compile(source, filename)
        func.__globals__.update(self._trace_methods_dict(traced_file))

        code_options = []  # type: List[CodeType]

        def find_code(root_code):
            # type: (CodeType) -> None
            for const in root_code.co_consts:  # type: CodeType
                if not inspect.iscode(const):
                    continue
                matches = (const.co_firstlineno == func.__code__.co_firstlineno and
                           const.co_name == func.__code__.co_name)
                if matches:
                    code_options.append(const)
                find_code(const)

        find_code(traced_file.code)
        if len(code_options) > 1:
            assert func.__code__.co_name == (lambda: 0).__code__.co_name
            raise ValueError("Failed to trace lambda. Convert the function to a def.")
        new_func_code = code_options[0]  # type: CodeType

        # http://stackoverflow.com/a/13503277/2482744
        # noinspection PyArgumentList
        new_func = FunctionType(new_func_code, func.__globals__, func.__name__, func.__defaults__, func.__closure__)
        update_wrapper(new_func, func)  # type: FunctionType
        if PY3:
            new_func.__kwdefaults__ = getattr(func, '__kwdefaults__', None)
        new_func.traced_file = traced_file
        return new_func

    def _treetrace_hidden_with_stmt(self, traced_file, _tree_index):
        # type: (TracedFile, int) -> _StmtContext
        node = traced_file.nodes[_tree_index]
        node = cast(ast.stmt, node)
        frame = inspect.currentframe().f_back  # type: FrameType
        return _StmtContext(self, node, frame)

    def _treetrace_hidden_before_expr(self, traced_file, _tree_index):
        # type: (TracedFile, int) -> ast.expr
        node = traced_file.nodes[_tree_index]
        node = cast(ast.expr, node)
        frame = inspect.currentframe().f_back  # type: FrameType

        frame_info = self.stack.get(frame)
        if frame_info is None:
            frame_info = FrameInfo()
            self.stack[frame] = frame_info
            owner_frame = frame
            while owner_frame.f_code.co_name in ('<listcomp>', '<dictcomp>', '<setcomp>'):
                owner_frame = owner_frame.f_back
            if owner_frame != frame:
                comprehension = safe_next(of_type(self.SPECIAL_COMPREHENSION_TYPES,
                                                  ancestors(node)))  # type: ast.expr
                self.stack[owner_frame].comprehension_frames[comprehension] = frame

        frame_info.expression_stack.append(node)

        self.before_expr(node, frame)
        return node

    def _treetrace_hidden_after_expr(self, _, node, value):
        # type: (TracedFile, ast.expr, Any) -> Any
        frame = inspect.currentframe().f_back  # type: FrameType
        self.stack[frame].expression_stack.pop()
        self.stack[frame].expression_values[node] = value
        result = self.after_expr(node, frame, value)
        if result is not None:
            assert isinstance(result, ChangeValue), "after_expr must return None or an instance of ChangeValue"
            value = result.value
        return value

    def _enter_call(self, enter_node, current_frame):
        # type: (ast.AST, FrameType) -> None
        caller_frame, call_node = self._get_caller_stuff(current_frame)
        self.stack[current_frame] = FrameInfo()
        self.enter_call(EnterCallInfo(call_node, enter_node, caller_frame, current_frame))

    def _get_caller_stuff(self, frame):
        # type: (FrameType) -> Tuple[FrameType, Optional[ast.expr]]
        caller_frame = frame.f_back
        call_node = None
        if caller_frame in self.stack:
            expression_stack = self.stack[caller_frame].expression_stack
            if expression_stack:
                call_node = expression_stack[-1]
        return caller_frame, call_node

    def before_expr(self, node, frame):
        # type: (ast.expr, FrameType) -> None
        pass

    def after_expr(self, node, frame, value):
        # type: (ast.expr, FrameType, Any) -> Optional[ChangeValue]
        pass

    def before_stmt(self, node, frame):
        # type: (ast.stmt, FrameType) -> None
        pass

    def after_stmt(self, node, frame, exc_value, exc_traceback):
        # type: (ast.stmt, FrameType, Exception, TracebackType) -> Optional[bool]
        pass

    def enter_call(self, enter_info):
        # type: (EnterCallInfo) -> None
        pass

    def exit_call(self, exit_info):
        # type: (ExitCallInfo) -> None
        pass

    def parse_extra(self, root, source, filename):
        # type: (ast.Module, str, str) -> Optional[ast.Module]
        pass

    def on_exception(self, node, frame, exc_value, exc_traceback):
        # type: (Union[ast.expr, ast.stmt], FrameType, Exception, TracebackType) -> None
        pass


class _NodeVisitor(ast.NodeTransformer):
    def generic_visit(self, node):
        # type: (ast.AST) -> ast.AST
        if isinstance(node, ast.expr) and not (hasattr(node, "ctx") and not isinstance(node.ctx, ast.Load)):
            return self.visit_expr(node)
        if isinstance(node, ast.stmt):
            if not (isinstance(node, ast.ImportFrom) and node.module == "__future__"):
                return self.visit_stmt(node)
        return super(_NodeVisitor, self).generic_visit(node)

    def visit_expr(self, node):
        # type: (ast.expr) -> ast.Call
        """
        each expression e gets wrapped like this:
            _after(_before(_tree_index), e)
        where
            _after is function that gives the resulting value
            _before is function that signals the beginning of evaluation of e
        """

        if isinstance(node, getattr(ast, 'Starred', ())):
            return super(_NodeVisitor, self).generic_visit(node)

        before_marker = _create_simple_marker_call(node, TreeTracerBase._treetrace_hidden_before_expr)
        ast.copy_location(before_marker, node)

        after_marker = ast.Call(
            func=ast.Name(id=TreeTracerBase._treetrace_hidden_after_expr.__name__,
                          ctx=ast.Load()),
            args=[
                before_marker,
                super(_NodeVisitor, self).generic_visit(node),
            ],
            keywords=[],
        )
        ast.copy_location(after_marker, node)
        ast.fix_missing_locations(after_marker)

        return after_marker

    def visit_stmt(self, node):
        # type: (ast.stmt) -> ast.With
        context_expr = _create_simple_marker_call(
            super(_NodeVisitor, self).generic_visit(node),
            TreeTracerBase._treetrace_hidden_with_stmt)

        if PY3:
            wrapped = ast.With(
                items=[ast.withitem(context_expr=context_expr)],
                body=[node],
            )
        else:
            wrapped = ast.With(
                context_expr=context_expr,
                body=[node],
            )
        ast.copy_location(wrapped, node)
        ast.fix_missing_locations(wrapped)
        return wrapped


class _StmtContext(object):
    __slots__ = ('tracer', 'node', 'frame')

    def __init__(self, tracer, node, frame):
        # type: (TreeTracerBase, ast.stmt, FrameType) -> None
        self.tracer = tracer
        self.node = node
        self.frame = frame

    def __enter__(self):
        tracer = self.tracer
        node = self.node
        frame = self.frame
        if isinstance(node.parent, (ast.FunctionDef, ast.Module)) and node is node.parent.body[0]:
            tracer._enter_call(node, frame)
        frame_info = tracer.stack[frame]
        frame_info.expression_stack = []
        frame_info.statement = node
        tracer.before_stmt(node, frame)

    def __exit__(self, exc_type, exc_val, exc_tb):
        # type: (Type[Exception], Exception, TracebackType) -> bool
        node = self.node
        tracer = self.tracer
        frame = self.frame
        frame_info = tracer.stack[frame]
        if exc_val and exc_val is not frame_info.exc_value:
            frame_info.exc_value = exc_val
            expression_stack = frame_info.expression_stack
            if expression_stack:
                while isinstance(expression_stack[-1], TreeTracerBase.SPECIAL_COMPREHENSION_TYPES):
                    inner_frame = frame_info.comprehension_frames[expression_stack[-1]]
                    expression_stack = tracer.stack[inner_frame].expression_stack
                exc_node = expression_stack[-1]
            else:
                exc_node = node  # type: ignore
            tracer.on_exception(exc_node, frame, exc_val, exc_tb)

        result = tracer.after_stmt(node, frame, exc_val, exc_tb)
        if isinstance(node, ast.Return):
            frame_info.return_node = node
        parent = node.parent  # type: ast.AST
        return_node = frame_info.return_node
        exiting = (isinstance(parent, (ast.FunctionDef, ast.Module)) and
                   (node is parent.body[-1] or
                    exc_val or
                    return_node))
        if exiting:
            caller_frame, call_node = tracer._get_caller_stuff(frame)
            return_value = None
            if return_node and return_node.value and not exc_val:
                return_value = frame_info.expression_values[return_node.value]
            tracer.exit_call(ExitCallInfo(call_node,
                                          return_node,
                                          caller_frame,
                                          frame,
                                          return_value,
                                          exc_val,
                                          exc_tb
                                          ))

            del tracer.stack[frame]
            for comprehension_frame in frame_info.comprehension_frames.values():
                del tracer.stack[comprehension_frame]
        return result


def _create_simple_marker_call(node, func):
    # type: (ast.AST, Callable) -> ast.Call
    return ast.Call(
        func=ast.Name(id=func.__name__,
                      ctx=ast.Load()),
        args=[ast.Num(node._tree_index)],
        keywords=[],
    )


def ancestors(node):
    # type: (ast.AST) -> Iterator[ast.AST]
    while True:
        try:
            node = node.parent
        except AttributeError:
            break
        yield node


def loops(node):
    # type: (ast.AST) -> Tuple[ast.AST, ...]
    result = []
    while True:
        try:
            parent = node.parent
        except AttributeError:
            break
        if isinstance(parent, (ast.FunctionDef, ast.ClassDef)):
            break

        is_containing_loop = (isinstance(parent, ast.For) and parent.iter is not node or
                              isinstance(parent, ast.While) and parent.test is not node)
        if is_containing_loop:
            result.append(parent)

        elif isinstance(parent, (ast.ListComp,
                                 ast.GeneratorExp,
                                 ast.DictComp,
                                 ast.SetComp)):
            if isinstance(parent, ast.DictComp):
                is_comprehension_element = node in (parent.key, parent.value)
            else:
                is_comprehension_element = node is parent.elt
            if is_comprehension_element:
                result.extend(reversed(parent.generators))

            if node in parent.generators:
                result.extend(reversed(list(takewhile(lambda n: n != node, parent.generators))))

        elif isinstance(parent, ast.comprehension) and node in parent.ifs:
            result.append(parent)

        node = parent

    result.reverse()
    return tuple(result)

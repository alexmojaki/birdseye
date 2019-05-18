"""
This module provides the generic functionality of tracing code by
modifying its AST. Eventually this will become a separate package.
This is similar to the standard library module bdb, while birdseye
itself would correspond to pdb.
Most of the work is in TreeTracerBase.
"""

from __future__ import print_function, division, absolute_import

from future import standard_library

standard_library.install_aliases()

import ast
import inspect
import sys
from collections import namedtuple, defaultdict
from copy import deepcopy
from functools import partial, update_wrapper, wraps
from itertools import takewhile
from typing import List, Dict, Any, Optional, NamedTuple, Tuple, Iterator, Callable, cast, Union
from types import FrameType, TracebackType, CodeType, FunctionType

from birdseye.utils import PY3, Type, is_lambda, lru_cache, read_source_file, is_ipython_cell, \
    is_future_import


class TracedFile(object):
    """
    An instance of this class corresponds to a single .py file.
    It contains some useful data in the following attributes:

    - filename: name of the source file
    - source: textual contents of the file
    - root: root of the original Abstract Syntax Tree (AST) of the source,
            where the nodes of this tree have an additional handy attribute:
            - parent: parent of the node, so this node is a child node of its parent
    - tracer: instance of TreeTracerBase
    - code: executable code object compiled from the modified AST
    """

    is_ipython_cell = False

    def __init__(self, tracer, source, filename, flags):
        # type: (TreeTracerBase, str, str, int) -> None
        # Here the source code is parsed, modified, and compiled
        self.root = compile(source, filename, 'exec', ast.PyCF_ONLY_AST | flags, dont_inherit=True)  # type: ast.Module

        self.nodes = []  # type: List[ast.AST]

        self.set_basic_node_attributes()

        new_root = tracer.parse_extra(self.root, source, filename)
        if new_root is not None:
            self.root = new_root

        self.set_basic_node_attributes()
        self.set_enter_call_nodes()

        new_root = deepcopy(self.root)
        new_root = _NodeVisitor().visit(new_root)

        self.code = compile(new_root, filename, "exec", dont_inherit=True, flags=flags)  # type: CodeType
        self.tracer = tracer
        self.source = source
        self.filename = filename

    def set_basic_node_attributes(self):
        self.nodes = []  # type: List[ast.AST]
        for node in ast.walk(self.root):  # type: ast.AST
            for child in ast.iter_child_nodes(node):
                child.parent = node
            node._tree_index = len(self.nodes)
            self.nodes.append(node)

        # Mark __future__ imports and anything before (i.e. module docstrings)
        # to be ignored by the AST transformer
        for i, stmt in enumerate(self.root.body):
            if is_future_import(stmt):
                for s in self.root.body[:i + 1]:
                    for node in ast.walk(s):
                        node._visit_ignore = True

    def set_enter_call_nodes(self):
        for node in self.nodes:
            if isinstance(node, (ast.Module, ast.FunctionDef)):
                for stmt in node.body:
                    if not is_future_import(stmt):
                        stmt._enter_call_node = True
                        break


class FrameInfo(object):
    """
    Contains extra data about an execution frame.
    Can be obtained from the stack attribute of a TreeTracerBase instance
    """
    def __init__(self):
        # Stack of statements currently being executed
        self.statement_stack = []  # type: List[ast.stmt]

        # Stack of expression nodes within the above statement that
        # the interpreter is planning on evaluating, or has just evaluated
        # in the case of the last element of the list. For example, given
        # the expression f(g(x)), the stack would be [f, g, x] before and just
        # after evaluating x, since function arguments are evaluated before the
        # actual function call.
        self.expression_stack = []  # type: List[ast.expr]

        # Mapping from the expression node to its most recent value
        # in the corresponding frame
        self.expression_values = {}  # type: Dict[ast.expr, Any]

        # Node where the frame has explicitly returned
        # There may be parent nodes such as enclosing loops that still need to finish executing
        self.return_node = None  # type: Optional[ast.Return]

        # Most recent exception raised in the frame
        self.exc_value = None  # type: Optional[BaseException]


# Some of the attributes of the classes below are unused for now and are
# intended for future use, possibly by other debuggers


# Argument of TreeTracerBase.enter_call
EnterCallInfo = NamedTuple('EnterCallInfo', [

    # Node  from where the call was made
    ('call_node', Optional[Union[ast.expr, ast.stmt]]),

    # Node where the call begins
    ('enter_node', ast.AST),

    # Frame from which the call was made
    ('caller_frame', FrameType),

    # Frame of the call
    ('current_frame', FrameType)])

# Argument of TreeTracerBase.exit_call
ExitCallInfo = NamedTuple('ExitCallInfo', [

    # Node  from where the call was made
    ('call_node', Optional[Union[ast.expr, ast.stmt]]),

    # Node where the call explicitly returned
    ('return_node', Optional[ast.Return]),

    # Frame from which the call was made
    ('caller_frame', FrameType),

    # Frame of the call
    ('current_frame', FrameType),

    # Node where the call explicitly returned
    ('return_value', Any),

    # Exception raised in the call causing it to end,
    # will propagate to the caller
    ('exc_value', Optional[Exception]),

    # Traceback corresponding to exc_value
    ('exc_tb', Optional[TracebackType])])

# see TreeTracerBase.after_expr
ChangeValue = namedtuple('ChangeValue', 'value')


class TreeTracerBase(object):
    """
    Create a subclass of this class with one or more of the 'hooks'
    (methods which are empty in this class) overridden to take a custom action
    in the given situation. Then decorate functions with an instance of this class
    to trace them.
    """

    def __init__(self):
        # Mapping from frames of execution being traced to FrameInfo objects
        # for extra metadata.
        self.stack = {}  # type: Dict[FrameType, FrameInfo]
        self.main_to_secondary_frames = defaultdict(list)
        self.secondary_to_main_frames = {}

    @lru_cache()
    def compile(self, source, filename, flags=0):
        # type: (str, str, int) -> TracedFile
        return TracedFile(self, source, filename, flags)

    def _trace_methods_dict(self, traced_file):
        # type: (TracedFile) -> Dict[str, Callable]
        return {f.__name__: partial(f, traced_file)
                for f in [
                    self._treetrace_hidden_with_stmt,
                    self._treetrace_hidden_before_expr,
                    self._treetrace_hidden_after_expr,
                ]}

    def trace_function(self, func):
        # type: (FunctionType) -> FunctionType
        """
        Returns a version of the passed function with the AST modified to
        trigger the tracing hooks.
        """
        if not isinstance(func, FunctionType):
            raise ValueError('You can only trace user-defined functions. '
                             'The birdseye decorator must be applied first, '
                             'at the bottom of the list.')

        try:
            if inspect.iscoroutinefunction(func) or inspect.isasyncgenfunction(func):
                raise ValueError('You cannot trace async functions')
        except AttributeError:
            pass

        if is_lambda(func):
            raise ValueError('You cannot trace lambdas')

        filename = inspect.getsourcefile(func)  # type: str

        if is_ipython_cell(filename):
            # noinspection PyPackageRequirements
            from IPython import get_ipython
            import linecache

            flags = get_ipython().compile.flags
            source = ''.join(linecache.cache[filename][2])
        else:
            source = read_source_file(filename)
            flags = 0

        # We compile the entire file instead of just the function source
        # because it can contain context which affects the function code,
        # e.g. enclosing functions and classes or __future__ imports
        traced_file = self.compile(source, filename, flags)

        if func.__dict__:
            raise ValueError('The birdseye decorator must be applied first, '
                             'at the bottom of the list.')

        # Then we have to recursively search through the newly compiled
        # code to find the code we actually want corresponding to this function
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
            # Currently lambdas aren't allowed anyway, but should be in the future
            assert is_lambda(func)
            raise ValueError("Failed to trace lambda. Convert the function to a def.")
        new_func_code = code_options[0]  # type: CodeType

        # Give the new function access to the hooks
        # We have to use the original __globals__ and not a copy
        # because it's the actual module namespace that may get updated by other code
        func.__globals__.update(self._trace_methods_dict(traced_file))

        # http://stackoverflow.com/a/13503277/2482744
        # noinspection PyArgumentList
        new_func = FunctionType(new_func_code, func.__globals__, func.__name__, func.__defaults__, func.__closure__)
        update_wrapper(new_func, func)  # type: FunctionType
        if PY3:
            new_func.__kwdefaults__ = getattr(func, '__kwdefaults__', None)
        new_func.traced_file = traced_file
        return new_func

    def __call__(self, func=None, optional=False):
        # type: (FunctionType, bool) -> Callable
        """
        Decorator which returns a (possibly optionally) traced function.
        This decorator can be called with or without arguments.
        Typically it is called without arguments, in which case it returns
        a traced function.
        If optional=True, it returns a function similar to the original
        but with an additional optional parameter trace_call, default False.
        If trace_call is false, the underlying untraced function is used.
        If true, the traced version is used.
        """
        if inspect.isclass(func):
            raise TypeError('Decorating classes is no longer supported')

        if func:
            # The decorator has been called without arguments/parentheses,
            # e.g.
            # @eye
            # def ...
            return self.trace_function(func)

        # The decorator has been called with arguments/parentheses,
        # e.g.
        # @eye(...)
        # def ...
        # We must return a decorator

        if not optional:
            return self.trace_function

        def decorator(actual_func):

            traced = self.trace_function(actual_func)

            @wraps(actual_func)
            def wrapper(*args, **kwargs):
                trace_call = kwargs.pop('trace_call', False)
                if trace_call:
                    f = traced
                else:
                    f = actual_func
                return f(*args, **kwargs)

            return wrapper

        return decorator

    def _main_frame(self, node):
        # type: (ast.AST) -> Optional[FrameType]
        frame = sys._getframe(2)
        result = self.secondary_to_main_frames.get(frame)
        if result:
            return result

        original_frame = frame

        while frame.f_code.co_name in ('<listcomp>', '<dictcomp>', '<setcomp>'):
            frame = frame.f_back

        for node in ancestors(node):
            if isinstance(node, (ast.FunctionDef, ast.Lambda)):
                break

            if isinstance(node, ast.ClassDef):
                frame = frame.f_back

        if frame.f_code.co_name in ('<lambda>', '<genexpr>'):
            return None

        self.secondary_to_main_frames[original_frame] = frame
        self.main_to_secondary_frames[frame].append(original_frame)
        return frame

    def _treetrace_hidden_with_stmt(self, traced_file, _tree_index):
        # type: (TracedFile, int) -> _StmtContext
        """
        Called directly from the modified code.
        Every statement in the original code becomes:

        with _treetrace_hidden_with_stmt(...):
            <statement>
        """
        node = traced_file.nodes[_tree_index]
        node = cast(ast.stmt, node)
        frame = self._main_frame(node)
        return _StmtContext(self, node, frame)

    def _treetrace_hidden_before_expr(self, traced_file, _tree_index):
        # type: (TracedFile, int) -> ast.expr
        """
        Called directly from the modified code before an expression is
        evaluated.
        """
        node = traced_file.nodes[_tree_index]
        node = cast(ast.expr, node)
        frame = self._main_frame(node)
        if frame is None:
            return node

        frame_info = self.stack[frame]
        frame_info.expression_stack.append(node)

        self.before_expr(node, frame)
        return node

    def _treetrace_hidden_after_expr(self, _, node, value):
        # type: (TracedFile, ast.expr, Any) -> Any
        """
        Called directly from the modified code after an expression is
        evaluated.
        """
        frame = self._main_frame(node)
        if frame is None:
            return value

        result = self._after_expr(node, frame, value, None, None)
        if result is not None:
            assert isinstance(result, ChangeValue), "after_expr must return None or an instance of ChangeValue"
            value = result.value
        return value

    def _after_expr(self, node, frame, value, exc_value, exc_tb):
        frame_info = self.stack[frame]
        frame_info.expression_stack.pop()
        frame_info.expression_values[node] = value
        return self.after_expr(node, frame, value, exc_value, exc_tb)

    def _enter_call(self, enter_node, current_frame):
        # type: (ast.AST, FrameType) -> None
        caller_frame, call_node = self._get_caller_stuff(current_frame)
        self.stack[current_frame] = FrameInfo()
        self.enter_call(EnterCallInfo(call_node, enter_node, caller_frame, current_frame))

    def _get_caller_stuff(self, frame):
        # type: (FrameType) -> Tuple[FrameType, Optional[Union[ast.expr, ast.stmt]]]
        caller_frame = frame.f_back
        call_node = None
        main_frame = self.secondary_to_main_frames.get(caller_frame)
        if main_frame:
            caller_frame = main_frame
            frame_info = self.stack[caller_frame]
            expression_stack = frame_info.expression_stack
            if expression_stack:
                call_node = expression_stack[-1]
            else:
                call_node = frame_info.statement_stack[-1]  # type: ignore
        return caller_frame, call_node

    # The methods below are hooks meant to be overridden in subclasses to take custom actions

    def before_expr(self, node, frame):
        # type: (ast.expr, FrameType) -> None
        """
        Called right before the expression corresponding to `node` is evaluated
        within `frame`.
        """

    def after_expr(self, node, frame, value, exc_value, exc_tb):
        # type: (ast.expr, FrameType, Any, Optional[BaseException], Optional[TracebackType]) -> Optional[ChangeValue]
        """
        Called right after the expression corresponding to `node` is evaluated
        within `frame`. `value` is the value of the expression, if it succeeded.
        If the evaluation raised an exception, exc_value will be the exception object
        and exc_tb the traceback.

        Return `ChangeValue(x)` to change the value of the expression as
        seen by the rest of the program from `value` to `x`.
        """

    def before_stmt(self, node, frame):
        # type: (ast.stmt, FrameType) -> None
        """
        Called right before the statement corresponding to `node` is executed
        within `frame`.
        """

    def after_stmt(self, node, frame, exc_value, exc_traceback, exc_node):
        # type: (ast.stmt, FrameType, Optional[BaseException], Optional[TracebackType], Optional[ast.AST]) -> Optional[bool]
        """
        Called right after the statement corresponding to `node` is executed
        within `frame`.
        If the statement raised an exception, exc_value will be the exception object,
        exc_tb the traceback, and exc_node the node where the exception was raised
        (either this statement or an expression within).

        Returning True will suppress any exception raised (as with __exit__ in general).
        """

    def enter_call(self, enter_info):
        # type: (EnterCallInfo) -> None
        """
        Called before a function call begins executing. For typical `def` functions,
        this is called before the `before_stmt` for to the first statement in the function.
        """

    def exit_call(self, exit_info):
        # type: (ExitCallInfo) -> None
        """
        Called after a function call finishes executing. For typical `def` functions,
        this is called after the `after_stmt` for to the last statement to execute.
        """

    def parse_extra(self, root, source, filename):
        # type: (ast.Module, str, str) -> Optional[ast.Module]
        """
        Called before the AST (root) is modified to let subclasses make additional changes first.
        """


class _NodeVisitor(ast.NodeTransformer):
    """
    This does the AST modifications that call the hooks.
    """

    def generic_visit(self, node):
        # type: (ast.AST) -> ast.AST
        if not getattr(node, '_visit_ignore', False):
            if (isinstance(node, ast.expr) and
                    not (hasattr(node, "ctx") and not isinstance(node.ctx, ast.Load)) and
                    not isinstance(node, getattr(ast, 'Starred', ()))):
                return self.visit_expr(node)
            if isinstance(node, ast.stmt):
                return self.visit_stmt(node)
        return super(_NodeVisitor, self).generic_visit(node)

    def visit_expr(self, node):
        # type: (ast.expr) -> ast.Call
        """
        each expression e gets wrapped like this:
            _treetrace_hidden_after_expr(_treetrace_hidden_before_expr(_tree_index), e)

        where the _treetrace_* functions are the corresponding methods with the
        TreeTracerBase and traced_file arguments already filled in (see _trace_methods_dict)
        """

        before_marker = self._create_simple_marker_call(node, TreeTracerBase._treetrace_hidden_before_expr)
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
        """
        Every statement in the original code becomes:

        with _treetrace_hidden_with_stmt(_tree_index):
            <statement>

        where the _treetrace_hidden_with_stmt function is the the corresponding method with the
        TreeTracerBase and traced_file arguments already filled in (see _trace_methods_dict)
        """
        context_expr = self._create_simple_marker_call(
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

    @staticmethod
    def _create_simple_marker_call(node, func):
        # type: (ast.AST, Callable) -> ast.Call
        """
        Returns a Call node representing `func(node._tree_index)`
        where node._tree_index is a numerical literal which allows the node object
        to be retrieved later through the nodes attribute of a TracedFile.
        """
        return ast.Call(
            func=ast.Name(id=func.__name__,
                          ctx=ast.Load()),
            args=[ast.Num(node._tree_index)],
            keywords=[],
        )


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
        if getattr(node, '_enter_call_node', False):
            tracer._enter_call(node, frame)
        frame_info = tracer.stack[frame]
        frame_info.expression_stack = []
        frame_info.statement_stack.append(node)
        tracer.before_stmt(node, frame)

    def __exit__(self, exc_type, exc_val, exc_tb):
        # type: (Type[Exception], Exception, TracebackType) -> bool
        node = self.node
        tracer = self.tracer
        frame = self.frame
        frame_info = tracer.stack[frame]

        frame_info.statement_stack.pop()

        exc_node = None  # type: Optional[Union[ast.expr, ast.stmt]]
        if exc_val and exc_val is not frame_info.exc_value:
            exc_node = node
            frame_info.exc_value = exc_val

            # Call the after_expr hook if the exception was raised by an expression
            expression_stack = frame_info.expression_stack
            if expression_stack:
                exc_node = expression_stack[-1]
                tracer._after_expr(exc_node, frame, None, exc_val, exc_tb)

        result = tracer.after_stmt(node, frame, exc_val, exc_tb, exc_node)

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
            for secondary_frame in self.tracer.main_to_secondary_frames.pop(frame):
                del self.tracer.secondary_to_main_frames[secondary_frame]

        return result


def ancestors(node):
    # type: (ast.AST) -> Iterator[ast.AST]
    while True:
        try:
            node = node.parent
        except AttributeError:
            break
        yield node


Loop = Union[ast.For, ast.While, ast.comprehension]


def loops(node):
    # type: (ast.AST) -> Tuple[Loop, ...]
    """
    Return all the 'enclosing loops' of a node, up to the innermost class or
    function definition. This also includes the 'for in' clauses in list/dict/set/generator
    comprehensions. So for example, in this code:

      for x in ...:
          def foo():
              while True:
                  print([z for y in ...])

    The loops enclosing the node 'z' are 'while True' and 'for y in ...', in that order.
    """
    result = []
    while True:
        try:
            parent = node.parent
        except AttributeError:
            break
        if isinstance(parent, ast.FunctionDef):
            break

        is_containing_loop = (((isinstance(parent, ast.For) and parent.iter is not node or
                                isinstance(parent, ast.While))
                               and node not in parent.orelse) or
                              (isinstance(parent, ast.comprehension) and node in parent.ifs))
        if is_containing_loop:
            result.append(parent)

        elif isinstance(parent, (ast.ListComp,
                                 ast.GeneratorExp,
                                 ast.DictComp,
                                 ast.SetComp)):
            generators = parent.generators
            if node in generators:
                generators = list(takewhile(lambda n: n != node, generators))
            result.extend(reversed(generators))

        node = parent

    result.reverse()
    return tuple(result)

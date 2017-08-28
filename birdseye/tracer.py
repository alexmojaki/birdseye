import ast
import functools
import inspect
from collections import namedtuple
from copy import deepcopy
from functools import partial
from itertools import takewhile

from littleutils import file_to_string

from birdseye.utils import of_type, safe_next


class TracedFile(object):
    def __init__(self, tracer, source, filename):
        root = ast.parse(source, filename)

        def set_basic_node_attributes():
            self.nodes = []
            for node in ast.walk(root):
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

        self.code = compile(new_root, filename, "exec")
        self.root = root
        self.tracer = tracer
        self.source = source
        self.filename = filename


class FrameInfo(object):
    def __init__(self):
        self.statement = None
        self.expression_stack = []
        self.expression_values = {}
        self.return_node = None
        self.comprehension_frames = {}


EnterCallInfo = namedtuple('EnterCallInfo', 'call_node enter_node caller_frame current_frame')
ExitCallInfo = namedtuple('ExitCallInfo', 'call_node return_node caller_frame current_frame '
                                          'return_value exc_value exc_tb')


class TreeTracerBase(object):
    SPECIAL_COMPREHENSION_TYPES = (ast.ListComp, ast.DictComp, ast.SetComp)

    def __init__(self):
        self.stack = {}

    @functools.lru_cache()
    def compile(self, source, filename):
        return TracedFile(self, source, filename)

    def exec_string(self, source, filename, globs=None, locs=None):
        traced_file = self.compile(source, filename)
        globs = globs or {}
        locs = locs or {}
        globs = dict(globs, **self._trace_methods_dict(traced_file))
        exec(traced_file.code, globals=globs, locals=locs)

    def _trace_methods_dict(self, traced_file):
        return {f.__name__: partial(f, traced_file)
                for f in [
                    self._treetrace_hidden_with_stmt,
                    self._treetrace_hidden_before_expr,
                    self._treetrace_hidden_after_expr,
                ]}

    def __call__(self, func):
        filename = inspect.getsourcefile(func)
        source = file_to_string(filename)
        traced_file = self.compile(source, filename)
        func.__globals__.update(self._trace_methods_dict(traced_file))

        code_options = []

        def find_code(root_code):
            for const in root_code.co_consts:
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
        new_func_code = code_options[0]

        # http://stackoverflow.com/a/13503277/2482744
        # TODO python 2 methods
        new_func = type(func)(new_func_code, func.__globals__, func.__name__, func.__defaults__, func.__closure__)
        new_func = functools.update_wrapper(new_func, func)
        new_func.__kwdefaults__ = func.__kwdefaults__
        new_func.traced_file = traced_file
        return new_func

    def _treetrace_hidden_with_stmt(self, traced_file, _tree_index):
        node = traced_file.nodes[_tree_index]
        frame = inspect.currentframe().f_back
        return _StmtContext(self, node, frame)

    def _treetrace_hidden_before_expr(self, traced_file, _tree_index):
        node = traced_file.nodes[_tree_index]
        frame = inspect.currentframe().f_back

        frame_info = self.stack.get(frame)
        if frame_info is None:
            frame_info = FrameInfo()
            self.stack[frame] = frame_info
            owner_frame = frame
            while owner_frame.f_code.co_name in ('<listcomp>', '<dictcomp>', '<setcomp>'):
                owner_frame = owner_frame.f_back
            if owner_frame != frame:
                comprehension = safe_next(of_type(self.SPECIAL_COMPREHENSION_TYPES,
                                                  ancestors(node)))
                self.stack[owner_frame].comprehension_frames[comprehension] = frame

        frame_info.expression_stack.append(node)

        self.before_expr(node, frame)
        return node

    def _treetrace_hidden_after_expr(self, _, node, value):
        if node is None:
            return value
        frame = inspect.currentframe().f_back
        self.stack[frame].expression_stack.pop()
        self.stack[frame].expression_values[node] = value
        result = self.after_expr(node, frame, value)
        if result is not None:
            assert isinstance(result, self.ChangeValue), "after_expr must return None or an instance of ChangeValue"
            value = result.value
        return value

    def _enter_call(self, enter_node, current_frame):
        caller_frame, call_node = self._get_caller_stuff(current_frame)
        self.stack[current_frame] = FrameInfo()
        self.enter_call(EnterCallInfo(call_node, enter_node, caller_frame, current_frame))

    def _get_caller_stuff(self, frame):
        caller_frame = frame.f_back
        call_node = None
        if caller_frame in self.stack:
            expression_stack = self.stack[caller_frame].expression_stack
            if expression_stack:
                call_node = expression_stack[-1]
        return caller_frame, call_node

    def before_expr(self, node, frame):
        pass

    def after_expr(self, node, frame, value):
        pass

    def before_stmt(self, node, frame):
        pass

    def after_stmt(self, node, frame, exc_value, exc_traceback):
        pass

    def enter_call(self, enter_info):
        pass

    def exit_call(self, exit_info):
        pass

    def parse_extra(self, root, source, filename):
        pass

    ChangeValue = namedtuple('ChangeValue', 'value')


class _NodeVisitor(ast.NodeTransformer):
    def generic_visit(self, node):
        if isinstance(node, ast.expr) and not (hasattr(node, "ctx") and not isinstance(node.ctx, ast.Load)):
            return self.visit_expr(node)
        if isinstance(node, ast.stmt) and not (isinstance(node, ast.ImportFrom) and node.module == "__future__"):
            return self.visit_stmt(node)
        return super().generic_visit(node)

    def visit_expr(self, node):
        """
        each expression e gets wrapped like this:
            _after(_before(_tree_index), e)
        where
            _after is function that gives the resulting value
            _before is function that signals the beginning of evaluation of e
        """

        if isinstance(node, ast.Starred):
            return super().generic_visit(node)

        before_marker = _create_simple_marker_call(node, TreeTracerBase._treetrace_hidden_before_expr)
        ast.copy_location(before_marker, node)

        after_marker = ast.Call(
            func=ast.Name(id=TreeTracerBase._treetrace_hidden_after_expr.__name__,
                          ctx=ast.Load()),
            args=[
                before_marker,
                super().generic_visit(node),
            ],
            keywords=[],
        )
        ast.copy_location(after_marker, node)
        ast.fix_missing_locations(after_marker)

        return after_marker

    def visit_stmt(self, node):
        wrapped = ast.With(
            items=[ast.withitem(
                context_expr=_create_simple_marker_call(super().generic_visit(node),
                                                        TreeTracerBase._treetrace_hidden_with_stmt))],
            body=[node],
        )
        ast.copy_location(wrapped, node)
        ast.fix_missing_locations(wrapped)
        return wrapped


class _StmtContext:
    __slots__ = ('tracer', 'node', 'frame')

    def __init__(self, tracer, node, frame):
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
        node = self.node
        tracer = self.tracer
        frame = self.frame
        result = tracer.after_stmt(node, frame, exc_val, exc_tb)
        frame_info = tracer.stack[frame]
        if isinstance(node, ast.Return):
            frame_info.return_node = node
        parent = node.parent
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
    """
    :type func: FunctionType
    """
    return ast.Call(
        func=ast.Name(id=func.__name__,
                      ctx=ast.Load()),
        args=[ast.Num(node._tree_index)],
        keywords=[],
    )


def ancestors(node):
    while True:
        try:
            node = node.parent
        except AttributeError:
            break
        yield node


def loops(node):
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
                result.extend(reversed(list(takewhile(node.__ne__, parent.generators))))

        elif isinstance(parent, ast.comprehension) and node in parent.ifs:
            result.append(parent)

        node = parent

    result.reverse()
    return tuple(result)

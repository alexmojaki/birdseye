import ast
import html
import inspect
import json
import os
import traceback
from collections import defaultdict, Sequence, Set, Mapping, deque, namedtuple
from datetime import datetime
from functools import partial
from itertools import chain, islice
from threading import Lock

from asttokens import ASTTokens

from birdseye.app import db, Function, Call
from birdseye.cheap_repr import cheap_repr
from birdseye.tracer import TreeTracerBase, loops, TracedFile
from birdseye.utils import safe_qualname, correct_type, exception_string

CodeInfo = namedtuple('CodeInfo', 'db_func traced_file')


class BirdsEye(TreeTracerBase):
    def __init__(self):
        super().__init__()
        self._code_infos = {}

    def parse_extra(self, root, source, filename):
        for node in ast.walk(root):
            node._loops = loops(node)

    def compile(self, source, filename):
        traced_file = super(BirdsEye, self).compile(source, filename)
        traced_file.tokens = ASTTokens(source, tree=traced_file.root)
        return traced_file

    def before_stmt(self, node, frame):
        if frame.f_code not in self._code_infos:
            return
        if isinstance(node.parent, (ast.For, ast.While)) and node is node.parent.body[0]:
            iteration = self.stack[frame].iteration
            for i, loop_node in enumerate(node._loops):
                loop = iteration.loops[loop_node._tree_index]
                if i == len(node._loops) - 1:
                    loop.append(Iteration())
                else:
                    iteration = loop.last()

    def after_expr(self, node, frame, value):
        if frame.f_code not in self._code_infos:
            return
        if is_obvious_builtin(node, self.stack[frame]):
            return

        self._set_node_value(
            node, frame,
            expand(value, level=max(1, 3 - len(node._loops))))

    def _set_node_value(self, node, frame, value):
        iteration = self.stack[frame].iteration
        for i, loop_node in enumerate(node._loops):
            loop = iteration.loops[loop_node._tree_index]
            iteration = loop.last()
        iteration.vals[node._tree_index] = value

    def after_stmt(self, node, frame, exc_value, exc_traceback):
        if frame.f_code not in self._code_infos:
            return
        expression_stack = self.stack[frame].expression_stack
        if expression_stack:
            self._set_node_value(
                expression_stack[-1], frame,
                [exception_string(exc_value), -1])

    def enter_call(self, enter_info):
        frame = enter_info.current_frame
        if frame.f_code not in self._code_infos:
            return
        frame_info = self.stack[frame]
        frame_info.start_time = datetime.now()
        frame_info.iteration = Iteration()
        arg_info = inspect.getargvalues(frame)
        arg_names = chain(arg_info[0], arg_info[1:3])
        f_locals = arg_info[3].copy()
        arguments = [(name, f_locals.pop(name)) for name in arg_names if name] + list(f_locals.items())
        frame_info.arguments = json.dumps([[k, cheap_repr(v)] for k, v in arguments])

    def exit_call(self, exit_info):
        frame = exit_info.current_frame
        if frame.f_code not in self._code_infos:
            return
        frame_info = self.stack[frame]
        top_iteration = frame_info.iteration

        loop_iterations = top_iteration.extract_iterations()['loops']

        expr_values = _deep_dict()

        def extract_values(iteration, path):
            for k, v in iteration.vals.items():
                full_path = (k,) + path
                d = expr_values
                for path_k in full_path[:-1]:
                    d = d[path_k]
                d[full_path[-1]] = v

            for loop in iteration.loops.values():
                for i, iteration in enumerate(loop):
                    extract_values(iteration, path + (i,))

        extract_values(top_iteration, ())

        db_func = self._code_infos[frame.f_code].db_func
        exc = exit_info.exc_value
        if exc:
            traceback_str = ''.join(traceback.format_exception(type(exc), exc, exit_info.exc_tb))
            exception = exception_string(exc)
        else:
            traceback_str = exception = None

        call = Call(function=db_func,
                    arguments=frame_info.arguments,
                    return_value=cheap_repr(exit_info.return_value),
                    exception=exception,
                    traceback=traceback_str,
                    data=json.dumps(dict(
                        expr_values=expr_values,
                        loop_iterations=loop_iterations,
                        type_names=type_registry.names(),
                        num_special_types=type_registry.num_special_types,
                    )),
                    start_time=frame_info.start_time)
        db.session.add(call)
        db.session.commit()

    def __call__(self, func):
        new_func = super(BirdsEye, self).__call__(func)
        code_info = self._code_infos.get(new_func.__code__)
        if code_info:
            return new_func
        lines, start_lineno = inspect.getsourcelines(func)
        end_lineno = start_lineno + len(lines)
        name = safe_qualname(func)
        filename = os.path.abspath(inspect.getsourcefile(func))

        traced_file = new_func.traced_file
        traced_file.root._depth = 0
        for node in ast.walk(traced_file.root):
            for child in ast.iter_child_nodes(node):
                child._depth = node._depth + 1

        positions = []
        node_loops = {}
        for node in traced_file.nodes:
            if isinstance(node, ast.expr):
                node_type = 'expr'
                if (isinstance(node, (ast.Num, ast.Str)) or
                        isinstance(getattr(node, 'ctx', None),
                                   (ast.Store, ast.Del))):
                    continue
            elif isinstance(node, (ast.While, ast.For)):
                node_type = 'loop'
            else:
                continue
            assert isinstance(node, ast.AST)
            if not start_lineno <= node.lineno <= end_lineno:
                continue
            if (isinstance(node, ast.UnaryOp) and
                    isinstance(node.op, (ast.UAdd, ast.USub)) and
                    isinstance(node.operand, ast.Num)):
                continue
            start, end = traced_file.tokens.get_text_range(node)
            if start == end == 0:
                continue
            positions.append((start, 1, node._depth,
                              '<span data-index="%s" data-type="%s">' % (node._tree_index, node_type)))
            positions.append((end, 0, node._depth, '</span>'))
            if node._loops:
                node_loops[node._tree_index] = [n._tree_index for n in node._loops]
        positions.append((len(traced_file.source), None, None, ''))
        positions.sort()

        html_body = []
        start = 0
        for pos, _, _, part in positions:
            html_body.append(html.escape(traced_file.source[start:pos]))
            html_body.append(part)
            start = pos
        html_body = ''.join(html_body)
        html_body = '\n'.join(html_body.split('\n')[start_lineno - 1:end_lineno - 1])

        db_args = dict(file=filename,
                       name=name,
                       html_body=html_body,
                       lineno=start_lineno,
                       data=json.dumps(
                           dict(
                               node_loops=node_loops,
                           ),
                           sort_keys=True,
                       ))
        db_func = Function.query.filter_by(**db_args).one_or_none()
        if not db_func:
            db_func = Function(**db_args)
            db.session.add(db_func)
            db.session.commit()
        self._code_infos[new_func.__code__] = CodeInfo(db_func, traced_file)

        return new_func


def _deep_dict():
    return defaultdict(_deep_dict)


class IterationList(object):
    side_len = 3

    def __init__(self):
        self.start = []
        self.end = deque(maxlen=self.side_len)
        self.length = 0

    def append(self, x):
        if self.length < self.side_len:
            self.start.append(x)
        else:
            self.end.append(x)
        x.index = self.length
        self.length += 1

    def __iter__(self):
        return chain(self.start, self.end)

    def last(self):
        if self.end:
            return self.end[-1]
        else:
            return self.start[-1]


class Iteration(object):
    def __init__(self):
        self.vals = {}
        self.loops = defaultdict(IterationList)
        self.index = None

    def extract_iterations(self):
        return {
            'index': self.index,
            'loops': {
                k: [it.extract_iterations() for it in v]
                for k, v in self.loops.items()
            }
        }


class TypeRegistry(object):
    def __init__(self):
        self.lock = Lock()
        self.data = defaultdict(lambda: len(self.data))
        basic_types = [type(None), bool, int, float, complex]  # TODO long, unicode
        special_types = basic_types + [list, dict, tuple, set, frozenset, str, bytes]
        self.num_basic_types = len(basic_types)
        self.num_special_types = len(special_types)
        for t in special_types:
            _ = self.data[t]

    def __getitem__(self, item):
        t = correct_type(item)
        with self.lock:
            return self.data[t]

    def names(self):
        rev = dict((v, k) for k, v in self.data.items())
        return [safe_qualname(rev[i]) for i in range(len(rev))]


type_registry = TypeRegistry()


def expand(val, level=3):
    result = []
    type_index = type_registry[val]
    result += [cheap_repr(val), type_index]
    if type_index < type_registry.num_basic_types or level == 0:
        return result
    exp = partial(expand, level=level - 1)

    # noinspection PyBroadException
    try:
        length = len(val)
    except:
        pass
    else:
        result += ['len() = %s' % length]

    if isinstance(val, (str, bytes, range)):  # TODO unicode, xrange
        return result
    if isinstance(val, Sequence):
        if len(val) <= 8:
            indices = range(len(val))
        else:
            indices = chain(range(3), range(len(val) - 3, len(val)))
        for i in indices:
            result += [(str(i), exp(val[i]))]
    elif isinstance(val, Mapping):
        for k, v in islice(val.items(), 10):  # TODO iteritems
            result += [(cheap_repr(k), exp(v))]
    elif isinstance(val, Set):
        for i, v in enumerate(islice(val, 6)):
            result += [('<%s>' % i, exp(v))]

    d = getattr(val, '__dict__', None)
    if d:
        for k, v in islice(d.items(), 50):  # TODO iteritems
            if isinstance(v, TracedFile):
                continue
            result += [(str(k), exp(v))]
    else:
        slots = getattr(val, '__slots__', None)
        if slots:
            for s in slots:
                try:
                    attr = getattr(val, s)
                except AttributeError:
                    pass
                else:
                    result += [(str(s), exp(attr))]
    return result


def is_obvious_builtin(node, frame_info):
    try:
        value = frame_info.expression_values[node]
        # noinspection PyUnresolvedReferences
        is_top_level_builtin = ((isinstance(node, ast.Name) and
                                 node.id in __builtins__ and
                                 __builtins__[node.id] is value) or
                                isinstance(node, ast.NameConstant))
        if is_top_level_builtin:
            return True
            # if not isinstance(node, ast.Attribute):
            #     return False
            # name = node.attr
            # if name != value.__name__:
            #     return False
            # if value.__self__ is not frame_info.expression_values[node.value]:
            #     return False
            # TODO complete for methods
    except AttributeError:
        # return False
        raise

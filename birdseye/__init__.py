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
from uuid import uuid4

from asttokens import ASTTokens
from littleutils import group_by_key_func

from birdseye.cheap_repr import cheap_repr
from birdseye.db import Function, Call, session, db_consumer
from birdseye.tracer import TreeTracerBase, TracedFile
from birdseye import tracer
from birdseye.utils import safe_qualname, correct_type, exception_string, dummy_namespace

CodeInfo = namedtuple('CodeInfo', 'db_func traced_file')


class BirdsEye(TreeTracerBase):
    def __init__(self):
        super().__init__()
        self._code_infos = {}

    def parse_extra(self, root, source, filename):
        for node in ast.walk(root):
            node._loops = tracer.loops(node)
            if isinstance(node, ast.expr):
                node._is_interesting_expression = is_interesting_expression(node)

    def compile(self, source, filename):
        traced_file = super(BirdsEye, self).compile(source, filename)
        traced_file.tokens = ASTTokens(source, tree=traced_file.root)
        return traced_file

    def before_stmt(self, node, frame):
        if frame.f_code not in self._code_infos:
            return
        if isinstance(node.parent, (ast.For, ast.While)) and node is node.parent.body[0]:
            self._add_iteration(node._loops, frame)
        self._set_node_value(node, frame, True)

    def _add_iteration(self, loops, frame):
        iteration = self.stack[frame].iteration
        for i, loop_node in enumerate(loops):
            loop = iteration.loops[loop_node._tree_index]
            if i == len(loops) - 1:
                loop.append(Iteration())
            else:
                iteration = loop.last()

    def before_expr(self, node, frame):
        self.stack[frame].inner_call = None

    def after_expr(self, node, frame, value):
        if node._is_interesting_expression:
            original_frame = frame
            while frame.f_code.co_name in ('<listcomp>',
                                           '<dictcomp>',
                                           '<setcomp>'):
                frame = frame.f_back

            if frame.f_code not in self._code_infos:
                return

            if is_obvious_builtin(node, self.stack[original_frame]):
                return

            frame_info = self.stack[frame]
            expanded_value = expand(value, level=max(1, 3 - len(node._loops)))
            if frame_info.inner_call:
                expanded_value.insert(2, {'inner_call': frame_info.inner_call})
                frame_info.inner_call = None
            self._set_node_value(node, frame, expanded_value)

        is_special_comprehension_iter = (isinstance(node.parent, ast.comprehension) and
                                         node is node.parent.iter and
                                         not isinstance(node.parent.parent, ast.GeneratorExp))
        if not is_special_comprehension_iter:
            return

        self._set_node_value(node.parent, frame, True)

        def comprehension_iter_proxy():
            loops = node._loops + (node.parent,)
            for item in value:
                self._add_iteration(loops, frame)
                yield item

        return self.ChangeValue(comprehension_iter_proxy())

    def _set_node_value(self, node, frame, value):
        iteration = self.stack[frame].iteration
        for i, loop_node in enumerate(node._loops):
            loop = iteration.loops[loop_node._tree_index]
            iteration = loop.last()
        iteration.vals[node._tree_index] = value

    def after_stmt(self, node, frame, exc_value, exc_traceback):
        if frame.f_code not in self._code_infos:
            return
        frame_info = self.stack[frame]
        expression_stack = frame_info.expression_stack
        if expression_stack:
            while isinstance(expression_stack[-1], self.SPECIAL_COMPREHENSION_TYPES):
                inner_frame = frame_info.comprehension_frames[expression_stack[-1]]
                expression_stack = self.stack[inner_frame].expression_stack
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
        self.stack.get(frame.f_back, dummy_namespace).inner_call = frame_info.call_id = self._call_id()

    def _call_id(self):
        return uuid4().hex

    def exit_call(self, exit_info):
        frame = exit_info.current_frame
        if frame.f_code not in self._code_infos:
            return
        frame_info = self.stack[frame]
        top_iteration = frame_info.iteration

        loop_iterations = top_iteration.extract_iterations()['loops']

        node_values = _deep_dict()

        def extract_values(iteration, path):
            for k, v in iteration.vals.items():
                full_path = (k,) + path
                d = node_values
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

        @db_consumer
        def save_call():
            call = Call(id=frame_info.call_id,
                        function=db_func,
                        arguments=frame_info.arguments,
                        return_value=cheap_repr(exit_info.return_value),
                        exception=exception,
                        traceback=traceback_str,
                        data=json.dumps(
                            dict(
                                node_values=node_values,
                                loop_iterations=loop_iterations,
                                type_names=type_registry.names(),
                                num_special_types=type_registry.num_special_types,
                            ),
                            separators=(',', ':')
                        ),
                        start_time=frame_info.start_time)
            session.add(call)
            session.commit()

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
                if not node._is_interesting_expression:
                    continue
            elif (isinstance(node, (ast.While, ast.For, ast.comprehension))
                  and not isinstance(node.parent, ast.GeneratorExp)):
                node_type = 'loop'
            elif isinstance(node, ast.stmt):
                node_type = 'stmt'
            else:
                continue
            assert isinstance(node, ast.AST)
            if not start_lineno <= node.first_token.start[0] <= end_lineno:
                continue
            start, end = traced_file.tokens.get_text_range(node)
            if start == end == 0:
                continue
            positions.append((start, 1, node._depth,
                              '<span data-index="%s" data-type="%s">' % (node._tree_index, node_type)))
            positions.append((end, 0, node._depth, '</span>'))
            if node._loops:
                node_loops[node._tree_index] = [n._tree_index for n in node._loops]

        comprehensions = group_by_key_func([comp for comp in traced_file.nodes
                                            if isinstance(comp, ast.comprehension)],
                                           lambda c: c.first_token.line)

        def get_start(n):
            return traced_file.tokens.get_text_range(n)[0]

        for comp_list in comprehensions.values():
            prev_start = None
            for comp in sorted(comp_list, key=lambda c: c.first_token.startpos):
                if comp is comp.parent.generators[0]:
                    start = get_start(comp.parent)
                    if prev_start is not None and start < prev_start:
                        start = get_start(comp)
                else:
                    start = get_start(comp)
                if prev_start is not None:
                    positions.append((start, 1, 0, '\n '))
                    end_lineno += 1
                prev_start = start

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

        @db_consumer.wait
        def save_func():
            db_func = session.query(Function).filter_by(**db_args).one_or_none()
            if not db_func:
                db_func = Function(**db_args)
                session.add(db_func)
                session.commit()
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
    type_index = type_registry[val]
    result = [cheap_repr(val), type_index]
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


def is_interesting_expression(node):
    return (isinstance(node, ast.expr) and
            not (isinstance(node, (ast.Num, ast.Str, getattr(ast, 'NameConstant', ()))) or
                 isinstance(getattr(node, 'ctx', None),
                            (ast.Store, ast.Del)) or
                 (isinstance(node, ast.UnaryOp) and
                  isinstance(node.op, (ast.UAdd, ast.USub)) and
                  isinstance(node.operand, ast.Num)) or
                 (isinstance(node, (ast.List, ast.Tuple, ast.Dict)) and
                  not any(is_interesting_expression(n) for n in ast.iter_child_nodes(node)))))


def is_obvious_builtin(node, frame_info):
    value = frame_info.expression_values[node]
    # noinspection PyUnresolvedReferences
    return ((isinstance(node, ast.Name) and
             node.id in __builtins__ and
             __builtins__[node.id] is value) or
            isinstance(node, ast.NameConstant))

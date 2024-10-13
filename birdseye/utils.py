import ast

from typing import Union, Any, Iterator, Tuple, Iterable


def of_type(type_or_tuple, iterable):
    # type: (Union[type, Tuple[Union[type, tuple], ...]], Iterable[Any]) -> Iterator[Any]
    return (x for x in iterable if isinstance(x, type_or_tuple))


def is_future_import(node):
    return isinstance(node, ast.ImportFrom) and node.module == "__future__"


html_escape_table = {
    "&": "&amp;",
    '"': "&quot;",
    "'": "&#x27;",
    ">": "&gt;",
    "<": "&lt;",
}


def html_escape(text):
    return "".join(html_escape_table.get(c, c) for c in text)

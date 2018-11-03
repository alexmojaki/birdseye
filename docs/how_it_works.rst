How it works
============

The source file of a decorated function is parsed into the standard Python Abstract Syntax Tree. The tree is then modified so that every statement is wrapped in its own ``with`` statement and every expression is wrapped in a function call. The modified tree is compiled and the resulting code object is used to directly construct a brand new function. This is why the ``eye`` decorator must be applied first: it's not a wrapper like most decorators, so other decorators applied first would almost certainly either have no effect or bypass the tracing. The AST modifications notify the tracer both before and after every expression and statement.

`Here is a talk going into more detail. <https://www.youtube.com/watch?v=Wm47491S-Fo>`_

See the :ref:`source_overview` for an even closer look.

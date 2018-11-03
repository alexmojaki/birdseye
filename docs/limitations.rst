Performance and limitations
--------------------------------------------

Every function call is recorded, and every nontrivial expression is
traced. This means that:

-  Programs are greatly slowed down, and you should be wary of tracing
   functions that are called many times or that run through many loop
   iterations. Note that function calls are not visible in the interface
   until they have been completed.
-  A large amount of data may be collected for every function call,
   especially for functions with many loop iterations and large nested
   objects and data structures. This may be a problem for memory both
   when running the program and viewing results in your browser.
-  To limit the amount of data saved, only a sample is stored.
   Specifically:

   -  The first and last 3 iterations of loops, except if an expression
      or statement is only evaluated at some point in the middle of a
      loop, in which case up to two iterations where it was evaluated
      will also be included (see :ref:`middle-of-loop`).
   -  A limited version of the ``repr()`` of values is used, provided by
      the `cheap_repr`_ package.
   -  Nested data structures and objects can only be expanded by up to 3
      levels. Inside loops this is decreased, except when all current loops
      are in their first iteration.
   -  Only pieces of objects are recorded - see :ref:`collecting-data`.

In IPython shells and notebooks, ``shell.ast_transformers`` is ignored
in decorated functions.

.. _cheap_repr: https://github.com/alexmojaki/cheap_repr

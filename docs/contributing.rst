Contributing
============

Here’s how you can get started if you want to help:

1. Fork the `repository <https://github.com/alexmojaki/birdseye>`_, and clone your fork.

2. Run ::

        pip install -e .

   in the root of the repo. This will install it
   using a symlink such that changes to the code immediately affect the
   installed library. In other words, you can edit a ``.py`` file in your copy of birdseye, then debug a
   separate program, and the results of your edit will be
   visible. This makes development and testing straightforward.

   If you have one or more other projects that you’re working on where birdseye
   might be useful for development and debugging, install birdseye into
   the interpreter (so the virtualenv if there is one) used for that
   project.
3. Try using birdseye for a bit, ideally in a real
   scenario. Get a feel for what using it is like. Note any
   bugs it has or features you’d like added. `Create an issue`_ where
   appropriate or `ask questions on the gitter chatroom`_.
4. Pick an issue that interests you and that you’d like to work on,
   either one that you created or an existing one. An issue with the
   `easy label`_ might be a good place to start.
5. Read through the source code overview below to get an idea of how it all
   works.
6. :ref:`Run the tests <testing>` before making any changes just to verify that it all
   works on your computer.
7. Dive in and start coding! I’ve tried to make the code readable and
   well documented. Don’t hesitate to ask any questions on `gitter`_. If
   you installed correctly, you should find that changes you make to the
   code are reflected immediately when you run it.
8. Once you’re happy with your changes, `make a pull request`_.

.. _here: https://github.com/alexmojaki/birdseye#usage-and-features
.. _Create an issue: https://github.com/alexmojaki/birdseye/issues/new
.. _ask questions on the gitter chatroom: https://gitter.im/python_birdseye/Lobby
.. _easy label: https://github.com/alexmojaki/birdseye/issues?q=is%3Aissue+is%3Aopen+label%3Aeasy
.. _gitter: https://gitter.im/python_birdseye/Lobby
.. _make a pull request: http://scholarslab.org/research-and-development/forking-fetching-pushing-pulling/

.. _source_overview:

Source code overview
--------------------

This is a brief and rough overview of how the core of this library
works, to assist anyone reading the source code for the first time.

See also ':doc:`how_it_works`' for a higher level view of the concepts
apart from the actual source code.

Useful background knowledge
~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. The ``ast`` module of the Python standard library, for parsing,
   traversing, and modifying source code. You don’t need to know the
   details of this in advance, but you should know that `this`_ is a
   great resource for learning about it if necessary, as the official
   documentation is not very helpful.
2. **Code objects**: every function in Python has a ``__code__``
   attribute pointing to a special internal code object. This contains
   the raw instructions for executing the function. A locally defined
   function (i.e. a ``def`` inside a ``def``) can have multiple separate
   instances, but they all share the same code object, so this is the
   key used for storing/finding metadata for functions.
3. **Frame objects**: sometimes referred to as the frame of execution,
   this is another special python object that exists for every function
   call that is currently running. It contains local variables, the code
   object that is being run, a pointer to the previous frame on the
   stack, and more. It’s used as the key for data for the current call.

.. _this: https://greentreesnakes.readthedocs.io/en/latest/index.html

When a function is decorated [``BirdsEye.trace_function``]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. [``TracedFile.__init__``] The entire file is parsed using the
   standard ``ast`` module. The tree is modified so that every
   expression is wrapped in two function calls
   [``_NodeVisitor.visit_expr``] and every statement is wrapped in a
   ``with`` block [``_NodeVisitor.visit_stmt``].
2. [``BirdsEye.compile``] An ``ASTTokens`` object is created so that the
   positions of AST nodes in the source code are known.
3. The modified tree is compiled into a code object. Inside this we find
   the code object corresponding to the function being traced.
4. The ``__globals__`` of the function are updated to contain references
   to the functions that were inserted into the tree in step 1.
5. A new function object is created that’s a copy of the original
   function except with the new code object.
6. An HTML document is constructed where the expressions and statements
   of the source are wrapped in ``<span>``\ s.
7. A ``Function`` row is stored in the database containing the HTML and
   other metadata about the function.
8. A ``CodeInfo`` object is kept in memory to keep track of metadata
   about the function.

When a function runs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. When the first statement of the function runs, the tracer notices
   that it’s the first statement and calls
   ``TreeTracerBase._enter_call``. A new ``FrameInfo`` is created and
   associated with the current frame.
2. [``BirdsEye.enter_call``] The arguments to the function are noted and
   stored in the ``FrameInfo``. If the parent frame is also being
   traced, this is noted as an inner call of the parent call.
3. A ``_StmtContext`` is created for every statement in the function.
   These lead to calling ``BirdsEye.before_stmt`` and
   ``BirdsEye.after_stmt``.
4. For every expression in the function call, ``BirdsEye.before_expr``
   and ``BirdsEye.after_expr`` are called. The values of expressions are
   expanded in ``NodeValue.expression`` and stored in an ``Iteration``,
   belonging either directly to the current ``FrameInfo`` (if this is at
   the top level of the function) or indirectly via an ``IterationList``
   (if this is inside a loop).
5. When the function call ends, ``BirdsEye.exit_call`` is called. The
   data from the current ``FrameInfo`` is gathered and stored in the
   database in a new ``Call`` row.

.. _testing:

Testing
-------

Run ``python setup.py test`` to install test requirements and run all
tests with a single Python interpreter. You will need to have
`phantomjs`_ installed, e.g. via::

    npm install --global phantomjs

Run `tox`_ (``pip install tox``) to run tests on all supported
versions of Python: 2.7, 3.5, and 3.6. You must install the interpreters
separately yourself.

Pushes to GitHub will trigger a build on Travis to run tests
automatically. This will run ``misc/travis_test.sh``.

``test_against_files``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

One of the tests involves comparing data produced by the debugger to the
contents of golden JSON files. This produces massive diffs when the
tests fail. To read these I suggest redirecting or copying the output to
a file and then doing a regex search for ``^[+-]`` to find the
actual differences.

If you’re satisfied that the code is doing the correct thing and the
golden files need to be updated, set the environment variable ``FIX_TESTS=1``,
then rerun the tests. This will write
to the files instead of comparing to them. Since there are files for
each version of python, you will need to run the tests on all supported
interpreters, so tox is recommended.

Browser screenshots for test failures
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``test_interface.py`` runs a test using selenium and phantomjs. If it
fails, it produces a file ``error_screenshot.png`` which is helpful for
debugging the failure locally. If the test only fails on travis, you can
use the ``misc/travis_screenshot.py`` script to obtain the screenshot. See
the module docstring for details.

.. _phantomjs: http://phantomjs.org/download.html
.. _tox: https://tox.readthedocs.io/en/latest/


Linting
-------

None of this is strictly required, but may help spot errors to improve
the development process.

Linting Python using mypy (type warnings)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The code has type hints so that ``mypy`` can be used on it, but there
are many false warnings for various reasons. To ignore these, use the
``misc/mypy_filter.py`` script. The docstring explains in more detail.

Linting JavaScript using gulp and eslint
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Install ``npm``
2. Change to the ``gulp`` directory.
3. Run ``install-deps.sh``.
4. Run ``gulp``. This will lint the JavaScript continuously, checking
   every time the files change.

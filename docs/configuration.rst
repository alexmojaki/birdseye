Configuration
-------------

Server
~~~~~~

The server provides the user interface which can be accessed in the browser. You can run it using the ``birdseye`` command in a terminal. The command has a couple of options which can be viewed using ``--help``::

   $ birdseye --help
   usage: birdseye [-h] [-p PORT] [--host HOST] [--dark-mode]

   optional arguments:
     -h, --help            show this help message and exit
     -p PORT, --port PORT  HTTP port, default is 7777
     --host HOST           HTTP host, default is 'localhost'
     --dark-mode, --dark   use a high-contrast dark theme

To run a remote server accessible from anywhere, run
``birdseye --host 0.0.0.0``.
To use the high-contrast dark theme, run ``birdseye --dark-mode`` (or the
shorter ``birdseye --dark``).

The ``birdseye`` command uses the Flask development server, which is fine for local debugging but doesn't scale very well. You may want to use a proper WSGI server, especially if you host it remotely. `Here are some options <http://flask.pocoo.org/docs/1.0/deploying/>`_. The WSGI application is named ``app`` in the ``birdseye.server`` module. For example, you could use ``gunicorn`` as follows::

    gunicorn -b 0.0.0.0:7777 birdseye.server:app

.. _db_config:

Database
~~~~~~~~

Data is kept in a SQL database. You can configure this by setting the
environment variable ``BIRDSEYE_DB`` to a `database URL used by
SQLAlchemy`_, or just a path to a file for a simple sqlite database.
The default is ``.birdseye.db`` under the home directory. The variable is checked
by both the server and the tracing by the ``@eye`` decorator.

If environment variables are inconvenient, you can do this instead:

.. code:: python

   from birdseye import BirdsEye

   eye = BirdsEye('<insert URL here>')

You can conveniently empty the database by running:

.. code:: bash

   python -m birdseye.clear_db

Making tracing optional
~~~~~~~~~~~~~~~~~~~~~~~

Sometimes you may want to only trace certain calls based on a condition,
e.g. to increase performance or reduce database clutter. In this case,
decorate your function with ``@eye(optional=True)`` instead of just
``@eye``. Then your function will have an additional optional parameter
``trace_call``, default False. When calling the decorated function, if
``trace_call`` is false, the underlying untraced function is used. If
true, the traced version is used.

.. _collecting-data:

Collecting more or less data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Only pieces of objects are recorded, e.g. the first and last 3 items of
a list. The number depends on the type of object and the context, and it
can be configured according to the ``num_samples`` attribute of a
``BirdsEye`` instance. This can be set directly when constructing the
instance, e.g.:

.. code:: python

   from birdseye import BirdsEye

   eye = BirdsEye(num_samples=dict(...))

or modify the dict of an existing instance:

.. code:: python

   from birdseye import eye

   eye.num_samples['big']['list'] = 100

The default value is this:

.. code:: python

   dict(
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

Any value of ``num_samples`` must have this structure.

The values of the ``big`` dict are used when recording an expression
directly (as opposed to recording a piece of an expression, e.g. an item
of a list, which is just part of the tree that is viewed in the UI)
outside of any loop or in the first iteration of all current loops. In
these cases more data is collected because using too much time or space
is less of a concern. Otherwise, the ``small`` values are used. The
inner keys correspond to different types:

-  ``attributes``: (e.g. ``x.y``) collected from the ``__dict__``. This
   applies to any type of object.
-  ``dict`` (or any instance of ``Mapping``)
-  ``list`` (or any ``Sequence``, such as tuples, or numpy arrays)
-  ``set`` (or any instance of ``Set``)
-  ``pandas_rows``: the number of rows of a ``pandas`` ``DataFrame`` or
   ``Series``.
-  ``pandas_cols``: the number of columns of a ``pandas`` ``DataFrame``.

.. _full-capture:

Capturing complete values
~~~~~~~~~~~~~~~~~~~~~~~~~

By default the arguments and return value of each call are stored as short
summaries, e.g. ``[0, 1, 2, ..., 17, 18, 19]``, or a string cut down to 60
characters, and the values of expressions inside the function are only
sampled (see :ref:`collecting-data`). The rest of each value is never stored,
so it can't be expanded later. To store complete copies instead, set
``capture_options`` when constructing a ``BirdsEye`` instance:

.. code:: python

   from birdseye import BirdsEye

   eye = BirdsEye(capture_options=dict(arguments='full', result='full', expressions='full'))

or change the existing instance before the traced functions are called:

.. code:: python

   from birdseye import eye

   eye.capture_options['arguments'] = 'full'
   eye.capture_options['result'] = 'full'
   eye.capture_options['expressions'] = 'full'

You can also set the environment variable ``BIRDSEYE_CAPTURE`` before
starting your program, without changing its code::

   BIRDSEYE_CAPTURE=arguments,result,expressions python my_program.py

``BIRDSEYE_CAPTURE=full`` means the same, and any of the three names can be
used on its own. Options given in code take priority over the environment.
Invalid values in the environment only produce a warning, while invalid
options given to ``BirdsEye`` raise ``ValueError``.

The call page then shows each argument and the return value as a tree that
can be expanded to every item. Arguments are copied when the call starts, so
changes that the function makes to them later don't affect what is shown.
With ``expressions='full'``, clicking an expression in the code shows its
complete value in the inspector at the bottom, in every loop iteration that
birdseye keeps. Values whose contents take up to 1000 characters are
labelled with their complete ``repr()``, including in the one-line preview
shown when hovering over an expression. Larger values keep a short label,
but expanding them shows every item.

What is captured:

-  Every item of lists, tuples (including named tuples), sets, frozensets,
   dicts (including ``OrderedDict``, ``defaultdict`` and ``Counter``),
   ``collections.deque`` and ``array.array``, nested up to ``max_depth``
   levels. These are read with the built-in methods, so a subclass that
   overrides iteration can't hide or change what is captured.
-  The complete ``repr()`` of strings, bytes, numbers, and other simple
   values such as ``Decimal``, ``datetime``, ``UUID``, ``Path``, and enums.
-  For other objects, their attributes from ``__dict__`` or ``__slots__``,
   up to ``object_depth`` levels of attributes.
-  numpy arrays and pandas objects keep their usual sampled display.
-  Generators and iterators are never consumed.

Anything that isn't captured is shown as a highlighted marker that explains
why, e.g. a reference cycle or a limit being reached. These options limit
how much is stored (the defaults are shown):

.. code:: python

   dict(
       arguments='summary',    # or 'full'
       result='summary',       # or 'full'
       expressions='sampled',  # or 'full'
       max_bytes=10000000,     # approximate characters stored, None for no limit
       max_depth=50,           # levels of nesting
       object_depth=2,         # levels of attributes of other objects
   )

``max_bytes`` applies to each argument and to the return value separately,
and to all the expression values of a call together, so a long loop can't
store an unlimited amount. Once a call has used it up, its remaining
expression values are sampled as usual, with a marker saying so.
It can also be set with the environment variable
``BIRDSEYE_CAPTURE_MAX_BYTES`` (``none`` for no limit).

.. warning::

   Complete values can make the database and the call pages much larger, and
   tracing slower. They also store secrets such as passwords and API tokens in
   full. The database isn't encrypted, and the birdseye server has no
   authentication.

.. _database URL used by SQLAlchemy: http://docs.sqlalchemy.org/en/latest/core/engines.html#database-urls

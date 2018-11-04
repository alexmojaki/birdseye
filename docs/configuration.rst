Configuration
-------------

Server
~~~~~~

The server provides the user interface which can be accessed in the browser. You can run it using the ``birdseye`` command in a terminal. The command has a couple of options which can be viewed using ``--help``::

   $ birdseye --help
   usage: birdseye [-h] [-p PORT] [--host HOST]

   optional arguments:
     -h, --help            show this help message and exit
     -p PORT, --port PORT  HTTP port, default is 7777
     --host HOST           HTTP host, default is 'localhost'

To run a remote server accessible from anywhere, run
``birdseye --host 0.0.0.0``.

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

.. _database URL used by SQLAlchemy: http://docs.sqlalchemy.org/en/latest/core/engines.html#database-urls

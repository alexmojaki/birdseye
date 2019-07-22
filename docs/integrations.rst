Integrations with other tools
=============================

birdseye can be used no matter how you write or run your code, requiring only a browser for the interface. But it's also integrated with some common tools for a smoother experience.

snoop
-----

`snoop <https://github.com/alexmojaki/snoop>`_ is another fairly similar debugging library by the same author. Typically you decorate a function with ``@snoop`` and it will log the execution and local variables in the function. You can also use the ``@spy`` decorator which is a combination of ``@snoop`` and ``@eye`` from birdseye so that you get the best of both worlds with no extra effort.

PyCharm plugin
--------------

- `JetBrains Plugin Repository page`_
- `GitHub repo <https://github.com/alexmojaki/birdseye-pycharm>`_

This plugin lets you use birdseye right in the code editor, so that you can switch
between editing and debugging seamlessly:

.. figure:: https://i.imgur.com/xJQzXWe.gif
   :alt: demo

By default the plugin also runs the birdseye server for you, although
you can configure it for total freedom.

You can switch between using the plugin and the normal browser UI for
birdseye without any additional effort; both use the same database and
server.

Basic usage
~~~~~~~~~~~

1. As usual, decorate your function with the
   ``@eye`` decorator and run your function however you want.
   See :doc:`quickstart` and :doc:`tips` for more.
2. If your decorated function was called, the birdseye logo will appear
   on the left by the function definition. Click on it to see a table of
   calls to this function.
3. Click on the call that you want to inspect in a new tab. If there is
   only one call, it will automatically be selected, i.e. this step is
   done for you.
4. You can now hover over expressions in your code and see their values.
5. Click on expressions to expand their values in the call panel. Click
   on them again to deselect them, or press delete or backspace while
   they’re selected in the call panel.
6. Click on the arrows next to loops to step back and forth through
   iterations. The number by the arrows is the 0-based index of the
   iteration.
7. Minimise the birdseye tool window to hide debugging information
   and stop highlighting expressions when you hover over or click on
   them.

Further notes
~~~~~~~~~~~~~

1. Unlike the regular birdseye UI, functions and calls are not based on
   the names of functions or files. Clicking the eye icon shows a list
   of calls to a function with that *exact body*. This means that:

   - Which file contains the function doesn’t matter.
   - Editing the function at all hides the logo, although reverting those
     changes brings it back.
   - Running the function after editing it leads to a new list of calls.

   This is so that the debugging can happen right in the editor.
2. You can edit a function while you’re busy inspecting it, but you will
   usually no longer be able to see the values of the expressions whose
   code changes. Other expressions should be unaffected.
3. Inspecting a call can take a lot of memory, so close call panels when
   you’re done with them.
4. birdseye needs a server to connect to. By default the plugin will run
   the server for you. To configure this, go to the birdseye section of
   Preferences. Note that the database URL setting corresponds to the
   :ref:`BIRDSEYE_DB environment variable <db_config>`. The server needs to run at
   least version 0.5.0 of birdseye.

.. _JetBrains Plugin Repository page: https://plugins.jetbrains.com/plugin/10917-birdseye
.. _birdseye: https://github.com/alexmojaki/birdseye
.. _learn how: https://github.com/alexmojaki/birdseye#installation

.. |logo| image:: https://i.imgur.com/i7uaJDO.png

Jupyter/IPython notebooks
-------------------------

First, `load the birdseye extension <https://ipython.readthedocs.io/en/stable/config/extensions/#using-extensions>`_, using either ``%load_ext birdseye``
in a notebook cell or by adding ``'birdseye'`` to the list
``c.InteractiveShellApp.extensions`` in your IPython configuration file,
e.g. ``~/.ipython/profile_default/ipython_config.py``.

Use the cell magic ``%%eye`` at the top of a notebook cell to trace that
cell. When you run the cell and it finishes executing, a frame should
appear underneath with the traced code.

.. figure:: https://i.imgur.com/bYL5U4N.png
   :alt: Jupyter notebook screenshot

Hovering over an expression should show the value at the bottom of the
frame. This requires the bottom of the frame being visible. Sometimes
notebooks fold long output (which would include the birdseye frame) into
a limited space - if that happens, click the space just left of the
output. You can also resize the frame by dragging the bar at the bottom,
or click ‘Open in new tab’ just above the frame.

For convenience, the cell magic automatically starts a birdseye server
in the background. You can configure this by settings attributes on
``BirdsEyeMagics``, e.g. with::

    %config BirdsEyeMagics.port = 7778

in a cell or::

    c.BirdsEyeMagics.port = 7778

in your IPython config file. The available attributes are:

:``server_url``:
   If set, a server will not be automatically started by
   ``%%eye``. The iframe containing birdseye output will use this value
   as the base of its URL.

:``port``:
   Port number for the background server.

:``bind_host``: Host that the background server listens on. Set to
   0.0.0.0 to make it accessible anywhere. Note that birdseye is NOT
   SECURE and doesn’t require any authentication to access, even if the
   notebook server does. Do not expose birdseye on a remote server
   unless you have some other form of security preventing HTTP access to
   the server, e.g. a VPN, or you don’t care about exposing your code
   and data. If you don’t know what any of this means, just leave this
   setting alone and you’ll be fine.

:``show_server_output``: Set to True to show stdout and stderr from
   the background server.

:``db_url``: The database URL that the background server reads from.
   Equivalent to the :ref:`environment variable BIRDSEYE_DB <db_config>`.

Visual Studio Code extension
----------------------------

- `Visual Studio Marketplace page <https://marketplace.visualstudio.com/items?itemName=almenon.birdseye-vscode>`_
- `GitHub repo <https://github.com/Almenon/birdseye-vscode/>`_

Usage is simple: open the Command Palette (F1 or Cmd+Shift+P) and choose 'Show birdseye'.
This will start the server and show a browser pane with the UI inside VS Code.

You can also search for birdseye under settings for configuration and possibly
troubleshooting.

PythonAnywhere
--------------

This isn't really an integration, just some instructions.

The birdseye server needs to run in a web app for you to access it. You can either use a dedicated web app, or if you can't afford to spare one, combine it with an existing app.

To use a dedicated web app, create a new web app, choose any framework you want (manual configuration will do), and in the WSGI configuration file ``/var/www/your_domain_com_wsgi.py`` put the following code::

    from birdseye.server import app as application

To combine with an existing web app, add this code at the end of the WSGI file::

    import birdseye.server
    from werkzeug.wsgi import DispatcherMiddleware

    application = DispatcherMiddleware(application, {
        '/birdseye': birdseye.server.app
    })

Here ``application`` should already be defined higher up as the WSGI object for your original web app. Then your existing web app should be unaffected, except that you can also go to ``your.domain.com/birdseye`` to view the birdseye UI. You can also choose another prefix instead of ``'/birdseye'``.

Either way, you should also ensure that your web app is secure, as birdseye will expose your code and data. Under the Security section of your web app configuration, enable Force HTTPS and Password protection, choose a username and password, then reload the web app.

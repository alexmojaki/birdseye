Integrations with other tools
=============================

birdseye can be used no matter how you write or run your code, requiring only a browser for the interface. But it's also integrated with some common tools for a smoother experience.

snoop
-----

`snoop <https://github.com/alexmojaki/snoop>`_ is another fairly similar debugging library by the same author. Typically you decorate a function with ``@snoop`` and it will log the execution and local variables in the function. You can also use the ``@spy`` decorator which is a combination of ``@snoop`` and ``@eye`` from birdseye so that you get the best of both worlds with no extra effort.

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

PyCharm plugin
--------------

This plugin hasn't worked for a long time and is no longer being maintained.

- `JetBrains Plugin Repository page <https://plugins.jetbrains.com/plugin/10917-birdseye>`_
- `GitHub repo <https://github.com/alexmojaki/birdseye-pycharm>`_

.. _birdseye: https://github.com/alexmojaki/birdseye
.. _learn how: https://github.com/alexmojaki/birdseye#installation
.. |logo| image:: https://i.imgur.com/i7uaJDO.png

|logo| birdseye
===============

|Build Status| |Supports Python versions 2.7 and 3.5+|

birdseye is a Python debugger which records the values of expressions in a
function call and lets you easily view them after the function exits.
For example:

.. figure:: https://i.imgur.com/rtZEhHb.gif
   :alt: Hovering over expressions

You can use birdseye no matter how you run or edit your code. Just ``pip install birdseye``, add the ``@eye`` decorator
as seen above, run your function however you like, and view the results in your browser.
It's also `integrated with some common tools <http://birdseye.readthedocs.io/en/latest/integrations.html>`_ for a smoother experience.

You can try it out **instantly** on `futurecoder <https://futurecoder.io/course/#ide>`_: enter your code in the editor on the left and click the ``birdseye`` button to run. No imports or decorators required.

Feature Highlights
------------------

Rather than stepping through lines, move back and forth through loop
iterations and see how the values of selected expressions change:

.. figure:: https://i.imgur.com/236Gj2E.gif
   :alt: Stepping through loop iterations

See which expressions raise exceptions, even if they’re suppressed:

.. figure:: http://i.imgur.com/UxqDyIL.png
   :alt: Exception highlighting

Expand concrete data structures and objects to see their contents.
Lengths and depths are limited to avoid an overload of data.

.. figure:: http://i.imgur.com/PfmqZnT.png
   :alt: Exploring data structures and objects

Calls are organised into functions (which are organised into files) and
ordered by time, letting you see what happens at a glance:

.. figure:: https://i.imgur.com/5OrB76I.png
   :alt: List of function calls

.. |logo| image:: https://i.imgur.com/i7uaJDO.png
.. |Build Status| image:: https://travis-ci.com/alexmojaki/birdseye.svg?branch=master
   :target: https://travis-ci.com/alexmojaki/birdseye
.. |Supports Python versions 2.7 and 3.5+| image:: https://img.shields.io/pypi/pyversions/birdseye.svg
   :target: https://pypi.python.org/pypi/birdseye

.. inclusion-end-marker

**Read more documentation** `here <http://birdseye.readthedocs.io>`_

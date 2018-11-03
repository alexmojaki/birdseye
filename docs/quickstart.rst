Quick start
===============

First, install birdseye using `pip <https://pip.pypa.io/en/stable/installing/>`_::

    pip install --user birdseye

To debug a function:

1. Decorate it with ``birdseye.eye``, e.g.::

       from birdseye import eye

       @eye
       def foo():

   **The** ``eye`` **decorator must be applied before any other decorators,
   i.e. at the bottom of the list.**

2. Call the function [*]_.
3. Run ``birdseye`` or ``python -m birdseye`` in a terminal to run the
   UI server.
4. Open http://localhost:7777 in your browser.
5. Note the instructions at the top for navigating through the UI. Usually you will want to jump straight to the most recent call of the function you're debugging by clicking on the play icon:

   |most recent call|

When viewing a function call, you can:

-  Hover over an expression to view its value at the bottom of the
   screen.
-  Click on an expression to select it so that it stays in the
   inspection panel, allowing you to view several values simultaneously
   and expand objects and data structures. Click again to deselect.
-  Hover over an item in the inspection panel and it will be highlighted
   in the code.
-  Drag the bar at the top of the inspection panel to resize it
   vertically.
-  Click on the arrows next to loops to step back and forth through
   iterations. Click on the number in the middle for a dropdown to jump
   straight to a particular iteration.
-  If the function call you’re viewing includes a function call that was
   also traced, the expression where the call happens will have an arrow
   (|blue curved arrow|) in the corner which you can click on to go to
   that function call. For generator functions, the arrow will appear
   where the generator is first iterated over, not just when the function is called,
   since that is when execution of the function begins.

.. |blue curved arrow| image:: https://i.imgur.com/W7DfVeg.png
.. |most recent call| image:: /_static/img/call_to_foo.png
.. [*] You can run the program however you want, as long as the function gets called and completes, whether by a normal return or an exception. The program itself doesn't need to terminate, only the function.

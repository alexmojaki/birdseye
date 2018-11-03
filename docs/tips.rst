Tips
====

Debugging an entire file
-------------------------

Instead of decorating individual functions with ``@eye``, you may want to debug *all* the functions in a module, or you may want to debug the top-level execution of the module itself without wrapping it in a function.

To trace every function in the file, as well as the module execution itself, add the line::

    import birdseye.trace_module_deep

To trace only the module execution but none of the functions (to reduce the performance impact), leave out the ``_deep``, i.e.::

    import birdseye.trace_module

There are some caveats to note:

#. These import statements must be unindented, not inside a block such as ``if`` or ``try``.
#. If the module being traced is not the module that is being run directly, i.e. it's being imported by another module, then:
    #. The module will not be traced in Python 2.
    #. ``birdseye`` must be imported somewhere before importing the traced module.
    #. The execution of the entire module will be traced, not just the part after the import statement as when the traced module is run directly.

Debugging functions without importing
-------------------------------------

If you're working on a project with many files and you're tired of writing ``from birdseye import eye`` every time you want to debug a function, add code such as this to the entrypoint of your project::

    from birdseye import eye

    # If you don't need Python 2/3 compatibility,
    # just one of these lines will do
    try:
        import __builtin__ as builtins  # Python 2
    except ImportError:
        import builtins  # Python 3

    builtins.eye = eye
    # or builtins.<something else> = eye if you want to use a different name

Now you can decorate a function with ``@eye`` anywhere without importing.

.. _middle-of-loop:

Debugging the middle of a loop
------------------------------

birdseye will always save data from the first and last three iterations of a loop, but sometimes you have a loop with many iterations and you want to know about a specific iteration in the middle. If you were using a traditional debugger, you might do something like::

    for item in long_list_of_items:
        if has_specific_property(item):
            print(item)  # <-- put a breakpoint here
        ...

You can actually use the same technique in birdseye, and you don't even need anything like a breakpoint. For every statement/expression node in a loop block, birdseye will ensure that at least two iterations where that node was evaluated are saved, assuming they exist. That means that if a statement/expression is only evaluated in the middle of the loop, those iterations will still be saved. Use a specific ``if`` or ``try/except`` statement to track down the iterations you need.

You can also try wrapping the contents of the loop in a function and debugging that function. Then every call to the function will be saved and you can find the call you want by looking at the arguments and return values in the calls table. However this does come with a performance cost.

# Bird's Eye

[![Build Status](https://travis-ci.org/alexmojaki/birdseye.svg?branch=master)](https://travis-ci.org/alexmojaki/birdseye)

This is a Python debugger which instruments the abstract syntax tree to record the value of expressions in a function call and lets you easily view them after the function exits. For example:

![Hovering over expressions](https://i.imgur.com/rtZEhHb.gif)

Rather than stepping through lines, move back and forth through loop iterations and see how the values of selected expressions change:

![Stepping through loop iterations](https://i.imgur.com/236Gj2E.gif)

See which expressions raise exceptions, even if they're suppressed:

![Exception highlighting](http://i.imgur.com/UxqDyIL.png)

Expand concrete data structures and objects to see their contents. Lengths and depths are limited to avoid an overload of data.

![Exploring data structures and objects](http://i.imgur.com/PfmqZnT.png)

Calls are organised into functions (which are organised into files) and organised by time, letting you see what happens at a glance:

![List of function calls](https://i.imgur.com/5OrB76I.png)

## Installation

Simply `pip install birdseye`.

Currently only Python 3.5 is supported. Python 3.4 or 3.6 might work but I haven't tested them.

## Usage

For a quick demonstration, copy [this example](https://github.com/alexmojaki/birdseye/blob/master/example_usage.py) and run it. Then continue from step 2 below.

To debug your own function, decorate it with an instance of `birdseye.BirdsEye`, e.g.

```
from birdseye import BirdsEye

@BirdsEye()
def foo():
```

1. Call the function.
2. Run `birdseye` or `python -m birdseye`.
3. Open http://localhost:7777 in your browser
4. Click on:
    1. The name of the file containing your function
    2. The name of the function
    3. The most recent call to the function
5. Hover over an expression to view its value at the bottom of the screen.
6. Click on an expression to select it so that it stays in the inspection panel, allowing you to view several values simultaneously and expand objects and data structures. Click again to deselect.
7. Click on the arrows next to loops to step back and forth through iterations. Click on the number in the middle for a dropdown to jump straight to a particular iteration. Note that data is only kept for the first and last few iterations of a loop.

## Configuration

Data is kept in a SQL database. You can configure this by setting the environment variable `BIRDSEYE_DB`. The default is `sqlite:///$HOME/.birdseye.db`.

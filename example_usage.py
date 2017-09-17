from itertools import islice
from random import shuffle

from birdseye import BirdsEye

eye = BirdsEye()


@eye
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)


def foo(*args):
    pass


class A(object):
    def __init__(self):
        self.x = 1
        self.y = 2


class B(object):
    __slots__ = ('slot1', 'slot2')

    def __init__(self):
        self.slot1 = 3
        self.slot2 = 4


def complex_args(pos1, pos2, key1=3, key2=4, *args, **kwargs):
    pass


@eye
def gen():
    for i in range(6):
        yield i


@eye
def use_gen_1(g):
    for x in islice(g, 3):
        print('foo', x)


@eye
def use_gen_2(g):
    for y in g:
        print('bar', y)


@eye
def quicksort(lst):
    if len(lst) <= 1:
        return lst
    else:
        pivot = lst[0]
        left = []
        right = []
        for x in lst[1:]:
            if x < pivot:
                left.append(x)
            else:
                right.append(x)

        return quicksort(left) + [pivot] + quicksort(right)


@eye
def main():
    print(factorial(5))

    vals = []
    for i in range(100):
        vals.append([])
        for j in range(2 * i):
            vals[-1].append(i + j)

    for i in range(6):
        try:
            foo(1 / (i % 2) + 10)
        except ZeroDivisionError:
            pass

    lst = [[x + y for x in range(100)] for y in range(100)]
    x = {
        'a': A(),
        'b': B(),
        'tup': (7, 8, 9),
        'lst': lst,
        'string': "Hello World!" * 50,
        'none': None,
        'true': True,
        'false': False
    }
    x['x'] = x
    len(x)

    complex_args(list(range(1000)),
                 "hello",
                 key2=8,
                 kwarg1={},
                 kwarg2=[])

    g = gen()
    use_gen_1(g)
    use_gen_2(g)

    lst = list(range(100))
    original = lst.copy()
    shuffle(lst)
    assert lst != original
    assert quicksort(lst) == original


main()

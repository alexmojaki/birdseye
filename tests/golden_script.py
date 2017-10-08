from collections import Mapping
from itertools import islice

from birdseye import eye


@eye
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)


def dummy(*args):
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


@eye
def complex_args(pos1, pos2, key1=3, key2=4, *args, **kwargs):
    pass


@eye
def gen():
    for i in range(6):
        yield i


@eye
def use_gen_1(g):
    for x in islice(g, 3):
        dummy(x)


@eye
def use_gen_2(g):
    for y in g:
        dummy(y)


class MyDict(Mapping):
    def __len__(self):
        return 3

    @eye
    def __iter__(self):
        yield (7, 8, 9)

    @eye
    def __getitem__(self, key):
        return key


@eye
def main():
    factorial(5)

    vals = []
    for i in range(100):
        vals.append([])
        for j in range(2 * i):
            vals[-1].append(i + j)
            dummy(vals)

    for i in range(6):
        try:
            dummy(1 / (i % 2) + 10)
        except ZeroDivisionError:
            pass

    dummy([[x + y for x in range(100)] for y in range(100)])
    len(MyDict())

    complex_args(list(range(1000)),
                 "hello",
                 key2=8,
                 kwarg1={})

    g = gen()
    use_gen_1(g)
    use_gen_2(g)


main()

from itertools import islice

from birdseye import eye

G = 9


@eye
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)


def dummy(*args):
    pass


class SlotClass(object):
    __slots__ = ('slot1',)

    def __init__(self):
        self.slot1 = 3


@eye
def complex_args(pos1, pos2, key1=3, key2=4, *args, **kwargs):
    return [pos1, pos2, kwargs]


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


class MyClass(object):
    @eye
    def __add__(self, other):
        return other

    @eye
    def __enter__(self):
        pass

    @eye
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


@eye
def main():
    assert factorial(3) == 6

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
            continue
        if i == 3:
            break

    c = MyClass() + MyClass()
    c.list = [[x + y for x in range(100)] for y in range(100)]
    sum  (n for n in range(4))
    dummy({n for n in range(4)})
    dummy({n: n for n in range(1)})
    with c:
        pass
    dummy(c + SlotClass())

    assert complex_args(
        list(range(1000)),
        "hello",
        key2=8,
        kwarg1={'key': 'value'}
    ) == [list(range(1000)),
          'hello',
          dict(kwarg1={'key': 'value'})]

    assert complex_args(*[1, 2], **{'k': 23}) == [1, 2, {'k': 23}]

    assert eval('%s + %s' % (1, 2)) == 3

    x = 1
    x += 5
    assert x == 6
    del x

    dummy(True, False, None)

    assert [1, 2, 3][1] == 2
    assert (1, 2, 3)[:2] == (1, 2)

    try:
        raise ValueError()
    except AssertionError as e:
        pass
    except TypeError:
        pass
    except:
        pass
    finally:
        dummy()

    while True:
        break

    assert (lambda x: x * 2)(4) == 8

    global G
    G = 4
    assert G == 4

    g = gen()
    use_gen_1(g)
    use_gen_2(g)


main()

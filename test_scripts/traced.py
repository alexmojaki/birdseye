import birdseye.trace_module_deep


def deco(f):
    return f


def m():
    qwe = 9
    str(qwe)

    @deco
    class A:
        for i in range(3):
            str(i * i)

        @deco
        def foo(self):
            x = 9 * 0
            str(1 + 2 + x)
            return self

        @deco
        def bar(self):
            return 1 + 3

    A().foo().bar()


m()

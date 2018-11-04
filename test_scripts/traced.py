import birdseye.trace_module_deep


def deco(f):
    return f


def m():
    qwe = 9
    str(qwe)

    class A:
        for i in range(3):
            str(i * i)

        class B:
            str([[i * 2 for i in range(j)]
                 for j in range(3)])

        (lambda *_: 9)(None)
        (lambda x: [i * x for i in range(3)])(8)
        str({(lambda x: i + x)(7) for i in range(3)})

        @deco
        def foo(self):
            x = 9 * 0
            str(1 + 2 + x)
            return self

        def bar(self):
            return 1 + 3

    A().foo().bar()


m()

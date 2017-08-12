import unittest
from birdseye.utils import iter_get
from random import shuffle


class TestUtils(unittest.TestCase):
    def test_iter_get(self):
        lst = list(range(100))
        shuffle(lst)
        for i in range(-100, 100):
            self.assertEqual(iter_get(lst, i),
                             lst[i])


if __name__ == '__main__':
    unittest.main()

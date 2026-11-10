import unittest

from calc import add, mean


class CalcTest(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)

    def test_mean(self):
        self.assertAlmostEqual(mean([1, 2, 3]), 2.0)


if __name__ == "__main__":
    unittest.main()

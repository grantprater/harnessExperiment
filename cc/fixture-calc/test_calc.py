import unittest

import calc


class CalcTest(unittest.TestCase):
    def test_add(self):
        self.assertEqual(calc.add(2, 3), 5)

    def test_subtract(self):
        self.assertEqual(calc.subtract(5, 3), 2)

    def test_multiply(self):
        self.assertEqual(calc.multiply(4, 3), 12)

    def test_mean(self):
        self.assertEqual(calc.mean([2, 4, 6]), 4)

    def test_mean_empty(self):
        with self.assertRaises(ValueError):
            calc.mean([])


if __name__ == '__main__':
    unittest.main()

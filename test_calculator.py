"""Test suite for sample_calculator."""

import sys
from sample_calculator import add, calculate_discount, format_receipt

def test_all():
    assert add(10, 5) == 15, "add(10, 5) failed"
    result = calculate_discount(50.0, 10.0)
    assert result == 45.0, f"Expected 45.0, got {result}"
    print("ALL TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    try:
        test_all()
    except AssertionError as e:
        print(f"AssertionError: {e}", file=sys.stderr)
        sys.exit(1)

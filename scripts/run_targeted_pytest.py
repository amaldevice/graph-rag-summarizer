import sys

import pytest


def main() -> int:
    args = sys.argv[1:] or ["tests", "-v"]
    return pytest.main(args)


if __name__ == "__main__":
    raise SystemExit(main())

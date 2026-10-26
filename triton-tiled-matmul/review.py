"""Compatibility entrypoint; shared implementation lives in ../review.py."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from review import main

if __name__ == '__main__':
    main(default_project='triton-tiled-matmul')

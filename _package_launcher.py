"""PyInstaller entry point for the preserved compiled application module."""

import os
import runpy
import sys


def main():
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    runpy.run_path(
        os.path.join(base_dir, "inkscape2forza_new.cpython-313.pyc"),
        run_name="__main__",
    )


if __name__ == "__main__":
    main()

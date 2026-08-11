"""Recursively slim SVG files larger than 10 MiB in a selected folder."""

import argparse
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

try:
    from .slim_svg import slim_file
except ImportError:
    from slim_svg import slim_file


MIN_SIZE = 10 * 1024 * 1024


def select_folder():
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    folder = filedialog.askdirectory(title='Select folder containing SVG files')
    root.destroy()
    return folder


def find_large_svgs(folder):
    paths = []
    for path in Path(folder).rglob('*'):
        try:
            if path.is_file() and path.suffix.lower() == '.svg' and path.stat().st_size > MIN_SIZE:
                paths.append(path)
        except OSError as error:
            print(f'Skip {path}: {error}', file=sys.stderr)
    return sorted(paths, key=lambda path: str(path).lower())


def format_size(size):
    return f'{size / (1024 * 1024):.2f} MiB'


def main():
    parser = argparse.ArgumentParser(
        description='Recursively remove unused symbols and patterns from SVG files larger than 10 MiB.'
    )
    parser.add_argument('folder', nargs='?', help='Folder to scan recursively.')
    args = parser.parse_args()

    folder = args.folder or select_folder()
    if not folder:
        return

    folder = Path(folder).resolve()
    if not folder.is_dir():
        print(f'Invalid folder: {folder}', file=sys.stderr)
        raise SystemExit(1)

    paths = find_large_svgs(folder)
    if not paths:
        print('No SVG files larger than 10 MiB found.')
        return

    print(f'Found {len(paths)} SVG file(s) larger than 10 MiB in:\n{folder}')
    if input('Overwrite these files in place? [y/N]: ').strip().lower() not in ('y', 'yes'):
        return

    processed = 0
    failed = 0
    total_removed = 0
    total_saved = 0

    for path in paths:
        try:
            before = path.stat().st_size
            removed = slim_file(path)
            after = path.stat().st_size
            saved = max(0, before - after)
            processed += 1
            total_removed += removed
            total_saved += saved
            print(f'{path}: removed {removed} defs, {format_size(before)} -> {format_size(after)}')
        except Exception as error:
            failed += 1
            print(f'{path}: {error}', file=sys.stderr)

    print(
        f'Done: {processed} processed, {failed} failed, '
        f'{total_removed} defs removed, {format_size(total_saved)} saved.'
    )


if __name__ == '__main__':
    main()

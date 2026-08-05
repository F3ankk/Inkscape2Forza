"""Remove unused SVG symbols and patterns in place."""

import argparse
import os
import re
import sys
import tkinter as tk
import xml.etree.ElementTree as ET
from tkinter import filedialog


SVG_NS = 'http://www.w3.org/2000/svg'
XLINK_NS = 'http://www.w3.org/1999/xlink'
INKSCAPE_NS = 'http://www.inkscape.org/namespaces/inkscape'
SODIPODI_NS = 'http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd'


def local_name(element):
    return element.tag.rsplit('}', 1)[-1]


def href(element):
    return element.get(f'{{{XLINK_NS}}}href') or element.get('href', '')


def collect_used_ids(root):
    used = set()
    for element in root.iter():
        if local_name(element) in ('symbol', 'pattern'):
            continue
        reference = href(element)
        if reference.startswith('#'):
            used.add(reference[1:])
        for value in element.attrib.values():
            used.update(re.findall(r'url\(#([^)]+)\)', value))

    changed = True
    while changed:
        changed = False
        for element in root.iter():
            if element.get('id') not in used:
                continue
            reference = href(element)
            if reference.startswith('#') and reference[1:] not in used:
                used.add(reference[1:])
                changed = True
            for value in element.attrib.values():
                for match in re.findall(r'url\(#([^)]+)\)', value):
                    if match not in used:
                        used.add(match)
                        changed = True
    return used


def slim_file(path):
    tree = ET.parse(path)
    root = tree.getroot()
    used = collect_used_ids(root)
    parents = {child: parent for parent in root.iter() for child in parent}
    removed = 0
    for element in list(root.iter()):
        if local_name(element) not in ('symbol', 'pattern'):
            continue
        if element.get('id') not in used:
            parent = parents.get(element)
            if parent is not None:
                parent.remove(element)
                removed += 1
    if removed:
        ET.register_namespace('', SVG_NS)
        ET.register_namespace('inkscape', INKSCAPE_NS)
        ET.register_namespace('sodipodi', SODIPODI_NS)
        ET.register_namespace('xlink', XLINK_NS)
        ET.indent(tree, space='  ')
        tree.write(path, encoding='utf-8', xml_declaration=True, short_empty_elements=True)
    return removed


def select_files():
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    paths = filedialog.askopenfilenames(title='Select SVG files', filetypes=[('SVG', '*.svg')])
    root.destroy()
    return list(paths)


def main():
    parser = argparse.ArgumentParser(description='Remove unused SVG symbols and patterns in place.')
    parser.add_argument('files', nargs='*', help='SVG files to process.')
    paths = parser.parse_args().files or select_files()
    if not paths:
        return
    if input('Overwrite selected files? [y/N]: ').strip().lower() not in ('y', 'yes'):
        return
    for path in paths:
        try:
            print(f'{os.path.basename(path)}: removed {slim_file(path)} defs')
        except Exception as error:
            print(f'{os.path.basename(path)}: {error}', file=sys.stderr)


if __name__ == '__main__':
    main()

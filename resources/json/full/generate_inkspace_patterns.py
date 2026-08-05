"""Build the FH6 mask-indicator paint library for Inkscape."""

import argparse
import os

from generate_inkspace_template import MASK_PATTERNS


def build_pattern_library(output_filepath):
    svg_content = '''<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
     xmlns:xlink="http://www.w3.org/1999/xlink"
     sodipodi:docname="FH6_Vinyl_Patterns.svg">
  <defs>''' + MASK_PATTERNS + '''
  </defs>
</svg>
'''
    with open(output_filepath, 'w', encoding='utf-8', newline='\n') as output:
        output.write(svg_content)
    print(f'Built FH6 mask indicator patterns: {output_filepath}')


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description='Generate the FH6 Inkscape pattern library SVG.')
    parser.add_argument(
        'output_svg', nargs='?', default=os.path.join(script_dir, 'FH6_Vinyl_Patterns.svg'),
        help='Generated patterns-only SVG path.'
    )
    args = parser.parse_args()
    build_pattern_library(args.output_svg)


if __name__ == '__main__':
    main()

"""Build an Inkscape Symbols-panel library from the FH6 shape JSON files.

The generated SVG intentionally contains definitions only.  Install it in the
Inkscape user symbols directory, then insert symbols through Inkscape so each
working SVG receives only the definitions it actually uses.
"""

import argparse
import base64
import glob
import html
import json
import os

from generate_inkspace_template import create_jpg_mask


SVG_HEADER = '''<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"
     xmlns:xlink="http://www.w3.org/1999/xlink"
     sodipodi:docname="fh6_vinyl_symbols.svg">
  <defs>'''


def build_symbol_library(input_folder, output_filepath):
    json_files = sorted(glob.glob(os.path.join(input_folder, '*.json')))
    if not json_files:
        raise FileNotFoundError(f'No JSON files found in: {input_folder}')

    svg_content = [SVG_HEADER]
    seen_symbol_ids = set()
    total_shapes = 0

    for file_path in json_files:
        filename = os.path.basename(file_path)
        print(f'Processing: {filename}')
        with open(file_path, 'r', encoding='utf-8') as source:
            data = json.load(source)

        for shape in data:
            info = shape.get('Info', {})
            symbol_id = 'fh6_t{}_i{}_w{}'.format(
                info.get('Type', 0), info.get('TypeIndex', 0), info.get('ShapeWord', 0)
            )
            vertices = shape.get('Vertices', [])
            indices = shape.get('Indices', [])
            if not vertices or not indices:
                continue
            if symbol_id in seen_symbol_ids:
                print(f'  Skipping duplicate symbol id: {symbol_id}')
                continue
            seen_symbol_ids.add(symbol_id)

            alpha_b64 = shape.get('VerticesAlpha', '')
            if alpha_b64:
                alpha_bytes = base64.b64decode(alpha_b64)
                if len(alpha_bytes) != len(vertices):
                    print(f'  Warning: alpha count mismatch for {symbol_id}')
                alpha_bytes = alpha_bytes[:len(vertices)]
                alpha_bytes += bytes([255]) * (len(vertices) - len(alpha_bytes))
            else:
                alpha_bytes = bytes([255]) * len(vertices)

            min_x = min(vertex['X'] for vertex in vertices)
            max_x = max(vertex['X'] for vertex in vertices)
            min_y = min(vertex['Y'] for vertex in vertices)
            max_y = max(vertex['Y'] for vertex in vertices)
            width = max(max_x - min_x, 1)
            height = max(max_y - min_y, 1)
            mask_id = f'mask_{symbol_id}'
            source_name = os.path.splitext(filename)[0]
            label = html.escape(f'{source_name} | {symbol_id}')

            svg_content.append(
                f'    <symbol id="{symbol_id}" inkscape:label="{label}" '
                f'viewBox="{min_x} {min_y} {width} {height}" width="{width}" height="{height}">'
            )
            svg_content.append(f'      <title>{label}</title>')
            jpg_mask = create_jpg_mask(
                vertices, indices, alpha_bytes, min_x, min_y, max_x, max_y,
                scale_factor=4, max_resolution=4000
            )
            svg_content.append(
                f'      <mask id="{mask_id}" maskUnits="userSpaceOnUse" '
                f'x="{min_x}" y="{min_y}" width="{width}" height="{height}">'
            )
            svg_content.append(
                f'        <image xlink:href="data:image/jpeg;base64,{jpg_mask}" '
                f'x="{min_x}" y="{min_y}" width="{width}" height="{height}" '
                'preserveAspectRatio="none" />'
            )
            svg_content.append('      </mask>')
            svg_content.append(
                f'      <rect x="{min_x}" y="{min_y}" width="{width}" height="{height}" '
                f'fill="unset" mask="url(#{mask_id})" />'
            )
            svg_content.append('    </symbol>')
            total_shapes += 1

    svg_content.extend(['  </defs>', '</svg>'])
    with open(output_filepath, 'w', encoding='utf-8', newline='\n') as output:
        output.write('\n'.join(svg_content))

    print(f'Built {total_shapes} symbols: {output_filepath}')


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description='Generate the FH6 Inkscape symbol library SVG.')
    parser.add_argument('input_folder', nargs='?', default=script_dir, help='Directory containing FH6 JSON files.')
    parser.add_argument(
        'output_svg', nargs='?', default=os.path.join(script_dir, 'fh6_vinyl_symbols.svg'),
        help='Generated symbols-only SVG path.'
    )
    args = parser.parse_args()
    build_symbol_library(args.input_folder, args.output_svg)


if __name__ == '__main__':
    main()

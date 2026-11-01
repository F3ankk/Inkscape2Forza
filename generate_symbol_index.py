"""Generate the small runtime index from the bundled FH6 symbol SVG."""
import argparse
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path


SYMBOL_ID = re.compile(r'fh6_t[0-9]+_i[0-9]+_w([0-9]+)\Z')


def build_index(source, destination):
    symbols = []
    seen_words = set()
    for _, element in ET.iterparse(source, events=('end',)):
        if element.tag.rsplit('}', 1)[-1] != 'symbol':
            continue
        symbol_id = element.get('id', '')
        match = SYMBOL_ID.fullmatch(symbol_id)
        values = element.get('viewBox', '').split()
        if match is None or len(values) != 4:
            raise ValueError(f'Invalid FH6 symbol metadata: {symbol_id}')
        word = int(match.group(1))
        if word in seen_words:
            raise ValueError(f'Duplicate FH6 ShapeWord: {word}')
        seen_words.add(word)
        viewbox = tuple(float(value) for value in values)
        if (not all(math.isfinite(value) for value in viewbox)
                or viewbox[2] <= 0 or viewbox[3] <= 0):
            raise ValueError(f'Invalid FH6 symbol viewBox: {symbol_id}')
        symbols.append((word, symbol_id, *viewbox))
        element.clear()
    symbols.sort()
    lines = [
        '"""Generated FH6 symbol metadata; rebuild with generate_symbol_index.py."""',
        'SYMBOL_INDEX = (',
        *(f'    {entry!r},' for entry in symbols),
        ')',
        '',
    ]
    Path(destination).write_text('\n'.join(lines), encoding='utf-8')
    return len(symbols)


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='?', default=root / 'fh6_vinyl_symbols.svg', type=Path)
    parser.add_argument('destination', nargs='?', default=root / 'inkscape2forza' / '_symbol_index.py', type=Path)
    args = parser.parse_args()
    print(f'Indexed {build_index(args.source, args.destination)} FH6 symbols')

"""Export one or more FH6 LayerGroup directories to individual SVG files."""

import argparse
import re
import sys
from pathlib import Path


# Allow direct execution from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from inkscape2forza import cgroup_codec, svg_codec
from inkscape2forza.model import count_shapes


def safe_title(title):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title)[:180].strip(" .")
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"COM{i}" for i in range(1, 10))
    reserved.update(f"LPT{i}" for i in range(1, 10))
    if name.upper().split(".")[0] in reserved:
        name = f"_{name}"
    return name or "Untitled"


def available_output(output_dir, filename):
    path = output_dir / filename
    if not path.exists():
        return path
    title, layer_count = path.stem.rsplit(".", 1)
    number = 2
    while True:
        path = output_dir / f"{title} ({number}).{layer_count}.svg"
        if not path.exists():
            return path
        number += 1


def export_directory(source, output_dir):
    if not source.is_dir():
        raise ValueError("输入路径不是目录 / Input path is not a directory")

    cgroup_path = source / "C_group"
    header_path = source / "header"
    if not cgroup_path.is_file() or not header_path.is_file():
        raise ValueError("目录缺少 C_group 或 header / Missing C_group or header")

    title, _ = cgroup_codec.parse_header(header_path)
    root_group = cgroup_codec.decode_cgroup_payload(
        cgroup_codec.unwrap_cgroup_file(cgroup_path)
    )
    filename = f"{safe_title(title)}.{count_shapes(root_group)}.svg"
    svg_path = available_output(output_dir, filename)
    svg_codec.export_group_to_svg(root_group, svg_path)
    return svg_path


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Export FH6 LayerGroup directories to separate SVG files."
    )
    parser.add_argument(
        "-i", "--input", nargs="+", action="append", required=True,
        metavar="LAYERGROUP_DIR", help="One or more LayerGroup directories",
    )
    parser.add_argument(
        "-o", "--output", required=True, type=Path, metavar="OUTPUT_DIR",
        help="Directory for exported SVG files",
    )
    args = parser.parse_args(argv)

    try:
        args.output.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        parser.error(f"无法创建输出目录 / Cannot create output directory: {exc}")

    failed = False
    for group_dir in (Path(value) for batch in args.input for value in batch):
        try:
            svg_path = export_directory(group_dir, args.output)
        except Exception as exc:
            print(f"导出失败 / Export failed: {group_dir}: {exc}", file=sys.stderr)
            failed = True
        else:
            print(f"已导出 / Exported: {svg_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

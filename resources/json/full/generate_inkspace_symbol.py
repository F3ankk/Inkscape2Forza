import json
import base64
import os
import glob
import io
import numpy as np
from PIL import Image

# Pattern for mask_indicator_dark and mask_indicator_light
MASK_PATTERNS = """
    <pattern patternUnits="userSpaceOnUse" width="11" height="11" preserveAspectRatio="xMidYMid" id="mask_indicator_dark">
      <g id="g9" transform="translate(0.49999999,0.49999999)" style="opacity:1">
        <g data-cell-id="0" id="g8">
          <g data-cell-id="1" id="g7">
            <g data-cell-id="eUeji3bos1076LAfJfyz-17" id="g2">
              <g id="g1">
                <rect x="0" y="0" width="10" height="10" fill="#3b3b3b" stroke="#505050" pointer-events="all" id="rect1" />
              </g>
            </g>
            <g data-cell-id="eUeji3bos1076LAfJfyz-18" id="g4">
              <g id="g3">
                <path d="M 0,10 10,0" fill="none" stroke="#505050" stroke-miterlimit="10" pointer-events="stroke" id="path2" />
              </g>
            </g>
            <g data-cell-id="eUeji3bos1076LAfJfyz-19" id="g5" />
            <g data-cell-id="eUeji3bos1076LAfJfyz-20" id="g6" />
          </g>
        </g>
      </g>
    </pattern>
    <pattern patternUnits="userSpaceOnUse" width="11" height="11" preserveAspectRatio="xMidYMid" id="mask_indicator_light">
      <g id="g9-4" transform="translate(0.49999999,0.49999999)">
        <g data-cell-id="0" id="g8-8">
          <g data-cell-id="1" id="g7-8">
            <g data-cell-id="eUeji3bos1076LAfJfyz-17" id="g1-2" />
            <g data-cell-id="eUeji3bos1076LAfJfyz-18" id="g2-4" />
            <g data-cell-id="eUeji3bos1076LAfJfyz-19" id="g4-5">
              <g id="g3-5">
                <rect x="0" y="0" width="10" height="10" fill="#d1d1d1" stroke="#bdbdbd" pointer-events="all" id="rect2" />
              </g>
            </g>
            <g data-cell-id="eUeji3bos1076LAfJfyz-20" id="g6-1">
              <g id="g5-7">
                <path d="M 0,10 10,0" fill="none" stroke="#bdbdbd" stroke-miterlimit="10" pointer-events="stroke" id="path4" />
              </g>
            </g>
          </g>
        </g>
      </g>
    </pattern>
"""
# ==================================================

def create_jpg_mask(vertices, indices, alphas, min_x, min_y, max_x, max_y, scale_factor=4, max_resolution=4096):
    """
    Create JPG mask from resource
    """
    w = max_x - min_x
    h = max_y - min_y
    if w == 0: w = 1
    if h == 0: h = 1

    scale = float(scale_factor)
    img_w = int(w * scale)
    img_h = int(h * scale)

    # OOM protection
    if max(img_w, img_h) > max_resolution:
        scale = float(max_resolution) / max(w, h)
        img_w = int(w * scale)
        img_h = int(h * scale)

    img_w = max(1, img_w)
    img_h = max(1, img_h)

    img_array = np.zeros((img_h, img_w), dtype=np.float32)

    grid_y, grid_x = np.mgrid[0:img_h, 0:img_w]
    world_x = (grid_x + 0.5) / scale + min_x
    world_y = (grid_y + 0.5) / scale + min_y

    for i in range(0, len(indices), 3):
        idx0, idx1, idx2 = indices[i], indices[i+1], indices[i+2]
        v0, v1, v2 = vertices[idx0], vertices[idx1], vertices[idx2]
        x0, y0 = v0['X'], v0['Y']
        x1, y1 = v1['X'], v1['Y']
        x2, y2 = v2['X'], v2['Y']
        a0, a1, a2 = alphas[idx0], alphas[idx1], alphas[idx2]

        min_ix = max(0, int((min(x0, x1, x2) - min_x) * scale))
        max_ix = min(img_w - 1, int((max(x0, x1, x2) - min_x) * scale) + 1)
        min_iy = max(0, int((min(y0, y1, y2) - min_y) * scale))
        max_iy = min(img_h - 1, int((max(y0, y1, y2) - min_y) * scale) + 1)

        if min_ix > max_ix or min_iy > max_iy:
            continue

        wx = world_x[min_iy:max_iy+1, min_ix:max_ix+1]
        wy = world_y[min_iy:max_iy+1, min_ix:max_ix+1]

        det = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if det == 0:
            continue

        lambda0 = ((y1 - y2) * (wx - x2) + (x2 - x1) * (wy - y2)) / det
        lambda1 = ((y2 - y0) * (wx - x2) + (x0 - x2) * (wy - y2)) / det
        lambda2 = 1.0 - lambda0 - lambda1

        mask = (lambda0 >= -0.005) & (lambda1 >= -0.005) & (lambda2 >= -0.005)

        # drop protection: if the triangle is too small and has no valid pixels, still put a single pixel in the center with average alpha to ensure visibility
        if not np.any(mask):
            center_x = (min_ix + max_ix) // 2
            center_y = (min_iy + max_iy) // 2
            avg_alpha = (a0 + a1 + a2) / 3.0
            img_array[center_y, center_x] = max(img_array[center_y, center_x], avg_alpha)
            continue

        alpha_interp = lambda0 * a0 + lambda1 * a1 + lambda2 * a2
        alpha_interp = np.clip(alpha_interp, 0, 255)

        target_region = img_array[min_iy:max_iy+1, min_ix:max_ix+1]
        target_region[mask] = np.maximum(target_region[mask], alpha_interp[mask])

    img_uint8 = np.clip(img_array, 0, 255).astype(np.uint8)
    img = Image.fromarray(img_uint8)

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=90)
    b64_str = base64.b64encode(buffer.getvalue()).decode('utf-8')
    return b64_str

def build_symbol_library(input_folder, output_filepath):
    json_files = sorted(glob.glob(os.path.join(input_folder, "*.json")))
    if not json_files:
        print("no json files found in the specified folder")
        return

    svg_content = [
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        'width="100%" height="100%">',
        '  <defs>'
    ]

    svg_content.append(MASK_PATTERNS)
    total_shapes = 0

    for file_path in json_files:
        filename = os.path.basename(file_path)
        print(f"processing: {filename} ...")

        with open(file_path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                print(f"{filename} is not a valid JSON file, skipping")
                continue

        for shape in data:
            info = shape.get('Info', {})
            t_type = info.get('Type', 0)
            t_index = info.get('TypeIndex', 0)
            t_word = info.get('ShapeWord', 0)

            symbol_id = f"fh6_t{t_type}_i{t_index}_w{t_word}"

            vertices = shape.get('Vertices', [])
            indices = shape.get('Indices', [])
            if not vertices or not indices:
                continue

            alpha_b64 = shape.get('VerticesAlpha', "")
            has_gradient = False

            if alpha_b64:
                alpha_bytes = base64.b64decode(alpha_b64)

                if len(alpha_bytes) != len(vertices):
                    print(f"  [Warning] Alpha mismatch ({symbol_id}): vertices={len(vertices)}, alpha_bytes={len(alpha_bytes)}.")

                if len(alpha_bytes) > len(vertices):
                    alpha_bytes = alpha_bytes[:len(vertices)]
                elif len(alpha_bytes) < len(vertices):
                    alpha_bytes = alpha_bytes + bytes([255] * (len(vertices) - len(alpha_bytes)))

                non_255_count = sum(1 for a in alpha_bytes if a != 255)
                if non_255_count > 0:
                    has_gradient = True
            else:
                alpha_bytes = bytes([255] * len(vertices))

            # viewBox
            min_x = min(v['X'] for v in vertices)
            max_x = max(v['X'] for v in vertices)
            min_y = min(v['Y'] for v in vertices)
            max_y = max(v['Y'] for v in vertices)

            width = max_x - min_x
            height = max_y - min_y
            if width == 0: width = 1
            if height == 0: height = 1

            svg_content.append(f'    <symbol id="{symbol_id}" '
                               f'viewBox="{min_x} {min_y} {width} {height}" '
                               f'width="{width}" height="{height}">')

            clean_name = filename.replace('.json', '')
            title_suffix = "[gradient]" if has_gradient else ""
            svg_content.append(f'      <title>{clean_name} | {t_type}-{t_index}-{t_word}{title_suffix}</title>')

            b64_img = create_jpg_mask(vertices, indices, alpha_bytes, min_x, min_y, max_x, max_y, scale_factor=4, max_resolution=4000)
            mask_id = f"mask_{symbol_id}"

            svg_content.append(f'      <mask id="{mask_id}" maskUnits="userSpaceOnUse" x="{min_x}" y="{min_y}" width="{width}" height="{height}">')
            svg_content.append(f'        <image xlink:href="data:image/jpeg;base64,{b64_img}" x="{min_x}" y="{min_y}" width="{width}" height="{height}" preserveAspectRatio="none" />')
            svg_content.append(f'      </mask>')

            # Rectangle as background to change color
            svg_content.append(f'      <rect x="{min_x}" y="{min_y}" width="{width}" height="{height}" fill="unset" mask="url(#{mask_id})" />')

            svg_content.append('    </symbol>')
            total_shapes += 1

    svg_content.append('  </defs>')
    svg_content.append('</svg>')

    with open(output_filepath, 'w', encoding='utf-8') as f:
        f.write("\n".join(svg_content))

    print(f"Parsed {total_shapes} shapes, packed into symbol library: {output_filepath}")

if __name__ == "__main__":
    build_symbol_library('.', 'All_fh6_Vinyls_4x.svg')
import math
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from generate_symbol_index import build_index
from inkscape2forza import cgroup_codec, gamesave, library, svg_codec
from inkscape2forza.model import GroupNode, ShapeNode, iter_shapes


class PerformancePathTests(unittest.TestCase):
    def test_group_listing_defers_cgroup_decode(self):
        with tempfile.TemporaryDirectory() as directory:
            group = Path(directory) / 'LayerGroup_0000_example'
            group.mkdir()
            (group / 'C_group').write_bytes(b'not a valid C_group')
            (group / 'header').write_bytes(b'header')
            with patch.object(cgroup_codec, 'recover_pending_cgroup') as recover:
                with patch.object(cgroup_codec, 'parse_header', return_value=('Name', 'Author')):
                    with patch.object(cgroup_codec, 'validate_cgroup_data', side_effect=AssertionError('decoded during listing')):
                        result = gamesave.get_target_layer_groups(directory)
            recover.assert_called_once_with(str(group / 'C_group'))
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]['title'], 'Name')

    def test_shape_extents_need_no_full_symbol_library(self):
        with patch.object(library, '_shape_half_extents_cache', None):
            with patch.object(library, 'load_symbol_library', side_effect=AssertionError('full library loaded')):
                extents = library.load_shape_half_extents()
        self.assertIn(101, extents)
        self.assertGreater(extents[101][0], 0)

    def test_generated_symbol_index_matches_bundled_library(self):
        root = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory) / 'index.py'
            count = build_index(root / 'fh6_vinyl_symbols.svg', generated)
            self.assertGreater(count, 0)
            self.assertEqual(generated.read_bytes(),
                             (root / 'inkscape2forza' / '_symbol_index.py').read_bytes())

    def test_group_metrics_compute_each_shape_once(self):
        items = [ShapeNode(101, 0, index * 20, 0, 1, 1, 0, 1, 2, 3, 255)
                 for index in range(30)]
        nested = GroupNode(children=items)
        for _ in range(5):
            nested = GroupNode(children=[ShapeNode(102, 0, 0, 0, 1, 1, 0, 1, 2, 3, 255), nested])
        root = GroupNode(children=[nested])
        original = cgroup_codec._shape_bounds
        calls = []

        def count_bounds(shape, extents):
            calls.append(id(shape))
            return original(shape, extents)

        with patch.object(cgroup_codec, '_shape_bounds', side_effect=count_bounds):
            cgroup_codec.build_cgroup_payload(root)
        self.assertEqual(len(calls), len(set(calls)))
        self.assertEqual(len(calls), 35)

    def test_cached_group_origins_match_flat_corner_walk(self):
        shapes = [ShapeNode(101, index * 7, index * 12, index * -3,
                            1 + index * 0.02, 0.8, 0.1,
                            1, 2, 3, 255, is_mask=index % 2 == 0)
                  for index in range(12)]
        inner = GroupNode(children=shapes[:6])
        outer = GroupNode(children=[inner, *shapes[6:]])
        root = GroupNode(children=[outer])
        extents = {101: (31.0, 52.0)}
        metrics = cgroup_codec._build_group_metrics(root, extents)

        for group in (inner, outer, root):
            points = []
            for shape in iter_shapes(group):
                a, b, c, d = cgroup_codec.shape_matrix(shape)
                for x, y in ((-31, -52), (31, -52), (31, 52), (-31, 52)):
                    points.append((shape.tx + a * x + c * y,
                                   shape.ty + b * x + d * y))
            expected = ((min(x for x, _ in points) + max(x for x, _ in points)) / 2,
                        (min(y for _, y in points) + max(y for _, y in points)) / 2)
            actual = metrics[id(group)][1]
            self.assertTrue(all(math.isclose(a, b, abs_tol=1e-12)
                                for a, b in zip(expected, actual)))

    def test_root_mask_group_is_encoded_and_inherited(self):
        root = GroupNode(children=[ShapeNode(101, 0, 0, 0, 1, 1, 0,
                                             255, 255, 255, 255)], is_mask_group=True)
        payload = cgroup_codec.build_cgroup_payload(root)
        self.assertEqual(payload[0x1d], cgroup_codec.GROUP_MARKER_MASK)
        decoded = cgroup_codec.decode_cgroup_payload(payload)
        self.assertTrue(decoded.is_mask_group)
        cgroup_codec._assert_encoded_model(root, decoded)

    def test_recovery_scan_without_history_creates_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / 'recovery'
            with patch.object(cgroup_codec, '_recovery_base', return_value=base):
                cgroup_codec.recover_pending_cgroup(Path(directory) / 'C_group')
            self.assertFalse(base.exists())

    def test_overlap_sweep_matches_previous_pairwise_rule(self):
        rng = random.Random(312)

        def pairwise(boxes):
            return all(left[2] <= right[0] or right[2] <= left[0]
                       or left[3] <= right[1] or right[3] <= left[1]
                       for index, left in enumerate(boxes) for right in boxes[:index])

        for count in range(1, 35):
            for _ in range(30):
                boxes = []
                for _ in range(count):
                    x, y = rng.randint(-20, 20), rng.randint(-20, 20)
                    boxes.append((x, y, x + rng.randint(0, 8), y + rng.randint(0, 8)))
                self.assertEqual(svg_codec.boxes_do_not_overlap(boxes), pairwise(boxes))


if __name__ == '__main__':
    unittest.main()

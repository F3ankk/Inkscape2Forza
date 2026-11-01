"""Safety regressions for SVG import and FH6 save writes."""
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from inkscape2forza import cgroup_codec, svg_codec, workflows
from inkscape2forza.common import SVG_NS
from inkscape2forza.model import GroupNode, ShapeNode


def sample_shape(word=101):
    return ShapeNode(word, 25, 120, -75, -1.25, 0.75, 0.1,
                     10, 20, 30, 220, False)


class AuditTests(unittest.TestCase):
    def test_transform_list_supports_adjacent_signed_numbers_and_rejects_garbage(self):
        self.assertEqual(svg_codec.parse_transform('translate(100-50)'),
                         (1, 0, 0, 1, 100, -50))
        for value in ('translate(1,2) bogus', 'translate(1,2,3)',
                      'perspective(1)', 'scale(NaN)'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                svg_codec.parse_transform(value)

    def test_cgroup_rejects_unexpected_trailing_data(self):
        payload = cgroup_codec.build_cgroup_payload(
            GroupNode(children=[sample_shape()]))
        with self.assertRaisesRegex(ValueError, 'trailing data'):
            cgroup_codec.decode_cgroup_payload(payload + b'unknown')

    def test_colors_and_href_priority(self):
        self.assertEqual(svg_codec.parse_css_color('rgba(100%,0%,50%,25%)'),
                         (255, 0, 128, 0.25))
        self.assertEqual(svg_codec.parse_css_color('transparent'), (0, 0, 0, 0.0))
        self.assertEqual(svg_codec.parse_color(
            ET.fromstring('<use fill="currentColor" color="#123456"/>')),
            (18, 52, 86, 255))
        with self.assertRaises(ValueError):
            svg_codec.parse_css_color('unsupported-paint')
        element = ET.fromstring('<use xmlns:xlink="http://www.w3.org/1999/xlink" '
                                'href="#new" xlink:href="#old"/>')
        self.assertEqual(svg_codec.get_href(element), '#new')

    def test_exported_svg_round_trip_without_library_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'vinyl.svg'
            svg_codec.export_group_to_svg(GroupNode(children=[sample_shape()]), path)
            with (patch('inkscape2forza.library.load_symbol_library',
                        side_effect=AssertionError('symbol library reloaded')),
                  patch('inkscape2forza.library.load_pattern_library',
                        side_effect=AssertionError('pattern library reloaded')),
                  patch('inkscape2forza.library.load_shape_half_extents',
                        side_effect=AssertionError('symbol extents reloaded'))):
                original, count = svg_codec.process_svg(path)
            self.assertEqual(count, 1)
            self.assertEqual(original.children[0].shape_word, 101)
            tree = ET.parse(path)
            symbol = next(element for element in tree.getroot().iter()
                          if svg_codec.get_local_name(element) == 'symbol')
            symbol.set('viewBox', '-1 -1 2 2')
            tree.write(path, encoding='utf-8')
            self.assertEqual(svg_codec.process_svg(path)[0].children[0].shape_word, 101)

    def test_symbol_reference_format_shape_word_presence_and_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'invalid.svg'
            root = ET.Element(f'{{{SVG_NS}}}svg', {'viewBox': '0 0 1920 1080'})
            defs = ET.SubElement(root, f'{{{SVG_NS}}}defs')
            symbol = ET.SubElement(defs, f'{{{SVG_NS}}}symbol',
                                   {'id': 'fh6_t1_i1_w101', 'viewBox': '-64 -64 128 128'})
            use = ET.SubElement(root, f'{{{SVG_NS}}}use',
                                {'href': '#fh6_t1_i1_w101'})

            def check(error):
                ET.ElementTree(root).write(path, encoding='utf-8')
                with self.assertRaisesRegex(ValueError, error):
                    svg_codec.process_svg(path)

            use.set('href', '#fh6_t1_i1_w102')
            check('Missing FH6 symbol')
            use.set('href', '#fh6_t1_i1_w9999')
            check('Unknown FH6 ShapeWord')
            use.set('href', '#fh6_t1_w101')
            check('Invalid FH6 symbol ID')
            use.set('href', '#fh6_t1_i1_w101')
            ET.SubElement(defs, f'{{{SVG_NS}}}symbol',
                          {'id': symbol.get('id'), 'viewBox': '-64 -64 128 128'})
            check('duplicate element IDs')

    def test_unrepresentable_css_transform_and_gradient_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'vinyl.svg'
            svg_codec.export_group_to_svg(GroupNode(children=[sample_shape()]), path)
            tree = ET.parse(path)
            use = next(element for element in tree.getroot().iter()
                       if svg_codec.get_local_name(element) == 'use')
            use.set('style', 'fill:#112233;transform:translate(1px)')
            tree.write(path, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Unsupported SVG transform'):
                svg_codec.process_svg(path)
            use.set('style', 'fill:url(#gradient)')
            tree.write(path, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Unsupported SVG paint'):
                svg_codec.process_svg(path)

    def test_overlapping_group_opacity_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'group.svg'
            one = sample_shape()
            two = sample_shape()
            two.tx += 5
            svg_codec.export_group_to_svg(
                GroupNode(children=[GroupNode(children=[one, two])]), path)
            tree = ET.parse(path)
            group = next(element for element in tree.getroot().iter()
                         if svg_codec.get_local_name(element) == 'g')
            group.set('opacity', '0.5')
            tree.write(path, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Group opacity'):
                svg_codec.process_svg(path)

    def test_hidden_reference_image_is_skipped_and_visible_one_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'reference.svg'
            svg_codec.export_group_to_svg(GroupNode(children=[sample_shape()]), path)
            tree = ET.parse(path)
            image = ET.SubElement(tree.getroot(), f'{{{SVG_NS}}}image',
                                  {'style': 'display:none', 'href': 'reference.png'})
            tree.write(path, encoding='utf-8')
            self.assertEqual(svg_codec.process_svg(path)[1], 1)
            image.set('style', 'display:inline')
            tree.write(path, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Unsupported visible SVG element'):
                svg_codec.process_svg(path)

    def test_json_array_and_shape_alias(self):
        self.assertEqual(workflows.json_shape_array([{'type': 1}]), [{'type': 1}])
        with self.assertRaises(ValueError):
            workflows.json_shape_array({'shapes': 'bad'})
        boundary = {'type': 1, 'data': [0, 0, 2048, 2048],
                    'color': [0, 0, 0, 0]}
        art = {'type': 1, 'data': [900, 900, 100, 100],
               'color': [255, 0, 0, 255]}
        self.assertEqual(workflows.geometrize_canvas_marker([boundary, art]), 0)
        self.assertIsNone(workflows.geometrize_canvas_marker([
            {'type': 1, 'data': [0, 0, 10, 10], 'color': [0, 0, 0, 0]}, art]))
        center = workflows.vinylizer_bounds_center([
            {'type': 1, 'data': [0, 0, 100, 100], 'color': [1, 2, 3, 255]},
            {'type': 1, 'data': [100, 0, 10, 10], 'color': [1, 2, 3, 255]},
        ], {1}, 0)
        self.assertEqual(center, (27.5, 0.0))
        payload = cgroup_codec.build_cgroup_payload(GroupNode(children=[sample_shape(3000)]))
        decoded = cgroup_codec.decode_cgroup_payload(payload)
        self.assertEqual(decoded.children[0].shape_word, 3001)

    def test_real_fh6_samples_round_trip_through_svg(self):
        samples = list(Path('ref/lock_sample').rglob('C_group'))
        if not samples:
            self.skipTest('FH6 samples are unavailable')
        for sample in samples:
            with self.subTest(sample=str(sample)), tempfile.TemporaryDirectory() as directory:
                original = cgroup_codec.decode_cgroup_payload(
                    cgroup_codec.unwrap_cgroup_file(sample))
                svg_path = Path(directory) / 'roundtrip.svg'
                svg_codec.export_group_to_svg(original, svg_path)
                exported = ET.parse(svg_path).getroot()
                svg_codec.validate_generated_svg(exported)
                for element in exported.iter():
                    self.assertNotIn(svg_codec.get_local_name(element),
                                     {'title', 'desc', 'metadata'})
                    self.assertFalse(any(name.startswith('data-')
                                         for name in element.attrib))
                imported, _ = svg_codec.process_svg(svg_path)
                cgroup_codec._assert_encoded_model(original, imported)
                encoded = cgroup_codec.build_cgroup_payload(imported)
                decoded = cgroup_codec.decode_cgroup_payload(encoded)
                cgroup_codec._assert_encoded_model(imported, decoded)

    def test_real_vinylizer_json_to_svg_to_cgroup(self):
        source = Path('ref/vinylizer1.0.0_sample/test.json')
        if not source.is_file():
            self.skipTest('Vinylizer sample is unavailable')
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'vinylizer.svg'
            logs = []
            with (patch.object(workflows.ui, 'ask_open_file', return_value=str(source)),
                  patch.object(workflows.ui, 'ask_int', return_value=0),
                  patch.object(workflows.ui, 'ask_save_file', return_value=str(output)),
                  patch.object(workflows.ui, 'log', side_effect=logs.append)):
                workflows.workflow_vinylizer_to_svg()
            self.assertTrue(output.is_file(), '\n'.join(logs))
            model, count = svg_codec.process_svg(output)
            self.assertGreater(count, 0)
            decoded = cgroup_codec.decode_cgroup_payload(
                cgroup_codec.build_cgroup_payload(model))
            cgroup_codec._assert_encoded_model(model, decoded)

    def test_header_failure_rolls_back_and_keeps_original_copies(self):
        source = Path('ref/lock_sample/LayerGroup_0000_20260809103046')
        if not source.is_dir():
            self.skipTest('FH6 sample is unavailable')
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            originals = {name: (source / name).read_bytes()
                         for name in ('C_group', 'header')}
            for name, data in originals.items():
                (target / name).write_bytes(data)
            actual_overwrite = cgroup_codec.overwrite_file_preserving_metadata
            failed = False

            def fail_header(path, replacement, metadata):
                nonlocal failed
                if str(path).endswith('header') and not failed:
                    failed = True
                    raise OSError('simulated Header write failure')
                return actual_overwrite(path, replacement, metadata)

            with patch.object(cgroup_codec, '_recovery_base', return_value=target / 'recovery'):
                with patch.object(cgroup_codec, 'overwrite_file_preserving_metadata',
                                  side_effect=fail_header):
                    with self.assertRaisesRegex(OSError, 'simulated'):
                        cgroup_codec.write_cgroup_file(target / 'C_group',
                                                       GroupNode(children=[sample_shape()]))
                for name, data in originals.items():
                    self.assertEqual((target / name).read_bytes(), data)
                journal = next((target / 'recovery').rglob('journal.json'))
                self.assertEqual(json.loads(journal.read_text())['state'], 'rolled_back')
                self.assertTrue((journal.parent / 'C_group.original').is_file())
                self.assertTrue((journal.parent / 'header.original').is_file())

    def test_successful_write_keeps_file_identity_and_durable_backup(self):
        source = Path('ref/lock_sample/LayerGroup_0000_20260809103046')
        if not source.is_dir():
            self.skipTest('FH6 sample is unavailable')
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            originals = {name: (source / name).read_bytes()
                         for name in ('C_group', 'header')}
            for name, data in originals.items():
                (target / name).write_bytes(data)
            before = {name: cgroup_codec.snapshot_file_metadata(target / name)
                      for name in originals}
            with patch.object(cgroup_codec, '_recovery_base', return_value=target / 'recovery'):
                cgroup_codec.write_cgroup_file(target / 'C_group',
                                               GroupNode(children=[sample_shape()]))
            for name in originals:
                self.assertEqual(cgroup_codec.snapshot_file_metadata(target / name),
                                 before[name])
            journal = next((target / 'recovery').rglob('journal.json'))
            self.assertEqual(json.loads(journal.read_text())['state'], 'committed')
            for name, data in originals.items():
                self.assertEqual((journal.parent / (name + '.original')).read_bytes(),
                                 data)

    def test_failed_rollback_remains_recoverable_on_next_start(self):
        source = Path('ref/lock_sample/LayerGroup_0000_20260809103046')
        if not source.is_dir():
            self.skipTest('FH6 sample is unavailable')
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            originals = {name: (source / name).read_bytes()
                         for name in ('C_group', 'header')}
            for name, data in originals.items():
                (target / name).write_bytes(data)
            actual_overwrite = cgroup_codec.overwrite_file_preserving_metadata

            def block_header(path, replacement, metadata):
                if str(path).endswith('header'):
                    raise PermissionError('simulated persistent Header lock')
                return actual_overwrite(path, replacement, metadata)

            with patch.object(cgroup_codec, '_recovery_base', return_value=target / 'recovery'):
                with patch.object(cgroup_codec, 'overwrite_file_preserving_metadata',
                                  side_effect=block_header):
                    with self.assertRaisesRegex(RuntimeError, 'copies retained'):
                        cgroup_codec.write_cgroup_file(target / 'C_group',
                                                       GroupNode(children=[sample_shape()]))
                journal = next((target / 'recovery').rglob('journal.json'))
                self.assertEqual(json.loads(journal.read_text())['state'], 'prepared')
                cgroup_codec.recover_pending_cgroup(target / 'C_group')
                self.assertEqual(json.loads(journal.read_text())['state'], 'rolled_back')
                for name, data in originals.items():
                    self.assertEqual((target / name).read_bytes(), data)

    def test_partial_cgroup_write_is_rolled_back(self):
        source = Path('ref/lock_sample/LayerGroup_0000_20260809103046')
        if not source.is_dir():
            self.skipTest('FH6 sample is unavailable')
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            originals = {name: (source / name).read_bytes()
                         for name in ('C_group', 'header')}
            for name, data in originals.items():
                (target / name).write_bytes(data)
            actual_overwrite = cgroup_codec.overwrite_file_preserving_metadata
            failed = False

            def partial_write(path, replacement, metadata):
                nonlocal failed
                if str(path).endswith('C_group') and not failed:
                    failed = True
                    with open(path, 'r+b') as target_file:
                        target_file.write(b'broken')
                        target_file.flush()
                    raise OSError('simulated partial C_group write')
                return actual_overwrite(path, replacement, metadata)

            with patch.object(cgroup_codec, '_recovery_base', return_value=target / 'recovery'):
                with patch.object(cgroup_codec, 'overwrite_file_preserving_metadata',
                                  side_effect=partial_write):
                    with self.assertRaisesRegex(OSError, 'partial C_group'):
                        cgroup_codec.write_cgroup_file(target / 'C_group',
                                                       GroupNode(children=[sample_shape()]))
            for name, data in originals.items():
                self.assertEqual((target / name).read_bytes(), data)

    def test_process_termination_after_first_file_is_recovered(self):
        source = Path('ref/lock_sample/LayerGroup_0000_20260809103046')
        if not source.is_dir():
            self.skipTest('FH6 sample is unavailable')
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            originals = {name: (source / name).read_bytes()
                         for name in ('C_group', 'header')}
            for name, data in originals.items():
                (target / name).write_bytes(data)
            script = '''import os, sys
from pathlib import Path
from unittest.mock import patch
from inkscape2forza import cgroup_codec as c
from inkscape2forza.model import GroupNode, ShapeNode
target = Path(sys.argv[1])
real = c.overwrite_file_preserving_metadata
def crash(path, replacement, metadata):
    real(path, replacement, metadata)
    os._exit(77)
root = GroupNode(children=[ShapeNode(101, 0, 0, 0, 1, 1, 0, 1, 2, 3, 255)])
with patch.object(c, '_recovery_base', return_value=target / 'recovery'):
    with patch.object(c, 'overwrite_file_preserving_metadata', side_effect=crash):
        c.write_cgroup_file(target / 'C_group', root)
'''
            process = subprocess.run([sys.executable, '-c', script, str(target)],
                                     cwd=Path(__file__).resolve().parent,
                                     capture_output=True, text=True)
            self.assertEqual(process.returncode, 77, process.stderr)
            self.assertNotEqual((target / 'C_group').read_bytes(), originals['C_group'])
            with patch.object(cgroup_codec, '_recovery_base', return_value=target / 'recovery'):
                cgroup_codec.recover_pending_cgroup(target / 'C_group')
            for name, data in originals.items():
                self.assertEqual((target / name).read_bytes(), data)


if __name__ == '__main__':
    unittest.main()

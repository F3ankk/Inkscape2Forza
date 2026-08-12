import struct
import unittest

from inkscape2forza import cgroup_codec
from inkscape2forza.model import GroupNode, ShapeNode, count_shapes


def shape(word, x, y, *, mask=False):
    return ShapeNode(word, 15.0, x, y, 1.25, 0.75, 0.1,
                     10, 20, 30, 220, is_mask=mask)


class CGroupCodecTests(unittest.TestCase):
    def make_group(self):
        return GroupNode(children=[
            shape(101, 120.0, 240.0),
            GroupNode(children=[
                shape(102, 400.0, 300.0),
                shape(103, 520.0, 420.0, mask=True),
            ]),
        ], name="root")

    def test_generated_container_validates_and_decodes(self):
        root = self.make_group()
        payload = cgroup_codec.build_cgroup_payload(root)
        container = cgroup_codec.wrap_cgroup_payload(payload)

        self.assertEqual(cgroup_codec.validate_cgroup_data(container), payload)
        decoded = cgroup_codec.decode_cgroup_payload(payload)
        self.assertEqual(count_shapes(decoded), 3)
        self.assertEqual([child.shape_word for child in decoded.children
                          if isinstance(child, ShapeNode)], [101])

    def test_rejects_non_group_root_marker(self):
        payload = bytearray(cgroup_codec.build_cgroup_payload(self.make_group()))
        payload[0x1d] = 0x7f

        with self.assertRaisesRegex(ValueError, "root marker"):
            cgroup_codec.validate_cgroup_data(
                cgroup_codec.wrap_cgroup_payload(bytes(payload))
            )

    def test_rejects_trailing_or_truncated_compressed_data(self):
        container = cgroup_codec.wrap_cgroup_payload(
            cgroup_codec.build_cgroup_payload(self.make_group())
        )
        with self.assertRaisesRegex(ValueError, "container"):
            cgroup_codec.validate_cgroup_data(container + b"extra")

        truncated = bytearray(container[:-1])
        struct.pack_into("<I", truncated, 0, len(truncated) - 8)
        with self.assertRaisesRegex(ValueError, "compressed stream"):
            cgroup_codec.validate_cgroup_data(bytes(truncated))


if __name__ == "__main__":
    unittest.main()

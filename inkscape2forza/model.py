"""Shared SVG and C_group models."""
from dataclasses import dataclass, field


@dataclass
class ShapeNode:
    shape_word: int
    rot: float
    tx: float
    ty: float
    sx: float
    sy: float
    skew: float
    r: int
    g: int
    b: int
    a: int
    is_mask: bool = False


@dataclass
class GroupNode:
    children: list = field(default_factory=list)
    is_mask_group: bool = False
    name: str = ""
    tx: float = 0.0
    ty: float = 0.0
    sx: float = 1.0
    sy: float = 1.0
    rot: float = 0.0


def iter_shapes(group):
    """Yield shapes depth-first."""
    stack = list(reversed(group.children))
    while stack:
        child = stack.pop()
        if isinstance(child, GroupNode):
            stack.extend(reversed(child.children))
        else:
            yield child


def count_shapes(group):
    return sum(1 for _ in iter_shapes(group))

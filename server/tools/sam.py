"""Reader and writer for the client's `.sam` animation files (zcAnimNode).

Format, decoded from libjinqu.so (`zcanim_tag_factory::createTag`, the
`zcanim_*::create` readers and the `writeData` writers). All integers are
little-endian 32 bit. A file is a flat list of tags, each starting with

    u32 type, u32 size

The loader ignores `size`; it reads each tag's fields in order by `type`. The
writer emits the size the shipped files carry (for place it is the size of the
full struct: 20 + 24 with a matrix + 40 with a color form).

Tag types:
    1 image   u32 id, cstring name       dictionary entry: id -> atlas frame name
    2 label   cstring name               starts a named section (playSection)
    3 place   see Place below            put or move a sprite on the display list
    4 remove  u32 depth                  remove the sprite at this depth
    5 show    (no fields)                end of frame
    6 handle  u32 width, u32 height, f32 fps, u32 count (first tag, once)
    7 anchor  cstring name               script callback marker (registerScriptAnchor)
    0 end     (no fields)                last tag of the file

Place: u32 char_id, u32 depth, u32 z, u32 has_color, u32 has_matrix, then
    matrix (when has_matrix): 6 f32 a b c d tx ty (cocos2d affine)
    color form (when has_color): u32 has_add, u32 has_mult,
        mult 4 u32 (when has_mult), add 4 u32 (when has_add); 256 is 1.0
`char_id` 0 or less moves the sprite that already sits at `depth`.
"""

import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

END = 0
IMAGE, LABEL, PLACE, REMOVE, SHOW, HANDLE, ANCHOR = range(1, 8)
Matrix = Tuple[float, float, float, float, float, float]
Quad = Tuple[int, int, int, int]


class SamError(ValueError):
    pass


@dataclass(frozen=True)
class Image:
    id: int = 0
    name: str = ""


@dataclass(frozen=True)
class Label:
    name: str = ""


@dataclass(frozen=True)
class Remove:
    depth: int = 0


@dataclass(frozen=True)
class Show:
    pass


@dataclass(frozen=True)
class Handle:
    width: int = 0
    height: int = 0
    fps: float = 24.0
    count: int = 0


@dataclass(frozen=True)
class End:
    pass


@dataclass(frozen=True)
class Anchor:
    name: str = ""


@dataclass(frozen=True)
class ColorForm:
    """Tint of a placed sprite; both parts may be absent (the flag is still set)."""
    mult: Optional[Quad] = None
    add: Optional[Quad] = None


@dataclass(frozen=True)
class Place:
    char_id: int = 0
    depth: int = 0
    z: int = 0
    matrix: Optional[Matrix] = None
    color: Optional[ColorForm] = None


Tag = object  # any of the dataclasses above


@dataclass
class Sam:
    tags: List[Tag] = field(default_factory=list)

    def sections(self):
        """Section name -> [first frame, last frame] (0-based, inclusive)."""
        out, index, label = {}, 0, None
        for tag in self.tags:
            if isinstance(tag, Label):
                label = tag.name
                out.setdefault(label, [index, index])
            elif isinstance(tag, Show):
                if label is not None:
                    out[label][1] = index
                index += 1
        return out

    def frame_count(self) -> int:
        return sum(isinstance(t, Show) for t in self.tags)

    def images(self):
        return {t.id: t.name for t in self.tags if isinstance(t, Image)}


class _Reader:
    def __init__(self, data: bytes):
        self.data, self.pos = data, 0

    def _unpack(self, fmt: str):
        if self.pos + 4 > len(self.data):
            raise SamError("truncated at %d" % self.pos)
        (v,) = struct.unpack_from(fmt, self.data, self.pos)
        self.pos += 4
        return v

    def u32(self) -> int:
        return self._unpack("<I")

    def f32(self) -> float:
        return self._unpack("<f")

    def cstring(self) -> str:
        end = self.data.find(b"\0", self.pos)
        if end < 0:
            raise SamError("unterminated string at %d" % self.pos)
        s = self.data[self.pos:end].decode("utf-8")
        self.pos = end + 1
        return s


def loads(data: bytes) -> Sam:
    r, tags = _Reader(data), []
    while r.pos < len(data):
        start = r.pos
        kind = r.u32()
        r.u32()  # declared size, unused by the loader
        if kind == IMAGE:
            tags.append(Image(id=r.u32(), name=r.cstring()))
        elif kind == LABEL:
            tags.append(Label(name=r.cstring()))
        elif kind == PLACE:
            tags.append(_read_place(r))
        elif kind == REMOVE:
            tags.append(Remove(depth=r.u32()))
        elif kind == SHOW:
            tags.append(Show())
        elif kind == HANDLE:
            tags.append(Handle(width=r.u32(), height=r.u32(), fps=r.f32(), count=r.u32()))
        elif kind == ANCHOR:
            tags.append(Anchor(name=r.cstring()))
        elif kind == END:
            tags.append(End())
        else:
            raise SamError("unknown tag %d at %d" % (kind, start))
    return Sam(tags)


def _read_place(r: _Reader) -> Place:
    char_id, depth, z = r.u32(), r.u32(), r.u32()
    has_color, has_matrix = r.u32(), r.u32()
    matrix = tuple(r.f32() for _ in range(6)) if has_matrix else None
    color = None
    if has_color:
        has_add, has_mult = r.u32(), r.u32()
        mult = tuple(r.u32() for _ in range(4)) if has_mult else None
        add = tuple(r.u32() for _ in range(4)) if has_add else None
        color = ColorForm(mult=mult, add=add)
    return Place(char_id=char_id, depth=depth, z=z, matrix=matrix, color=color)


def dumps(sam: Sam) -> bytes:
    out = bytearray()

    def tag(kind: int, size: int, body: bytes):
        out.extend(struct.pack("<II", kind, size))
        out.extend(body)

    for t in sam.tags:
        if isinstance(t, Image):
            body = struct.pack("<I", t.id) + t.name.encode() + b"\0"
            tag(IMAGE, len(body), body)
        elif isinstance(t, Label):
            body = t.name.encode() + b"\0"
            tag(LABEL, len(body), body)
        elif isinstance(t, Place):
            tag(PLACE, 20 + 24 * (t.matrix is not None) + 40 * (t.color is not None), _write_place(t))
        elif isinstance(t, Remove):
            tag(REMOVE, 4, struct.pack("<I", t.depth))
        elif isinstance(t, Show):
            tag(SHOW, 0, b"")
        elif isinstance(t, Handle):
            tag(HANDLE, 16, struct.pack("<IIfI", t.width, t.height, t.fps, t.count))
        elif isinstance(t, Anchor):
            body = t.name.encode() + b"\0"
            tag(ANCHOR, len(body), body)
        elif isinstance(t, End):
            tag(END, 0, b"")
        else:
            raise SamError("cannot write %r" % (t,))
    return bytes(out)


def _write_place(p: Place) -> bytes:
    body = struct.pack("<5I", p.char_id, p.depth, p.z, int(p.color is not None), int(p.matrix is not None))
    if p.matrix is not None:
        body += struct.pack("<6f", *p.matrix)
    if p.color is not None:
        c = p.color
        body += struct.pack("<II", int(c.add is not None), int(c.mult is not None))
        if c.mult is not None:
            body += struct.pack("<4I", *c.mult)
        if c.add is not None:
            body += struct.pack("<4I", *c.add)
    return body


def load(path: str) -> Sam:
    with open(path, "rb") as fh:
        return loads(fh.read())


def save(sam: Sam, path: str) -> None:
    with open(path, "wb") as fh:
        fh.write(dumps(sam))

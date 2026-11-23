"""Slice Cocos2d-x atlases (.pvr.ccz + .plist) into PNG parts.

Usage: ccz2png.py <anim_dir> <out_dir> <name> [<name> ...]
       ccz2png.py <anim_dir> <out_dir> --characters <character_detail.config>
Writes <out_dir>/<name>/<name>_atlas.png and every frame listed in the plist.
"""
import json, os, plistlib, re, struct, sys, zlib
import numpy as np
from PIL import Image

def load_atlas(path):
    b = open(path, 'rb').read()
    if b[:4] != b'CCZ!':
        raise ValueError('not CCZ')
    d = zlib.decompress(b[16:])
    hs, h, w, _, flags, _, bpp = struct.unpack('<7I', d[:28])
    fmt = flags & 0xff
    if fmt == 0x10 and bpp == 16:  # RGBA4444
        v = np.frombuffer(d, dtype='<u2', count=w * h, offset=hs).reshape(h, w)
        rgba = np.stack([(v >> s & 15) * 17 for s in (12, 8, 4, 0)], -1).astype(np.uint8)
    elif fmt == 0x12 and bpp == 32:  # RGBA8888
        rgba = np.frombuffer(d, dtype=np.uint8, count=w * h * 4, offset=hs).reshape(h, w, 4)
    else:
        raise ValueError(f'unsupported PVR flags={flags:#x} bpp={bpp}')
    return Image.fromarray(rgba, 'RGBA')

def find_atlas(src, name):
    for suffix in ('-hd.pvr.ccz', '.pvr.ccz'):
        p = os.path.join(src, name + suffix)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f'{name}: no .pvr.ccz')

def slice_one(src, out, name):
    if os.path.exists(os.path.join(out, name, name + '_atlas.png')):
        return 0  # already done
    im = load_atlas(find_atlas(src, name))
    plist = plistlib.load(open(os.path.join(src, name + '.plist'), 'rb'))
    dst = os.path.join(out, name)
    os.makedirs(dst, exist_ok=True)
    im.save(os.path.join(dst, name + '_atlas.png'))
    for key, v in plist['frames'].items():
        x, y, w, h = map(int, re.findall(r'-?\d+', v['frame']))
        if v.get('rotated'):
            w, h = h, w
        part = im.crop((x, y, x + w, y + h))
        if v.get('rotated'):
            part = part.rotate(90, expand=True)
        part.save(os.path.join(dst, os.path.basename(key)))
    return len(plist['frames'])

def main(argv):
    src, out, *rest = argv
    if rest[0] == '--characters':
        cfg = json.load(open(rest[1]))
        names = sorted({v['animation'] for v in cfg.values() if v.get('animation')})
    else:
        names = rest
    done = failed = parts = 0
    for name in names:
        try:
            parts += slice_one(src, out, name); done += 1
        except Exception as e:
            failed += 1; print(f'FAIL {name}: {e}')
    print(f'done {done}, failed {failed}, sprites {parts}')

if __name__ == '__main__':
    main(sys.argv[1:])

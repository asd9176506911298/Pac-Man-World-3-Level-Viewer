import struct, sys, os, glob, json, re

# =========================================================
# Pac-Man World 3 (PC) level data extractor
# Extracts, per level/map:
#   - collision meshes (vertices + triangle faces) from "c_" prefixed
#     entries inside *sectorNN.pc / *world.pc containers
#   - entity/trigger placement data (position, rotation, bounding box)
#     from the scene serialization format found in *_fet.pc / *_fetm.pc
#     / *_world.pc single-content files
#
# Requires the .pc files to already be extracted from AllPaks.pc using
# QuickBMS with a Blitz Games engine script (blitz_games.bms).
# =========================================================

# ---------- container parsing ----------

def read_header(data):
    ts, align, zero, files, info_off, texr_off, zero2, dummy, offset3, dummy2, names_off, names_size = struct.unpack('<12I', data[0:48])
    return files, info_off*align, names_off*align, names_size, align

def list_entries(data):
    """List all named sub-entries inside a multi-file .pc container."""
    files, info_off, names_off, names_size, align = read_header(data)
    names_blob = data[names_off:names_off+names_size]
    pos = info_off
    entries = []
    for i in range(files):
        off, crc, size, name_off, is_file, zero_, crc_lo, crc_hi = struct.unpack('<8I', data[pos:pos+32])
        pos += 32
        off *= align
        name = names_blob[name_off:].split(b'\x00')[0].decode(errors='replace') if name_off < names_size else ''
        entries.append((name, off, size))
    return entries

def extract_single_content(data):
    """For single-content containers (fet/fetm/world scene files): return
    the actual payload bytes (skipping the internal FilenameTable.pak.sys index)."""
    files, info_off, names_off, names_size, align = read_header(data)
    if files == 0:
        return data[0x800:]
    names_blob = data[names_off:names_off+names_size]
    pos = info_off
    for i in range(files):
        off, crc, size, name_off, is_file, zero_, crc_lo, crc_hi = struct.unpack('<8I', data[pos:pos+32])
        pos += 32
        off *= align
        name = names_blob[name_off:].split(b'\x00')[0].decode(errors='replace') if name_off < names_size else ''
        if name.endswith('.pak.sys'):
            continue
        return data[off:off+size]
    return b''

# ---------- entity/trigger boxes (tag-value scene serialization) ----------

def scan_tags(content):
    """Walk a scene-data blob and pull out every typed value we recognise:
    0x06 = float32, 0x07 = null-terminated string."""
    out = []
    i = 0
    n = len(content)
    while i < n:
        b = content[i]
        if b == 0x06 and i + 5 <= n:
            val = struct.unpack('<f', content[i+1:i+5])[0]
            out.append((i, 'float', val))
            i += 5
        elif b == 0x07:
            j = i + 1
            s = bytearray()
            while j < n and content[j] != 0 and len(s) < 64:
                c = content[j]
                if 32 <= c < 127:
                    s.append(c)
                else:
                    break
                j += 1
            if j < n and content[j] == 0 and 1 <= len(s) <= 64:
                out.append((i, 'string', s.decode()))
                i = j + 1
            else:
                i += 1
        else:
            i += 1
    return out

def extract_boxes(entries, source_name):
    """Group runs of 16 consecutive floats into entity transforms:
    position(3) + scale(3) + quaternion(4) + bbox_min(3) + bbox_max(3)."""
    boxes = []
    i = 0
    n = len(entries)
    recent_strings = []
    while i < n:
        off, typ, val = entries[i]
        if typ == 'string':
            recent_strings.append((off, val))
            if len(recent_strings) > 4:
                recent_strings.pop(0)
            i += 1
            continue
        j = i
        run = []
        while j < n and entries[j][1] == 'float':
            run.append(entries[j][2])
            j += 1
        if len(run) >= 16:
            vals = run[:16]
            pos = vals[0:3]
            scale = vals[3:6]
            quat = vals[6:10]
            bmin = vals[10:13]
            bmax = vals[13:16]

            def sane(nums, limit=50000):
                """Reject NaN / absurd-magnitude values (usually noise
                from scanning unrelated binary data)."""
                for v in nums:
                    if v != v:
                        return False
                    if abs(v) > limit:
                        return False
                return True

            if not (sane(pos) and sane(bmin) and sane(bmax) and sane(scale, 10000) and sane(quat, 10)):
                i = j
                continue
            cls = recent_strings[-2][1] if len(recent_strings) >= 2 else '?'
            name = recent_strings[-1][1] if recent_strings else '?'
            boxes.append({
                'class': cls, 'name': name,
                'pos': pos, 'scale': scale, 'quat': quat,
                'bbox_min': bmin, 'bbox_max': bmax, 'source': source_name
            })
        i = j if j > i else i + 1
    return boxes

# ---------- collision mesh ----------

def parse_collision_mesh(data):
    """Parse a 'c_' prefixed collision-mesh blob.
    Layout (validated against real game data):
      0x60: uint32[4] = [vertex_offset, normal_offset, index_offset, end_offset]
      vertex block:  N * float3  (12 bytes/vertex)
      normal block:  N * float3  (12 bytes/face, one normal per triangle)
      index block:   N * 8x uint16 (16 bytes/face; first 3 shorts = triangle indices)
    Returns (verts, faces) or None if the data doesn't match this layout."""
    if len(data) < 0x70:
        return None
    try:
        off_vert, off_norm, off_idx, off4 = struct.unpack('<4I', data[0x60:0x70])
    except struct.error:
        return None
    if not (0 < off_vert < off_norm < off_idx < off4 <= len(data)):
        return None
    vcount = (off_norm - off_vert) // 12
    fcount_a = (off_idx - off_norm) // 12
    fcount_b = (off4 - off_idx) // 16
    if vcount <= 0 or fcount_a <= 0 or fcount_a != fcount_b:
        return None
    verts = []
    for i in range(vcount):
        o = off_vert + i*12
        verts.append(struct.unpack('<3f', data[o:o+12]))
    faces = []
    for i in range(fcount_a):
        o = off_idx + i*16
        h = struct.unpack('<8H', data[o:o+16])
        a, b, c = h[0], h[1], h[2]
        if a >= vcount or b >= vcount or c >= vcount:
            return None
        faces.append((a, b, c))
    return verts, faces

# ---------- map/level name grouping ----------

SUFFIX_PATTERNS = [
    r'_sector[\s_]*\d+.*$',
    r'_sector[\s_]*maze\d+.*$',
    r'_maze\d+.*$',
    r'_vista.*$',
    r'_cutscenesector\d*$',
    r'_world$',
    r'_fetm$',
    r'_fet$',
    r'_timeline\d*$',
    r'_collectorscardslarge\d*$',
]

def map_name_of(fname):
    """Strip known suffixes (_sectorNN, _world, _fet, _fetm, etc.) so all
    files belonging to the same level are grouped under one map name."""
    base = fname[:-3] if fname.lower().endswith('.pc') else fname
    for pat in SUFFIX_PATTERNS:
        base2 = re.sub(pat, '', base, flags=re.IGNORECASE)
        if base2 != base:
            base = base2
    return base.strip()

# ---------- main ----------

if __name__ == '__main__':
    src_dir = r"E:\Games\Pac-Man World 3\output"
    if len(sys.argv) > 1:
        src_dir = sys.argv[1]

    pc_files = sorted(glob.glob(os.path.join(src_dir, "*.pc")))
    if not pc_files:
        print(f"No .pc files found in {src_dir}")
        sys.exit(1)

    groups = {}
    for path in pc_files:
        fname = os.path.basename(path)
        name = map_name_of(fname)
        groups.setdefault(name, []).append(path)

    out_dir = os.path.join(src_dir, "level_data")
    os.makedirs(out_dir, exist_ok=True)

    print(f"Detected {len(groups)} map groups\n")

    written_maps = []
    for mapname, paths in sorted(groups.items()):
        meshes = []
        boxes = []
        for path in paths:
            fname = os.path.basename(path)
            data = open(path, 'rb').read()
            lower = fname.lower()

            if lower.endswith('_fet.pc') or lower.endswith('_fetm.pc') or lower.endswith('_world.pc'):
                # try as a single-content scene file (entity/trigger data)
                try:
                    content = extract_single_content(data)
                    tags = scan_tags(content)
                    bx = extract_boxes(tags, fname)
                    boxes.extend(bx)
                except Exception:
                    pass

            # also try as a multi-entry container (collision meshes live in
            # sector files, and occasionally in world files too)
            try:
                entries = list_entries(data)
                for name, off, size in entries:
                    if not name.startswith('c_'):
                        continue
                    chunk = data[off:off+size]
                    result = parse_collision_mesh(chunk)
                    if result:
                        v, f = result
                        meshes.append({
                            'name': name, 'source': fname,
                            'verts': [list(p) for p in v],
                            'faces': [list(t) for t in f]
                        })
            except Exception:
                pass

        if not meshes and not boxes:
            continue

        out_path = os.path.join(out_dir, mapname + '.json')
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump({'map': mapname, 'meshes': meshes, 'boxes': boxes}, f)

        total_verts = sum(len(m['verts']) for m in meshes)
        print(f"{mapname:30s}  meshes={len(meshes):3d} (verts={total_verts:6d})  boxes={len(boxes):5d}  -> {mapname}.json")
        written_maps.append(mapname)

    manifest_path = os.path.join(out_dir, 'manifest.json')
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(sorted(written_maps), f)

    print(f"\nDone. Output written to: {out_dir}")
    print(f"manifest.json lists {len(written_maps)} maps for the auto-loading viewer.")
    print("Open level_viewer.html and load any .json file from this folder to view that map.")

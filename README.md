# Pac-Man World 3 (PC) — Level Data Extractor & Viewer

Reverse-engineered tools for extracting level collision geometry and
entity/trigger placement data from **Pac-Man World 3 (PC, 2005, Blitz
Games)**, and viewing it in the browser. Built for speedrunning research
(collision shapes, trigger volumes, spawn points, portals, etc.).

**Live demo:** load any `level_data/*.json` file into `level_viewer.html`
to explore a level in 3D — rotate, pan, zoom, click any box for details.

## What this extracts

For each level, two kinds of data are pulled out of the game's `.pc`
archive files:

- **Collision meshes** — the simplified geometry the game engine uses for
  walls/floors/platforms (vertices + triangle faces), per room.
- **Entity/trigger boxes** — every placed object's position, rotation,
  scale, and local bounding box: triggers, portals, lights, checkpoints,
  props, etc. Class and instance names come straight from embedded engine
  strings (`TVTrigger`, `CardTrigger`, `dynamic_light`, `portal`, ...).

This does **not** include textured visual geometry — only collision-level
detail. See [Format notes](#format-notes) below for why.

## Usage

### 1. Extract the archive

You need [QuickBMS](https://aluigi.altervista.org/quickbms.htm) and a
Blitz Games engine script (`blitz_games.bms`, available from Luigi
Auriemma's script collection / ZenHAX).

```powershell
quickbms.exe blitz_games.bms AllPaks.pc output
```

This unpacks ~330 `.pc` files (one per level sector / entity table /
asset pack) into the `output` folder.

### 2. Run the extractor

```powershell
python extract_level_data.py "path\to\output"
```

This scans every `.pc` file, groups them by level (`gogekka_2`,
`mountains_1`, `erwins_pit`, ...), and writes one combined
`level_data/<map>.json` per level containing both the collision meshes
and the entity boxes.

### 3. View it

Open `level_viewer.html` in any browser (works locally via `file://`, or
hosted on GitHub Pages) and load one of the generated JSON files.

- Left-drag: rotate · Right-drag: pan · Scroll: zoom
- Click a box to see its class, name, source file, position and bounds
- Toggle mesh/box visibility, adjust mesh opacity, click legend entries
  to hide/show a specific object class

## Format notes

The game's `.pc` archive format uses a consistent container header
(magic/hash, alignment, entry count, info-table offset, name-table
offset) wrapping either:

- a **multi-entry index** (sector packs: textures, meshes, collision
  data, all as named sub-entries), or
- a **single payload** (scene/entity definition files: `_fet.pc`,
  `_fetm.pc`, `_world.pc`), which uses a simple tag-value serialization
  (`0x06` = float32, `0x07` = null-terminated string) for entity trees.

**Collision meshes** (`c_`-prefixed entries) have a clean, validated
layout: a 4×uint32 offset table at `0x60` pointing to a vertex block
(float3 × N), a face-normal block (float3 × N), and an index block
(8×uint16 per face, first 3 = triangle indices). This was fully
reverse-engineered and cross-checked against the header's bounding box
and every triangle index (100% in-range across all tested files).

**Visual/textured meshes** (`*_levelmesh.lit`, `m_`-prefixed prop
models) use a different, more complex vertex format — a mix of full
float positions and 8-bit compressed normals/tangents (`0x7f7f7f7f`
signature) — which was **not** fully solved. That's why this toolset
only outputs collision-level geometry, not textured visuals.

## Files

| File | Purpose |
|---|---|
| `extract_level_data.py` | Batch extractor — run against the QuickBMS output folder |
| `level_viewer.html` | Three.js-based browser viewer, no server required |

## Credits

- Format reverse engineering & extraction tooling: built with Claude (Anthropic) AI assistance
- Archive extraction: [QuickBMS](https://aluigi.altervista.org/quickbms.htm) + community `blitz_games.bms` script

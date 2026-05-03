---
name: grid-layout-enforcer
description: Use when changing GremlinBoard layout or resizing logic.
---

Preserve the grid system.

The board can scale from 4 to 8 columns based on available width.

Allowed sizes only:
- 1x1
- 1x2
- 2x2
- 4x2
- 2x4
- 4x4

Rules:
- snap to grid
- no freeform resize
- resize from widget corners only
- show dashed allowed-size previews during resize
- move from the top widget band, excluding corners
- keep spacing consistent
- preserve alignment across all board states

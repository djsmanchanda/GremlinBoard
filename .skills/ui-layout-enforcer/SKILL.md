---
name: ui-layout-enforcer
description: Use when modifying GremlinBoard UI/grid/layout.
---

Maintain strict grid ratios.

The board may scale from 4 to 8 columns based on available width.

Allowed:
1x1
1x2
2x2
4x2
2x4
4x4

Do NOT introduce arbitrary scaling.

Snap-to-grid mandatory.

Resize interaction belongs on the widget corner, not in a size button strip.

Show dashed outlines for allowed resize targets and highlight the nearest target while resizing.

Move interaction belongs to the top 5-10% of the widget, excluding corners.

Keep widget chrome minimal. Use the board-level Stats overlay for freshness, uptime, mode, and restarts.

Maintain visual harmony, spacing, and high-density data display.

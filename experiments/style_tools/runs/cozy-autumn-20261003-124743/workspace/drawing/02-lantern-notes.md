# Asset 02 — lantern and pumpkin

Deliverable: `artifacts/02-lantern.png`
Rebuild: `python drawing/lantern.py`
Editable source: `drawing/lantern.py`, using unchanged `drawing/autumn.py`.

Read STYLE.md and the palette PNG and inspected the pinned style profile. Inspected asset 01 through its full-resolution pixel counts and editable composition source. Reused its exact six reference inks, 768px artboard, 4px cocoa contours, 2–3px details, rounded curves, olive/oat V-stitch knitting, ribbing, tassels and lobed leaves. No rendered-image viewer was available, so visual review was limited to source and pixel inspection.

Composition: arch-handled chestnut lantern with oat glass, cream light field, orange flame and cream flame core; organic ribbed orange pumpkin with olive bent stem; folded olive scarf below; five scattered autumn leaves. Cream background with no text or enclosing card. Main illustration bounds: (84,149)–(662,657), similar to the first asset's scale.

Validation:
- Nonblank, 768×768, opaque RGB PNG.
- Direct full-resolution inspection confirms exactly the six colors in references/autumn-palette.png.
- Final style_check: measured_checks_passed=true, outside_palette_fraction=0.0659 (below 0.10 threshold).
- Advisory brightness 0.8197 exceeds the palette swatch's 0.5131, consistent with a cream-background illustration.
- Checker reports intermediate sampled colors even though they are not present in the saved image pixels. A palette application was performed to a separate preserved output, artifacts/02-lantern-palette-checked.png; its automatic recheck also passes and reports the same outside-palette fraction. The requested main image retains the exact reference colors to match asset 01, rather than the pinned profile's slightly different extracted centroids.
- artifacts/02-lantern-antialiased-original.png preserves the render before exact six-color quantization.

Palette checks do not establish semantic style, composition or artistic quality. No reference, target or first-asset file was modified.

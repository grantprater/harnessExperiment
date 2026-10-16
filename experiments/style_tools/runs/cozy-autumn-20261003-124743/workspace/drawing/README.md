# Cozy autumn illustration vocabulary

Rebuild asset 1 from the workspace root:

    python drawing/reading.py

`autumn.py` supplies the exact six inks sampled from references/autumn-palette.png, a cream RGB canvas, cubic paths, round-ended strokes, and a reusable lobed leaf. Artboard: 768 square. Main outlines: 4px; secondary details: 2–3px. Rounded flat shapes, no lettering, broad negative space. Keep these conventions for asset 2.

Outputs:
- artifacts/01-reading.png — opaque RGB, 768×768, exactly six reference colors.
- artifacts/01-reading-antialiased-original.png — preserved supersampled render before exact-palette mapping.

Composition: steaming orange ceramic mug on oat saucer above/right of an open cream book; olive knitted throw behind, with ribbing and tassels; five fallen leaves arranged asymmetrically around the reading vignette.

Validation: final style_check reported measured_checks_passed=true. It still reported 6.9% outside-palette samples, despite direct full-resolution Pillow inspection confirming precisely the six reference colors; intermediate sampled colors are therefore not present as pixels in the saved PNG. Brightness is advisory and above the swatch reference, consistent with the brief's cream background and breathing room. Automated checking does not judge composition/theme. No rendered-image visual inspection tool was available in this session.

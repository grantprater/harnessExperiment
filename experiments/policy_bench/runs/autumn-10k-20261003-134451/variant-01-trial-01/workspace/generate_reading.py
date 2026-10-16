"""Cozy autumn / 01: a quiet reading corner.
Editable, dependency-free (apart from Pillow) vector-like drawing vocabulary.
Coordinates are in a shared 768-square artboard; all strokes have round joins.
Run: python generate_reading.py
"""
from pathlib import Path
import math
import re
from collections import Counter
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
PALETTE = {
    'cream': (244, 230, 206), 'oat': (218, 180, 131),
    'orange': (186, 108, 54), 'chestnut': (125, 63, 40),
    'cocoa': (70, 50, 38), 'olive': (122, 120, 78),
}
SCALE = 3

class Canvas:
    """Small reusable flat-illustration vocabulary: paths, strokes and ellipses."""
    def __init__(self):
        self.image = Image.new('RGB', (768*SCALE, 768*SCALE), PALETTE['cream'])
        self.draw = ImageDraw.Draw(self.image)

    def path(self, data, fill=None, stroke='cocoa', width=4):
        tokens = re.findall(r'[MLCQZ]|-?\d+(?:\.\d+)?', data)
        points, cursor, start = [], (0, 0), (0, 0)
        i = 0
        while i < len(tokens):
            cmd = tokens[i]; i += 1
            if cmd == 'Z':
                points.append(start); cursor = start
                continue
            count = {'M':2, 'L':2, 'C':6, 'Q':4}[cmd]
            vals = list(map(float, tokens[i:i+count])); i += count
            if cmd in ('M','L'):
                cursor = tuple(vals); points.append(cursor)
                if cmd == 'M': start = cursor
            else:
                p0 = cursor
                if cmd == 'C':
                    p1,p2,p3 = tuple(vals[:2]),tuple(vals[2:4]),tuple(vals[4:])
                    for j in range(1, 33):
                        t=j/32; u=1-t
                        points.append(tuple(u**3*p0[k]+3*u*u*t*p1[k]+3*u*t*t*p2[k]+t**3*p3[k] for k in (0,1)))
                    cursor=p3
                else:
                    p1,p2=tuple(vals[:2]),tuple(vals[2:])
                    for j in range(1,25):
                        t=j/24; u=1-t
                        points.append(tuple(u*u*p0[k]+2*u*t*p1[k]+t*t*p2[k] for k in (0,1)))
                    cursor=p2
        pts=[(round(x*SCALE),round(y*SCALE)) for x,y in points]
        if fill: self.draw.polygon(pts, fill=PALETTE[fill])
        if stroke:
            w=round(width*SCALE)
            self.draw.line(pts, fill=PALETTE[stroke], width=w, joint='curve')
            r=w/2
            for x,y in (pts[0],pts[-1]):
                self.draw.ellipse((x-r,y-r,x+r,y+r),fill=PALETTE[stroke])

    def ellipse(self, box, fill, stroke=None, width=4):
        self.draw.ellipse(tuple(round(v*SCALE) for v in box), fill=PALETTE[fill],
                          outline=PALETTE[stroke] if stroke else None, width=round(width*SCALE))

    def leaf(self, x, y, size, angle, color):
        """Curved almond leaf and a single delicate vein, rotated about its stem."""
        a=math.radians(angle)
        def p(u,v):
            return (x+size*(u*math.cos(a)-v*math.sin(a)),
                    y+size*(u*math.sin(a)+v*math.cos(a)))
        def coords(u,v):
            px,py=p(u,v); return f'{px:.2f} {py:.2f}'
        self.path(f'M {coords(0,0)} C {coords(-.5,-.4)} {coords(-.43,-.95)} {coords(0,-1.3)} C {coords(.45,-.91)} {coords(.46,-.42)} {coords(0,0)} Z',color,width=3)
        self.path(f'M {coords(0,.22)} Q {coords(-.03,-.4)} {coords(0,-1.02)}',stroke='cocoa',width=2.5)
        self.path(f'M {coords(0,-.39)} L {coords(-.21,-.65)} M {coords(0,-.66)} L {coords(.20,-.88)}',stroke='cocoa',width=2)

    def save(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.image.resize((768,768), Image.Resampling.LANCZOS).save(path)


def render():
    # Read the supplied raster reference, and verify the six working inks occur.
    reference = Image.open(ROOT/'references/autumn-palette.png').convert('RGB')
    counts = Counter(reference.getdata())
    print('Reference colors:', counts.most_common(6))
    assert all(c in counts for c in PALETTE.values())
    c=Canvas()
    # Broad, unoutlined grounding shape keeps the scene airy rather than card-like.
    c.path('M 125 525 C 151 462 291 461 414 471 C 553 478 660 525 648 576 C 635 637 432 660 276 636 C 181 622 111 580 125 525 Z', 'oat', None)

    # Blanket: a gently folded olive knit, with a turned-over cuff and fringe.
    c.path('M 441 304 C 486 285 530 284 590 311 Q 614 322 618 351 L 656 552 Q 661 572 640 579 L 486 610 Q 470 614 466 596 L 425 337 Q 420 315 441 304 Z','olive')
    c.path('M 441 304 C 486 288 542 295 589 314 Q 600 318 602 332 L 609 364 C 555 341 495 342 433 357 L 425 337 Q 420 315 441 304 Z','oat')
    c.path('M 435 347 C 493 332 552 333 605 354',stroke='cocoa',width=2.5)
    # Regular paired knit loops, sparse enough to read as fabric, not noise.
    for row in range(6):
        for col in range(7):
            x=454+col*23+row*5; y=374+row*32+col*1.6
            c.path(f'M {x} {y} Q {x-8} {y+7} {x+2} {y+14} Q {x+12} {y+4} {x+8} {y-1}',stroke='oat',width=2)
    c.path('M 485 593 L 640 563',stroke='cocoa',width=2.5)
    for j in range(12):
        x=491+j*13; y=606-j*2.45
        c.path(f'M {x} {y} Q {x+3} {y+10} {x+4} {y+17}',stroke='cocoa',width=3)

    # Saucer and rounded ceramic mug. Handle is behind the vessel.
    c.ellipse((202,401,404,454),'chestnut','cocoa')
    c.ellipse((216,406,391,440),'oat','cocoa',3)
    c.path('M 356 323 C 421 307 431 383 388 399 L 357 402 L 357 382 L 377 382 C 404 375 402 337 361 345 Z','orange')
    c.path('M 224 314 L 230 392 C 232 417 252 430 290 432 C 331 434 358 420 361 396 L 369 314 Z','orange')
    # Warm glazed highlight, restrained leaf motif and lower contour.
    c.path('M 240 340 L 244 382 Q 246 393 253 398',stroke='oat',width=6)
    c.path('M 272 408 Q 307 418 335 405',stroke='chestnut',width=3)
    c.ellipse((224,293,369,335),'oat','cocoa',4)
    c.ellipse((238,303,356,325),'chestnut','cocoa',2.5)
    c.path('M 251 310 C 277 301 313 302 339 310',stroke='orange',width=3)
    c.leaf(300,391,27,27,'oat')
    # Three unhurried steam ribbons.
    c.path('M 259 278 C 229 254 277 240 261 218 C 254 208 249 202 254 192',stroke='chestnut',width=4)
    c.path('M 295 273 C 318 246 276 232 296 206 C 308 191 310 180 302 168',stroke='chestnut',width=4)
    c.path('M 333 279 C 357 260 330 246 340 229',stroke='chestnut',width=4)

    # Open book: thick curved cover, page block, bowed sheets and a central gutter.
    c.path('M 156 439 C 223 424 281 430 348 461 C 398 430 463 424 525 443 L 555 584 Q 553 594 542 596 C 458 581 402 586 350 613 C 286 584 228 578 157 596 Q 144 595 146 582 Z','chestnut')
    c.path('M 163 438 C 230 419 288 438 348 461 C 406 433 464 424 518 440 L 544 580 C 470 564 409 578 350 602 C 287 575 225 567 156 583 Z','oat')
    c.path('M 173 422 C 235 413 287 429 348 453 C 408 428 461 412 509 423 L 534 565 C 473 553 410 566 349 591 C 288 565 231 551 162 563 Z','cream')
    # Individual page edges underneath, not lettering.
    c.path('M 160 574 C 229 559 289 578 338 595 M 361 594 C 422 570 477 564 540 577',stroke='chestnut',width=2)
    c.path('M 348 453 Q 339 517 349 591',stroke='cocoa',width=3)
    c.path('M 356 457 Q 349 516 357 580',stroke='oat',width=3)
    # Long bowed impressions on paper emphasize the open page surfaces.
    for offset in (0,21,42):
        c.path(f'M 193 {449+offset} C 237 {445+offset} 282 {458+offset} 319 {473+offset}',stroke='oat',width=2.5)
        c.path(f'M 378 {473+offset} C 414 {456+offset} 458 {443+offset} 488 {448+offset}',stroke='oat',width=2.5)
    # Cloth bookmark descends out of the spine.
    c.path('M 371 586 L 389 580 L 399 624 L 387 619 L 379 632 Z','orange',width=3)

    # Scattered autumn leaves balance the scene without boxing it in.
    c.leaf(165,386,43,-47,'orange')
    c.leaf(613,263,39,43,'oat')
    c.leaf(593,656,46,61,'orange')
    c.leaf(181,643,36,-64,'olive')
    c.leaf(126,552,29,-25,'chestnut')
    # A few quiet breeze/seed marks.
    c.path('M 136 421 Q 144 426 154 423',stroke='chestnut',width=2.5)
    c.path('M 572 239 Q 578 230 587 231',stroke='oat',width=3)
    c.ellipse((620,614,626,620),'chestnut')
    c.ellipse((214,662,220,668),'orange')
    c.save(ROOT/'artifacts/01-reading.png')
    print('Created artifacts/01-reading.png (768x768 RGB)')

if __name__ == '__main__':
    render()

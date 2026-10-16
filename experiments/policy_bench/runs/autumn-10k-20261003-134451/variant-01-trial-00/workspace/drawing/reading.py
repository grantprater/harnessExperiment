"""Asset 01: a quiet reading afternoon. Run: python drawing/reading.py"""
from pathlib import Path
from PIL import Image
from autumn import Canvas, PALETTE

ROOT = Path(__file__).resolve().parents[1]
# Read the supplied raster reference, and verify our explicit shared colors.
reference = Image.open(ROOT/'references/autumn-palette.png').convert('RGB')
reference_colors = {rgb for count, rgb in reference.getcolors(reference.width*reference.height)}
assert set(PALETTE.values()).issubset(reference_colors)
c = Canvas()

# A quiet grounding patch, without a frame or enclosing card.
c.ellipse((137,506,646,630),'oat')

# Draped knitted throw, behind the two focal objects.
c.path([('M',446,310),('C',484,286,531,306,575,316),
        ('C',600,322,628,317,637,338),('L',650,530),
        ('C',653,556,619,559,595,567),('L',491,586),
        ('C',469,588,448,575,449,554),('L',431,343),
        ('C',429,327,434,318,446,310),('Z',)],'olive')
# Broad curved fold and bound edge.
c.path([('M',571,320),('C',565,381,586,470,592,542),
        ('C',593,555,583,562,575,568)],None,'cocoa',3)
c.path([('M',461,565),('C',501,578,575,548,639,542)],None,'oat',5)
# Small paired loops communicate knit rather than plaid.
for row in range(10):
    y=337+row*21
    for col in range(7):
        x=454+col*25 + (row%2)*3
        if x>628 or (x>568 and y<345): continue
        c.path([('M',x-5,y-5),('C',x-9,y,x-1,y+5,x,y+8),
                ('C',x+2,y+3,x+9,y,x+6,y-5)],None,'oat',2.3)
# Loose wool tassels.
for x,y in [(495,583),(512,581),(529,578),(546,574),(563,571),(580,567),(600,562),(619,557),(637,551)]:
    c.line([(x,y),(x+2,y+15)],'cocoa',3)
    c.line([(x+6,y-1),(x+7,y+12)],'olive',4)

# Ceramic handle, with the background visible through its hollow center.
c.path([('M',379,278),('C',452,253,465,356,399,376),
        ('L',381,356),('C',429,346,434,288,389,300),('Z',)],'orange',width=4.5)
c.path([('M',398,301),('C',421,292,428,330,402,346)],None,'cream',5)
# Mug silhouette, softened foot and slightly flared lip.
c.path([('M',210,263),('L',395,263),('L',387,388),
        ('C',385,416,357,436,306,436),('C',251,436,223,416,220,390),
        ('Z',)],'orange',width=4.5)
c.path([('M',234,302),('L',240,379),('C',242,397,254,405,265,408)],None,'oat',7)
c.ellipse((210,241,395,287),'oat','cocoa',4.5)
c.ellipse((226,252,380,276),'chestnut','cocoa',3)
c.path([('M',235,265),('C',274,256,332,257,368,265)],None,'orange',3)
# Glaze detail: a small olive sprig, not a logo or text.
c.path([('M',312,396),('C',303,373,315,346,328,324)],None,'cocoa',2.5)
c.path([('M',315,367),('C',291,369,291,345,315,367),('Z',)],'olive',width=2)
c.path([('M',319,350),('C',342,352,344,331,319,350),('Z',)],'olive',width=2)
# Three airy ribbons of rising steam.
for x,y in [(259,216),(304,198),(347,216)]:
    c.path([('M',x,y),('C',x-23,y-26,x+21,y-43,x+5,y-69)],None,'oat',5)

# Open book cover, page block and subtly curved facing pages.
c.path([('M',180,460),('L',196,433),('C',258,423,297,443,335,474),
        ('C',373,450,436,439,490,454),('L',544,559),
        ('C',480,552,419,564,364,595),('C',310,566,256,548,187,554),
        ('Z',)],'chestnut',width=4.5)
c.path([('M',197,444),('C',250,434,297,451,334,481),
        ('C',380,456,435,455,480,463),('L',530,550),
        ('C',469,547,410,564,363,583),('C',309,558,253,539,195,543),('Z',)],'oat',width=3)
c.path([('M',196,433),('C',251,418,297,439,335,466),
        ('C',380,440,429,431,478,440),('L',519,536),
        ('C',462,530,408,543,360,568),('C',310,540,256,524,196,529),('Z',)],'cream',width=4)
c.path([('M',335,466),('C',335,500,347,533,360,568)],None,'cocoa',3.3)
# Sparse curved ink strokes suggest pages; no typographic glyphs.
for j in range(5):
    y=460+j*12
    c.path([('M',218,y),('C',250,y-3,286,y+9,311,y+23)],None,'oat',2.6)
    c.path([('M',362+j*2,y+8),('C',395,y-7,433,y-10,466+j*4,y-7)],None,'oat',2.6)
# Book ribbon draped over the lower edge.
c.path([('M',405,549),('L',418,544),('L',436,587),('L',425,583),
        ('L',419,596),('Z',)],'orange',width=2.5)

# A handful of leaves makes the season explicit without a decorative border.
c.leaf(137,446,-48,71,'orange')
c.leaf(592,249,28,79,'orange')
c.leaf(633,606,-25,69,'chestnut')
c.leaf(197,605,16,58,'olive')
# A few restrained wind/twig accents.
c.path([('M',566,225),('C',550,215,542,220,545,229)],None,'oat',3)
c.line([(118,499),(133,502)],'chestnut',3)
c.line([(572,627),(584,625)],'olive',3)

(ROOT/'artifacts').mkdir(exist_ok=True)
c.save(ROOT/'artifacts/01-reading.png')
print('Saved artifacts/01-reading.png; 768×768 opaque RGB; six reference colors with antialiasing.')

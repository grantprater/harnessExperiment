"""Asset 02: lantern light in autumn. Run: python drawing/lantern.py.
Shared 768px composition, palette, rounded strokes and knit/leaf vocabulary
come from autumn.py and the companion reading illustration. No external assets.
"""
from pathlib import Path
from PIL import Image
from autumn import Canvas, PALETTE

ROOT = Path(__file__).resolve().parents[1]
reference = Image.open(ROOT/'references/autumn-palette.png').convert('RGB')
reference_colors = {rgb for count, rgb in reference.getcolors(reference.width*reference.height)}
assert set(PALETTE.values()).issubset(reference_colors)
c = Canvas()

# Same modest oval grounding patch as the companion; generous cream margins.
c.ellipse((137,506,646,630), 'oat')

# Arched carrying handle, slender and softly rounded.
c.path([('M',239,264),('L',239,214),('C',239,140,360,140,360,214),
        ('L',360,264)], None, 'cocoa', 9)
c.path([('M',240,213),('C',240,157,351,150,359,210)], None, 'chestnut', 3)
# Warm glass chamber. Flat, nested pools of light rather than a gradient.
c.path([('M',225,304),('L',375,304),('L',391,497),
        ('C',371,520,227,520,209,497),('Z',)], 'oat', width=4.5)
c.path([('M',257,324),('C',243,371,240,448,251,484),
        ('C',270,500,330,500,349,484),('C',360,448,357,371,343,324),('Z',)],
       'cream', stroke=None)
# Restrained radiating light marks, using only the six reference colors.
for pts in [[(182,345),(164,334)],[(177,403),(157,403)],[(415,337),(432,324)]]:
    c.line(pts,'oat',4)
# Candle, rolled wax lip, wick and a curved flame.
c.path([('M',277,416),('C',286,412,314,412,323,416),('L',323,484),
        ('L',277,484),('Z',)], 'cream', width=3)
c.ellipse((277,410,323,422),'oat','cocoa',2.5)
c.line([(300,415),(300,399)],width=2.5)
c.path([('M',300,399),('C',273,389,289,366,302,348),
        ('C',301,369,330,390,300,399),('Z',)], 'orange', stroke=None)
c.path([('M',301,393),('C',292,389,296,380,301,373),
        ('C',309,383,310,389,301,393),('Z',)], 'oat', stroke=None)
# Protective ironwork: straight uprights with rounded shoulders and feet.
for x1,x2 in [(225,209),(375,391)]:
    c.line([(x1,309),(x2,493)],'cocoa',8)
    c.line([(x1,315),(x2,487)],'chestnut',3)
c.path([('M',211,302),('C',224,293,233,278,249,268),('L',351,268),
        ('C',367,278,376,293,389,302),('C',358,312,241,312,211,302),('Z',)],
       'chestnut',width=4.5)
c.path([('M',252,267),('L',252,255),('C',253,247,347,247,348,255),
        ('L',348,267),('Z',)],'cocoa',width=3)
c.path([('M',240,291),('C',267,298,332,298,359,291)],None,'oat',3)
c.path([('M',208,493),('C',243,505,357,505,392,493),('L',402,520),
        ('C',402,537,198,537,198,520),('Z',)],'chestnut',width=4.5)
c.path([('M',222,520),('C',259,526,344,526,379,520)],None,'oat',3)

# Squat, asymmetric pumpkin with a bent stem and rounded rib structure.
c.path([('M',510,386),('C',505,368,510,350,525,342),('L',538,352),
        ('C',523,360,525,373,529,387),('Z',)],'olive',width=4)
c.path([('M',519,382),('C',478,360,428,387,420,431),
        ('C',401,493,441,543,512,550),('C',584,560,629,517,627,463),
        ('C',626,407,592,368,552,382),('C',542,376,530,377,519,382),('Z',)],
       'orange',width=4.5)
c.path([('M',488,389),('C',451,408,445,486,475,528)],None,'chestnut',3)
c.path([('M',516,393),('C',496,429,495,510,514,540)],None,'chestnut',3)
c.path([('M',544,393),('C',567,427,569,504,549,536)],None,'chestnut',3)
c.path([('M',572,391),('C',602,412,611,484,586,516)],None,'chestnut',3)
c.path([('M',454,421),('C',444,437,440,457,443,471)],None,'oat',5)
c.path([('M',511,386),('C',520,392,543,392,552,386)],None,'cocoa',3)

# Folded knitted scarf crosses the foreground, soft corners and visible layers.
c.path([('M',219,536),('L',461,513),('C',479,512,484,523,486,537),
        ('L',506,589),('C',511,600,501,609,486,610),('L',253,630),
        ('C',235,632,226,623,225,613),('L',207,558),
        ('C',204,546,208,539,219,536),('Z',)],'olive',width=4.5)
c.path([('M',217,548),('L',447,527),('C',459,526,467,531,470,543),
        ('L',484,576),('C',488,585,482,590,468,592),('L',241,613),
        ('C',226,614,220,607,219,597),('L',207,558)],'olive',width=3)
c.path([('M',238,603),('L',469,582)],None,'oat',4)
# Reuse the small paired knit loops from the reading blanket.
for row in range(3):
    for col in range(9):
        x=234+col*25 + (row%2)*2
        y=555+row*16-(x-234)*0.091
        c.path([('M',x-5,y-5),('C',x-9,y,x-1,y+5,x,y+8),
                ('C',x+2,y+3,x+9,y,x+6,y-5)],None,'oat',2.3)
for x in range(263,488,19):
    y=629-(x-253)*0.086
    c.line([(x,y),(x+3,y+12)],'cocoa',3)
    c.line([(x+6,y-1),(x+9,y+10)],'olive',4)

# Fallen leaves echo the exact silhouettes and veins of asset 01.
c.leaf(153,544,-28,64,'orange')
c.leaf(579,593,24,69,'olive')
c.leaf(629,552,-38,50,'chestnut')
c.leaf(183,624,14,52,'orange')
c.line([(591,643),(607,640)],'chestnut',2.5)
c.ellipse((137,593,142,598),'chestnut')

(ROOT/'artifacts').mkdir(exist_ok=True)
c.save(ROOT/'artifacts/02-lantern.png')
if __name__ == '__main__':
    image = Image.open(ROOT/'artifacts/02-lantern.png')
    assert image.size == (768,768) and image.mode == 'RGB'
    assert len(image.getcolors(768*768)) > 6
    print('Saved opaque 768x768 artifacts/02-lantern.png')

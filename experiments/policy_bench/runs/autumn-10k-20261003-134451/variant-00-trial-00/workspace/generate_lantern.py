"""Asset 02 — lantern, pumpkin and folded scarf.
Run locally with: python generate_lantern.py
Uses the same six sampled colors, 4x antialiasing, curves, cocoa outlines,
leaf shapes and knit stitches as generate_reading.py. No external assets.
"""
from pathlib import Path
from autumn_draw import *

c = Canvas()
# Same low, softly irregular oat ground as the reading still life.
c.path([('M',128,530),('C',128,489,212,471,290,474),('C',390,476,504,448,596,480),('C',660,503,652,567,590,599),('C',496,636,341,628,227,600),('C',159,584,129,560,128,530),('Z',)],OAT,stroke=None)
# Fallen foliage behind the objects.
leaf(c,174,435,-32,.86,ORANGE)
leaf(c,614,388,29,.74,OLIVE)
# Lantern handle: a rounded arch and a quiet metal highlight.
c.path([('M',247,251),('L',247,213),('C',247,150,351,150,351,213),('L',351,251)],stroke=COCOA,width=8)
c.path([('M',255,209),('C',256,164,323,158,340,189)],stroke=OAT,width=2.5)
# Glass chamber, tapering gently towards the domed cap.
c.path([('M',229,278),('L',368,278),('L',386,477),('C',364,496,238,496,215,477),('Z',)],OAT,width=4.5)
# Warm luminous central glass pane, kept flat rather than airbrushed.
c.path([('M',252,295),('L',345,295),('L',354,461),('C',327,470,273,470,244,461),('Z',)],CREAM,width=3)
# Reflections in side glass, matching the mug highlight language.
c.path([('M',236,310),('L',225,449)],stroke=CREAM,width=4)
c.path([('M',361,310),('L',372,450)],stroke=CREAM,width=3)
# Candle tray and rounded candle, with visible wick and flame.
c.ellipse((256,449,344,471),CHESTNUT,COCOA,width=3)
c.path([('M',280,402),('C',286,397,312,397,320,402),('L',322,451),('C',311,458,288,458,278,451),('Z',)],OAT,width=3)
c.path([('M',281,403),('C',288,410,292,399,298,404),('C',304,412,310,404,319,404)],stroke=CREAM,width=3)
c.line([(300,400),(300,389)],COCOA,3)
c.path([('M',300,390),('C',271,376,278,351,300,327),('C',298,346,324,351,319,371),('C',317,382,310,388,300,390),('Z',)],ORANGE,width=3)
c.path([('M',300,381),('C',289,374,294,365,301,356),('C',301,365,310,371,300,381),('Z',)],OAT,stroke=None)
# The two curved cage rails and broad base anchor the lantern.
c.path([('M',250,285),('C',246,344,237,408,238,479)],stroke=COCOA,width=5)
c.path([('M',347,285),('C',351,344,360,408,360,479)],stroke=COCOA,width=5)
c.path([('M',217,476),('C',250,487,351,487,384,476),('L',393,497),('C',395,505,387,511,376,513),('L',224,513),('C',212,511,205,505,207,498),('Z',)],CHESTNUT,width=4.5)
c.path([('M',228,497),('C',261,503,339,503,373,497)],stroke=OAT,width=3)
# Rounded ventilator dome, brim and little top finial.
c.path([('M',232,267),('C',235,243,255,231,275,227),('L',278,217),('C',286,211,312,211,320,217),('L',323,227),('C',347,232,362,247,365,267),('Z',)],OLIVE,width=4.5)
for x in (275,299,323):
    c.line([(x,240),(x,250)],COCOA,3)
c.path([('M',221,263),('C',263,256,337,256,377,263),('L',382,278),('C',336,287,262,287,215,278),('Z',)],CHESTNUT,width=4.5)
c.path([('M',231,272),('C',267,267,333,267,366,272)],stroke=OAT,width=3)
# Pumpkin stem with a curled vine. Body overlaps the lantern's right foot.
c.path([('M',501,380),('C',496,361,501,344,512,332),('L',528,340),('C',516,352,514,366,520,382),('Z',)],OLIVE,width=4)
c.path([('M',525,360),('C',544,341,569,343,568,356),('C',566,367,552,364,556,355)],stroke=OLIVE,width=4)
# Lobed silhouette: organic and squat rather than a perfect oval.
c.path([('M',507,380),('C',478,363,455,368,445,383),('C',406,377,385,414,391,455),('C',393,489,416,522,452,525),('C',471,542,498,542,513,535),('C',541,544,565,532,575,520),('C',609,514,628,484,625,451),('C',632,409,607,379,576,385),('C',554,366,530,369,507,380),('Z',)],ORANGE,width=4.5)
# Curved ribs describe volume with restrained chestnut lines.
c.path([('M',472,382),('C',435,405,434,490,464,523)],stroke=CHESTNUT,width=3)
c.path([('M',498,385),('C',477,415,479,508,498,531)],stroke=CHESTNUT,width=3)
c.path([('M',521,385),('C',547,415,547,501,526,531)],stroke=CHESTNUT,width=3)
c.path([('M',551,384),('C',590,408,591,485,564,515)],stroke=CHESTNUT,width=3)
c.path([('M',433,405),('C',417,421,413,448,418,466)],stroke=OAT,width=5)
c.path([('M',487,396),('C',479,411,475,430,475,449)],stroke=OAT,width=4)
# Folded olive scarf in front: two layers, soft corners, sparse knit columns.
c.path([('M',279,533),('C',325,521,439,527,517,543),('C',532,546,537,557,532,569),('L',522,590),('C',518,602,505,608,490,605),('L',280,579),('C',264,577,257,566,263,553),('Z',)],CHESTNUT,width=4)
c.path([('M',287,516),('C',339,512,445,525,518,537),('C',533,540,538,549,532,562),('L',512,585),('C',504,593,494,594,482,592),('L',271,568),('C',258,566,254,555,263,545),('Z',)],OLIVE,width=4)
c.path([('M',282,527),('C',340,527,440,539,517,549)],stroke=OAT,width=2.5)
for row in range(3):
    for col in range(9):
        knit(c,290+col*24-row*7,537+row*14+col*2.7)
# Curled fringe at the near folded edge.
for i in range(10):
    x=283+i*22; y=581+(x-283)*.12
    c.path([('M',x,y),('C',x-3,y+8,x-10,y+13,x-8,y+19)],stroke=OAT,width=3.5)
# Leaves reprise the first asset's shape and scale, not a decorative frame.
leaf(c,168,589,-63,.73,CHESTNUT)
leaf(c,583,618,64,.83,ORANGE)
leaf(c,239,641,32,.57,OLIVE)
c.line([(177,625),(187,628)],CHESTNUT,3)
c.line([(626,551),(635,547)],CHESTNUT,3)
Path('artifacts').mkdir(exist_ok=True)
c.save('artifacts/02-lantern.png')
print('Saved artifacts/02-lantern.png')

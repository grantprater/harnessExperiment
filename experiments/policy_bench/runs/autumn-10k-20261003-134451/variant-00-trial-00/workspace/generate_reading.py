"""Asset 01: a quiet reading nook. Run: python generate_reading.py.
Editable composition using autumn_draw.py's reusable shapes and six-color palette.
"""
from pathlib import Path
from autumn_draw import *

c=Canvas()
# A quiet oat grounding shape, not a frame or card.
c.path([('M',121,515),('C',119,481,186,457,274,461),('C',368,460,480,432,579,463),('C',659,488,665,565,591,596),('C',497,636,337,630,207,592),('C',151,576,123,550,121,515),('Z',)],OAT,stroke=None)
# Folded olive blanket: a rounded cloth silhouette behind the still life.
c.path([('M',406,425),('C',454,419,541,433,598,447),('C',618,452,632,465,627,487),('L',607,591),('C',603,612,588,623,566,617),('L',381,577),('C',361,573,356,557,361,538),('L',386,446),('C',389,434,396,428,406,425),('Z',)],OLIVE)
# Underfold and hem.
c.path([('M',375,559),('C',427,563,519,591,605,591),('L',601,607),('C',594,620,580,621,565,616),('L',382,578),('C',371,575,366,568,375,559),('Z',)],CHESTNUT,width=3.5)
c.path([('M',405,440),('C',465,439,548,454,610,470)],stroke=OAT,width=2.5)
c.path([('M',601,482),('C',592,512,587,548,581,579)],stroke=OAT,width=2.5)
# Small knitted columns, intentionally sparse rather than texture noise.
for row in range(7):
    for col in range(6):
        knit(c,449+col*24-row*2,460+row*17+col*4)
for i in range(12):
    x=383+i*18; y=582+(x-383)*0.205
    c.path([('M',x,y),('C',x-2,y+10,x-7,y+15,x-5,y+22)],stroke=OAT,width=4)
# Book cover, page blocks, and rounded corners.
c.path([('M',153,398),('C',209,373,273,376,334,408),('C',385,387,430,376,481,388),('L',527,533),('C',469,527,420,545,362,572),('C',294,547,221,547,154,557),('L',132,415),('C',131,407,141,403,153,398),('Z',)],CHESTNUT,width=4.5)
c.path([('M',145,406),('C',208,387,278,391,332,421),('C',385,395,431,389,472,396),('L',515,519),('L',514,535),('C',460,532,411,546,362,565),('C',296,544,221,540,150,548),('L',137,421),('Z',)],OAT)
# Lower page-edge contour lines.
c.path([('M',151,538),('C',222,530,293,536,359,555),('C',413,535,463,523,505,527)],stroke=CHESTNUT,width=2.2)
c.path([('M',149,530),('C',223,523,291,529,357,548)],stroke=CHESTNUT,width=2)
# Open cream pages.
c.path([('M',145,397),('C',211,375,273,380,330,414),('L',356,545),('C',287,519,222,516,155,530),('L',134,409),('C',133,403,140,400,145,397),('Z',)],CREAM)
c.path([('M',330,414),('C',374,381,424,374,467,387),('L',511,513),('C',455,506,412,520,356,545),('L',330,414),('Z',)],CREAM)
c.path([('M',330,415),('C',334,446,345,511,356,542)],stroke=CHESTNUT,width=3)
# Sparse editorial page strokes, no lettering.
for i in range(5):
    y=419+i*17
    c.path([('M',165+i*3,y),('C',204+i*3,y-10,260+i*3,y-5,300+i*3,y+12)],stroke=OAT,width=3)
for i in range(4):
    y=413+i*19
    c.path([('M',359+i*4,y),('C',389+i*4,y-14,417+i*4,y-18,452+i*5,y-12)],stroke=OAT,width=3)
# A narrow burnt-orange bookmark peeking below the book.
c.path([('M',290,530),('L',312,535),('L',324,588),('L',309,579),('L',298,594),('Z',)],ORANGE,width=3)
# Saucer and handle sit behind the mug.
c.ellipse((410,379,630,438),OAT,COCOA)
c.path([('M',430,408),('C',469,426,567,429,610,406)],stroke=CHESTNUT,width=2.5)
c.path([('M',574,278),('C',635,258,648,297,625,332),('C',614,349,597,358,571,354),('L',570,334),('C',593,338,609,325,614,308),('C',619,291,608,287,583,298),('Z',)],ORANGE,width=4.5)
# Ceramic body: soft taper, oat inset as a glazed highlight.
c.path([('M',438,272),('L',587,272),('L',577,380),('C',575,416,455,423,450,384),('Z',)],ORANGE,width=4.5)
c.path([('M',453,292),('L',465,375),('C',467,388,476,395,487,396)],stroke=OAT,width=7)
c.ellipse((438,249,587,294),OAT,COCOA,width=4.5)
c.ellipse((450,258,575,282),CHESTNUT,COCOA,width=2.5)
c.path([('M',459,269),('C',482,259,527,259,553,264)],stroke=OAT,width=2.3)
# Two gentle steam curls rise into ample negative space.
c.path([('M',486,232),('C',469,219,474,201,485,188),('C',498,172,494,158,484,146)],stroke=COCOA,width=4)
c.path([('M',530,228),('C',545,208,538,196,527,181),('C',515,165,521,150,531,137)],stroke=COCOA,width=4)
# Fallen leaves balance the diagonal book/blanket arrangement.
leaf(c,188,340,-38,0.88,ORANGE)
leaf(c,252,336,37,0.68,OLIVE)
leaf(c,154,602,-69,0.72,CHESTNUT)
leaf(c,484,641,75,0.79,ORANGE)
# Only a few scattered seed-like marks.
c.line([(208,300),(217,290)],CHESTNUT,3)
c.line([(127,579),(119,577)],CHESTNUT,3)
c.line([(531,631),(540,628)],CHESTNUT,3)
Path('artifacts').mkdir(exist_ok=True)
c.save('artifacts/01-reading.png')
print('Saved artifacts/01-reading.png')

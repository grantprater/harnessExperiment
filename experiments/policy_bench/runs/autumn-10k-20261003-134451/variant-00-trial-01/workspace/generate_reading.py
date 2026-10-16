"""Asset 01: a quiet reading corner. Run: python generate_reading.py.
Layer order: soft grounding shapes, folded knit, saucer/mug, book, fallen leaves.
No fonts, assets, randomness, network, or dependencies beyond Pillow.
"""
from pathlib import Path
from autumn_draw import Canvas

c = Canvas()
# Quiet, irregular oat grounding plane; ample cream margins.
c.path([('M',135,529),('C',106,439,160,350,267,350),
        ('C',350,323,479,318,572,379),('C',654,417,678,536,628,588),
        ('C',560,650,252,662,176,612),('C',145,591,140,558,135,529),('Z',)],
       fill='oat',stroke=None)
# Folded throw, draped diagonally behind the book.
c.path([('M',452,274),('C',485,258,534,275,558,289),('L',644,331),
        ('Q',657,337,650,356),('L',605,582),('Q',600,609,578,602),
        ('L',448,552),('Q',429,545,432,525),('L',458,340),
        ('Q',435,306,452,274),('Z',)],fill='olive',width=4.5)
# Turned top fold with rounded edges.
c.path([('M',453,278),('C',487,257,538,281,558,290),('L',643,331),
        ('Q',651,336,647,350),('L',633,380),('Q',627,392,612,386),
        ('L',475,332),('Q',452,321,453,278),('Z',)],fill='oat',width=4.5)
c.path([('M',470,285),('Q',470,307,491,317),('L',620,366)],stroke='chestnut',width=3)
# Measured rows of knit chevrons, not a dense texture.
for row in range(7):
    for col in range(6):
        x=478+col*23-row*3.4; y=357+row*29+col*8.5
        c.path([('M',x-5,y-6),('Q',x-5,y,x,y+5),('Q',x+6,y+1,x+8,y-4)],stroke='oat',width=2.5)
# Throw hem and soft tassels.
c.path([('M',447,538),('L',586,590)],stroke='oat',width=3)
for i in range(10):
    x=451+i*14; y=554+i*5
    c.path([('M',x,y),('Q',x-3,y+13,x-7,y+21)],stroke='cocoa',width=4)
    c.path([('M',x,y+3),('L',x-5,y+19)],stroke='oat',width=2)
# Saucer: broad, shallow ceramic dish.
c.ellipse((191,367,439,445),'cream','cocoa',4.5)
c.path([('M',218,402),('C',262,431,371,431,414,402)],stroke='oat',width=3)
# Handle, drawn first so its join is concealed by the mug body.
c.path([('M',386,293),('C',464,278,469,372,398,382),('L',387,356),
        ('C',428,359,439,316,389,319),('Z',)],fill='orange',width=4.5)
# Gently tapered ceramic mug.
c.path([('M',238,286),('C',251,277,369,277,393,289),('L',384,379),
        ('C',381,416,255,419,250,380),('L',238,286),('Z',)],fill='orange',width=4.5)
# A ceramic sheen and discreet belly decoration.
c.path([('M',263,321),('L',268,372),('Q',270,382,280,385)],stroke='oat',width=5)
c.path([('M',306,359),('Q',326,370,348,355)],stroke='chestnut',width=3)
c.ellipse((236,267,396,307),'oat','cocoa',4.5)
c.ellipse((250,279,382,300),'chestnut','cocoa',3)
c.path([('M',259,286),('Q',317,274,373,288)],stroke='orange',width=2)
# Three softly curling steam trails.
c.path([('M',280,250),('C',252,227,303,213,284,185),('C',273,168,277,158,287,151)],stroke='chestnut',width=4)
c.path([('M',322,245),('C',346,217,302,205,322,176),('C',333,162,333,150,325,139)],stroke='chestnut',width=4)
c.path([('M',359,250),('C',344,231,370,217,360,201)],stroke='chestnut',width=4)
# Book: stout chestnut binding and layered paper edges.
c.path([('M',154,441),('Q',226,408,337,458),('Q',425,415,501,449),
        ('L',526,584),('Q',444,571,355,622),('Q',252,576,151,580),
        ('Q',141,580,143,568),('L',154,441),('Z',)],fill='chestnut',width=4.5)
c.path([('M',164,444),('Q',246,417,338,466),('Q',421,425,493,453),
        ('L',515,572),('Q',431,570,354,610),('Q',253,567,152,569),('Z',)],fill='oat',width=4)
# Open cream pages: curved rather than rectangular planes.
c.path([('M',170,423),('C',232,404,292,428,338,456),
        ('C',390,419,451,415,485,431),('L',509,554),
        ('C',446,544,398,567,351,592),('C',284,554,222,547,158,549),
        ('L',170,423),('Z',)],fill='cream',width=4.5)
c.path([('M',338,456),('Q',334,517,351,592)],stroke='cocoa',width=3.5)
c.path([('M',330,460),('Q',326,524,340,579)],stroke='oat',width=3)
# Restrained page rules suggest print without any actual lettering.
for off in (0,17,34,51):
    c.path([('M',189,452+off),('C',231,447+off,270,460+off,307,477+off)],stroke='oat',width=3)
    c.path([('M',370,475+off),('Q',427,450+off,468,460+off)],stroke='oat',width=3)
c.path([('M',191,524),('Q',227,522,258,534)],stroke='oat',width=3)
# A burnt-orange ribbon tucked into the center crease.
c.path([('M',354,586),('Q',372,582,379,579),('L',389,623),
        ('L',377,617),('L',367,633),('Z',)],fill='orange',width=3)
# Fallen leaves frame the scene without forming a border.
c.leaf(167,375,67,-42,'olive')
c.leaf(569,254,72,32,'orange',lobed=True)
c.leaf(636,480,60,53,'chestnut')
c.leaf(213,639,69,-69,'orange',lobed=True)
c.leaf(463,649,52,64,'olive')
# A few tiny companion stems, deliberately sparse.
c.path([('M',138,408),('Q',147,395,151,392)],stroke='chestnut',width=3)
c.path([('M',580,648),('Q',595,645,602,637)],stroke='chestnut',width=3)
Path('artifacts').mkdir(exist_ok=True)
c.save('artifacts/01-reading.png')

"""Companion autumn still life. Local Pillow; run python generate_lantern.py.
Uses asset 01's shared curved paths, 4.5 px contours and leaf/knit vocabulary.
"""
from pathlib import Path
from autumn_draw import Canvas
c=Canvas()
c.path([('M',138,512),('C',115,408,199,350,303,352),('C',422,326,581,353,630,427),('C',678,502,645,593,587,617),('C',487,657,228,650,169,602),('Q',141,571,138,512),('Z',)],fill='oat',stroke=None)
# Folded scarf across the foreground, with a softly turned end.
c.path([('M',211,508),('Q',221,491,248,498),('L',558,549),('Q',583,553,579,575),('L',565,617),('Q',560,632,539,627),('L',221,572),('Q',197,569,202,549),('Z',)],fill='olive',width=4.5)
c.path([('M',225,493),('Q',228,479,253,485),('L',568,537),('Q',586,541,581,559),('L',572,586),('Q',568,597,549,594),('L',230,540),('Q',209,537,215,521),('Z',)],fill='olive',width=4.5)
for row in range(3):
    for col in range(12):
        x=239+col*26-row*3; y=504+col*4.4+row*12
        c.path([('M',x-5,y-4),('Q',x-4,y,x,y+4),('Q',x+5,y+1,x+7,y-3)],stroke='oat',width=2.5)
c.path([('M',229,557),('L',550,611)],stroke='oat',width=3)
for i in range(7):
    x=556+i*3; y=559+i*7
    c.path([('M',x,y),('Q',x+17,y+5,x+22,y+12)],width=4)
    c.path([('M',x+3,y+1),('L',x+20,y+10)],stroke='oat',width=2)
# Lantern bail: generous rounded silhouette echoes the first asset's steam.
c.path([('M',229,258),('L',229,219),('C',229,135,363,135,363,219),('L',363,258)],width=5)
c.path([('M',243,237),('L',243,215),('C',243,158,349,158,349,215),('L',349,237)],stroke='orange',width=3)
# Main enclosure; warm glazing uses solid reference colors, not gradients.
c.path([('M',211,289),('L',379,289),('L',392,485),('Q',395,509,374,513),('L',218,513),('Q',200,510,203,488),('Z',)],fill='orange',width=4.5)
c.path([('M',235,309),('L',355,309),('L',365,471),('Q',365,479,355,479),('L',237,479),('Q',227,479,228,468),('Z',)],fill='oat',width=3)
# Cream light pool and candle flame: flat, restrained warm glow.
c.ellipse((253,335,341,449),'cream')
c.path([('M',276,406),('Q',296,412,316,406),('L',316,464),('L',276,464),('Z',)],fill='cream',width=3)
c.path([('M',277,407),('Q',285,419,291,409),('Q',298,420,304,411),('Q',310,417,316,407)],stroke='orange',width=2.5)
c.path([('M',296,403),('C',269,394,291,373,299,351),('C',319,377,318,396,296,403),('Z',)],fill='orange',stroke=None)
c.path([('M',296,399),('Q',286,389,299,378),('Q',306,392,296,399),('Z',)],fill='cream',stroke=None)
c.path([('M',296,406),('L',296,400)],width=2.5)
c.path([('M',254,327),('L',249,363)],stroke='cream',width=4)
# Sturdy cocoa rails and low, rounded foot.
for x in (222,369):
    c.path([('M',x,295),('L',x+( -6 if x==222 else 6),484)],width=6)
c.path([('M',210,480),('Q',295,491,384,480)],width=5)
c.path([('M',210,493),('Q',295,503,384,493),('L',396,519),('Q',396,529,380,530),('L',211,530),('Q',195,529,197,519),('Z',)],fill='chestnut',width=4.5)
c.path([('M',216,516),('Q',295,522,375,516)],stroke='orange',width=3)
# Curved canopy and vent cap.
c.path([('M',200,290),('Q',215,272,239,267),('Q',248,233,270,232),('L',322,232),('Q',345,234,354,268),('Q',380,273,391,290),('Q',391,301,378,302),('L',212,302),('Q',199,301,200,290),('Z',)],fill='chestnut',width=4.5)
c.path([('M',221,284),('Q',296,272,371,284)],stroke='orange',width=3)
for x in (276,296,316):
    c.path([('M',x,244),('L',x,256)],width=3)
# Pumpkin tucked beside the lantern: scalloped silhouette, curved lobes.
c.path([('M',456,360),('C',421,335,380,365,387,415),('C',368,463,394,506,435,513),('Q',475,538,516,518),('C',565,519,593,478,582,434),('C',592,385,558,348,522,362),('Q',485,344,456,360),('Z',)],fill='orange',width=4.5)
c.path([('M',447,366),('C',408,403,408,473,441,502)],stroke='chestnut',width=3.5)
c.path([('M',468,363),('C',445,407,446,487,470,516)],stroke='chestnut',width=3.5)
c.path([('M',501,363),('C',528,402,529,481,504,516)],stroke='chestnut',width=3.5)
c.path([('M',528,370),('C',565,407,566,474,535,500)],stroke='chestnut',width=3.5)
c.path([('M',472,383),('C',461,413,462,443,465,461)],stroke='oat',width=5)
# Bent woody stem and a small curling tendril.
c.path([('M',471,363),('Q',475,345,467,320),('Q',478,309,491,315),('Q',494,337,486,362),('Q',479,368,471,363),('Z',)],fill='olive',width=4)
c.path([('M',479,321),('Q',484,341,479,355)],stroke='oat',width=2.5)
c.path([('M',491,350),('C',513,329,540,335,533,349),('C',526,362,512,345,525,341)],stroke='olive',width=3)
# The same spare curved fallen leaves as the reading illustration.
c.leaf(180,568,65,-58,'chestnut',True)
c.leaf(616,509,68,31,'olive')
c.leaf(593,647,64,64,'orange',True)
c.leaf(338,657,56,-69,'chestnut')
c.leaf(162,427,42,-30,'orange')
Path('artifacts').mkdir(exist_ok=True)
c.save('artifacts/02-lantern.png')

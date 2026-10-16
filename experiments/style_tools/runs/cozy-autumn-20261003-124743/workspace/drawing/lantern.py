"""Asset 02: candlelight, a pumpkin and a folded knit scarf.
Rebuild from the workspace root with: python drawing/lantern.py
Uses the unchanged drawing vocabulary and exact six inks of asset 01.
"""
from pathlib import Path
from autumn import Canvas

c = Canvas()

# A long scarf folded over itself: a low, rounded olive foundation.
c.path([('M',284,490),('C',347,473,438,480,490,502),('L',593,531),('C',614,537,626,553,621,572),('L',613,601),('C',609,616,596,623,580,619),('L',305,564),('C',285,560,273,545,275,527),('L',278,504),('C',278,496,280,492,284,490),('Z',)],'olive')
# Lower fold seam glimpsed beneath the top layer.
c.path([('M',289,544),('C',357,545,442,572,507,582),('L',611,601)],stroke='oat',width=3)
# Turned-over end with a broad soft bend; no sharp textile corners.
c.path([('M',310,480),('C',361,478,394,485,438,496),('L',589,529),('C',608,533,617,546,610,560),('C',604,573,591,578,576,574),('L',334,521),('C',315,517,303,506,304,495),('C',304,488,307,483,310,480),('Z',)],'olive')
c.path([('M',326,492),('C',363,490,393,500,429,508),('L',580,541)],stroke='oat',width=3)
# Same restrained oat V-stitches, spacing and weight as the reading throw.
for col in range(10):
    x = 340 + col*25
    y = 506 + col*5.4
    c.line([(x-5,y-4),(x,y+2),(x+5,y-4)],'oat',2)
for col in range(10):
    x = 332 + col*25
    y = 558 + col*5.0
    c.line([(x-5,y-4),(x,y+2),(x+5,y-4)],'oat',2)
# Ribbed end and tassels visible beyond the fold, lower right.
c.path([('M',565,579),('L',612,589),('L',608,603),('C',593,602,579,598,562,594),('Z',)],'olive',width=3)
for x in range(569,608,8):
    y = 581+(x-569)*.22
    c.line([(x,y),(x-3,y+12)],'oat',2)
for x in range(570,609,9):
    y = 601+(x-570)*.20
    c.line([(x,y),(x-4,y+17)],'cocoa',3)
    c.line([(x+2,y+1),(x-2,y+15)],'olive',3)

# Candle lantern's arching carry handle. Height mirrors asset 01's steam.
c.path([('M',445,260),('C',418,196,449,153,502,153),('C',555,153,585,196,558,260)],stroke='cocoa',width=8)
c.path([('M',445,254),('C',424,198,451,159,502,159),('C',550,159,578,198,558,254)],stroke='oat',width=3)
# Rounded chamber: warm oat glass, cream light pool, cocoa edges.
c.path([('M',436,263),('C',430,307,424,374,431,438),('C',437,465,464,477,502,477),('C',540,477,568,465,574,438),('C',581,374,575,307,568,263),('Z',)],'oat')
c.path([('M',452,279),('C',444,314,442,369,446,427),('C',450,447,468,459,502,460),('C',536,459,553,447,558,427),('C',562,369,560,314,551,279),('Z',)],'cream',stroke=None)
# Broad, discreet glass shine; no off-palette gradients.
c.path([('M',449,304),('C',444,331,443,357,445,378)],stroke='cream',width=4)
# Candle holder behind the pillar.
c.ellipse((464,427,541,450),'chestnut',width=3)
c.path([('M',478,374),('C',486,369,518,369,526,374),('L',525,433),('C',514,440,487,440,478,433),('Z',)],'oat',width=3)
c.ellipse((478,368,527,381),'cream',width=3)
# A curved flame with a light core, framed by open space in the glass.
c.path([('M',502,362),('C',479,353,484,337,495,325),('C',506,313,507,302,504,295),('C',526,311,533,336,521,352),('C',516,359,510,362,502,362),('Z',)],'orange',stroke='chestnut',width=3)
c.path([('M',504,353),('C',494,347,499,338,508,329),('C',517,340,515,348,504,353),('Z',)],'cream',stroke=None)
c.line([(503,369),(504,361)],'cocoa',2.5)
# Side stays echo the rounded cup edges of asset 01.
c.path([('M',442,269),('C',436,325,435,391,443,443)],stroke='cocoa',width=4)
c.path([('M',561,269),('C',568,325,569,391,561,443)],stroke='cocoa',width=4)
# Crown: a soft domed hood and rolled brim.
c.path([('M',438,248),('C',450,239,461,229,466,214),('C',473,204,529,204,537,214),('C',542,229,554,239,567,248),('Z',)],'chestnut')
c.path([('M',470,222),('C',486,216,513,216,529,222)],stroke='oat',width=3)
c.path([('M',429,247),('C',462,242,541,242,574,247),('C',584,249,585,264,574,268),('C',541,272,462,272,429,268),('C',419,264,419,250,429,247),('Z',)],'chestnut')
c.path([('M',441,254),('C',473,251,529,251,562,254)],stroke='oat',width=3)
# Small hinged pivots.
c.ellipse((432,251,442,261),'oat',width=2)
c.ellipse((561,251,571,261),'oat',width=2)
# A rounded plinth, gently flared like the reading asset's saucer.
c.path([('M',440,443),('C',470,455,534,455,563,443),('L',579,464),('C',586,473,581,484,570,486),('C',529,491,476,491,433,486),('C',422,484,418,473,425,464),('Z',)],'chestnut')
c.path([('M',438,476),('C',474,481,531,481,566,476)],stroke='oat',width=3)
# Restrained light marks outside the lantern; cream background stays open.
c.line([(400,308),(389,302)],'oat',3)
c.line([(601,304),(612,298)],'oat',3)
c.line([(603,351),(618,351)],'oat',3)

# The low pumpkin balances the tall lantern. Organic lobes, not a face.
c.path([('M',288,370),('C',250,350,207,365,186,389),('C',157,414,154,459,172,490),('C',190,524,235,546,289,543),('C',340,551,385,530,402,499),('C',427,456,417,406,386,382),('C',365,361,326,355,304,370),('Z',)],'orange')
c.path([('M',260,376),('C',215,380,200,424,207,471),('C',211,506,237,533,270,538)],stroke='chestnut',width=3)
c.path([('M',324,376),('C',366,379,386,422,379,470),('C',374,506,350,533,319,540)],stroke='chestnut',width=3)
c.path([('M',287,382),('C',265,410,259,484,282,537)],stroke='chestnut',width=3)
c.path([('M',302,382),('C',324,413,329,485,307,540)],stroke='chestnut',width=3)
# Soft oat reflected highlight on the shoulder.
c.path([('M',187,430),('C',191,411,203,398,216,392)],stroke='oat',width=4)
# A bent stem and curled tendril link pumpkin to the olive scarf.
c.path([('M',279,380),('C',288,361,284,345,277,331),('C',281,327,291,325,298,328),('C',309,347,308,363,307,379),('C',299,385,286,385,279,380),('Z',)],'olive',width=3)
c.path([('M',297,341),('C',296,353,296,364,292,373)],stroke='oat',width=2)
c.path([('M',310,368),('C',327,345,351,345,353,360),('C',353,375,335,375,335,363)],stroke='olive',width=3)

# Match the first illustration's sparse asymmetrical leaf scatter.
c.leaf(198,302,66,-48,'orange')
c.leaf(357,297,52,28,'olive')
c.leaf(148,592,64,-76,'orange')
c.leaf(343,642,65,65,'chestnut')
c.leaf(619,476,57,46,'oat')
c.path([('M',151,332),('C',139,329,131,322,127,312)],stroke='oat',width=3)
c.path([('M',223,601),('C',238,597,248,589,253,579)],stroke='oat',width=3)

out = Path(__file__).resolve().parent.parent/'artifacts'/'02-lantern.png'
out.parent.mkdir(exist_ok=True)
c.save(out)
print(out.relative_to(out.parent.parent))

"""Asset 01: a quiet autumn reading corner. Run: python drawing/reading.py"""
from pathlib import Path
from autumn import Canvas

c=Canvas()
# A folded olive throw anchors the diagonal composition.
c.path([('M',347,375),('C',423,348,526,350,609,378),('C',628,384,644,411,641,444),('L',631,590),('C',630,608,619,622,600,622),('C',524,619,464,603,402,597),('L',353,425),('C',345,408,341,391,347,375),('Z',)],'olive')
c.path([('M',372,382),('C',448,368,543,372,609,397),('C',625,407,626,424,620,440)],stroke='oat',width=3)
# Knit chevrons: broad spacing keeps the weave understated.
for row in range(8):
    y=428+row*21
    for col in range(8):
        x=421+col*25
        if x<616:
            c.line([(x-5,y-4),(x,y+2),(x+5,y-4)],'oat',2)
# A ribbed folded edge and short soft tassels.
c.path([('M',397,564),('C',465,570,536,592,632,584),('L',631,600),('C',529,610,466,585,402,583),('Z',)],'olive')
for x in range(432,619,14):
    y=585+(x-432)*.075
    c.line([(x,y-9),(x-2,y+4)],'oat',2)
for x in range(426,618,18):
    y=596+(x-426)*.06
    c.line([(x,y),(x-2,y+16)],'cocoa',3)
    c.line([(x+3,y+1),(x+1,y+14)],'olive',4)

# Warm saucer, handle and a tapered, rounded ceramic cup.
c.ellipse((395,391,610,441),'oat')
c.path([('M',421,417),('C',459,430,551,430,583,416)],stroke='chestnut',width=3)
c.path([('M',562,286),('C',631,273,634,365,572,367),('L',568,345),('C',605,344,606,304,570,309),('Z',)],'orange',width=4)
c.path([('M',437,284),('L',447,381),('C',450,409,556,420,568,381),('L',582,284),('Z',)],'orange',width=4)
c.path([('M',451,309),('L',458,369),('C',458,386,476,392,491,393)],stroke='oat',width=5)
c.ellipse((436,266,583,310),'oat')
c.ellipse((447,275,572,300),'chestnut',width=3)
c.path([('M',464,288),('C',484,281,513,280,535,285)],stroke='oat',width=2.5)
# Three curling ribbons of steam, plenty of negative space above.
c.path([('M',476,248),('C',453,227,489,216,475,195),('C',468,185,468,180,473,171)],stroke='chestnut',width=4)
c.path([('M',510,239),('C',532,211,492,203,510,177),('C',518,164,521,154,514,141)],stroke='chestnut',width=4)
c.path([('M',547,249),('C',560,233,540,220,547,208)],stroke='chestnut',width=4)

# Open book: layered page blocks and gently arcing cream pages.
c.path([('M',142,440),('L',295,418),('L',446,462),('L',469,570),('C',412,549,361,550,307,574),('C',250,553,204,561,165,579),('Z',)],'chestnut',width=4)
c.path([('M',147,435),('C',197,412,250,414,298,441),('C',344,417,405,430,443,453),('L',464,559),('C',409,538,352,540,307,565),('C',260,540,204,547,164,566),('Z',)],'oat',width=4)
c.path([('M',146,425),('C',192,403,246,405,295,433),('C',340,407,400,419,440,442),('L',457,545),('C',404,523,350,527,305,553),('C',254,523,205,534,161,554),('Z',)],'cream',width=4)
c.path([('M',295,433),('C',299,474,301,519,305,553)],stroke='cocoa',width=3)
# Page contours, not text.
c.path([('M',165,438),('C',209,423,244,427,276,443)],stroke='oat',width=3)
c.path([('M',175,526),('C',214,513,249,515,281,532)],stroke='oat',width=3)
c.path([('M',315,442),('C',349,427,389,433,422,449)],stroke='oat',width=3)
c.path([('M',324,529),('C',361,512,397,515,438,531)],stroke='oat',width=3)
# Rust ribbon spills from the central binding.
c.path([('M',310,539),('C',320,552,326,572,331,591),('L',342,581),('L',353,583),('C',345,562,335,545,325,533),('Z',)],'orange',width=3)

# A few wind-scattered leaves balance the scene, not a decorative frame.
c.leaf(209,338,76,-48,'orange')
c.leaf(286,365,56,24,'olive')
c.leaf(148,618,64,-76,'orange')
c.leaf(351,646,65,65,'chestnut')
c.leaf(613,258,51,39,'oat')
# Small stem gestures reinforce the gentle diagonal.
c.path([('M',154,367),('C',142,363,133,356,129,345)],stroke='oat',width=3)
c.path([('M',216,616),('C',231,612,241,604,246,594)],stroke='oat',width=3)

out=Path(__file__).resolve().parent.parent/'artifacts'/'01-reading.png'
out.parent.mkdir(exist_ok=True)
c.save(out)
print(out.relative_to(out.parent.parent))

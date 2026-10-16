"""Shared cozy-autumn vocabulary. Coordinates are in a 768-square design space.
Only the six colors sampled from references/autumn-palette.png are used;
4x supersampling introduces antialiasing only. No external assets required.
"""
from PIL import Image, ImageDraw
import math

CREAM = (244,230,206)
OAT = (217,179,130)
ORANGE = (185,107,54)
CHESTNUT = (125,63,40)
COCOA = (72,51,38)
OLIVE = (114,115,74)
PALETTE = [CREAM,OAT,ORANGE,CHESTNUT,COCOA,OLIVE]

class Canvas:
    def __init__(self, size=768, scale=4):
        self.scale = scale
        self.image = Image.new('RGB',(size*scale,size*scale),CREAM)
        self.draw = ImageDraw.Draw(self.image)
    def line(self, points, color=COCOA, width=4):
        s=self.scale
        pts=[(round(x*s),round(y*s)) for x,y in points]
        self.draw.line(pts,fill=color,width=round(width*s),joint='curve')
        r=width*s/2
        for x,y in [pts[0],pts[-1]]:
            self.draw.ellipse((int(x-r),int(y-r),int(x+r),int(y+r)),fill=color)
    def path(self, commands, fill=None, stroke=COCOA, width=4):
        pts=[]; p=(0,0); start=None
        for c in commands:
            if c[0]=='M':
                p=(c[1],c[2]); start=p; pts.append(p)
            elif c[0]=='L':
                p=(c[1],c[2]); pts.append(p)
            elif c[0]=='C':
                a=p; b=c[1:3]; d=c[3:5]; e=c[5:7]
                for i in range(1,41):
                    t=i/40; u=1-t
                    pts.append((u**3*a[0]+3*u*u*t*b[0]+3*u*t*t*d[0]+t**3*e[0],u**3*a[1]+3*u*u*t*b[1]+3*u*t*t*d[1]+t**3*e[1]))
                p=e
            elif c[0]=='Z': pts.append(start); p=start
        if fill is not None:
            self.draw.polygon([(round(x*self.scale),round(y*self.scale)) for x,y in pts],fill=fill)
        if stroke is not None: self.line(pts,stroke,width)
    def ellipse(self, box, fill, stroke=None, width=4):
        b=tuple(round(v*self.scale) for v in box)
        self.draw.ellipse(b,fill=fill,outline=stroke,width=round(width*self.scale))
    def save(self, path):
        self.image.resize((768,768),Image.Resampling.LANCZOS).save(path)

def leaf(c, x,y, angle=0, size=1, color=ORANGE):
    """Curved pointed leaf with a central vein and sparse lateral veins."""
    def tr(p):
        a=math.radians(angle); u,v=p
        return (x+size*(u*math.cos(a)-v*math.sin(a)),y+size*(u*math.sin(a)+v*math.cos(a)))
    commands=[('M',0,0),('C',-29,-12,-33,-48,0,-76),('C',29,-48,30,-15,0,0),('Z',)]
    transformed=[]
    for q in commands:
        v=[q[0]]
        for i in range(1,len(q),2): v.extend(tr(q[i:i+2]))
        transformed.append(tuple(v))
    c.path(transformed,color,width=3.5)
    c.line([tr((0,12)),tr((0,-59))],width=2.6)
    for yy, direction in [(-20,-1),(-31,1),(-42,-1)]:
        c.line([tr((0,yy)),tr((direction*13,yy-10))],width=2)

def knit(c,x,y,color=OAT):
    """One restrained V-shaped knit stitch."""
    c.path([('M',x-5,y-7),('C',x-5,y-2,x-2,y+2,x,y+5),('C',x+2,y+2,x+5,y-2,x+5,y-7)],stroke=color,width=2.4)

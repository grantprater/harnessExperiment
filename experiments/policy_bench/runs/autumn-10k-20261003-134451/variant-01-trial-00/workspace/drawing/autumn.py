"""Reusable flat editorial drawing vocabulary. Coordinates are in a 768px canvas."""
from PIL import Image, ImageDraw
import math

PALETTE = {
    'cream': (244,230,206), 'oat': (217,179,130),
    'orange': (185,107,54), 'chestnut': (125,63,40),
    'cocoa': (72,51,38), 'olive': (114,115,74),
}

class Canvas:
    def __init__(self, size=768, scale=3):
        self.size, self.scale = size, scale
        self.image = Image.new('RGB', (size*scale, size*scale), PALETTE['cream'])
        self.draw = ImageDraw.Draw(self.image)

    def color(self, name):
        return PALETTE[name] if isinstance(name, str) else name

    def line(self, pts, color='cocoa', width=4):
        s = self.scale
        xy = [(round(x*s),round(y*s)) for x,y in pts]
        self.draw.line(xy, fill=self.color(color), width=round(width*s), joint='curve')
        r = width*s/2
        for x,y in (xy[0],xy[-1]):
            self.draw.ellipse((x-r,y-r,x+r,y+r), fill=self.color(color))

    def path(self, commands, fill=None, stroke='cocoa', width=4):
        pts=[]
        for c in commands:
            if c[0]=='M':
                pts.append((c[1],c[2]))
            elif c[0]=='L':
                pts.append((c[1],c[2]))
            elif c[0]=='C':
                x,y=pts[-1]; a,b,d,e,f,g=c[1:]
                for i in range(1,33):
                    t=i/32; u=1-t
                    pts.append((u*u*u*x+3*u*u*t*a+3*u*t*t*d+t*t*t*f,
                                u*u*u*y+3*u*u*t*b+3*u*t*t*e+t*t*t*g))
            elif c[0]=='Z':
                pts.append(pts[0])
        if fill:
            self.draw.polygon([(round(x*self.scale),round(y*self.scale)) for x,y in pts], fill=self.color(fill))
        if stroke:
            self.line(pts,stroke,width)

    def ellipse(self, box, fill, stroke=None, width=4):
        self.draw.ellipse(tuple(round(v*self.scale) for v in box),fill=self.color(fill),
                          outline=self.color(stroke) if stroke else None,width=round(width*self.scale))

    def leaf(self, x,y,angle,length=62, color='orange'):
        # A tapered, gently lobed fallen leaf, in its own local coordinate system.
        a=math.radians(angle)
        def tr(p):
            u,v=p; return (x+u*math.cos(a)-v*math.sin(a), y+u*math.sin(a)+v*math.cos(a))
        k=length/70
        local=[('M',-35,0),('C',-21,-6,-18,-24,-6,-18),('C',1,-31,9,-23,15,-17),
               ('C',22,-17,26,-7,35,0),('C',20,7,15,24,4,18),('C',-11,26,-16,11,-35,0),('Z',)]
        commands=[]
        for cmd in local:
            vals=[]
            for j in range(1,len(cmd),2): vals.extend(tr((cmd[j]*k,cmd[j+1]*k)))
            commands.append((cmd[0],*vals))
        self.path(commands, color, width=3.2)
        self.line([tr((-43*k,0)),tr((24*k,0))],width=2.6)
        for u,v in [(-15,-12),(0,-14),(12,12),(-10,13)]:
            self.line([tr(((u-8)*k,0)),tr((u*k,v*k))],width=2)

    def save(self,path):
        self.image.resize((self.size,self.size),Image.Resampling.LANCZOS).save(path)

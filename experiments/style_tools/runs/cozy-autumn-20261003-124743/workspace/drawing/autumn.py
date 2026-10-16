"""Shared flat-editorial vocabulary. Coordinates are in a 768px artboard."""
from PIL import Image, ImageDraw
import math

PALETTE = dict(cream='#f4e6ce', oat='#d9b382', orange='#b96b36', chestnut='#7d3f28', cocoa='#483326', olive='#72734a')

class Canvas:
    def __init__(self, size=768, scale=3):
        self.size, self.scale = size, scale
        self.image = Image.new('RGB', (size*scale, size*scale), PALETTE['cream'])
        self.draw = ImageDraw.Draw(self.image)
    def color(self, value):
        return PALETTE.get(value, value) if value else None
    def points(self, pts):
        return [(round(x*self.scale), round(y*self.scale)) for x,y in pts]
    def line(self, pts, color='cocoa', width=4, rounded=True):
        p = self.points(pts)
        self.draw.line(p, fill=self.color(color), width=round(width*self.scale), joint='curve')
        if rounded:
            r=width*self.scale/2
            for x,y in (p[0],p[-1]):
                self.draw.ellipse((int(x-r),int(y-r),int(x+r),int(y+r)),fill=self.color(color))
    def ellipse(self, box, fill, stroke='cocoa', width=4):
        self.draw.ellipse(tuple(round(v*self.scale) for v in box), fill=self.color(fill), outline=self.color(stroke), width=round(width*self.scale))
    def path(self, commands, fill=None, stroke='cocoa', width=4):
        pts=[]
        for command in commands:
            op,*v=command
            if op=='M': pts.append((v[0],v[1]))
            elif op=='L': pts.append((v[0],v[1]))
            elif op=='C':
                x0,y0=pts[-1]; x1,y1,x2,y2,x3,y3=v
                for i in range(1,41):
                    t=i/40; u=1-t
                    pts.append((u**3*x0+3*u*u*t*x1+3*u*t*t*x2+t**3*x3,u**3*y0+3*u*u*t*y1+3*u*t*t*y2+t**3*y3))
            elif op=='Z': pts.append(pts[0])
        if fill: self.draw.polygon(self.points(pts),fill=self.color(fill))
        if stroke: self.line(pts,stroke,width)
    def leaf(self, x,y,length=70,angle=0,fill='orange'):
        def trans(a,b):
            r=math.radians(angle)
            return x+a*math.cos(r)-b*math.sin(r),y+a*math.sin(r)+b*math.cos(r)
        def cmd(op,*v):
            out=[]
            for i in range(0,len(v),2): out.extend(trans(v[i],v[i+1]))
            return (op,*out)
        # A gently pointed, lobed fallen leaf.
        self.path([cmd('M',0,0),cmd('C',-length*.36,-length*.1,-length*.42,-length*.36,-length*.23,-length*.46),cmd('L',-length*.28,-length*.63),cmd('C',-length*.08,-length*.57,-length*.14,-length*.85,0,-length),cmd('C',length*.14,-length*.85,length*.08,-length*.57,length*.28,-length*.63),cmd('L',length*.23,-length*.46),cmd('C',length*.42,-length*.36,length*.36,-length*.1,0,0),('Z',)],fill,width=3)
        self.line([trans(0,12),trans(0,-length*.79)],width=2.5)
        for h in (.28,.48):
            self.line([trans(0,-length*h),trans(-length*.15,-length*(h+.13))],width=2)
            self.line([trans(0,-length*h),trans(length*.15,-length*(h+.13))],width=2)
    def save(self,path):
        from pathlib import Path
        from PIL import ImageColor
        rendered = self.image.resize((self.size,self.size),Image.Resampling.LANCZOS)
        path = Path(path)
        rendered.save(path.with_name(path.stem + '-antialiased-original.png'))
        # Map edge blends to the exact six reference inks, with no dithering.
        inks = [ImageColor.getrgb(value) for value in PALETTE.values()]
        palette = Image.new('P', (1,1))
        palette.putpalette([channel for rgb in inks for channel in rgb] + list(inks[0]) * 250)
        rendered.quantize(palette=palette, dither=Image.Dither.NONE).convert('RGB').save(path)

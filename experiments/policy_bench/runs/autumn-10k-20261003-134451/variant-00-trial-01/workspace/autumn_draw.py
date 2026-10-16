"""Reusable six-color drawing vocabulary for the cozy autumn illustration pair.
Coordinates are in a 768 px design space. All artwork is drawn locally in Pillow.
"""
from PIL import Image, ImageDraw
import math

PALETTE = {
    'cream': (244, 230, 206), 'oat': (217, 179, 130),
    'orange': (185, 107, 54), 'chestnut': (125, 63, 40),
    'cocoa': (72, 51, 38), 'olive': (114, 115, 74),
}
SCALE = 3

class Canvas:
    def __init__(self):
        self.image = Image.new('RGB', (768*SCALE, 768*SCALE), PALETTE['cream'])
        self.draw = ImageDraw.Draw(self.image)

    def path(self, commands, fill=None, stroke='cocoa', width=4):
        points = []
        cursor = (0, 0)
        first = None
        for command in commands:
            op, *v = command
            if op == 'M':
                cursor = tuple(v); first = cursor; points.append(cursor)
            elif op == 'L':
                cursor = tuple(v); points.append(cursor)
            elif op in ('C', 'Q'):
                start = cursor
                count = 48
                for i in range(1, count+1):
                    t = i/count; u = 1-t
                    if op == 'C':
                        x = u**3*start[0]+3*u*u*t*v[0]+3*u*t*t*v[2]+t**3*v[4]
                        y = u**3*start[1]+3*u*u*t*v[1]+3*u*t*t*v[3]+t**3*v[5]
                    else:
                        x = u*u*start[0]+2*u*t*v[0]+t*t*v[2]
                        y = u*u*start[1]+2*u*t*v[1]+t*t*v[3]
                    points.append((x,y))
                cursor = points[-1]
            elif op == 'Z':
                points.append(first); cursor = first
        pts = [(round(x*SCALE), round(y*SCALE)) for x,y in points]
        if fill:
            self.draw.polygon(pts, fill=PALETTE[fill])
        if stroke and width:
            self.draw.line(pts, fill=PALETTE[stroke], width=round(width*SCALE), joint='curve')
            r = width*SCALE/2
            for x,y in (pts[0],pts[-1]):
                self.draw.ellipse((x-r,y-r,x+r,y+r), fill=PALETTE[stroke])

    def ellipse(self, box, fill, stroke=None, width=4):
        self.draw.ellipse(tuple(round(x*SCALE) for x in box), fill=PALETTE[fill],
                          outline=PALETTE[stroke] if stroke else None, width=round(width*SCALE))

    def leaf(self, x, y, length, angle, color, lobed=False):
        """A curved fallen leaf with a spare central vein; angle is in degrees."""
        a = math.radians(angle)
        def tr(px, py):
            return (x+px*math.cos(a)-py*math.sin(a), y+px*math.sin(a)+py*math.cos(a))
        def cmd(op, *vals):
            out = [op]
            for i in range(0,len(vals),2): out.extend(tr(vals[i],vals[i+1]))
            return tuple(out)
        l=length
        if lobed:
            shape=[cmd('M',0,0),cmd('Q',-.28*l,-.1*l,-.34*l,-.36*l),
                   cmd('L',-.13*l,-.34*l),cmd('L',-.18*l,-.64*l),
                   cmd('L',-.03*l,-.54*l),cmd('L',.08*l,-l),
                   cmd('L',.20*l,-.58*l),cmd('L',.38*l,-.70*l),
                   cmd('L',.29*l,-.39*l),cmd('L',.48*l,-.41*l),
                   cmd('Q',.35*l,-.09*l,0,0),('Z',)]
        else:
            shape=[cmd('M',0,0),cmd('C',-.45*l,-.23*l,-.32*l,-.72*l,0,-l),
                   cmd('C',.32*l,-.69*l,.37*l,-.24*l,0,0),('Z',)]
        self.path(shape, fill=color, width=3)
        self.path([cmd('M',-.02*l,.14*l),cmd('Q',.05*l,-.34*l,0,-.82*l)],width=2.5)
        for depth, side in ((.30,-1),(.48,1)):
            self.path([cmd('M',.01*l,-depth*l),cmd('L',side*.19*l,-(depth+.13)*l)],width=2)

    def save(self,path):
        self.image.resize((768,768),Image.Resampling.LANCZOS).save(path)

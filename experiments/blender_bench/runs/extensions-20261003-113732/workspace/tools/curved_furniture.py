"""Reusable solid circular-arc back panel, for execution inside Blender."""
import math
import bpy


def arc_back(name, width, sagitta, edge_y, bottom, top, thickness, mat, segments=48):
    """Sweep a vertical panel across X; center bows toward positive Y.

    Thickness is measured along Y, keeping the full X span exact.
    Returns a closed mesh with four vertices at each arc station.
    """
    assert width > 0 and 0 < sagitta < width / 2
    assert top > bottom and thickness > 0 and segments >= 8
    half = width / 2
    radius = (half * half + sagitta * sagitta) / (2 * sagitta)
    baseline = math.sqrt(radius * radius - half * half)
    def y_at(x):
        return edge_y + math.sqrt(radius * radius - x * x) - baseline
    verts = []
    for i in range(segments + 1):
        x = -half + width * i / segments
        y = y_at(x)
        verts.extend([(x,y-thickness/2,bottom), (x,y+thickness/2,bottom),
                      (x,y+thickness/2,top), (x,y-thickness/2,top)])
    faces = [(3,2,1,0)]
    for i in range(segments):
        a, b = 4*i, 4*(i+1)
        for j in range(4):
            k = (j+1)%4
            faces.append((a+j,a+k,b+k,b+j))
    a = segments*4
    faces.append((a,a+1,a+2,a+3))
    mesh = bpy.data.meshes.new(name + ' | segmented circular arc')
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(mat)
    # Smooth the curved vertical front/back, keep horizontal faces and ends flat.
    for polygon in mesh.polygons:
        polygon.use_smooth = abs(polygon.normal.z) < 0.1 and abs(polygon.normal.x) < 0.99
    bevel = obj.modifiers.new('Soft arc edges', 'BEVEL')
    bevel.width = 0.002
    bevel.segments = 3
    bevel.limit_method = 'ANGLE'
    obj['arc_segments'] = segments
    obj['arc_sagitta_m'] = sagitta
    obj['arc_radius_m'] = radius
    return obj, y_at

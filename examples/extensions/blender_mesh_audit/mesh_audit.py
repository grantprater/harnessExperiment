"""Read-only mesh diagnostics, usable as a Blender script or an imported module.

Detects topology defects and positive-area coplanar, same-facing overlaps.
Ordinary intersections and opposite-facing assembly contacts are not rejected.
This is a bounded diagnostic, not proof of geometric or visual correctness.
"""
from collections import defaultdict
import json
import math
from pathlib import Path
import sys


def cross2(a, b):
    return a[0] * b[1] - a[1] * b[0]


def polygon_area(points):
    return abs(sum(cross2(points[i], points[(i + 1) % len(points)])
                   for i in range(len(points)))) / 2 if len(points) >= 3 else 0.0


def triangle_overlap_area(first, second):
    """Area of intersection of two 2D triangles via convex clipping."""
    clip = list(second)
    if cross2((clip[1][0]-clip[0][0], clip[1][1]-clip[0][1]),
              (clip[2][0]-clip[0][0], clip[2][1]-clip[0][1])) < 0:
        clip.reverse()
    result = list(first)
    for index in range(3):
        a, b = clip[index], clip[(index + 1) % 3]
        edge = (b[0]-a[0], b[1]-a[1])
        def side(p):
            return cross2(edge, (p[0]-a[0], p[1]-a[1]))
        source, result = result, []
        if not source:
            break
        previous = source[-1]
        previous_side = side(previous)
        for point in source:
            current_side = side(point)
            if (current_side >= 0) != (previous_side >= 0):
                amount = previous_side / (previous_side-current_side)
                result.append((previous[0]+amount*(point[0]-previous[0]),
                               previous[1]+amount*(point[1]-previous[1])))
            if current_side >= 0:
                result.append(point)
            previous, previous_side = point, current_side
    return polygon_area(result)


def topology(mesh, matrix, require_closed):
    import bmesh
    from mathutils.kdtree import KDTree
    if not all(math.isfinite(value) for row in matrix for value in row):
        return {'counts': {'nonfinite_transform': 1}, 'errors': ['nonfinite_transform'],
                'warnings': [], 'examples': {}}, []
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.normal_update()
        points = [vertex.co for vertex in bm.verts]
        finite = all(all(math.isfinite(x) for x in point) for point in points)
        if not finite:
            return {'counts': {'nonfinite_vertices': sum(not all(math.isfinite(x) for x in p) for p in points)},
                    'errors': ['nonfinite_vertices'], 'warnings': [], 'examples': {}}, []
        diagonal = math.sqrt(sum((max((p[i] for p in points), default=0) -
                                  min((p[i] for p in points), default=0))**2 for i in range(3)))
        length_tolerance = max(diagonal * 1e-8, 1e-10)
        area_tolerance = length_tolerance ** 2
        ids = {
            'boundary_edges': [e.index for e in bm.edges if e.is_boundary],
            'wire_edges': [e.index for e in bm.edges if e.is_wire],
            'nonmanifold_edges': [e.index for e in bm.edges if len(e.link_faces) > 2],
            'inconsistent_winding_edges': [e.index for e in bm.edges if e.is_manifold and not e.is_contiguous],
            'zero_length_edges': [e.index for e in bm.edges if e.calc_length() <= length_tolerance],
            'zero_area_faces': [f.index for f in bm.faces if f.calc_area() <= area_tolerance],
            'nonplanar_faces': [], 'duplicate_faces': [], 'duplicate_vertices': [],
        }
        kd = KDTree(len(points))
        for index, point in enumerate(points):
            kd.insert(point, index)
        kd.balance()
        for index, point in enumerate(points):
            if any(other < index for _, other, _ in kd.find_range(point, length_tolerance)):
                ids['duplicate_vertices'].append(index)
        seen = {}
        for face in bm.faces:
            key = tuple(sorted(tuple(round(float(x)/length_tolerance) for x in v.co) for v in face.verts))
            if key in seen:
                ids['duplicate_faces'].append(face.index)
            seen[key] = face.index
            if len(face.verts) > 3 and any(abs((v.co-face.verts[0].co).dot(face.normal)) > max(diagonal*1e-5, 1e-8)
                                         for v in face.verts):
                ids['nonplanar_faces'].append(face.index)
        # Winding and volume are checked per connected shell, so an inward shell
        # cannot be concealed by a larger correctly oriented shell in the same object.
        pending = set(bm.faces)
        components = []
        while pending:
            stack = [pending.pop()]
            faces = []
            while stack:
                face = stack.pop()
                faces.append(face)
                for edge in face.edges:
                    for neighbor in edge.link_faces:
                        if neighbor in pending:
                            pending.remove(neighbor)
                            stack.append(neighbor)
            components.append(faces)
        mesh.calc_loop_triangles()
        triangles_by_face = defaultdict(list)
        for triangle in mesh.loop_triangles:
            triangles_by_face[triangle.polygon_index].append(triangle.vertices)
        inward, flat_shells = [], []
        for faces in components:
            if not all(len(e.link_faces) == 2 for f in faces for e in f.edges):
                continue
            vertices = {v for f in faces for v in f.verts}
            reference = sum((v.co for v in vertices), start=points[0].copy()*0) / len(vertices)
            volume = 0.0
            for face in faces:
                for triangle in triangles_by_face[face.index]:
                    a, b, c = [mesh.vertices[i].co-reference for i in triangle]
                    volume += a.dot(b.cross(c)) / 6
            shell_diagonal = math.sqrt(sum((max(v.co[i] for v in vertices)-min(v.co[i] for v in vertices))**2
                                          for i in range(3)))
            volume_tolerance = max(shell_diagonal ** 3 * 1e-12, 1e-18)
            if volume < -volume_tolerance:
                inward.append(faces[0].index)
            if abs(volume) <= volume_tolerance:
                flat_shells.append(faces[0].index)
        ids['inward_closed_shells'] = inward
        ids['zero_volume_closed_shells'] = flat_shells
        errors = [name for name, values in ids.items() if values and name not in
                  {'boundary_edges', 'duplicate_vertices', 'nonplanar_faces'}]
        if require_closed and ids['boundary_edges']:
            errors.append('boundary_edges')
        if not bm.faces:
            errors.append('empty_mesh')
        if matrix.determinant() == 0:
            errors.append('singular_transform')
        warnings = [name for name in ('duplicate_vertices', 'nonplanar_faces') if ids[name]]
        if not require_closed and ids['boundary_edges']:
            warnings.append('boundary_edges')
        if matrix.determinant() < 0:
            warnings.append('negative_transform_determinant')
        geometry = []
        for triangle in mesh.loop_triangles:
            vertices = [matrix @ mesh.vertices[i].co for i in triangle.vertices]
            normal = (vertices[1]-vertices[0]).cross(vertices[2]-vertices[0])
            if normal.length <= area_tolerance:
                continue
            normal.normalize()
            geometry.append({'face': triangle.polygon_index, 'vertices': vertices, 'normal': normal,
                             'plane': normal.dot(vertices[0]),
                             'low': tuple(min(p[i] for p in vertices) for i in range(3)),
                             'high': tuple(max(p[i] for p in vertices) for i in range(3))})
        return {'counts': {name: len(values) for name, values in ids.items()},
                'errors': errors, 'warnings': warnings,
                'examples': {name: values[:12] for name, values in ids.items() if values},
                'vertices': len(mesh.vertices), 'faces': len(mesh.polygons),
                'connected_components': len(components), 'length_tolerance': length_tolerance}, geometry
    finally:
        bm.free()


def coplanar_overlaps(triangles, distance_tolerance=1e-6, max_candidates=2_000_000):
    groups = defaultdict(list)
    found = {}
    candidates = 0
    for index, triangle in enumerate(triangles):
        normal = triangle['normal']
        key = tuple(round(float(value), 4) for value in normal)
        plane = round(triangle['plane']/distance_tolerance)
        for neighbor_plane in (plane-1, plane, plane+1):
            for other in groups[(key, neighbor_plane)]:
                candidates += 1
                if candidates > max_candidates:
                    return list(found.values()), False, candidates
                if (triangle['object'], triangle['face']) == (other['object'], other['face']):
                    continue
                if normal.dot(other['normal']) < 1-1e-7:
                    continue
                if any(abs(normal.dot(p)-triangle['plane']) > distance_tolerance for p in other['vertices']):
                    continue
                if any(triangle['low'][i] > other['high'][i]+distance_tolerance or
                       other['low'][i] > triangle['high'][i]+distance_tolerance for i in range(3)):
                    continue
                axis = max(range(3), key=lambda i: abs(normal[i]))
                axes = [i for i in range(3) if i != axis]
                first = [tuple(p[i] for i in axes) for p in triangle['vertices']]
                second = [tuple(p[i] for i in axes) for p in other['vertices']]
                area = triangle_overlap_area(first, second) / abs(normal[axis])
                if area <= distance_tolerance ** 2:
                    continue
                identities = tuple(sorted(((triangle['object'], triangle['face']), (other['object'], other['face']))))
                if identities not in found:
                    found[identities] = {'objects': [p[0] for p in identities], 'faces': [p[1] for p in identities],
                                         'overlap_area': 0.0, 'normal': list(normal),
                                         'kind': 'same_facing_coplanar_overlap'}
                found[identities]['overlap_area'] += area
        groups[(key, plane)].append(triangle)
    return sorted(found.values(), key=lambda row: -row['overlap_area']), True, candidates


def audit_scene(object_names=None, require_closed=True, max_triangles=20_000):
    import bpy
    scene = bpy.context.scene
    selected = sorted((obj for obj in scene.objects if obj.type == 'MESH'
                       and (object_names is not None or not obj.hide_render)
                       and (object_names is None or obj.name in object_names)), key=lambda obj: obj.name)
    if object_names is not None and set(object_names)-{obj.name for obj in selected}:
        raise ValueError('Requested mesh objects were not found')
    stages = {'source': [], 'evaluated': []}
    rows = []
    complete = True
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in selected:
        source, geometry = topology(obj.data, obj.matrix_world, require_closed)
        for triangle in geometry:
            triangle['object'] = obj.name
        stages['source'].extend(geometry)
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            result, geometry = topology(mesh, evaluated.matrix_world, require_closed)
        finally:
            evaluated.to_mesh_clear()
        for triangle in geometry:
            triangle['object'] = obj.name
        stages['evaluated'].extend(geometry)
        modifier_warnings = []
        if any(m.type == 'WEIGHTED_NORMAL' and m.show_viewport for m in obj.modifiers) and not any(p.use_smooth for p in obj.data.polygons):
            modifier_warnings.append('weighted_normals_without_source_smooth_faces')
        rows.append({'object': obj.name, 'source': source, 'evaluated': result,
                     'modifier_warnings': modifier_warnings})
    overlap_results = {}
    for name, triangles in stages.items():
        if len(triangles) > max_triangles:
            overlap_results[name] = {'complete': False, 'reason': 'triangle_limit', 'triangles': len(triangles), 'pairs': []}
            complete = False
        else:
            pairs, finished, candidates = coplanar_overlaps(triangles)
            overlap_results[name] = {'complete': finished, 'triangles': len(triangles),
                                     'candidates': candidates, 'pair_count': len(pairs), 'pairs': pairs[:100]}
            complete &= finished
    topology_errors = sum(len(row[stage]['errors']) for row in rows for stage in ('source', 'evaluated'))
    overlaps = sum(result.get('pair_count', len(result['pairs'])) for result in overlap_results.values())
    evaluated_errors = sum(len(row['evaluated']['errors']) for row in rows)
    evaluated_overlaps = overlap_results['evaluated'].get('pair_count', len(overlap_results['evaluated']['pairs']))
    warnings = sum(len(row[stage]['warnings']) for row in rows for stage in ('source', 'evaluated'))
    warnings += sum(len(row['modifier_warnings']) for row in rows)
    if not selected:
        complete = False
    return {'audit_version': 1, 'complete': complete,
            'passed': complete and evaluated_errors == 0 and evaluated_overlaps == 0,
            'policy': {'require_closed': require_closed, 'distance_tolerance_world_units': 1e-6,
                       'acceptance_geometry': 'evaluated; source findings are diagnostic',
                       'default_object_selection': 'render-visible meshes; explicitly named objects override',
                       'opposite_facing_contacts': 'allowed', 'ordinary_intersections': 'not checked',
                       'self_intersections': 'not comprehensively checked', 'visual_shading': 'not established'},
            'summary': {'objects': len(rows), 'topology_error_categories': topology_errors,
                        'evaluated_topology_error_categories': evaluated_errors,
                        'evaluated_coplanar_face_pairs': evaluated_overlaps,
                        'coplanar_face_pairs_across_both_stages': overlaps, 'warning_categories': warnings},
            'objects': rows, 'overlaps': overlap_results}


if __name__ == '__main__':
    arguments = sys.argv[sys.argv.index('--') + 1:]
    output = Path(arguments[0])
    options = json.loads(arguments[1]) if len(arguments) > 1 else {}
    report = audit_scene(**options)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('RETICLE_MESH_AUDIT=' + json.dumps(report['summary']))

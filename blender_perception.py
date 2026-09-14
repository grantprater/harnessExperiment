"""Blender Scene Graph Perception Engine.

Provides multi-scale sensory transduction for 3D Blender projects:
1. Macro Scene Sensor (`extract_scene_graph`, `render_scene_skeleton`):
   - Extracts complete scene graph hierarchy, object types, bounding boxes, active modifiers, and materials into a ~150-token Markdown skeleton.
2. Mesoscopic Object Saccade (`inspect_object_detail`):
   - Foveates into a specific 3D object to inspect modifier parameters, vertex counts, and shader node trees without polluting context with other assets.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any, Dict, List, Optional, Union

import blender_env as be


INSPECTION_SCRIPT = """
import bpy
import json
import sys

def get_scene_summary():
    data = {
        "scene_name": bpy.context.scene.name,
        "render_engine": bpy.context.scene.render.engine,
        "resolution": [bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y],
        "objects": []
    }
    
    for obj in bpy.data.objects:
        obj_info = {
            "name": obj.name,
            "type": obj.type,
            "parent": obj.parent.name if obj.parent else None,
            "location": [round(v, 2) for v in obj.location],
            "dimensions": [round(v, 2) for v in obj.dimensions] if hasattr(obj, "dimensions") else None,
            "modifiers": [{"name": m.name, "type": m.type} for m in getattr(obj, "modifiers", [])],
            "materials": [slot.material.name for slot in getattr(obj, "material_slots", []) if slot.material]
        }
        
        # Light specific
        if obj.type == "LIGHT" and hasattr(obj.data, "energy"):
            obj_info["light_energy"] = round(obj.data.energy, 1)
            obj_info["light_color"] = [round(c, 2) for c in obj.data.color]
            
        # Camera specific
        if obj.type == "CAMERA" and hasattr(obj.data, "lens"):
            obj_info["camera_lens"] = round(obj.data.lens, 1)
            obj_info["camera_dof"] = obj.data.dof.use_dof if hasattr(obj.data, "dof") else False
            
        data["objects"].append(obj_info)
        
    print("=== SCENE_JSON_START ===")
    print(json.dumps(data))
    print("=== SCENE_JSON_END ===")

if __name__ == "__main__":
    get_scene_summary()
"""


OBJECT_DETAIL_SCRIPT = """
import bpy
import json
import sys

target_name = sys.argv[-1]
obj = bpy.data.objects.get(target_name)
if not obj:
    print(f"=== OBJECT_DETAIL_START ===\\n{json.dumps({'error': f'Object {target_name} not found'})}\\n=== OBJECT_DETAIL_END ===")
else:
    info = {
        "name": obj.name,
        "type": obj.type,
        "location": [round(v, 3) for v in obj.location],
        "rotation_euler": [round(v, 3) for v in obj.rotation_euler],
        "dimensions": [round(v, 3) for v in obj.dimensions] if hasattr(obj, "dimensions") else None,
        "modifiers": []
    }
    if obj.type == "MESH" and obj.data:
        info["vertex_count"] = len(obj.data.vertices)
        info["polygon_count"] = len(obj.data.polygons)
        
    for m in getattr(obj, "modifiers", []):
        m_data = {"name": m.name, "type": m.type}
        for prop in ["width", "segments", "limit_method", "levels", "strength", "thickness"]:
            if hasattr(m, prop):
                m_data[prop] = getattr(m, prop)
        info["modifiers"].append(m_data)
        
    info["materials"] = []
    for slot in getattr(obj, "material_slots", []):
        if slot.material:
            mat = slot.material
            mat_info = {"name": mat.name, "use_nodes": mat.use_nodes, "nodes": []}
            if mat.use_nodes and mat.node_tree:
                for n in mat.node_tree.nodes:
                    mat_info["nodes"].append({"name": n.name, "type": n.type})
            info["materials"].append(mat_info)

    print("=== OBJECT_DETAIL_START ===")
    print(json.dumps(info))
    print("=== OBJECT_DETAIL_END ===")
"""


def extract_scene_graph(blend_file: Union[str, Path]) -> Dict[str, Any]:
    """Extract complete scene graph summary from a .blend file."""
    res = be.run_blender_script(INSPECTION_SCRIPT, blend_file=blend_file)
    if not res.success:
        raise RuntimeError(f"Failed to inspect scene graph: {res.traceback or res.stderr}")

    out = res.stdout
    if "=== SCENE_JSON_START ===" in out and "=== SCENE_JSON_END ===" in out:
        json_str = out.split("=== SCENE_JSON_START ===")[1].split("=== SCENE_JSON_END ===")[0].strip()
        return json.loads(json_str)
    raise ValueError(f"Could not parse scene graph output from Blender: {out[:300]}")


def render_scene_skeleton(scene_data: Dict[str, Any]) -> str:
    """Format scene graph data into a compact Markdown topological skeleton."""
    lines = [
        f"=== Blender Scene: {scene_data.get('scene_name')} ===",
        f"Engine: {scene_data.get('render_engine')} | Resolution: {scene_data.get('resolution')}",
        "| Object Name | Type | Parent | Location [x,y,z] | Modifiers | Materials |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |"
    ]

    for obj in scene_data.get("objects", []):
        mods = ", ".join([f"{m['name']} ({m['type']})" for m in obj.get("modifiers", [])]) or "None"
        mats = ", ".join(obj.get("materials", [])) or "None"
        parent = obj.get("parent") or "-"
        loc = str(obj.get("location"))
        lines.append(
            f"| `{obj['name']}` | {obj['type']} | {parent} | `{loc}` | {mods} | {mats} |"
        )

    lines.append("=== End Scene Skeleton ===")
    return "\n".join(lines)


def inspect_object_detail(blend_file: Union[str, Path], object_name: str) -> Dict[str, Any]:
    """Mesoscopic Saccade: Inspect exact modifier stack and shader node tree of one object."""
    res = be.run_blender_script(OBJECT_DETAIL_SCRIPT, blend_file=blend_file, args=[object_name])
    if not res.success:
        raise RuntimeError(f"Failed to inspect object '{object_name}': {res.traceback or res.stderr}")

    out = res.stdout
    if "=== OBJECT_DETAIL_START ===" in out and "=== OBJECT_DETAIL_END ===" in out:
        json_str = out.split("=== OBJECT_DETAIL_START ===")[1].split("=== OBJECT_DETAIL_END ===")[0].strip()
        return json.loads(json_str)
    raise ValueError(f"Could not parse object detail output: {out[:300]}")

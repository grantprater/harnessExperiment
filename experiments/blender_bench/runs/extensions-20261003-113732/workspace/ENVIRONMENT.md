Blender: `C:/Program Files/Blender Foundation/Blender 5.0/blender.exe` (5.0.0). Use background Python, not bpy in harness Python.
The workspace is your only editing scope. Artifacts and extension sources persist across turns.
Generated tools: write a directory containing manifest.json and tool.py. The manifest requires
name ext_*, description, parameters (object JSON schema), entrypoint "tool.py:execute",
smoke_tests [{"arguments": {...}, "expected": optional JSON}], optional timeout_seconds (0–600).
def execute(arguments, context) receives workspace (absolute path) and validation (bool), returning JSON.
Use extension_stage(path=directory) to validate/queue. Schemas and versions freeze for this turn;
the next turn activates pending tools. extension_list lists versions, extension_rollback queues a prior one.
Schemas support explicit types, properties, required, additionalProperties=false, items, enum,
minimum/maximum, min/maxLength, min/maxItems. Unknown constraints are rejected.
Use ordinary Python subprocess calls inside adapters to invoke Blender. No packages are installed for you.

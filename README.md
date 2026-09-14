# Cognitive Harness Prototype (Reticle)

A lightweight, zero-dependency cognitive agent harness built on systems theory, Gall's Law, and biological memory consolidation.

## Architecture Highlights
1. **Foveated Code Perception (`perception.py`):**
   - Macro view via Python `ast` outlines (function/class signatures and line bounds).
   - Foveated view via bounded line range slicing (`inspect_region`).
2. **Two-Phase Operational Loop (`harness.py`):**
   - **Phase 1: Generative ("Make it work")** — Solves functional requirements until tests turn green.
   - **Phase 2: Compaction ("Make it elegant")** — Editorial pass that red-lines boilerplate and trims unnecessary code without breaking tests.
3. **Predictive Trace Logging (`/traces/`):**
   - Records episodic JSON traces of tasks, tool actions, and step counts.
   - Designed for downstream "Sleep" consolidation into reusable `./skills/`.

## Running the Harness

### 1. Dry Run / Mock Mode (Zero Configuration)
Run directly with Python 3:
```powershell
.\.venv\Scripts\python.exe .\prototypes\cognitive_harness\harness.py
```

### 2. Live Run with Free Gemini 2.0 Flash (Google AI Studio)
Set your Google AI Studio API key and run against the OpenAI-compatible endpoint:
```powershell
$env:LLM_API_KEY = "your_gemini_api_key"
$env:LLM_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
$env:LLM_MODEL = "gemini-2.0-flash"

.\.venv\Scripts\python.exe .\prototypes\cognitive_harness\harness.py
```

### 3. Live Run with Local Ollama (100% Free / Private)
```powershell
$env:LLM_BASE_URL = "http://localhost:11434/v1"
$env:LLM_MODEL = "qwen2.5-coder:7b"

.\.venv\Scripts\python.exe .\prototypes\cognitive_harness\harness.py
```

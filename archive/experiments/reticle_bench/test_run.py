import sys, traceback
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

try:
    from experiments.reticle_bench.reticle_gameplay_analyzer import run_reticle_gameplay_analysis
    print("Calling run_reticle_gameplay_analysis()...")
    res = run_reticle_gameplay_analysis()
    print("Analysis finished successfully!")
except Exception as e:
    traceback.print_exc()

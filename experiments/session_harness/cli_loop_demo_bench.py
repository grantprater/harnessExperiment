"""Fixed correctness and peak-allocation measurement for the CLI loop demo."""
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import tracemalloc


def expected(root):
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        relative = path.relative_to(root).as_posix().encode('utf-8')
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, 'big'))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, 'big'))
        digest.update(content)
    return 'sha256:' + digest.hexdigest()


def measure():
    from reticle.runtime.workspace import WorkspaceTracker, StaleWorkspaceError
    correctness = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tracker = WorkspaceTracker(root)
        correctness.append(tracker.revision() == expected(root))
        (root / 'empty').touch()
        (root / 'nested').mkdir()
        (root / 'nested/unicode.txt').write_text('caf\u00e9\n', encoding='utf-8')
        (root / 'binary').write_bytes(bytes(range(256)))
        correctness.append(tracker.revision() == expected(root))
        before = tracker.revision()
        tracker.write('new.txt', b'new', expected_workspace_revision=before)
        correctness.append(tracker.revision() == expected(root))
        try:
            tracker.write('new.txt', b'wrong', expected_workspace_revision=before)
            correctness.append(False)
        except StaleWorkspaceError:
            correctness.append((root / 'new.txt').read_bytes() == b'new')
        target = root / 'large.bin'
        with target.open('wb') as file:
            for _ in range(16):
                file.write(b'x' * 1048576)
        reference = expected(root)
        peaks, seconds = [], []
        for _ in range(3):
            tracemalloc.start()
            started = time.perf_counter()
            actual = tracker.revision()
            seconds.append(time.perf_counter() - started)
            peaks.append(tracemalloc.get_traced_memory()[1])
            tracemalloc.stop()
            correctness.append(actual == reference)
        return {'correctness_passed': all(correctness), 'checks': len(correctness),
                'file_bytes': target.stat().st_size, 'peaks_bytes': peaks,
                'peak_bytes': max(peaks), 'seconds': seconds,
                'median_seconds': statistics.median(seconds), 'revision': reference}


if __name__ == '__main__':
    if len(sys.argv) > 1:
        sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
    result = measure()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['correctness_passed'] else 1)

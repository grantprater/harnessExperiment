"""Unified CLI for the Reticle Cognitive Harness."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from reticle import __version__
from reticle.adapters.blender_engine import verify_blender_installed, get_blender_path
from reticle.adapters.code_ast import parse_and_inspect_code
from reticle.sensory.spatial_saccade import create_spatial_grid, render_spatial_map
from reticle.sensory.video_stream import VideoStreamTransducer, HAS_CV2


def cmd_version(args):
    print(f"Reticle Cognitive Harness v{__version__}")


def cmd_blender_info(args):
    installed = verify_blender_installed()
    path = get_blender_path()
    print(f"Blender Installed: {installed}")
    print(f"Blender Path: {path if path else 'Not found'}")


def cmd_scan_video(args):
    if not HAS_CV2:
        print("Error: opencv-python and numpy are required to scan video.")
        sys.exit(1)

    video_path = Path(args.video_path)
    if not video_path.exists():
        print(f"Error: Video not found at {video_path}")
        sys.exit(1)

    print(f"Scanning video: {video_path}")
    transducer = VideoStreamTransducer(video_path)
    print(f"Video Properties: {transducer.width}x{transducer.height} @ {transducer.fps} fps ({transducer.duration_s}s)")
    
    dynamics = transducer.scan_dynamics(stride=args.stride)
    print(f"Scan Completed in {dynamics['scan_duration_s']}s ({dynamics['fps_processed']} fps)")
    if dynamics["blackout_timestamp_s"]:
        print(f"Detected Blackout / Cut: t = {dynamics['blackout_timestamp_s']}s")
    transducer.close()


def cmd_scan_audio(args):
    from reticle.sensory.audio_transducer import AudioTransducer
    audio_path = Path(args.audio_path)
    if not audio_path.exists():
        print(f"Error: Audio/video file not found at {audio_path}")
        sys.exit(1)

    print(f"Scanning audio dynamics: {audio_path}")
    transducer = AudioTransducer(audio_path)
    profile = transducer.analyze_profile()
    print(profile.summary())


def cmd_spatial_grid(args):
    w, h = args.width, args.height
    sectors = create_spatial_grid(w, h, rows=args.rows, cols=args.cols)
    print(render_spatial_map(sectors, (w, h)))


def cmd_verify_ast(args):
    fpath = Path(args.file)
    if not fpath.exists():
        print(f"Error: File not found: {fpath}")
        sys.exit(1)
    code = fpath.read_text(encoding="utf-8")
    res = parse_and_inspect_code(code)
    if res.valid:
        print(f"SUCCESS: Valid Python syntax in {fpath}")
        print(f"Functions ({len(res.functions)}): {res.functions}")
        print(f"Classes ({len(res.classes)}): {res.classes}")
        print(f"Imports ({len(res.imports)}): {res.imports}")
    else:
        print(f"SYNTAX ERROR on line {res.error_line}: {res.syntax_error}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="reticle",
        description="Reticle: Cognitive Harness for Multimodal AI Agents"
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # version
    p_ver = subparsers.add_parser("version", help="Show Reticle version")
    p_ver.set_defaults(func=cmd_version)

    # blender-info
    p_blend = subparsers.add_parser("blender-info", help="Check local Blender installation")
    p_blend.set_defaults(func=cmd_blender_info)

    # scan-video
    p_video = subparsers.add_parser("scan-video", help="Deterministically scan video dynamics")
    p_video.add_argument("video_path", help="Path to video file (.mp4, .mov, etc.)")
    p_video.add_argument("--stride", type=int, default=5, help="Frame stride for optical sampling (default: 5)")
    p_video.set_defaults(func=cmd_scan_video)

    # scan-audio
    p_audio = subparsers.add_parser("scan-audio", help="Deterministically scan audio transients and RMS envelope")
    p_audio.add_argument("audio_path", help="Path to audio (.wav) or video (.mp4) file")
    p_audio.set_defaults(func=cmd_scan_audio)

    # spatial-grid
    p_grid = subparsers.add_parser("spatial-grid", help="Display spatial sector topology")
    p_grid.add_argument("width", type=int, help="Canvas width in pixels")
    p_grid.add_argument("height", type=int, help="Canvas height in pixels")
    p_grid.add_argument("--rows", type=int, default=3, help="Grid rows (default: 3)")
    p_grid.add_argument("--cols", type=int, default=3, help="Grid columns (default: 3)")
    p_grid.set_defaults(func=cmd_spatial_grid)

    # verify-ast
    p_ast = subparsers.add_parser("verify-ast", help="Validate Python syntax via AST compiler")
    p_ast.add_argument("file", help="Python source file to inspect")
    p_ast.set_defaults(func=cmd_verify_ast)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

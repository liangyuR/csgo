from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import OfflineAimAnalyzer, run_pipeline


# ------------------------------------------------------------------
# Offline sub-command
# ------------------------------------------------------------------

def _build_offline_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "offline",
        help="Process a pre-recorded image / video and export annotated output.",
    )
    p.add_argument("--source", type=Path, required=True, help="Image, directory, or video to process.")
    p.add_argument("--model", type=Path, default=Path("model/best.pt"), help="Path to YOLO model.")
    p.add_argument("--output-dir", type=Path, default=Path("outputs/default_run"), help="Output directory.")
    p.add_argument("--conf", type=float, default=0.35, help="Confidence threshold.")
    p.add_argument("--imgsz", type=int, default=960, help="Inference image size.")
    p.add_argument("--device", type=str, default=None, help="Ultralytics device, e.g. cpu, 0.")
    p.add_argument(
        "--target-class-name",
        action="append",
        default=[],
        help="Allowed target class name. Repeat this flag to add more classes.",
    )
    p.add_argument(
        "--target-class-id",
        action="append",
        type=int,
        default=[],
        help="Allowed target class id. Repeat this flag to add more ids.",
    )
    p.add_argument(
        "--aim-mode",
        choices=["center", "upper_center"],
        default="center",
        help="How to convert a bbox into a suggested aim point.",
    )
    p.add_argument(
        "--head-fraction",
        type=float,
        default=0.18,
        help="When aim-mode=upper_center, y is placed at bbox_top + height * head_fraction.",
    )
    p.add_argument(
        "--list-classes",
        action="store_true",
        help="Print model class ids/names and exit.",
    )


def _run_offline(args: argparse.Namespace) -> int:
    analyzer = OfflineAimAnalyzer(
        model_path=args.model,
        confidence=args.conf,
        imgsz=args.imgsz,
        device=args.device,
        target_class_names=args.target_class_name,
        target_class_ids=args.target_class_id,
        aim_mode=args.aim_mode,
        head_fraction=args.head_fraction,
    )

    if args.list_classes:
        for class_id, class_name in analyzer.list_classes().items():
            print(f"{class_id}: {class_name}")
        return 0

    summary = run_pipeline(args.source, args.output_dir, analyzer)
    print(f"Input:             {summary.input_path}")
    print(f"Output:            {summary.output_dir}")
    print(f"Media type:        {summary.media_type}")
    print(f"Files processed:   {summary.files_processed}")
    print(f"Frames processed:  {summary.frames_processed}")
    print(f"Detections written:{summary.detections_written}")
    return 0


# ------------------------------------------------------------------
# Realtime sub-command
# ------------------------------------------------------------------

def _build_realtime_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "realtime",
        help="Real-time screen capture + YOLO inference + mouse control.",
    )
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to YAML config file (default: config.yaml in CWD).",
    )


def _run_realtime(args: argparse.Namespace) -> int:
    from .config import load_config
    from .realtime import run_realtime

    cfg = load_config(args.config)
    run_realtime(cfg)
    return 0


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CSGO vision demo -- offline analysis and real-time aim assist.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py offline --source footage.mp4 --model model/best.pt\n"
            "  python main.py realtime --config config.yaml\n"
            "  python main.py offline --list-classes --model model/best.pt\n"
        ),
    )
    sub = parser.add_subparsers(dest="command")
    _build_offline_parser(sub)
    _build_realtime_parser(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "offline":
        return _run_offline(args)
    if args.command == "realtime":
        return _run_realtime(args)

    parser.print_help()
    return 1

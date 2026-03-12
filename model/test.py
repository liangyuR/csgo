from __future__ import annotations

import argparse
from pathlib import Path

import cv2
from ultralytics import YOLO


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a simple YOLO detection on one image.")
    parser.add_argument("--image", type=Path, default=Path(__file__).with_name("test.png"), help="Input image path.")
    parser.add_argument(
        "--model",
        type=Path,
        default=Path(__file__).with_name("yolo26n-pose.pt"),
        help="YOLO model path.",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.25,
        help="Confidence threshold.",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="0",
        help="Inference device, e.g. cpu or 0.",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Do not open an OpenCV preview window.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if not args.image.exists():
        raise FileNotFoundError(f"Image not found: {args.image}")
    if not args.model.exists():
        raise FileNotFoundError(f"Model not found: {args.model}")

    model = YOLO(str(args.model))
    result = model.predict(source=str(args.image), conf=args.conf, device=args.device, verbose=False)[0]
    annotated = result.plot()

    output_path = args.image.with_name(f"{args.image.stem}_detected{args.image.suffix}")
    cv2.imwrite(str(output_path), annotated)

    print(f"Image:   {args.image}")
    print(f"Model:   {args.model}")
    print(f"Output:  {output_path}")
    print(f"Device:  {args.device}")
    print(f"Boxes:   {0 if result.boxes is None else len(result.boxes)}")

    if not args.no_show:
        cv2.imshow("YOLO Detection", annotated)
        print("Press any key in the preview window to close.")
        cv2.waitKey(0)
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

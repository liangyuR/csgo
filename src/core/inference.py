"""Inference utilities."""

from __future__ import annotations

from typing import Any, List, Tuple

import numpy as np
import numpy.typing as npt

_FAST_PATH_INPUT_SIZE = 640
_PIXEL_SCALE = np.float32(1.0 / 255.0)


class PIDController:
    """Time-aware PID controller with conservative internal damping."""

    def __init__(
        self,
        Kp: float,
        Ki: float,
        Kd: float,
        integral_limit: float = 500.0,
        derivative_alpha: float = 0.25,
    ) -> None:
        self.Kp = Kp
        self.Ki = Ki
        self.Kd = Kd
        self.integral_limit = max(0.0, float(integral_limit))
        self.derivative_alpha = min(max(float(derivative_alpha), 0.0), 1.0)
        self.reset()

    def reset(self) -> None:
        self.integral: float = 0.0
        self.previous_error: float = 0.0
        self.filtered_derivative: float = 0.0
        self.has_previous_error: bool = False

    def update(self, error: float, dt: float) -> float:
        safe_dt = max(float(dt), 1e-4)

        self.integral += error * safe_dt
        if self.integral_limit > 0.0:
            self.integral = max(-self.integral_limit, min(self.integral_limit, self.integral))

        raw_derivative = 0.0
        if self.has_previous_error:
            raw_derivative = (error - self.previous_error) / safe_dt

        alpha = self.derivative_alpha
        self.filtered_derivative = ((1.0 - alpha) * self.filtered_derivative) + (alpha * raw_derivative)

        adjusted_kp = self._calculate_adjusted_kp(self.Kp)
        output = (
            (adjusted_kp * error)
            + (self.Ki * self.integral)
            + (self.Kd * self.filtered_derivative)
        )

        self.previous_error = error
        self.has_previous_error = True
        return output

    def _calculate_adjusted_kp(self, kp: float) -> float:
        # Linear passthrough: the previous 3x ramp above Kp=0.5 caused
        # oscillation at large errors and undershoot at small ones.
        return kp


def preprocess_image(
    image: npt.NDArray[np.uint8],
    model_input_size: int,
    buffer: npt.NDArray[np.float32] | None = None,
) -> npt.NDArray[np.float32]:
    if image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError(f"Expected HxWx3 or HxWx4 image, got shape {image.shape}")

    height, width = image.shape[:2]
    if height > model_input_size or width > model_input_size:
        raise ValueError(
            f"Capture size {width}x{height} exceeds fixed model input {model_input_size}x{model_input_size}"
        )

    expected_shape = (1, 3, model_input_size, model_input_size)
    if buffer is None or buffer.shape != expected_shape:
        tensor = np.empty(expected_shape, dtype=np.float32)
    else:
        tensor = buffer

    fast_path = (
        model_input_size == _FAST_PATH_INPUT_SIZE
        and image.shape == (_FAST_PATH_INPUT_SIZE, _FAST_PATH_INPUT_SIZE, 3)
        and image.dtype == np.uint8
        and image.flags.c_contiguous
    )
    if fast_path:
        tensor[0, 0] = image[:, :, 0] * _PIXEL_SCALE
        tensor[0, 1] = image[:, :, 1] * _PIXEL_SCALE
        tensor[0, 2] = image[:, :, 2] * _PIXEL_SCALE
        return tensor

    tensor.fill(0.0)

    if image.shape[2] == 4:
        rgb = image[:, :, 2::-1]
    else:
        rgb = image

    np.copyto(
        tensor[0, :, :height, :width],
        np.moveaxis(rgb, -1, 0).astype(np.float32, copy=False),
    )
    tensor[0, :, :height, :width] *= _PIXEL_SCALE
    return tensor


def postprocess_outputs(
    outputs: List[Any],
    original_width: int,
    original_height: int,
    model_input_size: int,
    min_confidence: float,
    offset_x: int = 0,
    offset_y: int = 0,
) -> Tuple[npt.NDArray[np.float32], npt.NDArray[np.float32], npt.NDArray[np.int32]]:
    predictions = outputs[0][0].T
    if predictions.size == 0:
        return (
            np.empty((0, 4), dtype=np.float32),
            np.empty((0,), dtype=np.float32),
            np.empty((0,), dtype=np.int32),
        )

    if predictions.shape[1] > 5:
        class_scores = predictions[:, 4:]
        class_ids = np.argmax(class_scores, axis=1)
        confidences = class_scores[np.arange(class_scores.shape[0]), class_ids]
    else:
        confidences = predictions[:, 4]
        class_ids = np.zeros(len(predictions), dtype=np.int32)

    conf_mask = confidences >= min_confidence
    filtered_predictions = predictions[conf_mask]
    filtered_confidences = confidences[conf_mask]
    filtered_class_ids = class_ids[conf_mask]

    if len(filtered_predictions) == 0:
        return (
            np.empty((0, 4), dtype=np.float32),
            np.empty((0,), dtype=np.float32),
            np.empty((0,), dtype=np.int32),
        )

    scale_x = original_width / model_input_size
    scale_y = original_height / model_input_size

    cx = filtered_predictions[:, 0]
    cy = filtered_predictions[:, 1]
    w = filtered_predictions[:, 2]
    h = filtered_predictions[:, 3]

    x1 = (cx - w / 2) * scale_x + offset_x
    y1 = (cy - h / 2) * scale_y + offset_y
    x2 = (cx + w / 2) * scale_x + offset_x
    y2 = (cy + h / 2) * scale_y + offset_y

    boxes = np.stack([x1, y1, x2, y2], axis=1).astype(np.float32, copy=False)
    return boxes, filtered_confidences.astype(np.float32, copy=False), filtered_class_ids.astype(np.int32, copy=False)


def non_max_suppression(
    boxes: npt.ArrayLike,
    confidences: npt.ArrayLike,
    class_ids: npt.ArrayLike,
    iou_threshold: float = 0.4,
) -> Tuple[npt.NDArray[np.float32], npt.NDArray[np.float32], npt.NDArray[np.int32]]:
    if len(boxes) == 0:
        return (
            np.empty((0, 4), dtype=np.float32),
            np.empty((0,), dtype=np.float32),
            np.empty((0,), dtype=np.int32),
        )

    boxes_arr = np.array(boxes, dtype=np.float32)
    confidences_arr = np.array(confidences, dtype=np.float32)
    class_ids_arr = np.array(class_ids, dtype=np.int32)

    kept_indices: List[int] = []
    for class_id in np.unique(class_ids_arr):
        class_mask = class_ids_arr == class_id
        class_indices = np.where(class_mask)[0]
        class_boxes = boxes_arr[class_mask]
        class_confidences = confidences_arr[class_mask]
        areas = (class_boxes[:, 2] - class_boxes[:, 0]) * (class_boxes[:, 3] - class_boxes[:, 1])
        order = class_confidences.argsort()[::-1]

        while len(order) > 0:
            current = order[0]
            kept_indices.append(class_indices[current])
            if len(order) == 1:
                break

            xx1 = np.maximum(class_boxes[current, 0], class_boxes[order[1:], 0])
            yy1 = np.maximum(class_boxes[current, 1], class_boxes[order[1:], 1])
            xx2 = np.minimum(class_boxes[current, 2], class_boxes[order[1:], 2])
            yy2 = np.minimum(class_boxes[current, 3], class_boxes[order[1:], 3])

            w = np.maximum(0, xx2 - xx1)
            h = np.maximum(0, yy2 - yy1)
            intersection = w * h
            union = areas[current] + areas[order[1:]] - intersection
            iou = np.divide(intersection, union, out=np.zeros_like(intersection), where=union > 0)
            order = order[1:][iou <= iou_threshold]

    kept_indices.sort(key=lambda idx: confidences[idx], reverse=True)
    return (
        boxes_arr[kept_indices],
        confidences_arr[kept_indices],
        class_ids_arr[kept_indices].astype(np.int32, copy=False),
    )

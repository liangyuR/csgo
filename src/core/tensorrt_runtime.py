"""Raw TensorRT engine runtime — minimal Python overhead inference.

Bypasses Ultralytics predict() pipeline entirely: no letterboxing wrapper,
no Results object construction, no per-call buffer allocation.
Requires: tensorrt, pycuda
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from .detection_state import DetectionPayload, empty_detection_payload
from .inference import non_max_suppression, postprocess_outputs, preprocess_image

logger = logging.getLogger(__name__)
EMPTY_DETECTION_PAYLOAD = empty_detection_payload()

_TRT_AVAILABLE = False
_trt = None
_cuda = None

try:
    import tensorrt as _trt_mod  # type: ignore[import-not-found]
    import pycuda.driver as _cuda_mod  # type: ignore[import-not-found]
    import pycuda.autoinit  # type: ignore[import-not-found]  # noqa: F401

    _trt = _trt_mod
    _cuda = _cuda_mod
    _TRT_AVAILABLE = True
except Exception:
    pass

_TRT_LOGGER = _trt.Logger(_trt.Logger.WARNING) if _TRT_AVAILABLE and _trt is not None else None


def is_available() -> bool:
    """Return True if tensorrt + pycuda are importable."""
    return _TRT_AVAILABLE


class TensorRTEngineModel:
    """Direct TensorRT inference with pre-allocated page-locked CUDA buffers.

    Compared to UltralyticsEngineModel.detect():
    - No letterbox/resize wrapper
    - No Ultralytics Results construction overhead
    - Reuses page-locked host and device buffers every call
    - Runs execute_async_v3 (TRT 8.5+) or execute_async_v2 (TRT 8.x)
    """

    provider_name = "TensorRT/Direct"

    def __init__(self, engine_path: str, input_size: int) -> None:
        if not _TRT_AVAILABLE or _trt is None or _cuda is None:
            raise RuntimeError(
                "tensorrt and pycuda are required for TensorRTEngineModel. "
                "pip install tensorrt pycuda"
            )

        self.engine_path = engine_path
        self.input_size = int(input_size)

        with open(engine_path, "rb") as f:
            engine_data = f.read()

        runtime = _trt.Runtime(_TRT_LOGGER)
        self._engine = runtime.deserialize_cuda_engine(engine_data)
        if self._engine is None:
            raise RuntimeError(f"Failed to deserialize TensorRT engine: {engine_path}")

        self._context = self._engine.create_execution_context()
        self._stream = _cuda.Stream()
        self._inputs: list[dict] = []
        self._outputs: list[dict] = []
        self._bindings: list[int] = []
        self._allocate_buffers()
        self._preprocess_buf: np.ndarray | None = None
        self._input_dtype = self._inputs[0]["dtype"] if self._inputs else np.float32

    # ------------------------------------------------------------------
    # Buffer allocation — handles TRT 10 (num_io_tensors) and TRT 8 (num_bindings)
    # ------------------------------------------------------------------

    def _allocate_buffers(self) -> None:
        use_new_api = hasattr(self._engine, "num_io_tensors")
        if use_new_api:
            self._allocate_buffers_new_api()
        else:
            self._allocate_buffers_legacy_api()

    def _allocate_buffers_new_api(self) -> None:
        for i in range(self._engine.num_io_tensors):
            name = self._engine.get_tensor_name(i)
            dtype = _trt.nptype(self._engine.get_tensor_dtype(name))
            raw_shape = tuple(self._engine.get_tensor_shape(name))
            shape = tuple(self.input_size if s < 0 else s for s in raw_shape)
            host_mem = _cuda.pagelocked_empty(int(np.prod(shape)), dtype)
            device_mem = _cuda.mem_alloc(host_mem.nbytes)
            self._bindings.append(int(device_mem))
            entry = {
                "name": name,
                "host": host_mem,
                "device": device_mem,
                "shape": shape,
                "dtype": dtype,
            }
            mode = self._engine.get_tensor_mode(name)
            if mode == _trt.TensorIOMode.INPUT:
                self._inputs.append(entry)
            else:
                self._outputs.append(entry)

    def _allocate_buffers_legacy_api(self) -> None:
        for binding in self._engine:
            dtype = _trt.nptype(self._engine.get_binding_dtype(binding))
            raw_shape = tuple(self._engine.get_binding_shape(binding))
            shape = tuple(self.input_size if s < 0 else s for s in raw_shape)
            host_mem = _cuda.pagelocked_empty(int(np.prod(shape)), dtype)
            device_mem = _cuda.mem_alloc(host_mem.nbytes)
            self._bindings.append(int(device_mem))
            entry = {
                "name": binding,
                "host": host_mem,
                "device": device_mem,
                "shape": shape,
                "dtype": dtype,
            }
            if self._engine.binding_is_input(binding):
                self._inputs.append(entry)
            else:
                self._outputs.append(entry)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def warmup(self, iterations: int = 3) -> None:
        warmup_frame = np.zeros((self.input_size, self.input_size, 3), dtype=np.uint8)
        for _ in range(max(1, int(iterations))):
            self.detect(warmup_frame, min_confidence=0.0)

    def detect(
        self,
        frame: Any,
        min_confidence: float,
        offset_x: int = 0,
        offset_y: int = 0,
        target_class_id: int | None = None,
        fov_bounds: tuple[int, int, int, int] | None = None,
    ) -> DetectionPayload:
        if frame is None:
            return EMPTY_DETECTION_PAYLOAD

        # Preprocess: uint8 HWC → float32 NCHW (reuses allocated buffer)
        tensor = preprocess_image(frame, self.input_size, self._preprocess_buf)
        self._preprocess_buf = tensor

        # Upload input — cast to engine's input dtype if needed (fp16 engines)
        inp = self._inputs[0]
        flat = tensor.ravel()
        if flat.dtype != inp["dtype"]:
            flat = flat.astype(inp["dtype"], copy=False)
        np.copyto(inp["host"], flat)
        _cuda.memcpy_htod_async(inp["device"], inp["host"], self._stream)

        # Execute
        self._execute()

        # Download outputs
        for out in self._outputs:
            _cuda.memcpy_dtoh_async(out["host"], out["device"], self._stream)
        self._stream.synchronize()

        # Reshape output and postprocess
        out = self._outputs[0]
        raw_output = out["host"].reshape(out["shape"]).astype(np.float32, copy=False)

        h = frame.shape[0] if hasattr(frame, "shape") else self.input_size
        w = frame.shape[1] if hasattr(frame, "shape") else self.input_size

        boxes, confidences, class_ids = postprocess_outputs(
            [raw_output], w, h, self.input_size, min_confidence, offset_x, offset_y
        )
        if boxes.size == 0:
            return EMPTY_DETECTION_PAYLOAD

        boxes, confidences, class_ids = non_max_suppression(boxes, confidences, class_ids)
        if boxes.size == 0:
            return EMPTY_DETECTION_PAYLOAD

        keep_mask = np.ones(len(boxes), dtype=bool)
        if target_class_id is not None:
            keep_mask &= class_ids == int(target_class_id)

        if fov_bounds is not None:
            fl, ft, fr, fb = fov_bounds
            keep_mask &= (
                (boxes[:, 0] < fr)
                & (boxes[:, 2] > fl)
                & (boxes[:, 1] < fb)
                & (boxes[:, 3] > ft)
            )

        if not np.any(keep_mask):
            return EMPTY_DETECTION_PAYLOAD

        return DetectionPayload(
            boxes=boxes[keep_mask],
            confidences=confidences[keep_mask],
            class_ids=class_ids[keep_mask],
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute(self) -> None:
        use_v3 = hasattr(self._context, "execute_async_v3")
        if use_v3:
            for binding in self._inputs + self._outputs:
                self._context.set_tensor_address(binding["name"], int(binding["device"]))
            self._context.execute_async_v3(self._stream.handle)
        else:
            self._context.execute_async_v2(
                bindings=self._bindings, stream_handle=self._stream.handle
            )

    def __del__(self) -> None:
        if _cuda is None:
            return
        try:
            for buf in self._inputs + self._outputs:
                buf["device"].free()
        except Exception:
            pass

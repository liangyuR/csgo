"""Raw TensorRT engine runtime — no pycuda, uses torch.cuda + CUDA Graphs.

Bypasses Ultralytics predict() pipeline: no letterbox wrapper,
no Results construction, no per-call buffer allocation.

Requires:
  tensorrt  — Python wheel (same install as the C++ TRT used by Ultralytics)
  torch     — already present via Ultralytics; provides all CUDA memory ops

Why torch instead of pycuda:
  pycuda.autoinit (used in the old version) must run AFTER a CUDA context
  exists.  When tensorrt_runtime is imported at startup — before PyTorch or
  Ultralytics touch the GPU — autoinit silently fails and _TRT_AVAILABLE
  stays False.  Using torch.cuda avoids this entirely: torch.cuda.init() is
  idempotent and always safe to call.

CUDA Graph optimisation:
  After warmup(), execute_async_v3 + H2D/D2H copies are captured into a
  replayable CUDA Graph.  Replay eliminates per-call CPU kernel-dispatch
  overhead (~0.5-1 ms for small models like YOLO nano).
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
_torch = None

try:
    import tensorrt as _trt_mod  # type: ignore[import-not-found]
    import torch as _torch_mod  # type: ignore[import-not-found]

    # torch.cuda.is_available() is a safe CPU-only check; no context required
    if _torch_mod.cuda.is_available():
        _trt = _trt_mod
        _torch = _torch_mod
        _TRT_AVAILABLE = True
except Exception:
    pass

_TRT_LOGGER = _trt.Logger(_trt.Logger.WARNING) if _TRT_AVAILABLE and _trt is not None else None

# Populated once after _trt and _torch are confirmed live
_TRT_TO_TORCH_DTYPE: dict = {}


def _init_dtype_map() -> None:
    if _TRT_TO_TORCH_DTYPE or not _TRT_AVAILABLE:
        return
    import torch
    _TRT_TO_TORCH_DTYPE.update(
        {
            _trt.DataType.FLOAT: torch.float32,
            _trt.DataType.HALF: torch.float16,
            _trt.DataType.INT32: torch.int32,
            _trt.DataType.INT8: torch.int8,
            _trt.DataType.BOOL: torch.bool,
        }
    )


def is_available() -> bool:
    """Return True if tensorrt Python wheel + torch CUDA are importable."""
    return _TRT_AVAILABLE


class TensorRTEngineModel:
    """Direct TensorRT inference with torch.cuda buffers and CUDA Graph replay.

    vs the previous pycuda implementation:
    - No pycuda dependency → no autoinit race at startup
    - Uses the same CUDA context as Ultralytics/PyTorch (zero conflicts)
    - CUDA Graph captured during warmup → near-zero dispatch overhead per call
    """

    provider_name = "TensorRT/Direct"

    def __init__(self, engine_path: str, input_size: int) -> None:
        if not _TRT_AVAILABLE or _trt is None or _torch is None:
            raise RuntimeError(
                "tensorrt Python wheel and CUDA-enabled torch are required. "
                "Install: pip install tensorrt"
            )
        _init_dtype_map()

        # Safe no-op if already initialised by Ultralytics
        _torch.cuda.init()

        self.engine_path = engine_path
        self.input_size = int(input_size)

        with open(engine_path, "rb") as f:
            engine_data = f.read()

        runtime = _trt.Runtime(_TRT_LOGGER)
        self._engine = runtime.deserialize_cuda_engine(engine_data)
        if self._engine is None:
            raise RuntimeError(f"Failed to deserialize TensorRT engine: {engine_path}")

        self._context = self._engine.create_execution_context()

        # Dedicated CUDA stream — keeps TRT work isolated from torch's default stream
        self._stream = _torch.cuda.Stream()

        # Pinned CPU + GPU tensor pairs keyed by binding name
        self._io: dict[str, dict] = {}
        self._input_name: str = ""
        self._output_name: str = ""
        self._bindings: list[int] = []  # for legacy TRT 8 execute_async_v2

        self._allocate_buffers()

        self._preprocess_buf: np.ndarray | None = None
        self._fp16_input: bool = self._io[self._input_name]["dtype"] == _torch.float16

        # Filled by _capture_cuda_graph() called from warmup()
        self._cuda_graph: Any = None
        self._graph_captured = False

    # ------------------------------------------------------------------
    # Buffer allocation — supports TRT 10 (num_io_tensors) and TRT 8
    # ------------------------------------------------------------------

    def _allocate_buffers(self) -> None:
        if hasattr(self._engine, "num_io_tensors"):
            self._allocate_buffers_v2()
        else:
            self._allocate_buffers_legacy()

    def _allocate_buffers_v2(self) -> None:
        for i in range(self._engine.num_io_tensors):
            name = self._engine.get_tensor_name(i)
            trt_dtype = self._engine.get_tensor_dtype(name)
            raw_shape = tuple(self._engine.get_tensor_shape(name))
            shape = tuple(self.input_size if s < 0 else s for s in raw_shape)
            numel = int(np.prod(shape))
            dtype = _TRT_TO_TORCH_DTYPE.get(trt_dtype, _torch.float32)

            gpu_buf = _torch.empty(numel, dtype=dtype, device="cuda")
            cpu_buf = _torch.empty(numel, dtype=dtype).pin_memory()

            is_input = self._engine.get_tensor_mode(name) == _trt.TensorIOMode.INPUT
            self._context.set_tensor_address(name, gpu_buf.data_ptr())
            self._io[name] = {
                "cpu": cpu_buf,
                "gpu": gpu_buf,
                "shape": shape,
                "is_input": is_input,
                "dtype": dtype,
            }
            if is_input:
                self._input_name = name
            elif not self._output_name:
                self._output_name = name

    def _allocate_buffers_legacy(self) -> None:
        for binding in self._engine:
            trt_dtype = self._engine.get_binding_dtype(binding)
            raw_shape = tuple(self._engine.get_binding_shape(binding))
            shape = tuple(self.input_size if s < 0 else s for s in raw_shape)
            numel = int(np.prod(shape))
            dtype = _TRT_TO_TORCH_DTYPE.get(trt_dtype, _torch.float32)

            gpu_buf = _torch.empty(numel, dtype=dtype, device="cuda")
            cpu_buf = _torch.empty(numel, dtype=dtype).pin_memory()
            self._bindings.append(gpu_buf.data_ptr())

            is_input = self._engine.binding_is_input(binding)
            self._io[binding] = {
                "cpu": cpu_buf,
                "gpu": gpu_buf,
                "shape": shape,
                "is_input": is_input,
                "dtype": dtype,
            }
            if is_input:
                self._input_name = binding
            elif not self._output_name:
                self._output_name = binding

    # ------------------------------------------------------------------
    # CUDA Graph capture
    # ------------------------------------------------------------------

    def _capture_cuda_graph(self) -> None:
        """Capture H2D + TRT execute + D2H as a single replayable CUDA Graph.

        Before each replay, write new input data to inp["cpu"] (pinned).
        The graph replays the DMA + kernel sequence using whatever is currently
        in those fixed memory addresses — correct and fast.
        """
        inp = self._io[self._input_name]
        out = self._io[self._output_name]

        use_v3 = hasattr(self._context, "execute_async_v3")

        def _run_once() -> None:
            with _torch.cuda.stream(self._stream):
                inp["gpu"].copy_(inp["cpu"], non_blocking=True)
                if use_v3:
                    self._context.execute_async_v3(self._stream.cuda_stream)
                else:
                    self._context.execute_async_v2(
                        bindings=self._bindings,
                        stream_handle=self._stream.cuda_stream,
                    )
                out["cpu"].copy_(out["gpu"], non_blocking=True)
            self._stream.synchronize()

        # Warmup so all lazy TRT internal state is flushed before capture
        for _ in range(3):
            _run_once()

        self._cuda_graph = _torch.cuda.CUDAGraph()
        with _torch.cuda.graph(self._cuda_graph, stream=self._stream):
            inp["gpu"].copy_(inp["cpu"], non_blocking=True)
            if use_v3:
                self._context.execute_async_v3(self._stream.cuda_stream)
            else:
                self._context.execute_async_v2(
                    bindings=self._bindings,
                    stream_handle=self._stream.cuda_stream,
                )
            out["cpu"].copy_(out["gpu"], non_blocking=True)

        self._graph_captured = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def warmup(self, iterations: int = 3) -> None:
        warmup_frame = np.zeros((self.input_size, self.input_size, 3), dtype=np.uint8)
        for _ in range(max(1, int(iterations))):
            self.detect(warmup_frame, min_confidence=0.0)

        try:
            self._capture_cuda_graph()
            logger.info(
                "TensorRT CUDA graph captured — zero-dispatch inference enabled"
            )
        except Exception as exc:
            logger.warning("CUDA graph capture failed (%s); using direct execute", exc)

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

        # Preprocess: uint8 HWC → float32 NCHW (reuses scratch buffer)
        tensor = preprocess_image(frame, self.input_size, self._preprocess_buf)
        self._preprocess_buf = tensor

        inp = self._io[self._input_name]
        out = self._io[self._output_name]

        # Write input into the pinned CPU buffer — pure CPU, not in graph
        flat = tensor.ravel()
        if self._fp16_input:
            flat = flat.astype(np.float16, copy=False)
        np.copyto(inp["cpu"].numpy(), flat)

        if self._graph_captured and self._cuda_graph is not None:
            # Replay: H2D → TRT kernels → D2H, with near-zero CPU overhead
            self._cuda_graph.replay()
            self._stream.synchronize()
        else:
            use_v3 = hasattr(self._context, "execute_async_v3")
            with _torch.cuda.stream(self._stream):
                inp["gpu"].copy_(inp["cpu"], non_blocking=True)
                if use_v3:
                    self._context.execute_async_v3(self._stream.cuda_stream)
                else:
                    self._context.execute_async_v2(
                        bindings=self._bindings,
                        stream_handle=self._stream.cuda_stream,
                    )
                out["cpu"].copy_(out["gpu"], non_blocking=True)
            self._stream.synchronize()

        raw_output = out["cpu"].numpy().reshape(out["shape"]).astype(np.float32, copy=False)

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

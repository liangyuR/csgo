"""TensorRT engine loading and inference helpers."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Any, Iterable

import numpy as np


@dataclass
class _TensorBinding:
    name: str
    index: int
    shape: tuple[int, ...]
    dtype: np.dtype
    is_input: bool
    host: np.ndarray
    device: Any


class TensorRTModel:
    """Thin TensorRT runtime wrapper with a stable infer() interface."""

    provider_name = "TensorRT/CUDA"

    def __init__(self, engine_path: str, expected_input_shape: tuple[int, ...]) -> None:
        self.engine_path = engine_path
        self.expected_input_shape = tuple(int(dim) for dim in expected_input_shape)
        self._trt = self._import_required_module("tensorrt")
        self._cuda = self._import_required_module("pycuda.driver")
        self._pycuda_autoinit = self._import_required_module("pycuda.autoinit")
        self._logger = self._trt.Logger(self._trt.Logger.WARNING)

        with open(engine_path, "rb") as engine_file:
            serialized_engine = engine_file.read()

        self._runtime = self._trt.Runtime(self._logger)
        self._engine = self._runtime.deserialize_cuda_engine(serialized_engine)
        if self._engine is None:
            raise RuntimeError(f"Failed to deserialize TensorRT engine: {engine_path}")

        self._context = self._engine.create_execution_context()
        if self._context is None:
            raise RuntimeError(f"Failed to create TensorRT execution context: {engine_path}")

        self._input_name = self._configure_input_shape()
        self._stream = self._cuda.Stream()
        self._bindings = self._allocate_bindings()
        self._input_binding = next(binding for binding in self._bindings if binding.is_input)
        self.input_shape = self._input_binding.shape
        self.input_dtype = self._input_binding.dtype
        self._binding_ptrs = [0] * len(self._bindings)
        for binding in self._bindings:
            self._binding_ptrs[binding.index] = int(binding.device)

    def _import_required_module(self, module_name: str):
        try:
            return importlib.import_module(module_name)
        except ImportError as exc:
            raise RuntimeError(
                f"TensorRT runtime dependency '{module_name}' is not installed. "
                "Install 'tensorrt' and 'pycuda' before launching the app."
            ) from exc

    def _iter_tensor_names(self) -> Iterable[str]:
        if hasattr(self._engine, "num_io_tensors"):
            for index in range(self._engine.num_io_tensors):
                yield self._engine.get_tensor_name(index)
            return

        for index in range(self._engine.num_bindings):
            yield self._engine.get_binding_name(index)

    def _get_tensor_index(self, name: str) -> int:
        if hasattr(self._engine, "get_binding_index"):
            return int(self._engine.get_binding_index(name))

        for index, tensor_name in enumerate(self._iter_tensor_names()):
            if tensor_name == name:
                return index
        raise KeyError(f"Unknown TensorRT tensor name: {name}")

    def _tensor_is_input(self, name: str) -> bool:
        if hasattr(self._engine, "get_tensor_mode"):
            return self._engine.get_tensor_mode(name) == self._trt.TensorIOMode.INPUT
        return bool(self._engine.binding_is_input(self._get_tensor_index(name)))

    def _get_tensor_dtype(self, name: str) -> np.dtype:
        if hasattr(self._engine, "get_tensor_dtype"):
            tensor_dtype = self._engine.get_tensor_dtype(name)
        else:
            tensor_dtype = self._engine.get_binding_dtype(self._get_tensor_index(name))
        return np.dtype(self._trt.nptype(tensor_dtype))

    def _get_tensor_shape(self, name: str) -> tuple[int, ...]:
        if hasattr(self._context, "get_tensor_shape"):
            shape = self._context.get_tensor_shape(name)
        elif hasattr(self._engine, "get_tensor_shape"):
            shape = self._engine.get_tensor_shape(name)
        else:
            shape = self._context.get_binding_shape(self._get_tensor_index(name))
        return tuple(int(dim) for dim in shape)

    def _configure_input_shape(self) -> str:
        input_names = [name for name in self._iter_tensor_names() if self._tensor_is_input(name)]
        if len(input_names) != 1:
            raise RuntimeError(
                f"Expected exactly one input tensor, found {len(input_names)} in {self.engine_path}"
            )

        input_name = input_names[0]
        current_shape = self._get_tensor_shape(input_name)
        if any(dim < 0 for dim in current_shape):
            if hasattr(self._context, "set_input_shape"):
                self._context.set_input_shape(input_name, self.expected_input_shape)
            else:
                self._context.set_binding_shape(self._get_tensor_index(input_name), self.expected_input_shape)
        return input_name

    def _allocate_bindings(self) -> list[_TensorBinding]:
        bindings: list[_TensorBinding] = []
        for name in self._iter_tensor_names():
            shape = self._get_tensor_shape(name)
            if any(dim < 0 for dim in shape):
                raise RuntimeError(
                    f"TensorRT tensor shape for '{name}' is still dynamic after configuration: {shape}"
                )

            dtype = self._get_tensor_dtype(name)
            size = int(self._trt.volume(shape))
            host = self._cuda.pagelocked_empty(size, dtype)
            device = self._cuda.mem_alloc(host.nbytes)
            bindings.append(
                _TensorBinding(
                    name=name,
                    index=self._get_tensor_index(name),
                    shape=shape,
                    dtype=dtype,
                    is_input=self._tensor_is_input(name),
                    host=host,
                    device=device,
                )
            )
        return sorted(bindings, key=lambda item: item.index)

    def warmup(self, iterations: int = 3) -> None:
        warmup_tensor = np.zeros(self.input_shape, dtype=self.input_dtype)
        for _ in range(max(1, int(iterations))):
            self.infer(warmup_tensor)

    def infer(self, input_tensor: np.ndarray) -> list[np.ndarray]:
        contiguous = np.ascontiguousarray(input_tensor, dtype=self.input_dtype)
        if contiguous.shape != self.input_shape:
            raise ValueError(
                f"TensorRT input shape mismatch: expected {self.input_shape}, got {contiguous.shape}"
            )

        np.copyto(self._input_binding.host.reshape(self.input_shape), contiguous)
        self._cuda.memcpy_htod_async(self._input_binding.device, self._input_binding.host, self._stream)

        if hasattr(self._context, "set_tensor_address"):
            for binding in self._bindings:
                self._context.set_tensor_address(binding.name, int(binding.device))
            success = self._context.execute_async_v3(stream_handle=self._stream.handle)
        else:
            success = self._context.execute_async_v2(
                bindings=self._binding_ptrs,
                stream_handle=self._stream.handle,
            )

        if not success:
            raise RuntimeError(f"TensorRT inference execution failed for {self.engine_path}")

        outputs: list[np.ndarray] = []
        for binding in self._bindings:
            if binding.is_input:
                continue
            self._cuda.memcpy_dtoh_async(binding.host, binding.device, self._stream)
            outputs.append(binding.host.reshape(binding.shape).copy())

        self._stream.synchronize()
        return outputs

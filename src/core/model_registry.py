from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    display_name: str
    engine_path: str
    input_size: int
    labels: List[str]
    class_to_semantic: Dict[str, str]
    legacy_paths: List[str] = field(default_factory=list)
    postprocess_type: str = "yolo_multiclass"
    lock_detect_range_to_input: bool = False

    def label_to_class_id(self, label: str) -> int:
        return self.labels.index(label)

    def class_id_to_label(self, class_id: int) -> str:
        if 0 <= class_id < len(self.labels):
            return self.labels[class_id]
        return f"class_{class_id}"

    def target_cycle(self) -> List[str]:
        return list(self.labels)


CS2_YOLO12M = ModelSpec(
    model_id="yolo12m_cs2",
    display_name="YOLO12M CS2",
    engine_path="Model/yolo12m_cs2.engine",
    input_size=640,
    labels=["c", "ch", "t", "th"],
    class_to_semantic={
        "c": "body",
        "ch": "head",
        "t": "body",
        "th": "head",
    },
    legacy_paths=["Model/yolo12m_cs2.onnx"],
    lock_detect_range_to_input=True,
)

CS2_YOLO12N = ModelSpec(
    model_id="yolo12n_cs2",
    display_name="YOLO12N CS2",
    engine_path="Model/yolo12n_cs2.engine",
    input_size=640,
    labels=["c", "ch", "t", "th"],
    class_to_semantic={
        "c": "body",
        "ch": "head",
        "t": "body",
        "th": "head",
    },
    legacy_paths=["Model/yolo12n_cs2.onnx", "Model/CS2.onnx"],
    lock_detect_range_to_input=True,
)


MODEL_REGISTRY: Dict[str, ModelSpec] = {
    CS2_YOLO12M.model_id: CS2_YOLO12M,
    CS2_YOLO12N.model_id: CS2_YOLO12N,
}


def list_model_specs() -> List[ModelSpec]:
    return list(MODEL_REGISTRY.values())


def get_model_spec(model_id: str) -> ModelSpec | None:
    return MODEL_REGISTRY.get(model_id)


def get_default_model_spec() -> ModelSpec:
    return CS2_YOLO12N


def resolve_model_spec_from_path(model_path: str) -> ModelSpec | None:
    normalized = (model_path or "").replace("\\", "/").lower()
    for spec in MODEL_REGISTRY.values():
        candidate_paths = [spec.engine_path, *spec.legacy_paths]
        if any(normalized.endswith(path.replace("\\", "/").lower()) for path in candidate_paths):
            return spec
    return None


def is_cs2_model(model_id: str) -> bool:
    spec = get_model_spec(model_id)
    if spec is None:
        return False
    return spec.model_id.endswith("_cs2")


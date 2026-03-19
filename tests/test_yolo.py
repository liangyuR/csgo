from ultralytics import YOLO

# 加载导出的 TensorRT 模型
model = YOLO("Model/yolo12n_cs2.engine", task="detect")

# 直接进行推理
results = model("https://ultralytics.com/images/bus.jpg")

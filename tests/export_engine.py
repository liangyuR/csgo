from ultralytics import YOLO
model = YOLO("Model/yolo12n_cs2.pt")
# 导出为 engine 格式，开启 FP16 以获得约 6 倍加速
model.export(format="engine", half=True) 

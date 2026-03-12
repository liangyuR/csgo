# CSGO YOLOv8 Offline Vision Demo

这是一个**离线学习项目**：使用你提供的 YOLOv8 模型对 `CSGO/CS2` 的截图、图片目录或录屏视频做目标检测，并在输出结果中标注“建议瞄点”。

项目**不实现**下列能力：
- 实时读取游戏画面
- 鼠标控制或自动开枪
- 注入、驱动、覆盖层、绕过反作弊
- 在线对战作弊

它适合拿来学习：
- YOLOv8 推理流程
- 检测框到“瞄点”几何转换
- 目标排序（离准星最近优先）
- 视频逐帧处理与结果导出

## 功能
- 加载自定义 YOLOv8 权重：默认 `model/best.pt`
- 支持输入：单张图片、图片目录、视频文件
- 输出标注结果：边框、类别、置信度、建议瞄点、屏幕中心到目标的偏移量
- 自动挑选“主目标”：离画面中心最近的检测目标
- 导出 `CSV` 明细和 `summary.json`
- 可列出模型类别，方便确认哪个类别是 head

## 目录
- `main.py`：简单入口
- `src/csgo_vision_demo/cli.py`：命令行参数
- `src/csgo_vision_demo/pipeline.py`：YOLO 推理与视频/图片处理
- `src/csgo_vision_demo/geometry.py`：瞄点计算与目标排序逻辑
- `tests/test_geometry.py`：基础单元测试

## 安装
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 查看模型类别
```bash
python3 main.py --list-classes --model model/best.pt
```

## 运行示例
单张图片：
```bash
python3 main.py \
  --source /path/to/frame.jpg \
  --model model/best.pt \
  --output-dir outputs/run_image
```

处理整个图片目录：
```bash
python3 main.py \
  --source /path/to/images \
  --model model/best.pt \
  --output-dir outputs/run_folder
```

处理录屏视频，并只把 `head` 类当目标：
```bash
python3 main.py \
  --source /path/to/demo.mp4 \
  --model model/best.pt \
  --output-dir outputs/run_video \
  --target-class-name head
```

如果模型没有单独的 `head` 类，而是只有 `person/enemy`，可以改用上方偏移的瞄点估计：
```bash
python3 main.py \
  --source /path/to/demo.mp4 \
  --model model/best.pt \
  --output-dir outputs/run_upper \
  --aim-mode upper_center \
  --head-fraction 0.18
```

## 输出说明
运行后会生成类似结构：
```text
outputs/run_video/
  annotated/
    demo_annotated.mp4
  detections.csv
  summary.json
```

`detections.csv` 主要字段：
- `source_file`：源文件名
- `frame_index`：视频帧序号；图片固定为 `0`
- `class_id` / `class_name`
- `confidence`
- `x1,y1,x2,y2`：检测框
- `aim_x, aim_y`：建议瞄点
- `offset_x, offset_y`：相对屏幕中心的偏移
- `distance_to_center`
- `is_primary_target`：是否被选为当前帧主目标

## 说明
如果你后续想继续做“学习用途”的扩展，我可以继续补：
- 批量评估脚本
- 结果统计图
- 针对你这份模型标签的定制类名配置
- 导出训练误检/漏检样本

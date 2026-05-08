# AGENTS.md

## 屏幕尺寸：1920x1080

## 项目简介

- 用于CSGO2的自动识别，瞄准，开火
- 核心使用 YOLO 检测

## 工作区

- 主入口文件：`src/main.py`
- Shell 环境：Windows 上的 PowerShell

## 当前状态

- TensorRT 运行时支持主要位于 `src/core/tensorrt_runtime.py`。
- 检测流水线逻辑主要位于 `src/core/ai_loop.py`。
- 配置加载与持久化主要位于 `src/core/config.py`。
- 模型选择与约束处理位于 `src/core/model_registry.py`。
- `config.json` 已被忽略，表示本地运行时配置。

## 验证

- 测试位于 `tests/`。
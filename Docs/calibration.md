下面是这个脚本的完整使用说明。

## 一、前置准备

### 1. 进入 CS2 并准备一个"有纹理的场景"
- 进训练靶场或离线练习，对着**有明显纹理**的墙壁或场地（草地、瓦片、木板都行）。
- 不要对着纯色/天空/雾区——相位相关需要画面有可识别的纹理才能算出像素位移。
- 关闭瞄准镜、不要切到刀（切刀时画面太空），步枪正常持枪即可。
- 确保游戏窗口处在**前景且获得焦点**（脚本会读取前景窗口标题，发现不像 CS2 会打 WARNING）。

### 2. 关闭 / 暂停本项目主程序
- 主程序会持续抢鼠标，跟校准脚本会冲突。先关掉 `launch.bat` 启动的主进程再跑校准。

### 3. 确认 `config.json` 里的鼠标后端
脚本默认会**读 [config.json](config.json:54) 里的 `mouse_move_method`** 作为校准时使用的后端（确保校准结果与运行时一致）。当前你的配置是：

```4:7:config.json
  "fov_size": 640,
  "detect_range_size": 640,
  "model_path": "Model/yolo11m_cs2.engine",
  "model_id": "yolo11m_cs2",
```

`mouse_move_method` 行：

```54:54:config.json
  "mouse_move_method": "ddxoft",
```

`ddxoft` 是可校准的后端，OK。`xbox` 与 `auto` 会被脚本拒绝（`xbox` 是摇杆量纲、`auto` 不明确），需要你显式 `--mouse-method` 指定。

---

## 二、最简用法（推荐第一次跑这个）

进 CS2 训练靶场 → 切到桌面打开 PowerShell → 运行：

```powershell
& "C:\Users\11601\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" tools/calibrate_aim_ratio.py --dry-run
```

`--dry-run` 表示**只打印结果不写回 config.json**，第一次先确认数值是否合理。

执行流程会是：
1. 脚本打印 `Calibrating with backend=ddxoft`
2. 1 秒 warmup
3. 打印当前前景窗口 + 倒数 `3, 2, 1`（这期间你要把焦点切回 CS2）
4. 自动做 X 轴 5 组采样（每组前进+反向各测 1 次，共 10 个数据点）
5. 自动做 Y 轴 5 组采样
6. 打印类似：
   ```
   aim_pixel_ratio_x=0.8543 (median 102.51px, MAD 2.13px, samples=10, counts=120)
   aim_pixel_ratio_y=0.8201 (median 98.41px, MAD 1.87px, samples=10, counts=120)
   Dry run: config.json was not modified.
   ```

**判断结果是否可信**：
- `MAD / median < 15%`：可信，可以正式写入。
- 脚本打印 `WARNING: high variance, consider re-running on a more textured scene`：换一面有纹理的墙再来一次。
- 数值贴在 `0.1` 或 `10.0`（被 clamp 到边界）：通常说明位移过小或过大被混叠了，看下面的诊断。

---

## 三、确认无误后正式写入

去掉 `--dry-run`：

```powershell
& "C:\Users\11601\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" tools/calibrate_aim_ratio.py
```

脚本会把 `aim_pixel_ratio_x` / `aim_pixel_ratio_y` 写回 [config.json](config.json:84)，结尾打印：

```
Updated <...>/config.json (mouse_method=ddxoft, mouse_counts_x=120, mouse_counts_y=120)
```

之后启动主程序，PID 输出阶段就会用新比例换算"屏幕像素 → 鼠标 count"。

---

## 四、常用参数速查（[tools/calibrate_aim_ratio.py:496-515](tools/calibrate_aim_ratio.py:496)）

| 参数 | 默认 | 用途 |
|---|---|---|
| `--config` | `./config.json` | 读取 mouse_move_method 与写回比例的目标 |
| `--mouse-counts` | `120` | 每次注入的鼠标 count；自动调节会基于首样本调整 |
| `--samples` | `5` | 每轴采样组数（每组实际产 2 个数据点） |
| `--settle-s` | `0.12` | 每次注入鼠标后等待秒数 |
| `--warmup-s` | `1.0` | 启动 dxcam 后的预热秒数 |
| `--countdown` | `3` | 抓帧前的可见倒数秒数 |
| `--roi-fraction` | `0.65` | 居中 ROI 占整帧的比例 |
| `--fresh-timeout-s` | `0.25` | 等 dxcam 出新帧的最长秒数 |
| `--debug-save DIR` | 空 | 把每次采样的 before/after/ROI 写到 DIR |
| `--no-auto-tune` | 关 | 关闭 mouse_counts 自动调节，强制用 `--mouse-counts` |
| `--mouse-method` | 空（读 config） | 强制覆盖鼠标后端 |
| `--dry-run` | 关 | 只打印不写回 |

---

## 五、典型场景

### 场景 1：第一次校准（推荐流程）
```powershell
# 先 dry-run 看结果
python tools/calibrate_aim_ratio.py --dry-run
# 数值合理后正式写入
python tools/calibrate_aim_ratio.py
```

### 场景 2：手感不稳，想看脚本到底拍到了什么
```powershell
python tools/calibrate_aim_ratio.py --dry-run --debug-save .\debug_calib
```
跑完后到 `debug_calib\` 看 `x_000_fwd_before.png` / `_after.png` / `_before_roi.png` / `_after_roi.png` 等。如果 ROI 里全是天空/纯色 → 换面墙；如果两张一模一样 → 鼠标后端没真的发出移动（换 `--mouse-method mouse_event` 试一下）。

### 场景 3：临时绕开 `config.json` 里的后端测试
```powershell
python tools/calibrate_aim_ratio.py --mouse-method mouse_event --dry-run
```

### 场景 4：游戏内灵敏度极低 / 极高
- 灵敏度极低、首次样本 < 5px：`auto-tune` 会**自动把 mouse_counts × 2**，最多 3 次（封顶 8×）。
- 灵敏度极高、首次样本 > 40% × ROI 宽：自动 **÷2**，下限 8。
- 想完全手动：加 `--no-auto-tune --mouse-counts 240`（或更小）。

### 场景 5：多显示器 / 主显示器不是 CS2 那块
当前 `dxcam.create()` 抓的是主显示器（[tools/calibrate_aim_ratio.py:388](tools/calibrate_aim_ratio.py:388)）。如果 CS2 在副屏，请把 CS2 移到主显示器再校准（脚本目前没有暴露 `--monitor` 参数）。

---

## 六、诊断常见错误

| 报错 / 现象 | 原因 | 处理 |
|---|---|---|
| `mouse backend 'xbox' cannot be calibrated…` | config 里是 xbox/auto | 显式传 `--mouse-method ddxoft`（或你实际想跑的） |
| `dxcam timed out waiting for fresh frame` | 游戏窗口被遮挡 / 切到后台 / DXGI 抓不到 | 把 CS2 切回前景，加大 `--fresh-timeout-s 0.5` 重试 |
| `measured displacement is zero` | 画面纯色无纹理，相位相关算出 0 | 换有纹理的墙；或 `--debug-save` 看 ROI |
| `dxcam.create returned no camera` | 显卡驱动 / DXGI 不可用 | 用管理员跑一次；或重启 dxcam 相关服务 |
| 比例都被 clamp 到 0.1 或 10.0 | 位移被卷绕（混叠）或太小 | 关 `--no-auto-tune` 手动调 `--mouse-counts`；或开 `--debug-save` 看实际位移 |
| `ImportError: cv2` / `dxcam` | 这两个包未安装 | `pip install opencv-python dxcam`；项目正常运行时这俩本来就装了 |
| WARNING: high variance | 纹理太弱 / 画面有动态元素 | 换墙；或把 `--samples` 提到 10 |

---

## 七、校准后如何验证生效
1. 启动主程序，对静态目标做 ±100px 偏差测试。
2. 观察是否还出现"扫过头再回拉"的过冲——如果仍然过冲且偏一边（比如 X 一直冲过头）说明 X 比例偏小，可手动微调 `aim_pixel_ratio_x` 上调 5–10%。
3. 若打开了 `enable_latency_stats`，看日志里准星到目标的稳定误差是否落在 `aim_position_deadzone_px`（默认 1px）以内。

需要我帮你做任何后续动作（比如帮你改 `--monitor` 参数、或者把这套写成一键 `.bat`），切到 Agent 模式我可以直接实现。
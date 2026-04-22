# Tennis Analysis Live Demo

## 概述

这个版本实现了完整的直播链路，满足以下目标：

- 将 `input_videos/youtube/youtube_match.mp4` 实时转成 RTMP 推流，模拟现场推流。
- 核心服务从 RTMP 拉流，使用 GPU 完成球员、网球、球场关键点分析。
- 核心服务同时输出两路结果：
  - 原始 H.264 码流
  - 带检测元数据的分析 H.264 码流
- 元数据支持两种模式：
  - `sei`：检测结果写入 H.264 SEI
  - `websocket`：检测结果通过 WebSocket 实时发送
- Demo 页面同时展示：
  - 原始视频流
  - 叠加效果后的视频流
- 目标配置偏向低时延和直播稳定性：`libx264 + zerolatency + 固定 GOP + 队列背压控制 + 可丢帧`

## 架构

完整链路如下：

```text
input_videos/youtube/youtube_match.mp4
  -> rtmp_source_service.py
  -> MediaMTX RTMP: live/source
  -> production_live_stream_service.py
  -> 分析管线(GPU)
  -> analysis_transport_hub
  -> demo_server.py 直接输出原始/分析 Annex-B H.264
  -> rtmp_egress.py 回推 RTMP: live/analysis
  -> overlay_ws_server.py 按需输出 WebSocket 元数据
  -> demo/app.js 在浏览器中解码并叠框
```

## 模型要求

默认从 `models/` 读取以下模型：

- 球员检测：`models/yolov8x.pt`
- 网球检测：`models/yolo5_last.pt`
- 球场关键点：`models/keypoints_model.pth`

运行时强制使用 GPU，默认设备是 `cuda:0`。

## 主要组件

- `services/rtmp_source_service.py`
  - 启动本地 MediaMTX
  - 将 `youtube_match.mp4` 低时延推到 `rtmp://127.0.0.1:1935/live/source`
- `services/production_live_stream_service.py`
  - 从文件或 RTMP 拉流
  - 运行实时分析
  - 同时发布原始码流与分析码流
- `services/rtmp_egress.py`
  - 将分析码流转发为 RTMP `live/analysis`
- `services/demo_app.py`
  - 启动核心服务、WebSocket 服务和 HTTP Demo
- `services/demo_server.py`
  - 提供 `/api/runtime`、`/api/metrics`、`/api/overlay`
  - 提供 `/stream/raw.h264` 和 `/stream/analysis.h264`
- `demo/app.js`
  - 浏览器端用 WebCodecs 解码双路 H.264
  - `sei` 模式从分析流解析 SEI
  - `websocket` 模式从 WS 收消息并同步叠框

## 快速启动

### 方式一：一键启动完整演示栈

```bash
bash scripts/start_full_demo_stack.sh \
  /home/chenyu/workplace/tennis_analysis/input_videos/youtube/youtube_match.mp4 \
  sei \
  18080 \
  8765
```

启动后打开：

- Demo 页面：`http://127.0.0.1:18080`
- 原始 RTMP：`rtmp://127.0.0.1:1935/live/source`
- 分析 RTMP：`rtmp://127.0.0.1:1935/live/analysis`

切换 WebSocket 模式：

```bash
bash scripts/start_full_demo_stack.sh \
  /home/chenyu/workplace/tennis_analysis/input_videos/youtube/youtube_match.mp4 \
  websocket \
  18080 \
  8765
```

## 启动说明

### 只启动推流

在项目根目录执行：

```bash
bash scripts/start_rtmp_source.sh \
  /home/chenyu/workplace/tennis_analysis/input_videos/youtube/youtube_match.mp4
```

说明：

- 这条命令会自动启动本地 `MediaMTX`
- 会把 `youtube_match.mp4` 按实时节奏循环推到 `rtmp://127.0.0.1:1935/live/source`
- 只负责推流，不启动分析页面

如果你想直接用 Python 命令启动：

```bash
python services/rtmp_source_service.py \
  --input /home/chenyu/workplace/tennis_analysis/input_videos/youtube/youtube_match.mp4 \
  --rtmp-url rtmp://127.0.0.1:1935/live/source
```

### 只启动分析和 Demo

前提：推流服务已经先启动，且 `rtmp://127.0.0.1:1935/live/source` 可访问。

在项目根目录执行：

```bash
bash scripts/start_demo.sh \
  rtmp://127.0.0.1:1935/live/source \
  /home/chenyu/workplace/tennis_analysis/models \
  sei \
  18080 \
  8765
```

参数含义：

- 第 1 个参数：输入 RTMP 地址
- 第 2 个参数：模型目录，默认是 `models`
- 第 3 个参数：元数据模式，填 `sei` 或 `websocket`
- 第 4 个参数：Demo HTTP 端口
- 第 5 个参数：WebSocket 端口，`sei` 模式下不会实际使用

如果你想直接用 Python 命令启动：

```bash
python services/demo_app.py \
  --input rtmp://127.0.0.1:1935/live/source \
  --models-dir /home/chenyu/workplace/tennis_analysis/models \
  --pace-input-realtime \
  --overlay-mode sei \
  --port 18080 \
  --ws-port 8765 \
  --analysis-rtmp-url rtmp://127.0.0.1:1935/live/analysis \
  --source-rtmp-url rtmp://127.0.0.1:1935/live/source \
  --device cuda:0
```

启动后可访问：

- Demo 页面：`http://127.0.0.1:18080`
- 原始 RTMP：`rtmp://127.0.0.1:1935/live/source`
- 分析 RTMP：`rtmp://127.0.0.1:1935/live/analysis`

### 停止方式

- 前台启动时：在对应终端按 `Ctrl+C`
- 如果是两个终端分开启动：推流终端和分析终端都需要各自停止一次
- 若端口未释放，可检查 `1935`、`18080`、`8765` 是否仍被占用
- 也可以直接执行一键停止脚本：

```bash
bash scripts/stop_demo_stack.sh
```

## 关键参数

### `services/rtmp_source_service.py`

```bash
python services/rtmp_source_service.py \
  --input input_videos/youtube/youtube_match.mp4 \
  --rtmp-url rtmp://127.0.0.1:1935/live/source
```

可选参数：

- `--no-loop`：单次推流，不循环
- `--no-realtime`：不按实时时钟推流，适合快速验证
- `--no-start-server`：不自动启动 MediaMTX

### `services/demo_app.py`

```bash
python services/demo_app.py \
  --input rtmp://127.0.0.1:1935/live/source \
  --models-dir models \
  --overlay-mode sei \
  --pace-input-realtime \
  --device cuda:0
```

可选参数：

- `--overlay-mode sei|websocket`
- `--analysis-rtmp-url rtmp://127.0.0.1:1935/live/analysis`
- `--source-rtmp-url rtmp://127.0.0.1:1935/live/source`
- `--port 18080`
- `--ws-port 8765`
- `--analysis-fps 12`
- `--output-fps 25`
- `--max-frames 100`：用于短时烟测

## Demo 说明

页面会同时显示两块画面：

- 左侧：原始视频流
- 右侧：分析叠框视频流

两种元数据模式：

- `sei`
  - 浏览器从 `/stream/analysis.h264` 中直接提取 SEI
  - 视频和元数据天然同通道，同步更直接
- `websocket`
  - 浏览器看分析视频流
  - 同时从 WebSocket 拉取元数据
  - 使用 `frame_id` 和 `pts` 对齐叠框

## 稳定性和低延迟策略

实现中使用了以下策略：

- RTMP 服务端使用 MediaMTX，本地部署简单稳定
- 推流编码使用 `libx264 + veryfast + zerolatency + yuv420p`
- 固定关键帧间隔，关闭场景切换触发的随机 GOP
- 读取与处理分线程，队列有限长，支持背压和丢帧
- Demo 浏览器端使用 WebCodecs，减少前端解码延迟
- SEI 模式避免额外元数据通道引入的时序漂移
- WebSocket 模式保留独立消息通道，便于与业务系统集成

## 测试

已补充并验证的测试类型：

- 核心服务单元测试
- SEI 注入与提取测试
- Demo HTTP 接口测试
- 双路 H.264 流接口测试
- RTMP 推流命令构造测试
- `max_frames` 停止控制测试

运行测试：

```bash
python -m unittest tests.test_production_live_stream_service
```

## 已知前提

- 需要本机可用 CUDA，且 `torch.cuda.is_available()` 为真。
- 浏览器需要支持 WebCodecs，推荐使用较新的 Chrome 或 Edge。
- 首次运行会自动下载 MediaMTX 到 `tools/mediamtx/`。

## 常见排查

- 页面黑屏：先确认浏览器支持 WebCodecs。
- RTMP 拉流失败：确认 `127.0.0.1:1935` 已被 MediaMTX 占用并监听。
- WebSocket 无叠框：确认启动模式为 `websocket`，且 `ws_port` 未被占用。
- GPU 未启用：检查 CUDA、PyTorch 和模型文件路径。
- 检测慢：适当降低 `--analysis-fps`，保持 `--output-fps` 为 25。

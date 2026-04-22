# 直播链路代码与设计详解

## 1. 文档目标

这份文档不是讲“理想方案”，而是直接对当前仓库里已经落地的直播代码做拆解，回答四个问题：

- 直播链路是怎么被拉起来的。
- 一帧视频和一份分析元数据是怎么流动的。
- 当前版本为什么能把延迟压到比较低。
- 当前版本已经做了哪些可用性设计，离真正生产级高可用还有哪些差距。

当前直播入口主要集中在以下几个文件：

- 启动脚本：[start_full_demo_stack.sh](file:///home/chenyu/workplace/tennis_analysis/scripts/start_full_demo_stack.sh#L1-L39)
- Demo 进程入口：[demo_app.py](file:///home/chenyu/workplace/tennis_analysis/services/demo_app.py#L1-L86)
- 主直播服务：[production_live_stream_service.py](file:///home/chenyu/workplace/tennis_analysis/services/production_live_stream_service.py#L30-L219)
- 实时分析管线：[analysis_pipeline.py](file:///home/chenyu/workplace/tennis_analysis/realtime/analysis_pipeline.py#L46-L183)
- RTMP 输入服务：[rtmp_source_service.py](file:///home/chenyu/workplace/tennis_analysis/services/rtmp_source_service.py#L21-L108)
- RTMP 输出服务：[rtmp_egress.py](file:///home/chenyu/workplace/tennis_analysis/services/rtmp_egress.py#L10-L84)
- HTTP Demo 服务：[demo_server.py](file:///home/chenyu/workplace/tennis_analysis/services/demo_server.py#L19-L160)
- WebSocket 元数据服务：[overlay_ws_server.py](file:///home/chenyu/workplace/tennis_analysis/services/overlay_ws_server.py#L9-L42)
- H.264 SEI 注入与编码：[h264_sei.py](file:///home/chenyu/workplace/tennis_analysis/services/h264_sei.py#L16-L232)
- 前端播放与叠框：[app.js](file:///home/chenyu/workplace/tennis_analysis/demo/app.js#L1-L939)

---

## 2. 先看整体架构

当前实现不是传统“后端直接把叠好框的视频吐给浏览器”的纯服务器渲染方案，而是一个“双路视频 + 元数据”的直播演示架构。

整体链路如下：

```text
本地 MP4 / 外部 RTMP
  -> rtmp_source_service.py
  -> MediaMTX: live/source
  -> production_live_stream_service.py
      -> 解码
      -> 实时分析
      -> 生成 TransportPacket 元数据
      -> 编码 raw H.264
      -> 在 analysis H.264 中注入 SEI
      -> 发布到两个 TransportHub
  -> demo_server.py
      -> /stream/raw.h264
      -> /stream/analysis.h264
  -> overlay_ws_server.py
      -> WebSocket 元数据
  -> rtmp_egress.py
      -> 再推到 MediaMTX: live/analysis
  -> 浏览器 demo/app.js
      -> WebCodecs 解码
      -> 解析 SEI 或接收 WebSocket
      -> Canvas 绘制叠层
```

这个设计最关键的思想是：

- 视频流和分析结果解耦。
- 分析结果以“状态”形式传播，而不是要求“每一帧都同步完成推理”。
- 输出链路优先保连续播放，不优先保每帧都是最新分析。

这也是当前实现能兼顾低延迟和稳定性的核心原因。

---

## 3. 启动链路怎么跑起来

### 3.1 一键启动脚本

[start_full_demo_stack.sh](file:///home/chenyu/workplace/tennis_analysis/scripts/start_full_demo_stack.sh#L1-L39) 做了两件事：

1. 先启动 `rtmp_source_service.py`，把输入视频按实时节奏推到 `rtmp://127.0.0.1:1935/live/source`。
2. 再启动 `demo_app.py`，让分析服务、RTMP 回推、WebSocket 服务、HTTP Demo 一起工作。

脚本里最重要的参数有：

- `SOURCE_URL`：原始 RTMP 输入地址
- `ANALYSIS_URL`：分析结果 RTMP 输出地址
- `OVERLAY_MODE`：前端默认使用 `sei` 还是 `websocket`
- `HTTP_PORT` / `WS_PORT`：前端访问端口

`trap cleanup EXIT INT TERM` 说明脚本退出时会主动停止源推流子进程，这属于最基础的进程回收能力。

### 3.2 RTMP 输入服务

[rtmp_source_service.py](file:///home/chenyu/workplace/tennis_analysis/services/rtmp_source_service.py#L21-L108) 的职责不是分析，而是“搭好直播源”：

- 如果本地 `1935` 端口没起来，就自动启动 MediaMTX。
- 用 `ffmpeg -re -stream_loop -1` 把 MP4 按实时速度循环推流。
- 视频直接 `-c:v copy`，避免输入侧重新编码。

这里有两个低延迟点：

- `-re` 让文件模拟真实直播节奏，避免上游一次性把数据灌爆下游。
- `-c:v copy` 避免源推流阶段额外编码延迟。

### 3.3 MediaMTX 管理

[mediamtx_manager.py](file:///home/chenyu/workplace/tennis_analysis/services/mediamtx_manager.py#L22-L93) 负责：

- 自动下载和解压 MediaMTX 二进制。
- 生成最小化配置，只开启 `RTMP`、`API`、`metrics`。
- 显式关闭 `RTSP`、`HLS`、`WebRTC`、`SRT`。

这点非常重要，因为当前演示目标是尽量减少无关协议带来的复杂度和资源占用。  
从配置模板看，MediaMTX 只暴露两个 path：

- `live/source`
- `live/analysis`

也就是说，这一版不是多租户转码平台，而是单机单场景的最小直播拓扑。

---

## 4. 主服务内部结构

### 4.1 入口组装方式

[demo_app.py](file:///home/chenyu/workplace/tennis_analysis/services/demo_app.py#L46-L83) 把几个模块装在一起：

- 创建 `analysis_transport_hub`
- 创建 `raw_transport_hub`
- 构建 `ProductionLiveStreamService`
- 启动 `RtmpAnnexBPublisher` 把分析流回推到 RTMP
- 启动 `OverlayWebSocketServer` 推送元数据
- 单独起线程执行 `service.run()`
- 主线程运行 `run_demo_server()`

这里有个很重要的设计：  
HTTP Demo 服务和分析服务不在同一个阻塞循环里，而是并行运行。这样浏览器接口不会因为模型推理阻塞而失去响应。

### 4.2 主服务对象的组成

[ProductionLiveStreamService.__init__()](file:///home/chenyu/workplace/tennis_analysis/services/production_live_stream_service.py#L31-L57) 里几个成员最关键：

- `self.decoder = StreamDecoder(ingress)`：把输入统一变成逐帧对象。
- `self.analysis_pipeline`：真正做球员、网球、球场分析。
- `self.raw_encoder = H264SeiEncoder(... inject_metadata=False)`：编码原始视频支路。
- `self.frame_queue = Queue(maxsize=...)`：读流与分析解耦的有界队列。
- `self.analysis_transport_hub` / `self.raw_transport_hub`：无锁感知的最新帧广播中心。
- `self.metrics = RuntimeMetricsTracker(...)`：实时记录延迟、队列和状态。

这个结构说明当前服务是典型的“两线程生产者-消费者”模型：

- reader thread 负责拉流和入队。
- processor thread 负责分析、编码、发布。

---

## 5. 一帧数据怎么走完整条链路

## 5.1 输入与解码

输入抽象在 [ingress.py](file:///home/chenyu/workplace/tennis_analysis/streaming/ingress.py#L6-L49)：

- `OpenCVStreamIngress`：读文件或普通视频源
- `RTMPStreamIngress`：复用 OpenCV 方式打开 RTMP

解码层在 [decoder.py](file:///home/chenyu/workplace/tennis_analysis/streaming/decoder.py#L4-L18)，做的事情很纯：

- 连续从 ingress `read()`
- 生成 `VideoFrame(frame_id, pts, image)`
- 交给下游

`VideoFrame` 的结构定义在 [models.py](file:///home/chenyu/workplace/tennis_analysis/streaming/models.py#L17-L22)。

这里有一个设计重点：  
后续所有模块都围绕 `frame_id` 和 `pts` 工作，而不是围绕“第几个数组元素”工作。  
这让视频帧、SEI 元数据、WebSocket 元数据、前端叠框都能靠同一套时间语义对齐。

## 5.2 Reader 线程

Reader 主循环在 [_reader_loop()](file:///home/chenyu/workplace/tennis_analysis/services/production_live_stream_service.py#L72-L96)。

它的流程是：

1. 从 `decoder.frames()` 不断拿 `VideoFrame`
2. 如果启用了 `pace_input_realtime`，按 `video_frame.pts` 做节流
3. 把帧放入有界 `frame_queue`
4. 更新 ingest metrics
5. 流结束时塞一个 `None` 作为终止标记

其中第 2 步非常关键：

```python
elapsed = time.perf_counter() - self._reader_started_at
delay = video_frame.pts - elapsed
if delay > 0:
    time.sleep(delay)
```

这个逻辑确保“文件输入”也按真实直播时间向后走，避免离线文件读得过快导致：

- 队列快速堆积
- 分析延迟失真
- 前端播放与元数据节奏脱节

## 5.3 有界队列与丢帧

入队逻辑在 [_enqueue_frame()](file:///home/chenyu/workplace/tennis_analysis/services/production_live_stream_service.py#L58-L71)。

如果队列满了：

- 当 `enable_frame_drop=False`，生产者阻塞等待。
- 当 `enable_frame_drop=True`，直接丢掉队列里最老的一帧，再塞入新帧。

这其实就是直播系统常见的策略：  
**宁可丢旧帧，也不要让延迟无限累积。**

这是当前代码里最直接、最有效的低延迟保护措施之一。

## 5.4 Processor 线程

处理主循环在 [_processor_loop()](file:///home/chenyu/workplace/tennis_analysis/services/production_live_stream_service.py#L97-L161)。

每拿到一帧，它会做以下步骤：

1. 调 `analysis_pipeline.process_frame(item, queue_size=queue_size)`
2. 把分析结果包装成 `TransportPacket`
3. 用 `raw_encoder` 编码原始画面
4. 把原始码流发布到 `raw_transport_hub`
5. 基于同一份编码结果注入 SEI，形成分析码流
6. 把分析码流发布到 `analysis_transport_hub`
7. 把当前 packet 和 metrics 写入状态文件
8. 更新各阶段耗时指标

注意这里的先后顺序：

- 先编码 raw
- 再对 raw 码流做 SEI 注入

这意味着分析流不是“重新画框后二次编码”，而是“同一份 H.264 码流 + 额外元数据”。  
所以右侧分析流的画面内容本身其实还是视频帧，叠框是前端画的。

这就是为什么前端可以自由切换 `sei` 和 `websocket` 两种叠框模式，而视频主体不需要重编码两遍。

---

## 6. 实时分析管线怎么做

### 6.1 分析调度

[AnalysisScheduler](file:///home/chenyu/workplace/tennis_analysis/streaming/scheduler.py#L1-L18) 只干两件事：

- 控制分析帧率 `analysis_fps`
- 控制球场关键点刷新周期 `court_refresh_seconds`

在 [process_frame()](file:///home/chenyu/workplace/tennis_analysis/realtime/analysis_pipeline.py#L77-L84) 里，如果当前帧不需要分析，直接返回 `state_store.get_overlay()`。

这点很重要，含义是：

- 输出帧率可以是 `25fps`
- 分析帧率可以只有 `12fps` 或 `15fps`
- 中间缺的帧直接复用最近一次稳定 overlay

这样就把“播放流畅度”和“模型推理成本”拆开了。

### 6.2 球场检测低频刷新

[analysis_pipeline.py](file:///home/chenyu/workplace/tennis_analysis/realtime/analysis_pipeline.py#L94-L105) 只在定时刷新时才做 court detection。

原因很简单：

- 球场关键点变化慢
- 每帧都跑 court model 很浪费
- 它通常比球员和网球检测更适合缓存

所以这里采用的是“慢变量低频更新，快变量高频更新”的典型实时系统设计。

### 6.3 球员检测复用缓存

球员检测逻辑在 [analysis_pipeline.py](file:///home/chenyu/workplace/tennis_analysis/realtime/analysis_pipeline.py#L107-L124)。

核心机制有两个：

- `player_detect_every_n_frames`
- `cached_player_boxes`

也就是说，球员框不是每个分析帧都重新检测。  
如果缓存有效，就直接复用上一轮的结果。

这么做的收益：

- 降低 GPU 压力
- 缩短平均分析时延
- 降低因为偶发漏检导致的框闪烁

代价是：

- 高速运动或遮挡场景下，球员框会有短暂滞后

但对于直播演示来说，这个 trade-off 很合理。

### 6.4 球检测与在线轨迹

球检测是逐次更新的，但不是离线插值，而是走在线状态缓冲：

- `BallHistoryBuffer`
- `shot_confirm_window_seconds`
- `shot_cooldown_seconds`
- `max_ball_gap_seconds`

这些参数由 [analysis_pipeline.py](file:///home/chenyu/workplace/tennis_analysis/realtime/analysis_pipeline.py#L61-L68) 初始化。

这说明当前实现已经从老的“整段视频回看式统计”切成了“有限窗口在线状态机”。

这对低延迟非常关键，因为直播系统不能依赖未来帧。

### 6.5 实时统计

[LiveStatsAggregator.update()](file:///home/chenyu/workplace/tennis_analysis/realtime/stats_aggregator.py#L39-L71) 的工作方式也是在线增量式：

- 根据当前帧和上一帧位置估算跑动距离
- 根据时间差估算球速和跑速
- 击球事件到达时累加统计

这意味着统计面板不是“事后复盘结果”，而是直播态近似统计值。  
它牺牲了一部分绝对精确性，换来实时性。

### 6.6 状态落地到 OverlayState

分析结果最后被写入 [OverlayState](file:///home/chenyu/workplace/tennis_analysis/streaming/models.py#L32-L47)，字段包括：

- `player_boxes`
- `ball_box`
- `ball_trail`
- `shot_event`
- `court_keypoints`
- `player_mini_court`
- `ball_mini_court`
- `stats_row`
- `quality_level`
- `debug`
- `status`

[LiveStateStore](file:///home/chenyu/workplace/tennis_analysis/streaming/state_store.py#L8-L28) 用一个锁保护最新状态。  
这就是全系统共享的“最新稳定分析快照”。

这个设计非常像实时控制系统里的“最新状态寄存器”：

- 生产端不断更新
- 消费端永远拿最新值
- 不回放历史，不积压旧消息

这也是减少延迟扩散的关键。

---

## 7. 元数据为什么能跟视频对齐

### 7.1 TransportPacket 是统一元数据载体

[TransportPacket](file:///home/chenyu/workplace/tennis_analysis/streaming/models.py#L99-L132) 是当前系统里最重要的数据结构之一。

它至少带了三个时间对齐关键字段：

- `frame_id`
- `pts`
- `overlay_frame_id`

含义分别是：

- 当前输出视频帧编号
- 当前输出视频时间戳
- 当前 overlay 实际对应的分析帧编号

这个字段设计很实用，因为分析结果可能是复用旧帧状态。  
所以 `frame_id` 和 `overlay_frame_id` 不一定相同。

### 7.2 TransportHub 的“只保最新”

[TransportHub](file:///home/chenyu/workplace/tennis_analysis/services/transport_hub.py#L17-L51) 内部只有一个 `_latest`，发布时直接覆盖。

这表示它不是 Kafka 式消息队列，而是“最新帧广播器”：

- 发布端只保一份最新包
- 订阅端只关心有没有更新
- 慢消费者不会把旧包越攒越多

这对直播低延迟很重要，因为视频播放最怕慢消费者导致整体回压。

### 7.3 SEI 模式

[h264_sei.py](file:///home/chenyu/workplace/tennis_analysis/services/h264_sei.py#L80-L111) 负责把 JSON 元数据封装成 H.264 的 user data unregistered SEI：

- 先 `json.dumps(...)`
- 前面拼接固定 UUID
- 做 emulation prevention
- 把 SEI NAL 插到 VCL NAL 之前

编码器 [H264SeiEncoder](file:///home/chenyu/workplace/tennis_analysis/services/h264_sei.py#L149-L213) 采用：

- `libx264`
- `preset=veryfast`
- `tune=zerolatency`
- `profile=baseline`
- `repeat-headers=1`
- `annexb=1`
- `aud=1`
- `g=fps`
- `keyint_min=fps`
- `sc_threshold=0`

这些选项的含义很关键：

- `zerolatency`：尽量减少编码缓存
- `baseline`：提高浏览器/硬解兼容性
- `repeat-headers=1`：随时加入的解码端更容易快速起播
- `g=fps`：大约 1 秒一个关键帧，兼顾恢复速度和码率
- `sc_threshold=0`：防止 GOP 不稳定，便于时间行为可预测

### 7.4 WebSocket 模式

[overlay_ws_server.py](file:///home/chenyu/workplace/tennis_analysis/services/overlay_ws_server.py#L17-L27) 会持续等待 `analysis_transport_hub` 的新包，然后把 `packet.metadata` 直接发给浏览器。

没有新数据时发：

```json
{"type":"heartbeat"}
```

这个心跳的作用有两个：

- 保活连接
- 避免前端把“短时无新包”误判成断链

---

## 8. 前端播放与叠框细节

### 8.1 前端不是 `<video>` 播放，而是自己解 Annex-B H.264

[app.js](file:///home/chenyu/workplace/tennis_analysis/demo/app.js#L644-L809) 里的 `StreamPlayer` 做了三件很底层的事：

1. 从 `/stream/raw.h264` 或 `/stream/analysis.h264` 连续 fetch 字节流
2. 自己切分 Annex-B NAL
3. 用 `WebCodecs VideoDecoder` 直接解码

这么做的好处是：

- 浏览器不需要 MSE/HLS 这类更重的播放路径
- 可以在 NAL 级别直接拿到 SEI
- 便于把视频时间戳和元数据强绑定

### 8.2 SEI 解析过程

[extractSeiMetadata()](file:///home/chenyu/workplace/tennis_analysis/demo/app.js#L117-L157) 做了和后端相反的步骤：

- 去掉 emulation prevention
- 解析 payload type / size
- 校验 UUID
- 把 JSON 反序列化回对象

当 `flushAccessUnit()` 扫到 NAL type `6` 时，就会提取这一帧的元数据，再把 `pts` 转成 `EncodedVideoChunk.timestamp`。

### 8.3 为什么视频和元数据能同步

关键逻辑在 [flushAccessUnit()](file:///home/chenyu/workplace/tennis_analysis/demo/app.js#L727-L766)：

- 如果有 SEI，就用 `metadata.pts` 生成时间戳
- 再把 `metadata` 放进 `streamMetadataByTimestamp`
- 解码完成后，在 `handleDecodedFrame()` 里通过 `frame.timestamp` 反查 metadata

也就是说，前端不是“收到视频后再猜测该配哪条元数据”，而是：

- 先在编码块层面绑定时间戳
- 解码后再按同一时间戳取回 metadata

这也是 SEI 模式对齐很稳的原因。

### 8.4 WebSocket 模式为什么也能对齐

WebSocket 模式下，前端维护 `wsMetadataByFrameId`，相关逻辑在：

- [rememberWsMetadata()](file:///home/chenyu/workplace/tennis_analysis/demo/app.js#L553-L562)
- [findWsMetadata()](file:///home/chenyu/workplace/tennis_analysis/demo/app.js#L564-L579)

匹配策略是：

- 优先按 `frame_id` 命中
- 命不中再按 `pts` 最近邻匹配
- 只接受 `0.2s` 以内的匹配结果

这个策略比单纯按到达顺序更鲁棒，因为 WebSocket 和视频流本来就可能有网络抖动差异。

### 8.5 叠框绘制

[drawOverlay()](file:///home/chenyu/workplace/tennis_analysis/demo/app.js#L581-L642) 在 Canvas 上画：

- 球员框
- 球拖尾
- 击球特效
- 状态栏
- 实时数据面板

当前前端渲染的好处是：

- 可以灵活切换特效，不影响后端编码
- 可以同时展示原始流和分析流
- 浏览器端开发调试成本低

代价是：

- 终端展示依赖浏览器算力
- 如果要做真正 CDN 级分发，通常还得提供服务器端烧录版本

---

## 9. 当前版本是如何压低延迟的

这里把“低延迟”拆成具体机制，而不是抽象口号。

### 9.1 输入节奏控制

Reader 线程的 `pace_input_realtime` 让文件输入按 PTS 节奏前进，避免离线源把队列瞬间塞满，见 [production_live_stream_service.py](file:///home/chenyu/workplace/tennis_analysis/services/production_live_stream_service.py#L78-L83)。

### 9.2 分析帧率与输出帧率解耦

通过 `analysis_fps` 和 `output_fps` 分离，系统不要求每个输出帧都跑模型，见 [config.py](file:///home/chenyu/workplace/tennis_analysis/streaming/config.py#L5-L30) 与 [scheduler.py](file:///home/chenyu/workplace/tennis_analysis/streaming/scheduler.py#L1-L18)。

这是最核心的低延迟设计之一，因为模型推理通常是最重的环节。

### 9.3 慢变量缓存

球场关键点低频刷新、球员框跨帧复用，见 [analysis_pipeline.py](file:///home/chenyu/workplace/tennis_analysis/realtime/analysis_pipeline.py#L94-L124)。

这样能显著降低平均单帧推理成本。

### 9.4 有界队列 + 旧帧淘汰

队列满时优先扔掉旧帧，见 [production_live_stream_service.py](file:///home/chenyu/workplace/tennis_analysis/services/production_live_stream_service.py#L58-L71)。

直播系统里最忌讳的是“每个环节都想保所有帧”，那样最后得到的是稳定的大延迟，而不是低延迟。

### 9.5 最新状态覆盖式传播

`LiveStateStore` 和 `TransportHub` 都采用“最新值覆盖”的思路，见：

- [state_store.py](file:///home/chenyu/workplace/tennis_analysis/streaming/state_store.py#L8-L28)
- [transport_hub.py](file:///home/chenyu/workplace/tennis_analysis/services/transport_hub.py#L17-L51)

这种结构天然抑制积压。

### 9.6 低延迟编码参数

`libx264 + zerolatency + 固定 GOP + copy egress` 见 [h264_sei.py](file:///home/chenyu/workplace/tennis_analysis/services/h264_sei.py#L160-L181) 和 [rtmp_egress.py](file:///home/chenyu/workplace/tennis_analysis/services/rtmp_egress.py#L64-L84)。

尤其 `rtmp_egress.py` 用的是：

- 输入 `-f h264 -i pipe:0`
- 输出 `-c:v copy -f flv`

说明回推 RTMP 时不再重编码，只做封装转换，这能继续减少一跳延迟。

### 9.7 浏览器端直接 WebCodecs 解码

前端不走更重的 HLS/MSE 播放栈，而是直接用 `VideoDecoder`，见 [app.js](file:///home/chenyu/workplace/tennis_analysis/demo/app.js#L665-L701)。

同时开启：

- `optimizeForLatency: true`
- `hardwareAcceleration: 'prefer-hardware'`

这是前端侧的低延迟优化。

---

## 10. 当前版本的“高可用”具体体现在哪里

这里要先明确边界：  
当前实现具备的是**单机单进程栈下的直播稳定性设计**，还不是多机容灾、无状态横向扩展意义上的平台级高可用。

### 10.1 已实现的稳定性设计

#### 10.1.1 服务职责拆分

当前至少拆成了几个相互独立的部件：

- RTMP 源服务
- MediaMTX
- 主分析服务
- RTMP 回推服务
- WebSocket 服务
- HTTP Demo 服务

这意味着某一层的实现是相对解耦的，而不是所有逻辑塞进一个大循环。

#### 10.1.2 基础进程生命周期管理

- `rtmp_source_service.py` 安装了 `SIGINT` / `SIGTERM` 处理器，见 [rtmp_source_service.py](file:///home/chenyu/workplace/tennis_analysis/services/rtmp_source_service.py#L101-L107)
- `start_full_demo_stack.sh` 通过 `trap` 做清理，见 [start_full_demo_stack.sh](file:///home/chenyu/workplace/tennis_analysis/scripts/start_full_demo_stack.sh#L14-L21)
- `stop_demo_stack.sh` 通过进程模式批量 stop，见 [stop_demo_stack.sh](file:///home/chenyu/workplace/tennis_analysis/scripts/stop_demo_stack.sh#L6-L32)

虽然这还是脚本式管理，但已经比“手工起一堆命令后不回收”要稳定很多。

#### 10.1.3 编码与推流自动重拉起

[rtmp_egress.py](file:///home/chenyu/workplace/tennis_analysis/services/rtmp_egress.py#L37-L63) 的 `_run()` 有自动恢复机制：

- 如果 ffmpeg 进程不存在或退出，就重新起一个
- 如果写 stdin 遇到 `BrokenPipeError`，杀掉旧进程并稍后重启

这意味着 RTMP 输出端发生短暂异常时，系统具备自愈能力。

#### 10.1.4 WebSocket 心跳保活

WebSocket 长时间没新包时会发送 heartbeat，见 [overlay_ws_server.py](file:///home/chenyu/workplace/tennis_analysis/services/overlay_ws_server.py#L20-L27)。

这可以减少前端误判连接断开。

#### 10.1.5 异常被收敛到服务状态

在 reader / processor 两个线程里，异常都会：

- 记录到 `self._error`
- `metrics.mark_status('error', str(exc))`
- 设置 `stop_event`

见 [production_live_stream_service.py](file:///home/chenyu/workplace/tennis_analysis/services/production_live_stream_service.py#L88-L95) 和 [production_live_stream_service.py](file:///home/chenyu/workplace/tennis_analysis/services/production_live_stream_service.py#L157-L160)。

这让故障至少可观测，而不是静默卡死。

#### 10.1.6 运行时指标持续输出

[RuntimeMetricsTracker](file:///home/chenyu/workplace/tennis_analysis/streaming/metrics.py#L10-L78) 会不断写：

- `frames_in`
- `frames_processed`
- `frames_out`
- `frames_dropped`
- `queue_max_size`
- `last_processing_ms`
- `avg_processing_ms`
- `last_analysis_ms`
- `last_raw_encode_ms`
- `last_sei_inject_ms`
- `status`
- `last_error`

这为后续接监控、做告警打下了基础。

### 10.2 当前“高可用”还没做到的部分

这部分很重要，避免误解为已经是生产级 HA。

当前尚未实现：

- 多实例热备或主备切换
- 输入 RTMP 断流自动重连策略
- 进程级 supervisor，例如 `systemd`、`supervisord`、K8s
- GPU 故障隔离与自动摘流
- 音视频同步与音频透传
- 跨机器共享状态
- 下游消费者多订阅背压隔离
- 真正的 SLA 级健康检查与告警

所以更准确地说：

- 当前已经实现“低延迟 + 单机可持续运行 + 一定程度自动恢复”
- 还没有实现“平台级高可用”

---

## 11. 为什么这个设计适合演示版，也适合继续演进

当前设计最好的地方，不是每个点都做到最强，而是分层比较清楚：

- 输入层负责拉流
- 主服务负责分析与打包
- TransportHub 负责跨模块传播最新结果
- Demo 层负责展示
- RTMP 回推层负责给外部播放器消费

这让后续演进比较顺：

- 如果以后要做服务端硬烧录，只需要把“前端 Canvas 叠框”换成“后端 OverlayComposer”
- 如果以后要接 WebRTC，只需要替换 egress 和前端播放链路
- 如果以后要做 HA，可以先把 MediaMTX、分析服务、状态管理拆成独立进程或独立节点

从代码组织上看，当前仓库已经具备继续服务化的基础，而不是一次性 Demo 脚本。

---

## 12. 一句话总结低延迟与高可用实现思路

如果只保留一句话，那就是：

**当前系统通过“分析和播放解耦、队列有界且允许丢旧帧、状态只保最新、编码走 zerolatency、元数据与视频按 frame_id/pts 对齐”来实现低延迟；通过“进程拆分、基础清理、RTMP 输出重启、WebSocket 心跳、运行时指标和错误状态暴露”来实现单机级稳定性。**

---

## 13. 阅读顺序建议

如果你要继续深挖代码，建议按下面顺序读：

1. [start_full_demo_stack.sh](file:///home/chenyu/workplace/tennis_analysis/scripts/start_full_demo_stack.sh#L1-L39)
2. [demo_app.py](file:///home/chenyu/workplace/tennis_analysis/services/demo_app.py#L46-L83)
3. [production_live_stream_service.py](file:///home/chenyu/workplace/tennis_analysis/services/production_live_stream_service.py#L30-L219)
4. [analysis_pipeline.py](file:///home/chenyu/workplace/tennis_analysis/realtime/analysis_pipeline.py#L77-L183)
5. [h264_sei.py](file:///home/chenyu/workplace/tennis_analysis/services/h264_sei.py#L80-L213)
6. [demo_server.py](file:///home/chenyu/workplace/tennis_analysis/services/demo_server.py#L40-L106)
7. [app.js](file:///home/chenyu/workplace/tennis_analysis/demo/app.js#L644-L939)

按这个顺序读，会最容易把“后端一帧数据”如何变成“前端一帧叠框画面”串起来。

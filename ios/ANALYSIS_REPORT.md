# TennisAnalysis iOS 项目分析报告

## 1. 项目概览

| 项目 | 详情 |
|------|------|
| 应用名称 | TennisAnalysisIOS |
| Bundle ID | com.chenyu.tennisanalysis.ios |
| 最低部署版本 | iOS 16.0 |
| 语言 | Swift 5.10 |
| UI 框架 | SwiftUI + UIKit 混合 |
| 项目生成 | XcodeGen (`project.yml`) |
| 依赖管理 | 无 SPM/CocoaPods，纯系统框架 |
| 设备支持 | iPhone + iPad（不含 Mac Catalyst） |
| 文件数 | 26 个（22 个 Swift 源文件 + 3 个 JSON 元数据 + 1 个 .gitkeep） |

## 2. 架构总览

```
TennisAnalysisIOSApp.swift          ← 入口
└── Features/Home/
    ├── HomeView.swift              ← 主界面（实时/离线 Tab）
    ├── HomeViewModel.swift         ← 离线模式 ViewModel
    └── LiveCameraPreviewView.swift ← 实时摄像头预览（UIViewRepresentable）

Core/
├── Pipeline/
│   ├── LiveCameraAnalyzer.swift    ← 实时摄像头分析管线
│   ├── OfflineVideoProcessor.swift ← 离线视频分析 + 导出
│   ├── CoreMLDetectors.swift       ← CoreML 检测器实现
│   ├── DetectorProtocols.swift     ← 检测器协议定义
│   ├── ModelMetadata.swift         ← 模型元数据加载
│   ├── PixelBufferTools.swift      ← 像素缓冲区工具
│   └── VideoAssetIO.swift          ← AVFoundation 读写
├── Analysis/
│   ├── AnalysisModels.swift        ← 数据模型定义
│   ├── Tracking.swift              ← SORT 跟踪器 + 球跟踪滤波
│   ├── PlayerSelection.swift       ← 两球员筛选
│   ├── BallPostProcessing.swift    ← 球插值 + 击球检测
│   ├── MiniCourtMapper.swift       ← 迷你球场坐标映射
│   ├── StatsAggregator.swift       ← 统计数据聚合
│   ├── AnalysisConstants.swift     ← 网球常量（场地尺寸等）
│   └── Geometry.swift              ← 几何/单位转换工具
└── Rendering/
    └── FrameRenderer.swift         ← CGContext 叠加层绘制
```

## 3. 两条分析管线

### 3.1 实时摄像头管线 (`LiveCameraAnalyzer`)

- **输入**: AVCaptureSession（后置摄像头，720p@60fps）
- **节流**: 目标 20fps 分析，`isProcessingFrame` 防止并发推理
- **流程**: 每 30 帧刷新球场关键点 → 球员+球检测并行 (`async let`) → SORT 跟踪 → BallTrackFilter → 输出 `LiveOverlaySnapshot`
- **渲染**: CAShapeLayer 叠加层（球员红框、球黄框、球场绿点），不写视频
- **统计**: 不做 stats/mini-court，仅叠框

### 3.2 离线视频管线 (`OfflineVideoProcessor`)

- **输入**: 用户从 Files App 导入的本地 MP4
- **两遍扫描**:
  1. **分析遍**: 逐帧读取 → 球员/球/球场检测 → SORT 跟踪 → 球员筛选 → 球插值 → 击球检测 → mini-court 映射 → stats 聚合
  2. **渲染遍**: 再次逐帧读取 → CGContext 绘制叠加层（框、关键点、mini-court、stats、帧号）→ H.264 编码导出
- **输出**: `Documents/Exports/<name>_analyzed.mp4`

### 3.3 管线对比

| 能力 | 实时摄像头 | 离线视频 |
|------|-----------|---------|
| 球员检测 | ✅ | ✅ |
| 球检测 | ✅ | ✅ |
| 球场关键点 | ✅（每30帧刷新） | ✅（首帧检测） |
| SORT 跟踪 | ✅ | ✅ |
| 球插值 | ❌ | ✅ |
| 击球检测 | ❌ | ✅ |
| Mini-court | ❌ | ✅ |
| 统计面板 | ❌ | ✅ |
| 叠加层渲染 | CAShapeLayer | CGContext → H.264 |
| 视频导出 | ❌ | ✅ |

## 4. CoreML 检测层

### 4.1 三个模型

| 模型 | 源权重 | 输入 | 输出 | 委托 |
|------|--------|------|------|------|
| `player_detector` | `yolov8x.pt` | 640×640×3 NHWC [0,1] | YOLO detection | ANE |
| `ball_detector` | `yolo5_last.pt` | 640×640×3 NHWC [0,1] | YOLO detection | ANE |
| `court_keypoints` | `keypoints_model.pth` | 224×224×3 NCHW ImageNet归一化 | [1, 28] 14个关键点 | ANE |

### 4.2 YOLO 输出解码 (`YoloCoreMLDetector`)

通用解码器，支持:
- 2D/3D 输出 shape（自动转置判断）
- objectness 有/无两种格式（6/85 属性 vs 4+class）
- 归一化/像素坐标自动检测（`maxCoordinate <= 2`）
- 内置 NMS（按 class 分组）
- float32/float16/double 三种 MLMultiArray 数据类型

### 4.3 模型加载

`ModelAssetLocator` 在 Bundle 中按优先级搜索: 根目录 → `Models/` → `Resources/` → `Resources/Models/`，支持 `.mlmodelc`（预编译）和 `.mlpackage`（运行时编译）。元数据从同名 `.json` 文件加载。

### 4.4 球场关键点检测器

- 使用 ImageNet 归一化（手动像素→NCHW MLMultiArray）
- 输出 shape 对齐: `[1,14,2]` / `[1,2,14]` / flat 三种格式自动处理
- 14 个关键点 (x,y) 映射回原始帧坐标

## 5. 分析算法

### 5.1 SORT 跟踪器 (`SortTracker`)

- IoU 匹配（贪心，按检测置信度排序）
- 参数: `maxAge=8`, `minHits=2`, `iouThreshold=0.2`
- 输出: 最多 2 个跟踪对象（按 `score * area` 排序取 top-2）
- 速度估算: 中心点位移 / 时间差

### 5.2 球跟踪滤波 (`BallTrackFilter`)

- 距离+置信度混合选最佳检测
- 指数平滑: `alpha=0.65`（偏保守）
- 丢失容忍: `maxLostFrames=5`，超时置 nil
- 速度估算: 同 SORT

### 5.3 球员筛选 (`PlayerSelection`)

- 取首帧检测，选距球场关键点最近的 2 人
- 将跟踪 ID 重映射为 1/2

### 5.4 球插值 (`BallInterpolation`)

- 逐坐标线性插值
- 首尾缺失: 向前/向后填充最近值
- 中间缺失: 线性插值补间

### 5.5 击球检测 (`BallShotDetector`)

- 基于 ball midY 的滚动均值（窗口=5）
- 检测 deltaY 符号变化
- 主策略: 找到符号变化后检查后续 `minimumChangeFramesForHit=25` 帧内同向变化数
- 备选策略: 简单符号变化，最小间隔 12 帧

### 5.6 Mini-Court 映射

- 固定 250×500 像素绘制区域，右上角
- 14 个关键点按真实网球尺寸（单打线 8.23m、双打线 10.97m 等）换算
- 球员位置: 用脚底位置 + 最近球场关键点 + 身高比例尺映射
- 球位置: 映射到离球最近的球员的坐标系

### 5.7 统计聚合 (`StatsAggregator`)

- 击球速度: 两击球帧间球在 mini-court 位移 → 像素→米→km/h
- 球员速度: 对手在两击球帧间位移
- 距离: 每回合两端球员总位移
- 卡路里: `distance_km × weight_kg × 1.036`
- 前向填充: 每帧复用最近统计行

## 6. 渲染层 (`FrameRenderer`)

直接在 CVPixelBuffer 上创建 CGContext 绘制:

| 元素 | 颜色 | 说明 |
|------|------|------|
| 球员框 | 红色 3px | + "Player ID: N" 标签 |
| 球框 | 黄色 3px | + "Ball ID: 1" 标签 |
| 球场关键点 | 红色实心圆 r=4 | + 索引编号 |
| Mini-court | 白色半透明背景 | 黑色线条 + 蓝色中线 + 绿色球员点 + 黄色球点 |
| Stats 面板 | 黑色半透明背景 | 白色文字: 击球速度/球员速度/平均/距离/卡路里 |
| 帧号 | 绿色 24pt bold | 左上角 |

## 7. 问题与风险

### 7.1 模型过时

| 模型 | 当前源 | 问题 |
|------|--------|------|
| `player_detector` | `yolov8x.pt` (COCO 通用) | 不区分网球球员/其他人，且 yolov8x 对移动端过重（131MB） |
| `ball_detector` | `yolo5_last.pt` (旧 YOLOv5) | 已被新训练的 YOLOv8s 替代（mAP50 0.820→更优） |
| `court_keypoints` | `keypoints_model.pth` | 无变化 |

**建议**: 用新训练的 `yolov8s_ball_sichuan_v1.pt` 和 `yolov8n_player_sichuan_v1.pt` 重新导出 CoreML 模型。球员模型从 131MB→6MB，且能区分 `tennis_player`/`other_person`。

### 7.2 球场关键点只检测首帧

`OfflineVideoProcessor` 仅在第一帧检测球场关键点，后续全部复用。对于有镜头切换的视频（如四川公开赛），关键点会完全错位。

`LiveCameraAnalyzer` 每 30 帧刷新一次，策略更好但仍有延迟。

### 7.3 离线管线两遍扫描性能

离线模式对视频做两遍完整读取（分析遍+渲染遍），长视频耗时翻倍。可考虑:
- 分析遍缓存每帧的 CVPixelBuffer 或 CGImage（内存风险）
- 或在分析遍同时写入渲染帧（需提前确定输出尺寸）

### 7.4 球员筛选依赖首帧

`PlayerSelection.chooseAndFilterPlayers` 仅根据第一帧的检测选 2 人。如果首帧球员未检出或选错，整段视频都会出错。

### 7.5 实时管线缺少球插值和击球检测

实时模式只做检测+跟踪+叠框，不做球插值和击球检测，因此也没有 stats 和 mini-court。这是有意为之（实时性能约束），但用户体验差距大。

### 7.6 Stats 面板硬编码坐标

`FrameRenderer.drawStats` 使用固定像素坐标 (`startX = frameSize.width - 400`, `startY = frameSize.height - 500`)，不适配不同分辨率。竖屏视频或 iPad 上可能溢出。

### 7.7 无持久化/回放

- 实时模式无录像/回放功能
- 离线模式的 stats 数据不持久化，仅写入视频叠加层
- 无与 PC 端 pipeline 结果对比的校验机制

### 7.8 开发者体验

- `DEVELOPMENT_TEAM` 为空，需要手动配置才能真机运行
- 无 Unit Test / UI Test
- 无 CI/CD 配置
- 调试日志依赖环境变量 `AUTO_PROCESS_DEBUG_VIDEO=1`

## 8. Feature Parity 现状（vs MIGRATION_PLAN）

| 功能 | 状态 |
|------|------|
| 两球员筛选 | ✅ |
| 球插值 | ✅ |
| 球场关键点渲染 | ✅ |
| Mini-court 绘制 | ✅ |
| 球员点（mini-court） | ✅ |
| 球点（mini-court） | ✅ |
| 击球速度 | ✅ |
| 球员速度 | ✅ |
| 距离 | ✅ |
| 卡路里 | ✅ |
| 帧号叠加 | ✅ |
| 输出视频导出 | ✅ |
| 实时摄像头模式 | ✅（额外功能，PC 端无） |

**MIGRATION_PLAN 中列出的 12 项功能全部已实现**，外加实时摄像头模式。

## 9. 改进建议优先级

| 优先级 | 建议 | 预期收益 |
|--------|------|---------|
| P0 | 用 sichuan 数据训练的新模型重新导出 CoreML | 球检测更准，球员模型 131MB→6MB |
| P1 | 球场关键点周期性刷新（离线模式） | 适应镜头切换视频 |
| P1 | 球员筛选改为滑动窗口投票 | 降低首帧依赖 |
| P2 | Stats 面板自适应布局 | 适配不同分辨率 |
| P2 | 实时模式增加简易 stats（击球计数） | 缩小实时/离线体验差距 |
| P3 | 离线管线合并为单遍 | 长视频处理时间减半 |
| P3 | 添加 Unit Test | 保证算法正确性 |

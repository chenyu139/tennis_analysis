# Tennis Analysis 项目深度分析

## 文档说明

- 本文基于当前仓库可见源码、配置文件、资源元数据和目录结构整理，结论仅以当前磁盘状态为准。
- 我尽量为关键结论提供可点击的源码定位；无法从当前仓库直接确认的内容，会明确标注“无法确认”或“仓库中未见对应文件”。
- 本文重点覆盖四条主线：Python PC 离线分析、iOS 离线分析、iOS 实时摄像头分析、模型导出与集成。

---

## 一、项目整体架构概览

### 1.1 项目的核心目标和功能定位

这个仓库的核心目标，是对网球比赛视频做结构化理解，并输出带叠加层的可视化结果视频。Python 端先完成一条 PC 离线分析链路，iOS 端则实现本地模型推理和视频导出，并扩展出实时摄像头分析能力。

从源码上看，项目至少包含以下能力：

- 球员检测与跟踪：见 [player_tracker.py:L8-L153](file:///home/chenyu/workplace/tennis_analysis/trackers/player_tracker.py#L8-L153)。
- 网球检测、轨迹补全与击球帧估计：见 [ball_tracker.py:L7-L148](file:///home/chenyu/workplace/tennis_analysis/trackers/ball_tracker.py#L7-L148)。
- 球场关键点检测：见 [court_line_detector.py:L8-L51](file:///home/chenyu/workplace/tennis_analysis/court_line_detector/court_line_detector.py#L8-L51)。
- 小地图映射与统计指标计算：见 [mini_court.py:L17-L280](file:///home/chenyu/workplace/tennis_analysis/mini_court/mini_court.py#L17-L280) 和 [main.py:L99-L200](file:///home/chenyu/workplace/tennis_analysis/main.py#L99-L200)。
- 结果渲染与视频输出：见 [main.py:L203-L317](file:///home/chenyu/workplace/tennis_analysis/main.py#L203-L317)、[FrameRenderer.swift:L6-L192](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Rendering/FrameRenderer.swift#L6-L192)。
- iOS 本地视频导入、分析与导出：见 [HomeViewModel.swift:L40-L190](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/HomeViewModel.swift#L40-L190)、[OfflineVideoProcessor.swift:L12-L282](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/OfflineVideoProcessor.swift#L12-L282)。
- iOS 实时摄像头推理与叠框显示：见 [LiveCameraAnalyzer.swift:L83-L356](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/LiveCameraAnalyzer.swift#L83-L356)、[LiveCameraPreviewView.swift:L5-L199](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/LiveCameraPreviewView.swift#L5-L199)。

README 对项目能力的描述与上述实现基本一致，即对网球视频进行检测、统计和结果输出，见 [README.md:L4-L18](file:///home/chenyu/workplace/tennis_analysis/README.md#L4-L18)。

### 1.2 整体系统形态

当前项目不是一个单点程序，而是四条互相关联的能力线：

1. Python 离线分析主线：入口在 [main.py:L229-L320](file:///home/chenyu/workplace/tennis_analysis/main.py#L229-L320)。
2. iOS 离线视频处理主线：入口状态由 [HomeView.swift:L178-L396](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/HomeView.swift#L178-L396) 发起，核心执行器为 [OfflineVideoProcessor.swift:L12-L282](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/OfflineVideoProcessor.swift#L12-L282)。
3. iOS 实时摄像头分析主线：状态入口同样在 [HomeView.swift:L76-L176](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/HomeView.swift#L76-L176)，实时采集与分析在 [LiveCameraAnalyzer.swift:L102-L356](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/LiveCameraAnalyzer.swift#L102-L356)。
4. 模型导出与移动端资源准备主线：导出入口在 [export_models.py:L388-L399](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L388-L399)，资源拷贝在 [prepare_ios_assets.py:L65-L83](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/prepare_ios_assets.py#L65-L83)，导出校验在 [validate_models.py:L273-L282](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/validate_models.py#L273-L282)。

`ios/MIGRATION_PLAN.md` 说明过 Python 模块到 iOS 模块的映射关系，但它是迁移计划，不应高于实际实现。比如计划中的 feature parity checklist 仍全部是未打勾状态，见 [MIGRATION_PLAN.md:L46-L60](file:///home/chenyu/workplace/tennis_analysis/ios/MIGRATION_PLAN.md#L46-L60)；而 Swift 代码中其实已经存在对应实现，如 [StatsAggregator.swift:L23-L152](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Analysis/StatsAggregator.swift#L23-L152)、[MiniCourtMapper.swift:L57-L157](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Analysis/MiniCourtMapper.swift#L57-L157)。

### 1.3 技术栈与依赖关系

#### Python 端

- CLI 编排：`argparse`，见 [main.py:L27-L36](file:///home/chenyu/workplace/tennis_analysis/main.py#L27-L36)。
- 视频读写与图像绘制：`opencv-python`，见 [main.py:L16](file:///home/chenyu/workplace/tennis_analysis/main.py#L16)、[video_utils.py:L21-L108](file:///home/chenyu/workplace/tennis_analysis/utils/video_utils.py#L21-L108)。
- 球员与球检测：`ultralytics.YOLO`，见 [player_tracker.py:L58-L89](file:///home/chenyu/workplace/tennis_analysis/trackers/player_tracker.py#L58-L89)、[ball_tracker.py:L76-L100](file:///home/chenyu/workplace/tennis_analysis/trackers/ball_tracker.py#L76-L100)。
- 球场关键点模型：`torch` + `torchvision.models.resnet50`，见 [court_line_detector.py:L8-L35](file:///home/chenyu/workplace/tennis_analysis/court_line_detector/court_line_detector.py#L8-L35)。
- 数据补全与统计：`pandas`、`numpy`，见 [main.py:L17-L19](file:///home/chenyu/workplace/tennis_analysis/main.py#L17-L19)、[ball_tracker.py:L4-L23](file:///home/chenyu/workplace/tennis_analysis/trackers/ball_tracker.py#L4-L23)。

#### iOS 端

- UI：`SwiftUI`，见 [TennisAnalysisIOSApp.swift:L3-L9](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/App/TennisAnalysisIOSApp.swift#L3-L9)、[HomeView.swift:L21-L441](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/HomeView.swift#L21-L441)。
- 视频/相机：`AVFoundation`，见 [VideoAssetIO.swift:L5-L94](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/VideoAssetIO.swift#L5-L94)、[LiveCameraAnalyzer.swift:L90-L261](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/LiveCameraAnalyzer.swift#L90-L261)。
- 本地推理：`CoreML`，见 [CoreMLDetectors.swift:L13-L338](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/CoreMLDetectors.swift#L13-L338)、[ModelMetadata.swift:L4-L61](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/ModelMetadata.swift#L4-L61)。
- 图像与像素缓冲：`CoreImage`、`CoreGraphics`、`UIKit`，见 [PixelBufferTools.swift:L7-L121](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/PixelBufferTools.swift#L7-L121)、[FrameRenderer.swift:L6-L192](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Rendering/FrameRenderer.swift#L6-L192)。

#### 模型导出工具链

- PyTorch 模型恢复与导出：见 [export_models.py:L326-L385](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L326-L385)。
- Core ML 转换：`coremltools`，见 [export_models.py:L93-L109](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L93-L109)。
- TFLite 量化：`tensorflow`，见 [export_models.py:L142-L153](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L142-L153)、[export_models.py:L202-L234](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L202-L234)。
- 导出结果校验：`onnxruntime`、`PIL`、`torchvision.transforms`，见 [validate_models.py:L7-L13](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/validate_models.py#L7-L13)。

### 1.4 目录结构与职责

下面只列当前分析主链路相关目录：

| 路径 | 职责 |
| --- | --- |
| `main.py` | Python 端总入口，负责两遍处理编排 |
| `trackers/` | 球员/球的检测、跟踪、插值和击球帧启发式判断 |
| `court_line_detector/` | 球场关键点模型封装 |
| `mini_court/` | mini-court 布局和坐标映射 |
| `utils/` | 视频兼容处理、读写、绘制、坐标换算等基础工具 |
| `constants/` | 球场尺寸、球员身高体重等统计常量 |
| `ios/TennisAnalysisIOS/App/` | iOS App 入口 |
| `ios/TennisAnalysisIOS/Features/Home/` | 主页面、模式切换、导入与预览 UI |
| `ios/TennisAnalysisIOS/Core/Pipeline/` | 视频读取、CoreML 推理、离线/实时流程编排 |
| `ios/TennisAnalysisIOS/Core/Analysis/` | 跟踪、几何、插值、统计、小地图映射数据逻辑 |
| `ios/TennisAnalysisIOS/Core/Rendering/` | 导出视频叠层绘制 |
| `ios/TennisAnalysisIOS/Resources/Models/` | CoreML 模型和 JSON 元数据资源 |
| `tools/mobile_export/` | 模型导出、量化、校验、资源准备脚本 |
| `training/` | 训练 notebook 和数据集说明 |
| `mobile/android/` | Android 工程与资产准备，仓库存在但不是当前主文档重点 |

### 1.5 模型资产现状

仓库能直接确认的模型信息主要来自 iOS 资源中的 JSON 元数据：

- 球员模型元数据：见 [player_detector.json:L1-L24](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Resources/Models/player_detector.json#L1-L24)。
- 网球模型元数据：见 [ball_detector.json:L1-L24](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Resources/Models/ball_detector.json#L1-L24)。
- 球场关键点模型元数据：见 [court_keypoints.json:L1-L29](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Resources/Models/court_keypoints.json#L1-L29)。

可以确认的事实：

- `player_detector` 与 `ball_detector` 当前 iOS 资源目标格式都是 `coreml`，输入 shape 为 `1x640x640x3`，输入布局为 `NHWC`。
- `court_keypoints` 当前 iOS 资源目标格式是 `coreml`，输入 shape 为 `1x3x224x224`，布局为 `NCHW`，并保留了均值方差归一化参数。
- 三份 JSON 中的 `source_weights` 指向作者本机绝对路径，而不是当前仓库里的模型文件，因此仓库本身并不包含这些权重的实体文件。

无法从当前仓库确认的内容：

- 训练 epoch、mAP、loss 曲线、训练集版本冻结点。
- `.pt/.pth` 权重文件的真实内容和 checksum。
- 导出时使用的 Ultralytics 精确版本。

---

## 二、核心流程详解

### 2.1 Python 端到端生命周期

#### 入口与参数

Python 入口是 [main.py:L229-L320](file:///home/chenyu/workplace/tennis_analysis/main.py#L229-L320)。参数解析见 [main.py:L27-L36](file:///home/chenyu/workplace/tennis_analysis/main.py#L27-L36)：

- `--input-video`：输入视频路径。
- `--output-video`：输出视频路径。
- `--use-stubs`：是否复用缓存检测结果。

这个入口的配置面不大，说明项目当前仍是“固定流程型应用”，不是插件化平台。

#### 生命周期总览

`main()` 的执行顺序可分为 11 步：

1. 读取 CLI 参数并确定 stub 路径，见 [main.py:L229-L235](file:///home/chenyu/workplace/tennis_analysis/main.py#L229-L235)。
2. 对输入视频做 OpenCV 兼容处理，见 [main.py:L237-L238](file:///home/chenyu/workplace/tennis_analysis/main.py#L237-L238)、[video_utils.py:L21-L52](file:///home/chenyu/workplace/tennis_analysis/utils/video_utils.py#L21-L52)。
3. 初始化球员/网球检测器，见 [main.py:L239-L240](file:///home/chenyu/workplace/tennis_analysis/main.py#L239-L240)。
4. 第一遍逐帧扫描，收集 `player_detections` 与 `ball_detections`，见 [main.py:L242-L249](file:///home/chenyu/workplace/tennis_analysis/main.py#L242-L249) 和 [main.py:L50-L97](file:///home/chenyu/workplace/tennis_analysis/main.py#L50-L97)。
5. 用首帧推理球场关键点，见 [main.py:L253-L255](file:///home/chenyu/workplace/tennis_analysis/main.py#L253-L255)。
6. 在全量球员检测结果里筛出两名场上球员，见 [main.py:L257](file:///home/chenyu/workplace/tennis_analysis/main.py#L257)、[player_tracker.py:L13-L47](file:///home/chenyu/workplace/tennis_analysis/trackers/player_tracker.py#L13-L47)。
7. 对球轨迹做插值补全并识别击球帧，见 [main.py:L258-L261](file:///home/chenyu/workplace/tennis_analysis/main.py#L258-L261)、[ball_tracker.py:L12-L66](file:///home/chenyu/workplace/tennis_analysis/trackers/ball_tracker.py#L12-L66)。
8. 建立 mini-court 映射，见 [main.py:L260-L266](file:///home/chenyu/workplace/tennis_analysis/main.py#L260-L266)、[mini_court.py:L189-L271](file:///home/chenyu/workplace/tennis_analysis/mini_court/mini_court.py#L189-L271)。
9. 构造统计行和逐帧 DataFrame，见 [main.py:L268-L275](file:///home/chenyu/workplace/tennis_analysis/main.py#L268-L275)。
10. 第二遍重新读视频，按帧叠加可视元素并输出，见 [main.py:L277-L315](file:///home/chenyu/workplace/tennis_analysis/main.py#L277-L315)。
11. 清理临时视频目录，见 [main.py:L316-L317](file:///home/chenyu/workplace/tennis_analysis/main.py#L316-L317)。

这是一条很明确的“两遍式流水线”：第一遍产出分析中间结果，第二遍负责渲染输出。好处是渲染阶段可以随机访问分析结果，但代价是视频会被读两次。

### 2.2 视频输入、兼容和资源释放

`prepare_video_for_opencv()` 是 Python 主链路能否跑起来的第一道保险，见 [video_utils.py:L21-L52](file:///home/chenyu/workplace/tennis_analysis/utils/video_utils.py#L21-L52)。

其处理逻辑是：

1. 先用 `_can_read_first_frame()` 测试 OpenCV 能否直接读到第一帧，见 [video_utils.py:L9-L18](file:///home/chenyu/workplace/tennis_analysis/utils/video_utils.py#L9-L18)。
2. 如果能读，直接返回原始路径。
3. 如果不能读，就用 `ffmpeg` 转码成 `libx264 + yuv420p` 的中间文件。
4. 再次验证转码后文件能否被 OpenCV 正确读取。
5. 返回兼容视频路径和临时目录。

这说明作者已经遇到过输入视频编码不兼容的问题，而且是通过工程化兼容处理，而不是把责任完全留给用户。

打开输入视频时，`open_video_capture()` 会在失败时直接抛出 `ValueError`，见 [video_utils.py:L60-L65](file:///home/chenyu/workplace/tennis_analysis/utils/video_utils.py#L60-L65)。输出视频时，`create_video_writer()` 使用 `mp4v` 并校验 `VideoWriter` 是否打开，见 [video_utils.py:L68-L75](file:///home/chenyu/workplace/tennis_analysis/utils/video_utils.py#L68-L75)。

### 2.3 第一遍检测扫描

`detect_video_stream()` 是第一遍分析扫描的核心函数，见 [main.py:L50-L97](file:///home/chenyu/workplace/tennis_analysis/main.py#L50-L97)。

它的职责不是“处理整段视频”，而是生成后续阶段需要的最小中间状态：

- `first_frame`：供球场关键点检测和 mini-court 布局初始化。
- `fps`：供击球间隔时间换算。
- `player_detections`：每帧球员检测结果列表。
- `ball_detections`：每帧网球检测结果列表。

重要实现点：

- 支持 stub 复用，见 [main.py:L57-L64](file:///home/chenyu/workplace/tennis_analysis/main.py#L57-L64)。这能大幅减少调试时的推理成本。
- 不缓存整段原视频帧，只保留首帧和检测结果，见 [main.py:L73-L86](file:///home/chenyu/workplace/tennis_analysis/main.py#L73-L86)。这对长视频内存压力非常关键。
- 每 500 帧输出一次进度日志，见 [main.py:L80-L81](file:///home/chenyu/workplace/tennis_analysis/main.py#L80-L81)。
- 通过 `finally` 显式释放 `cap` 和 OpenCV 句柄，见 [main.py:L84-L86](file:///home/chenyu/workplace/tennis_analysis/main.py#L84-L86)。

### 2.4 球员检测与两人筛选

`PlayerTracker` 的关键逻辑集中在三部分。

#### 1. 单帧检测与跟踪

`detect_frame()` 见 [player_tracker.py:L71-L89](file:///home/chenyu/workplace/tennis_analysis/trackers/player_tracker.py#L71-L89)：

- 模型采用懒加载，第一次调用时创建 `YOLO(self.model_path)`。
- 使用 `model.track(frame, persist=True)`，说明它复用了 Ultralytics 内置的 tracking 状态，而不是仓库自己实现 Kalman/Sort。
- 只保留类别名为 `person` 的框。
- 如果检测框还没有 track id，则跳过，避免中断整段处理。

这意味着 Python 端的“球员 tracking”并不是完全自主可控实现，而是强依赖 Ultralytics 的内部跟踪行为。

#### 2. 两名真实球员筛选

`choose_players()` 和 `choose_and_filter_players()` 见 [player_tracker.py:L13-L47](file:///home/chenyu/workplace/tennis_analysis/trackers/player_tracker.py#L13-L47)。

它的策略是：

- 只看第一帧中所有被跟踪的 `person`。
- 对每个目标计算其中心点到所有球场关键点的最小距离。
- 选择距离球场结构最近的两个 track。
- 将这两个原始 track id 固定重映射为 `1` 和 `2`。

这个策略的意义在于，它试图排除裁判、观众、场边工作人员等 YOLO 同样可能检测出来的人体框。它不是按置信度筛人，而是按“与球场空间结构的相关性”筛人。

#### 3. 绘制层

`_draw_player_ring()` 使用环形高亮而不是普通矩形框，见 [player_tracker.py:L91-L145](file:///home/chenyu/workplace/tennis_analysis/trackers/player_tracker.py#L91-L145)。这说明 Python 输出视频更偏向展示层可读性，而不是纯调试框。

### 2.5 网球检测、轨迹补全与击球帧判断

`BallTracker` 同样有三块核心逻辑。

#### 1. 单帧网球检测

`detect_frame()` 见 [ball_tracker.py:L89-L100](file:///home/chenyu/workplace/tennis_analysis/trackers/ball_tracker.py#L89-L100)：

- 使用 `self.model.predict(frame, conf=0.15)`。
- 不做多实例管理，检测结果统一塞进 `ball_dict[1]`。
- 如果同一帧存在多个候选框，最终保留的是循环里最后一个框，而不是显式选最大分数框。

这里有一个实现上的隐含前提：主链路假设“每帧只有一个有效网球目标”。这一点在统计和 mini-court 映射里都被延续了。

#### 2. 插值补全

`interpolate_ball_positions()` 将 `[{1: bbox}, ...]` 转为 DataFrame 后，对 `x1/y1/x2/y2` 四列插值和反向填充，见 [ball_tracker.py:L12-L23](file:///home/chenyu/workplace/tennis_analysis/trackers/ball_tracker.py#L12-L23)。

这一步是整个统计质量的关键，因为如果球轨迹中有太多空洞，后面的击球帧判断、球速估算都会失真。

#### 3. 击球帧估计

`get_ball_shot_frames()` 见 [ball_tracker.py:L25-L66](file:///home/chenyu/workplace/tennis_analysis/trackers/ball_tracker.py#L25-L66)。它并不是动作识别模型，而是一个几何启发式：

- 计算球框中心 `mid_y`。
- 对 `mid_y` 做 5 帧滚动均值。
- 对滚动序列做一阶差分 `delta_y`。
- 检测一段时间窗口里的方向翻转是否持续足够多帧。
- 严格规则失败时，回退到符号变化 + 最小帧间隔的简化规则。

因此，这里的“shot frame”更准确地说是“疑似击球转折帧”。

### 2.6 球场关键点检测

`CourtLineDetector` 见 [court_line_detector.py:L8-L35](file:///home/chenyu/workplace/tennis_analysis/court_line_detector/court_line_detector.py#L8-L35)。

模型结构和预处理非常明确：

- 骨干：`resnet50(weights=None)`。
- 输出层：`Linear(..., 28)`，即 14 个点的 `(x, y)`。
- 输入预处理：BGR 转 RGB，缩放到 `224x224`，按 ImageNet 均值方差标准化。
- 输出回投：再按原图宽高比例还原到原始像素坐标。

主流程只在首帧调用一次 `predict()`，见 [main.py:L253-L255](file:///home/chenyu/workplace/tennis_analysis/main.py#L253-L255)。

这说明 Python 版当前默认相机视角在整段视频中相对稳定。如果中间发生镜头切换或显著变焦，后续映射很可能偏离真实场地位置。

### 2.7 Mini-Court 映射与数据几何意义

`MiniCourt` 一方面负责绘制小球场，另一方面负责完成“原图像素坐标 -> 小球场标准化坐标”的换算，见 [mini_court.py:L17-L280](file:///home/chenyu/workplace/tennis_analysis/mini_court/mini_court.py#L17-L280)。

#### 小球场布局

- 画布尺寸和边距：见 [mini_court.py:L18-L28](file:///home/chenyu/workplace/tennis_analysis/mini_court/mini_court.py#L18-L28)。
- 标准球场 14 个关键点布局：见 [mini_court.py:L36-L80](file:///home/chenyu/workplace/tennis_analysis/mini_court/mini_court.py#L36-L80)。
- 线段与网线绘制：见 [mini_court.py:L82-L128](file:///home/chenyu/workplace/tennis_analysis/mini_court/mini_court.py#L82-L128)。

#### 映射算法

核心函数是 [mini_court.py:L189-L271](file:///home/chenyu/workplace/tennis_analysis/mini_court/mini_court.py#L189-L271)，思路如下：

1. 对球员，取框底部中点作为脚点；对球，取框中心点，见 [mini_court.py:L210-L218](file:///home/chenyu/workplace/tennis_analysis/mini_court/mini_court.py#L210-L218)。
2. 在原图球场关键点里，为目标点选择最接近的参考关键点，见 [mini_court.py:L221-L223](file:///home/chenyu/workplace/tennis_analysis/mini_court/mini_court.py#L221-L223)。
3. 用球员真实身高和像素高度近似估计米/像素比例，见 [mini_court.py:L225-L235](file:///home/chenyu/workplace/tennis_analysis/mini_court/mini_court.py#L225-L235)。
4. 把相对于关键点的像素距离换算为米，再换算成 mini-court 像素距离，见 [mini_court.py:L164-L187](file:///home/chenyu/workplace/tennis_analysis/mini_court/mini_court.py#L164-L187)。
5. 得到小球场中的标准化位置。

#### 常量来源

换算用到的球场尺寸、球员身高体重来自 [constants/__init__.py:L1-L12](file:///home/chenyu/workplace/tennis_analysis/constants/__init__.py#L1-L12)。这也是后续统计统一尺度的基础。

#### 边界处理

这个模块做了明显的容错设计：

- 球丢失时，优先沿用上一次的小地图球位置，见 [mini_court.py:L202-L208](file:///home/chenyu/workplace/tennis_analysis/mini_court/mini_court.py#L202-L208)、[mini_court.py:L263-L266](file:///home/chenyu/workplace/tennis_analysis/mini_court/mini_court.py#L263-L266)。
- 球员框缺失时，沿用上一帧球员小地图坐标，见 [mini_court.py:L260-L261](file:///home/chenyu/workplace/tennis_analysis/mini_court/mini_court.py#L260-L261)。
- 计算球员高度窗口时跳过缺失帧，见 [mini_court.py:L226-L235](file:///home/chenyu/workplace/tennis_analysis/mini_court/mini_court.py#L226-L235)。

这说明后续统计更依赖“连续、对齐”的轨迹，而不是完全严格的逐帧真实观测。

### 2.8 统计计算逻辑

统计由 [main.py:L99-L184](file:///home/chenyu/workplace/tennis_analysis/main.py#L99-L184) 和 [main.py:L187-L200](file:///home/chenyu/workplace/tennis_analysis/main.py#L187-L200) 协作完成。

#### 稀疏事件级统计

`build_player_stats_data()` 以相邻两次击球帧之间的时间窗口为单位计算统计值，见 [main.py:L122-L183](file:///home/chenyu/workplace/tennis_analysis/main.py#L122-L183)。

具体逻辑：

- 球速：由球在 mini-court 上的位移和击球间隔计算，见 [main.py:L129-L147](file:///home/chenyu/workplace/tennis_analysis/main.py#L129-L147)。
- 击球者判定：在起始击球帧上，取距离球最近的球员，见 [main.py:L136-L141](file:///home/chenyu/workplace/tennis_analysis/main.py#L136-L141)。
- 对手速度：不是击球者速度，而是对手在这一来回窗口内的位移速度，见 [main.py:L141-L147](file:///home/chenyu/workplace/tennis_analysis/main.py#L141-L147)。
- 跑动距离：对两名球员都计算窗口内位移，见 [main.py:L158-L180](file:///home/chenyu/workplace/tennis_analysis/main.py#L158-L180)。
- 热量：`距离公里 * 体重 * 每公里每公斤热量系数`，见 [main.py:L169-L180](file:///home/chenyu/workplace/tennis_analysis/main.py#L169-L180)。

#### 逐帧展开

`build_player_stats_dataframe()` 会把稀疏事件统计 merge 到完整帧序列里，再用 `ffill()` 向前填充，见 [main.py:L187-L200](file:///home/chenyu/workplace/tennis_analysis/main.py#L187-L200)。

所以渲染层拿到的是“每帧都有值”的状态快照，而不是只在击球帧瞬间更新。

#### 统计语义上的注意点

从源码可以确认几个容易被误解的地方：

- `player_1_average_player_speed` 实际除数使用的是 `player_2_shots`，`player_2_average_player_speed` 使用的是 `player_1_shots`，见 [main.py:L196-L199](file:///home/chenyu/workplace/tennis_analysis/main.py#L196-L199)。这是因为“球员速度”统计被记到了对手回合窗口上，不是 bug 还是有意设计，仅从当前仓库无法确认作者意图。
- 击球者识别不是基于挥拍动作，而是基于击球帧时距离球最近的球员，见 [main.py:L136-L141](file:///home/chenyu/workplace/tennis_analysis/main.py#L136-L141)。
- 统计精度高度依赖 mini-court 映射的稳定性，因此球场关键点错误会连带污染所有速度和距离数据。

### 2.9 第二遍渲染与输出

逐帧绘制统一通过 [main.py:L203-L226](file:///home/chenyu/workplace/tennis_analysis/main.py#L203-L226) 完成。

绘制顺序非常清晰：

1. 球员环形高亮，见 [main.py:L206-L208](file:///home/chenyu/workplace/tennis_analysis/main.py#L206-L208)。
2. 网球火焰效果，见 [main.py:L209-L210](file:///home/chenyu/workplace/tennis_analysis/main.py#L209-L210)。
3. 球场关键点，见 [main.py:L212](file:///home/chenyu/workplace/tennis_analysis/main.py#L212)。
4. mini-court 背景和球场线，见 [main.py:L213-L214](file:///home/chenyu/workplace/tennis_analysis/main.py#L213-L214)。
5. mini-court 上的球员点和球点，见 [main.py:L216-L223](file:///home/chenyu/workplace/tennis_analysis/main.py#L216-L223)。
6. 统计面板，见 [main.py:L224](file:///home/chenyu/workplace/tennis_analysis/main.py#L224)。
7. 帧号，见 [main.py:L225](file:///home/chenyu/workplace/tennis_analysis/main.py#L225)。

统计面板本身的版式逻辑在 [player_stats_drawer_utils.py:L4-L72](file:///home/chenyu/workplace/tennis_analysis/utils/player_stats_drawer_utils.py#L4-L72)，iOS 端有对应实现 [FrameRenderer.swift:L148-L170](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Rendering/FrameRenderer.swift#L148-L170)。这说明作者在 iOS 迁移时保留了 Python 版面板结构，而不是重做一套视觉语义。

### 2.10 异常处理与边界情况

从 Python 主链路可以明确看到几类异常与边界处理：

- 视频打不开：`open_video_capture()` 直接抛异常，见 [video_utils.py:L60-L65](file:///home/chenyu/workplace/tennis_analysis/utils/video_utils.py#L60-L65)。
- OpenCV 不兼容：自动转码，转码后仍不可读则抛异常，见 [video_utils.py:L21-L52](file:///home/chenyu/workplace/tennis_analysis/utils/video_utils.py#L21-L52)。
- 输入视频无帧：`detect_video_stream()` 抛 `ValueError`，见 [main.py:L60-L61](file:///home/chenyu/workplace/tennis_analysis/main.py#L60-L61)、[main.py:L88-L89](file:///home/chenyu/workplace/tennis_analysis/main.py#L88-L89)。
- 球员检测框临时无 ID：直接跳过，见 [player_tracker.py:L79-L80](file:///home/chenyu/workplace/tennis_analysis/trackers/player_tracker.py#L79-L80)。
- 某帧球员/球丢失：通过插值、上次位置延续等策略保持轨迹对齐，见 [ball_tracker.py:L12-L23](file:///home/chenyu/workplace/tennis_analysis/trackers/ball_tracker.py#L12-L23)、[mini_court.py:L260-L266](file:///home/chenyu/workplace/tennis_analysis/mini_court/mini_court.py#L260-L266)。
- 长视频内存压力：多个模块都有显式 `del` 和资源释放，见 [main.py:L83-L86](file:///home/chenyu/workplace/tennis_analysis/main.py#L83-L86)、[main.py:L309-L314](file:///home/chenyu/workplace/tennis_analysis/main.py#L309-L314)、[court_line_detector.py:L32-L33](file:///home/chenyu/workplace/tennis_analysis/court_line_detector/court_line_detector.py#L32-L33)。

总体判断：当前 Python 版不是一个“异常全吞掉”的脚本，而是对输入错误尽早抛出，对长视频资源占用进行显式治理，对检测缺失做局部容错。

---

## 三、iOS 部分详解

### 3.1 iOS 工程结构

iOS 工程配置基于 `XcodeGen`，而不是手工维护 `.pbxproj` 作为唯一事实源。当前主配置文件是 [project.yml:L1-L73](file:///home/chenyu/workplace/tennis_analysis/ios/project.yml#L1-L73)。

可以确认的结构要点：

- 只有一个 App target：`TennisAnalysisIOS`，见 [project.yml:L16-L20](file:///home/chenyu/workplace/tennis_analysis/ios/project.yml#L16-L20)。
- 部署目标：iOS 16.0，见 [project.yml:L11-L14](file:///home/chenyu/workplace/tennis_analysis/ios/project.yml#L11-L14) 和 [project.yml:L18-L20](file:///home/chenyu/workplace/tennis_analysis/ios/project.yml#L18-L20)。
- 源码目录：`TennisAnalysisIOS/`，资源目录单独包含 `Resources/Models`，见 [project.yml:L21-L30](file:///home/chenyu/workplace/tennis_analysis/ios/project.yml#L21-L30)。
- 依赖系统框架而非 CocoaPods/SPM 包，见 [project.yml:L65-L73](file:///home/chenyu/workplace/tennis_analysis/ios/project.yml#L65-L73)。

从仓库当前文件可见情况看：

- 未发现 `Podfile`。
- 未发现顶层 `Package.swift`。
- 依赖管理主要通过系统 SDK + 本地源码完成。

### 3.2 资源文件组织与模型打包

iOS 模型资源位于 `ios/TennisAnalysisIOS/Resources/Models/`。`project.yml` 通过 `postBuildScripts` 把编译后的 `.mlmodelc` 和三份 JSON 元数据复制进 App bundle 的 `Models` 目录，见 [project.yml:L31-L43](file:///home/chenyu/workplace/tennis_analysis/ios/project.yml#L31-L43)。

这意味着 iOS 运行时读取模型并不是直接访问源码目录，而是访问最终 bundle 里的资源。与之配套的定位逻辑在 [ModelMetadata.swift:L32-L61](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/ModelMetadata.swift#L32-L61)：

- `ModelAssetLocator.modelURL()` 会优先找 `mlmodelc`，其次找 `mlpackage`。
- `ModelAssetLocator.metadata()` 会读取对应的 JSON 元数据。
- 资源搜索路径允许 `nil`、`Models`、`Resources`、`Resources/Models` 四种子目录，增强了 bundle 布局兼容性。

### 3.3 App 入口与 UI 层架构

App 入口非常简洁，直接在 `WindowGroup` 中挂载 `HomeView(viewModel: HomeViewModel())`，见 [TennisAnalysisIOSApp.swift:L3-L9](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/App/TennisAnalysisIOSApp.swift#L3-L9)。

UI 主界面都集中在 [HomeView.swift:L21-L441](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/HomeView.swift#L21-L441)。它不是多页面复杂导航，而是单页面双模式切换：

- `AnalysisMode.camera`：实时摄像头模式，见 [HomeView.swift:L5-L19](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/HomeView.swift#L5-L19)。
- `AnalysisMode.offline`：离线视频模式，见 [HomeView.swift:L178-L196](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/HomeView.swift#L178-L196)。

#### 页面状态驱动

`HomeView` 持有两个核心状态对象：

- `HomeViewModel`：负责离线导入、处理、导出列表、状态文字，见 [HomeView.swift:L24-L32](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/HomeView.swift#L24-L32)。
- `LiveCameraAnalyzer`：负责实时相机采集与推理状态，见 [HomeView.swift:L24-L32](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/HomeView.swift#L24-L32)。

`fileImporter` 只允许选择 `.movie`，导入结果交给 `viewModel.handleVideoImport()`，见 [HomeView.swift:L45-L51](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/HomeView.swift#L45-L51)。

#### 实时模式 UI

`cameraBody` 由三层组成，见 [HomeView.swift:L76-L176](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/HomeView.swift#L76-L176)：

- 底层是 `LiveCameraPreviewView` 的相机预览。
- 顶部是模式切换和运行状态。
- 底部是当前分析状态、最近事件和启动/停止按钮。

这类结构说明实时模式强调“单屏看结果”，而非多层级跳转。

#### 离线模式 UI

`offlineBody` 使用一列卡片式布局，见 [HomeView.swift:L178-L396](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/HomeView.swift#L178-L396)。包含：

- 头图和功能描述。
- 输入模式切换。
- 当前视频展示。
- 选择视频 / 开始处理按钮。
- 导出结果列表与分享按钮。
- 处理状态卡片。
- 最近事件和使用说明。

因此，iOS 离线产品形态是“导入本地视频 -> 本机分析 -> 导出 MP4 -> 系统分享”，没有服务端依赖。

### 3.4 离线视频处理链路

离线视频处理的状态入口在 [HomeViewModel.swift:L40-L90](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/HomeViewModel.swift#L40-L90)。

#### 1. 导入

`handleVideoImport()` 与 `importSelectedVideo()` 负责接收系统文件选择结果，把视频复制进 App 自己的 Documents 目录，见 [HomeViewModel.swift:L21-L38](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/HomeViewModel.swift#L21-L38) 和 [HomeViewModel.swift:L150-L190](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/HomeViewModel.swift#L150-L190)。

这里的重要点是：

- 使用了 `startAccessingSecurityScopedResource()`，说明作者考虑了沙箱外文件访问，见 [HomeViewModel.swift:L163-L169](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/HomeViewModel.swift#L163-L169)。
- 导入后统一复制到 `Documents/ImportedVideos`，后续处理都基于应用私有目录，见 [HomeViewModel.swift:L175-L189](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/HomeViewModel.swift#L175-L189)。

#### 2. 发起处理

`startProcessing()` 校验输入文件存在后，调用 `OfflineVideoProcessor.processVideo()`，并把回调进度同步到 UI，见 [HomeViewModel.swift:L40-L90](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/HomeViewModel.swift#L40-L90)。

#### 3. 处理器内部编排

`OfflineVideoProcessor.processVideo()` 是整个离线 iOS 链路的总入口，见 [OfflineVideoProcessor.swift:L12-L59](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/OfflineVideoProcessor.swift#L12-L59)。

内部先做三件事：

- 用 `VideoAssetIO` 读取 `AVAsset`、帧率、尺寸和时长，见 [OfflineVideoProcessor.swift:L16-L23](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/OfflineVideoProcessor.swift#L16-L23)。
- 初始化 `PlayerCoreMLDetector`、`BallCoreMLDetector`、`CourtCoreMLDetector`，见 [OfflineVideoProcessor.swift:L25-L27](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/OfflineVideoProcessor.swift#L25-L27)。
- 先跑 `analyzeVideo()` 再跑 `exportVideo()`，见 [OfflineVideoProcessor.swift:L29-L55](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/OfflineVideoProcessor.swift#L29-L55)。

#### 4. 第一遍分析

`analyzeVideo()` 的结构对应 Python 第一遍分析扫描，但 iOS 版本更加模块化，见 [OfflineVideoProcessor.swift:L61-L149](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/OfflineVideoProcessor.swift#L61-L149)。

它完成以下工作：

- 通过 `AVAssetReader` 逐帧拉取 `CMSampleBuffer`，见 [OfflineVideoProcessor.swift:L71-L83](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/OfflineVideoProcessor.swift#L71-L83)。
- 首帧时检测球场关键点，见 [OfflineVideoProcessor.swift:L88-L90](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/OfflineVideoProcessor.swift#L88-L90)。
- 每帧做球员检测、Sort 跟踪、网球检测、球轨迹滤波，见 [OfflineVideoProcessor.swift:L92-L100](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/OfflineVideoProcessor.swift#L92-L100)。
- 全量扫描完成后，做两人筛选、球插值、小地图映射、击球帧检测和统计聚合，见 [OfflineVideoProcessor.swift:L116-L148](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/OfflineVideoProcessor.swift#L116-L148)。

#### 5. 第二遍导出

`exportVideo()` 用第二个 `AVAssetReader` 再读一遍视频，同时创建 `AVAssetWriter` 写输出文件，见 [OfflineVideoProcessor.swift:L151-L224](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/OfflineVideoProcessor.swift#L151-L224)。

关键步骤：

- 使用 `PixelBufferTools.copyPixelBuffer()` 复制原始像素缓冲，见 [OfflineVideoProcessor.swift:L183-L187](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/OfflineVideoProcessor.swift#L183-L187)。
- 用 `makeOverlayFrame()` 把分析结果组装成统一的 `OverlayFrame`，见 [OfflineVideoProcessor.swift:L188-L193](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/OfflineVideoProcessor.swift#L188-L193) 和 [OfflineVideoProcessor.swift:L226-L269](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/OfflineVideoProcessor.swift#L226-L269)。
- 交给 `FrameRenderer.render()` 画框、画球、画关键点、画小地图、画统计和帧号，见 [OfflineVideoProcessor.swift:L200-L205](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/OfflineVideoProcessor.swift#L200-L205)。
- 用 `AVAssetWriterInputPixelBufferAdaptor.append()` 写出，见 [OfflineVideoProcessor.swift:L207-L209](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/OfflineVideoProcessor.swift#L207-L209)。

### 3.5 iOS 的数据模型与分析模块拆分

iOS 端比 Python 更强调“协议 + 数据模型 + 小模块”的拆分。

#### 基础数据模型

`AnalysisModels.swift` 定义了整个 iOS 分析层的公共模型，见 [AnalysisModels.swift:L4-L113](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Analysis/AnalysisModels.swift#L4-L113)：

- `BoundingBox`
- `Detection`
- `TrackedObject`
- `OverlayFrame`
- `PlayerStatsRow`
- `AnalysisArtifacts`
- `AnalysisErrors`

这使得离线处理器、实时处理器、渲染器都可以共享一套类型，而不必传递松散字典。

#### 几何与换算

`Geometry.swift` 提供距离、IOU、最近关键点索引和单位换算，见 [Geometry.swift:L23-L83](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Analysis/Geometry.swift#L23-L83)。其职责与 Python 的 `bbox_utils.py`、`conversions.py` 类似，但被统一收敛到一个 Swift 文件。

#### 跟踪

`Tracking.swift` 实现了轻量版 Sort-like 跟踪器与球轨迹滤波器，见 [Tracking.swift:L4-L163](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Analysis/Tracking.swift#L4-L163)。

和 Python 不同，iOS 端没有依赖 Ultralytics 自带 tracker，而是自己做了：

- `SortTracker.update()`：按 IOU 关联检测与轨迹，见 [Tracking.swift:L27-L97](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Analysis/Tracking.swift#L27-L97)。
- `BallTrackFilter.update()`：按与上一帧球中心的距离和得分选最合理球框，并做指数平滑，见 [Tracking.swift:L108-L163](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Analysis/Tracking.swift#L108-L163)。

这也是 iOS 与 Python 行为不可能做到逐行完全一致的原因之一。

#### 两人筛选、球插值、击球帧、统计

这些模块都被独立拆分：

- 两人筛选：见 [PlayerSelection.swift:L4-L37](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Analysis/PlayerSelection.swift#L4-L37)。
- 球插值和击球帧：见 [BallPostProcessing.swift:L4-L127](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Analysis/BallPostProcessing.swift#L4-L127)。
- 统计聚合：见 [StatsAggregator.swift:L4-L152](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Analysis/StatsAggregator.swift#L4-L152)。
- mini-court 映射：见 [MiniCourtMapper.swift:L11-L157](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Analysis/MiniCourtMapper.swift#L11-L157)。

这些模块的语义基本都在对齐 Python 版，但实现细节不完全相同。例如：

- Python 的 mini-court 会保留上一帧球员/球位置以维持连续性；iOS 当前 `MiniCourtMapper` 在球缺失时直接 append 空字典，见 [MiniCourtMapper.swift:L70-L76](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Analysis/MiniCourtMapper.swift#L70-L76)。
- Python 的球员 tracking 依赖 Ultralytics；iOS 使用自研 `SortTracker`，见 [Tracking.swift:L4-L97](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Analysis/Tracking.swift#L4-L97)。

因此，“迁移完成”不等于“逐像素行为完全一致”。

### 3.6 Core ML 调用方式与数据格式

#### 协议层

三个检测协议定义在 [DetectorProtocols.swift:L5-L35](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/DetectorProtocols.swift#L5-L35)：

- `PlayerDetecting`
- `BallDetecting`
- `CourtKeypointDetecting`

这允许在模型未准备好时，用 `Unconfigured*` 实现返回统一错误 `AnalysisErrors.modelsNotReady`，见 [DetectorProtocols.swift:L17-L35](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/DetectorProtocols.swift#L17-L35)。

#### 模型资源读取

`BaseCoreMLModel` 和 `ModelAssetLocator` 完成模型/元数据加载，见 [CoreMLDetectors.swift:L13-L46](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/CoreMLDetectors.swift#L13-L46) 与 [ModelMetadata.swift:L32-L61](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/ModelMetadata.swift#L32-L61)。

输入尺寸不是写死的，而是优先从模型 image constraint 或 JSON 元数据推断，这使导出脚本和 iOS 推理端之间形成了松耦合协议。

#### YOLO 类模型解码

`YoloCoreMLDetector.detect()` 完成以下步骤，见 [CoreMLDetectors.swift:L56-L77](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/CoreMLDetectors.swift#L56-L77)：

1. 从 `CMSampleBuffer` 取出 `CVPixelBuffer`。
2. Resize 到模型输入尺寸。
3. 用 `MLDictionaryFeatureProvider` 喂给 Core ML。
4. 取回 `MLMultiArray`。
5. 交给 `decodeYoloLikeOutput()` 解码。

`decodeYoloLikeOutput()` 会自动识别输出 shape 是否转置、是否包含 objectness、是否是归一化坐标，并最后执行 NMS，见 [CoreMLDetectors.swift:L79-L179](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/CoreMLDetectors.swift#L79-L179)。

#### 球场关键点模型解码

`CourtCoreMLDetector.detectCourtKeypoints()` 路径稍有不同，见 [CoreMLDetectors.swift:L248-L297](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/CoreMLDetectors.swift#L248-L297)：

- 先把像素缓冲转成归一化后的 `MLMultiArray`，见 [PixelBufferTools.swift:L79-L121](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/PixelBufferTools.swift#L79-L121)。
- 归一化参数从 JSON 读取，而不是写死在模型调用处，见 [CoreMLDetectors.swift:L254-L260](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/CoreMLDetectors.swift#L254-L260)。
- 输出支持 `[1, 14, 2]` 和 `[1, 2, 14]` 两种 shape 兼容对齐，见 [CoreMLDetectors.swift:L280-L297](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/CoreMLDetectors.swift#L280-L297)。

### 3.7 视频 I/O 与渲染实现

#### 视频读取和写出

`VideoAssetIO` 统一封装 `AVAssetReader`/`AVAssetWriter` 的创建，见 [VideoAssetIO.swift:L5-L94](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/VideoAssetIO.swift#L5-L94)。

可以确认的实现细节：

- 读视频输出格式固定为 `kCVPixelFormatType_32BGRA`，见 [VideoAssetIO.swift:L32-L37](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/VideoAssetIO.swift#L32-L37)。
- 写视频编码为 `H.264`，平均码率 10 Mbps，见 [VideoAssetIO.swift:L51-L78](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/VideoAssetIO.swift#L51-L78)。
- 输出目录优先放到 `Documents/Exports`，见 [VideoAssetIO.swift:L81-L93](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/VideoAssetIO.swift#L81-L93)。

#### 像素缓冲处理

`PixelBufferTools` 负责：

- 从 sample buffer 取 pixel buffer，见 [PixelBufferTools.swift:L10-L15](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/PixelBufferTools.swift#L10-L15)。
- resize 像素缓冲，见 [PixelBufferTools.swift:L17-L40](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/PixelBufferTools.swift#L17-L40)。
- 为写出复制 pixel buffer，见 [PixelBufferTools.swift:L42-L64](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/PixelBufferTools.swift#L42-L64)。
- 把球场模型输入转成归一化 `MLMultiArray`，见 [PixelBufferTools.swift:L79-L121](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/PixelBufferTools.swift#L79-L121)。

#### 渲染器

`FrameRenderer.render()` 会在同一个 `CGContext` 上依次绘制球员、球、球场关键点、小地图、统计和帧号，见 [FrameRenderer.swift:L7-L50](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Rendering/FrameRenderer.swift#L7-L50)。

模块化拆分如下：

- 球员框：见 [FrameRenderer.swift:L52-L71](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Rendering/FrameRenderer.swift#L52-L71)。
- 球框：见 [FrameRenderer.swift:L73-L91](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Rendering/FrameRenderer.swift#L73-L91)。
- 球场关键点：见 [FrameRenderer.swift:L93-L106](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Rendering/FrameRenderer.swift#L93-L106)。
- mini-court：见 [FrameRenderer.swift:L108-L146](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Rendering/FrameRenderer.swift#L108-L146)。
- 统计面板：见 [FrameRenderer.swift:L148-L170](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Rendering/FrameRenderer.swift#L148-L170)。

### 3.8 实时摄像头链路

#### 总体结构

实时分析由 `LiveCameraAnalyzer` 负责采集、节流、推理和发布状态，`LiveCameraPreviewView` 负责显示预览层和叠框层，见 [LiveCameraAnalyzer.swift:L83-L356](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/LiveCameraAnalyzer.swift#L83-L356)、[LiveCameraPreviewView.swift:L5-L199](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/LiveCameraPreviewView.swift#L5-L199)。

#### 权限与生命周期

`start()` 会先检查摄像头授权状态，必要时请求权限，见 [LiveCameraAnalyzer.swift:L102-L121](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/LiveCameraAnalyzer.swift#L102-L121)。

同时 `HomeView` 会依据 `scenePhase` 在前后台切换时启动/停止 analyzer，见 [HomeView.swift:L52-L73](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/HomeView.swift#L52-L73)。这是一条典型的 iOS 生命周期处理路径。

#### 相机会话配置

`configureSession()` 做了如下配置，见 [LiveCameraAnalyzer.swift:L181-L229](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/LiveCameraAnalyzer.swift#L181-L229)：

- 优先 `hd1280x720`。
- 使用后置广角摄像头。
- 输出像素格式设为 `32BGRA`。
- `alwaysDiscardsLateVideoFrames = true`，避免推理来不及时帧积压。
- 根据设备能力尽量设置到 60 fps，见 [LiveCameraAnalyzer.swift:L231-L261](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/LiveCameraAnalyzer.swift#L231-L261)。

#### 实时推理节流

`captureOutput()` 不是对每一帧都做推理，而是按 `targetAnalysisFPS = 20` 节流，见 [LiveCameraAnalyzer.swift:L99-L100](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/LiveCameraAnalyzer.swift#L99-L100) 和 [LiveCameraAnalyzer.swift:L318-L325](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/LiveCameraAnalyzer.swift#L318-L325)。

这意味着：

- 预览层可能是 30/60 fps。
- 分析层则按 20 fps 左右自适应运行。
- 项目在这里显式把“流畅预览”和“可承受推理负载”解耦了。

#### 实时推理内容

`LiveFramePipeline.process()` 里：

- 球场关键点不是每帧重算，而是每隔约 30 帧刷新一次，见 [LiveCameraAnalyzer.swift:L46-L52](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/LiveCameraAnalyzer.swift#L46-L52)。
- 球员检测与球检测使用 `async let` 并发执行，见 [LiveCameraAnalyzer.swift:L54-L57](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/LiveCameraAnalyzer.swift#L54-L57)。
- 球员跟踪和球轨迹滤波都在本地 actor 内完成，见 [LiveCameraAnalyzer.swift:L59-L79](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/LiveCameraAnalyzer.swift#L59-L79)。

#### 预览层叠框

`LiveCameraPreviewView` 用 `AVCaptureVideoPreviewLayer` 做底层预览，并叠加三个 `CAShapeLayer` 分别画球员、球和球场关键点，见 [LiveCameraPreviewView.swift:L27-L74](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/LiveCameraPreviewView.swift#L27-L74)。

坐标转换采用 aspect-fill 下的自定义映射，而不是简单按宽高拉伸，见 [LiveCameraPreviewView.swift:L135-L170](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Features/Home/LiveCameraPreviewView.swift#L135-L170)。这对预览叠框是否贴合非常关键。

### 3.9 iOS 构建配置、权限与已知限制

#### 权限与 Info.plist 生成

`project.yml` 中直接写入了相机权限说明、文件共享、原地打开文档等键值，见 [project.yml:L48-L64](file:///home/chenyu/workplace/tennis_analysis/ios/project.yml#L48-L64)。其中最关键的是：

- `NSCameraUsageDescription`
- `UIFileSharingEnabled`
- `LSSupportsOpeningDocumentsInPlace`

这与当前产品形态完全匹配：需要相机权限、需要访问导入视频、需要导出视频给 Files/App 分享。

#### Scheme / Build Settings / 依赖

可直接从 `project.yml` 确认的构建事实：

- Debug/Release 两套配置，见 [project.yml:L4-L6](file:///home/chenyu/workplace/tennis_analysis/ios/project.yml#L4-L6)。
- Swift 5.10，见 [project.yml:L9-L13](file:///home/chenyu/workplace/tennis_analysis/ios/project.yml#L9-L13)。
- 自动签名，见 [project.yml:L63-L64](file:///home/chenyu/workplace/tennis_analysis/ios/project.yml#L63-L64)。
- 仅依赖 Apple SDK 框架，见 [project.yml:L65-L73](file:///home/chenyu/workplace/tennis_analysis/ios/project.yml#L65-L73)。

无法从当前仓库确认的部分：

- 团队签名配置没有实际填写 `DEVELOPMENT_TEAM`。
- 没有看到额外的第三方二进制 framework。
- 没看到独立 Scheme 文件，但 XcodeGen/`.pbxproj` 会自动生成 target 对应 scheme，这在仓库静态文件中不能像源码一样精确引用到一段业务逻辑。

---

## 四、模型转换部分详解

### 4.1 原始模型来源、格式和版本线索

从 Python 主流程和 iOS 元数据可以确认三类原始模型：

- 球员检测模型：Python 直接用 `yolov8x` 名称初始化，见 [main.py:L239-L240](file:///home/chenyu/workplace/tennis_analysis/main.py#L239-L240)。iOS 元数据记录的源权重是 `models/yolov8x.pt`，见 [player_detector.json:L1-L24](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Resources/Models/player_detector.json#L1-L24)。
- 网球检测模型：Python 使用 `models/yolo5_last.pt`，见 [main.py:L239-L240](file:///home/chenyu/workplace/tennis_analysis/main.py#L239-L240)。iOS 元数据同样对应 `yolo5_last.pt`，见 [ball_detector.json:L1-L24](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Resources/Models/ball_detector.json#L1-L24)。
- 球场关键点模型：Python 使用 `models/keypoints_model.pth`，见 [main.py:L253-L255](file:///home/chenyu/workplace/tennis_analysis/main.py#L253-L255)。iOS 元数据记录来源一致，见 [court_keypoints.json:L1-L29](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Resources/Models/court_keypoints.json#L1-L29)。

可以确认格式：

- 球员和球原始权重大概率是 PyTorch/Ultralytics `.pt`。
- 球场关键点模型是 PyTorch `.pth` state dict。

不能确认的内容：

- 精确训练版本号。
- 导出时使用的 Ultralytics minor version。
- `yolo5_last.pt` 是 YOLOv5 原生模型，还是通过兼容方式在 Ultralytics API 中加载的模型。仓库从调用方式可推断它被当成 YOLO 权重使用，但无法仅凭当前静态文件确认内部结构。

### 4.2 转换目标格式与原因

导出工具支持的目标格式由 [export_models.py:L15-L42](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L15-L42) 和 [export_models.py:L45-L76](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L45-L76) 定义：

- 检测模型支持 `onnx`、`tflite`、`coreml`。
- 球场关键点模型支持 `onnx`、`coreml`。
- `mobile_target` 支持 `cpu`、`gpu`、`nnapi`、`ane`。

原因从代码里也很明确：

- `ANE` 目标必须配合 `coreml`，见 [export_models.py:L246-L247](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L246-L247)。
- `NNAPI` 目标必须配合 `tflite + int8`，见 [export_models.py:L239-L245](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L239-L245)。
- iOS App 当前实际使用的是 Core ML，因为运行时只查找 `mlmodelc/mlpackage`，见 [ModelMetadata.swift:L40-L50](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/ModelMetadata.swift#L40-L50)。

所以，当前仓库对 iOS 的实际部署路线是：`PyTorch/Ultralytics -> Core ML`。对 Android/NNAPI 的准备路线则是：`PyTorch/Ultralytics -> SavedModel -> INT8 TFLite`。

### 4.3 检测模型的完整导出流程

检测模型导出在 [export_models.py:L236-L324](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L236-L324)。

#### 参数层约束

导出前先做约束检查：

- `nnapi` 必须 `--format tflite --int8 --data`，见 [export_models.py:L239-L245](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L239-L245)。
- `ane` 必须 `--format coreml`，见 [export_models.py:L246-L247](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L246-L247)。

#### 普通导出路径

如果不是 NNAPI 的 INT8 特殊路径，则直接：

1. 加载 `YOLO(args.weights)`。
2. 调用 `model.export(**export_kwargs)`。
3. 把导出产物拷贝并规范重命名到目标目录。
4. 写入 JSON 元数据。

对应源码见 [export_models.py:L249-L323](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L249-L323)。

#### NNAPI / INT8 特殊路径

如果要导出给 NNAPI 用的 INT8 TFLite，则流程更复杂，见 [export_models.py:L263-L300](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L263-L300)：

1. 推断或显式提供 SavedModel 目录。
2. 推断或显式提供校准数据 `.npy`。
3. 如缺失，则先用 Ultralytics 导出 SavedModel。
4. 调用 `quantize_saved_model_to_int8()` 进行 TFLite INT8 量化。

`quantize_saved_model_to_int8()` 又进一步完成：

- 加载 SavedModel。
- 配置 TFLiteConverter。
- 设置 representative dataset。
- 强制 `TFLITE_BUILTINS_INT8`。
- 设置输入输出类型为 `int8`。

见 [export_models.py:L202-L234](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L202-L234)。

### 4.4 球场关键点模型导出流程

球场模型导出在 [export_models.py:L326-L385](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L326-L385)。

步骤很明确：

1. 构建 `resnet50(weights=None)`，并把全连接层替换成 28 维输出，见 [export_models.py:L332-L335](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L332-L335)。
2. 从 `.pth` 加载 state dict。
3. 构造 `dummy_input`，shape 为 `1x3xH xW`，见 [export_models.py:L338-L338](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L338-L338)。
4. 若目标是 ONNX，则用 `torch.onnx.export` 导出，见 [export_models.py:L340-L350](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L340-L350)。
5. 若目标是 Core ML，则先 `torch.jit.trace`，再 `ct.convert(..., convert_to="mlprogram")` 导出 `.mlpackage`，见 [export_models.py:L351-L368](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L351-L368)。
6. 最后写元数据 JSON，见 [export_models.py:L370-L385](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L370-L385)。

### 4.5 关键参数、输入输出 shape 与精度策略

从导出脚本和资源 JSON 可以确认如下关键参数：

#### 检测模型

- 默认输入尺寸：`imgsz=640`，见 [export_models.py:L57-L58](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L57-L58)。
- Core ML / TFLite 记录的输入 shape：`[1, 640, 640, 3]`，见 [export_models.py:L314-L316](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L314-L316) 和 [player_detector.json:L6-L16](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Resources/Models/player_detector.json#L6-L16)。
- 输入范围：`[0.0, 1.0]`，见 [export_models.py:L316-L320](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L316-L320)。
- `tracked_class_ids` 固定为 `[0]`，见 [export_models.py:L320-L322](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L320-L322)。

#### 球场关键点模型

- 默认输入尺寸：`224x224`，见 [export_models.py:L33-L34](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L33-L34)。
- 输入 shape：`[1, 3, 224, 224]`，见 [export_models.py:L377-L384](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L377-L384)。
- 均值方差：`mean=[0.485,0.456,0.406]`、`std=[0.229,0.224,0.225]`，见 [export_models.py:L378-L380](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L378-L380)。
- 输出 shape：`[1, 28]`，见 [export_models.py:L381-L384](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L381-L384)。

#### 精度策略

- 检测模型支持 `--half` 和 `--int8`，见 [export_models.py:L58-L60](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L58-L60)。
- 当前 iOS 资源中的三份 JSON 都是 `half=false`、`int8=false`，见 [player_detector.json:L17-L24](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Resources/Models/player_detector.json#L17-L24)、[ball_detector.json:L17-L24](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Resources/Models/ball_detector.json#L17-L24)。
- 也就是说，当前 iOS 交付资源不是量化模型，而是 Core ML 浮点模型。

### 4.6 导出后的集成与调用

导出产物进入 iOS 的完整路径是：

1. `export_models.py` 生成 `.mlpackage/.json`，见 [export_models.py:L307-L323](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L307-L323) 和 [export_models.py:L370-L385](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L370-L385)。
2. `prepare_ios_assets.py` 把模型和元数据复制到 `ios/TennisAnalysisIOS/Resources/Models`，见 [prepare_ios_assets.py:L65-L83](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/prepare_ios_assets.py#L65-L83)。
3. Xcode build 脚本再把 `.mlmodelc/.json` 拷贝进最终 App bundle，见 [project.yml:L31-L43](file:///home/chenyu/workplace/tennis_analysis/ios/project.yml#L31-L43)。
4. 运行时由 `ModelAssetLocator` 定位模型和元数据，见 [ModelMetadata.swift:L40-L61](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/ModelMetadata.swift#L40-L61)。
5. `PlayerCoreMLDetector`、`BallCoreMLDetector`、`CourtCoreMLDetector` 在离线和实时流程中被实际调用，见 [CoreMLDetectors.swift:L182-L298](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/CoreMLDetectors.swift#L182-L298)。

这条链路是闭合的，说明当前仓库已经不只是“能导模型”，而是“导出的模型确实被 iOS 运行时消费”。

### 4.7 导出后校验机制

`validate_models.py` 提供了导出后和原始模型做对比的能力，见 [validate_models.py:L193-L270](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/validate_models.py#L193-L270)。

#### 检测模型校验

- 原始参考模型使用 Ultralytics `YOLO(args.weights)` 运行，见 [validate_models.py:L193-L203](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/validate_models.py#L193-L203)。
- 导出模型支持 ONNX 和 TFLite 推理路径，见 [validate_models.py:L58-L99](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/validate_models.py#L58-L99)。
- 最终对比项包括检测数量、中心点误差、均值 IOU、top score 等，见 [validate_models.py:L210-L230](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/validate_models.py#L210-L230)。

#### 球场模型校验

- 参考模型用 PyTorch 加载 ResNet50 state dict。
- 导出模型用 ONNXRuntime 跑。
- 比较指标是 `mean_abs_error` 和 `max_abs_error`，见 [validate_models.py:L236-L270](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/validate_models.py#L236-L270)。

这说明项目对“导出后还能否复现原模型输出”至少建立了基础数值校验，而不是盲目依赖导出成功即正确。

### 4.8 已知兼容性问题与解决策略

从仓库当前代码可以明确看到以下兼容性关注点：

- WSL 下大 SavedModel 的 INT8 转换可能不稳定，脚本会在大于 256 MB 时直接拒绝或回退复用已有 INT8 产物，见 [export_models.py:L214-L219](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L214-L219) 和 [export_models.py:L281-L291](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L281-L291)。
- iOS 端通过元数据而不是代码硬编码输入输出信息，降低了导出 shape 轻微变化带来的运行时崩溃风险，见 [ModelMetadata.swift:L4-L29](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/ModelMetadata.swift#L4-L29)。
- 球场关键点输出 shape 兼容 `[1,14,2]` 与 `[1,2,14]`，见 [CoreMLDetectors.swift:L280-L297](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/CoreMLDetectors.swift#L280-L297)。

但也有当前仓库仍无法静态确认的风险：

- Core ML 与 Python 原始 Ultralytics 输出是否在所有视频上保持足够一致，仓库没有现成对比报告文件。
- 球员与球模型在 iOS 上的实际延迟、ANE 占用和温度表现，无法从静态代码确认。
- 量化后的精度损失只在工具上支持校验路径，当前仓库中没有保存现成校验结果 JSON 或报告。

---

## 五、综合判断与当前状态总结

### 5.1 这个项目目前已经完成了什么

基于当前仓库，可以确认以下能力已经落到代码实现层，而不是停留在设计稿：

- Python 离线视频分析链路完整可跑，且考虑了长视频内存和 OpenCV 编码兼容问题。
- iOS 离线视频导入、本地分析、导出 MP4 的完整链路已经形成闭环。
- iOS 实时摄像头检测与叠框预览已经有独立实现。
- 模型导出、资源准备、运行时加载、导出后校验构成了较完整的移动端模型工程链路。

### 5.2 当前实现与“完全产品化”之间仍有差距的地方

以下是从当前仓库可以推断出的主要差距：

- Python 和 iOS 虽然功能上对齐较多，但 tracking、缺失值处理等实现不完全一致，输出结果未必逐帧一致。
- 球场关键点在 Python 主链路只用首帧估计一次，镜头变化场景下可能不稳。
- Python 的球检测每帧只保留一个框且没有明确的 best-score 选择逻辑，复杂场景下鲁棒性有限。
- 仓库中未包含权重实体和验证报告，因此无法仅凭当前仓库证明模型精度达到了什么水平。

### 5.3 对阅读源码的建议顺序

如果后续还要继续深入，我建议按这个顺序读：

1. [main.py:L229-L320](file:///home/chenyu/workplace/tennis_analysis/main.py#L229-L320)：先建立 Python 总流程心智模型。
2. [player_tracker.py:L13-L89](file:///home/chenyu/workplace/tennis_analysis/trackers/player_tracker.py#L13-L89) 与 [ball_tracker.py:L12-L66](file:///home/chenyu/workplace/tennis_analysis/trackers/ball_tracker.py#L12-L66)：理解检测、筛选、插值、击球帧逻辑。
3. [mini_court.py:L156-L271](file:///home/chenyu/workplace/tennis_analysis/mini_court/mini_court.py#L156-L271)：理解所有统计为何能从像素变成“米”和“km/h”。
4. [OfflineVideoProcessor.swift:L61-L224](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/OfflineVideoProcessor.swift#L61-L224)：理解 iOS 如何复刻 Python 两遍式链路。
5. [CoreMLDetectors.swift:L56-L179](file:///home/chenyu/workplace/tennis_analysis/ios/TennisAnalysisIOS/Core/Pipeline/CoreMLDetectors.swift#L56-L179)：理解移动端推理与输出解码。
6. [export_models.py:L236-L385](file:///home/chenyu/workplace/tennis_analysis/tools/mobile_export/export_models.py#L236-L385)：理解模型如何从训练权重进入移动端。

以上内容均以当前仓库状态为准；对于模型权重内容、训练过程和真实性能指标，当前仓库无法直接证明，因此本文不做猜测。

# 球检测标注指南

## 当前模型配置

| 用途 | 模型 | 说明 |
|------|------|------|
| 球员检测 | `yolov8x.pt` | COCO 预训练，class 0 = person，直接用，不训练 |
| 球检测 | `yolov8s_ball_sichuan_v1.pt` | 自训练 YOLOv8s，class 0 = tennis ball |
| 场地关键点 | `keypoints_model.pth` | ResNet50，14个关键点 |

## 球检测训练数据来源

`sichuan_ball_merged` 里有两个数据源混合：

| 来源 | 文件特征 | 训练集数量 | 标注方式 |
|------|----------|-----------|---------|
| Roboflow 公开数据集 | `clay*.rf.*.jpg`, `fed*.rf.*.jpg`, `hard_*.jpg` | ~313张 | 人工标注 |
| 四川视频抽帧 | `scene_*.jpg`, `uniform_*.jpg`, `hard_miss/low/high_*.jpg` | ~906张 | 自动标注（yolo5_last.pt 生成） |

## 当前标注方式的问题

球的标注是用 `yolo5_last.pt`（旧模型）自动生成的，这是用旧模型自己给自己标数据来训练新模型，问题很明显：

1. **伪标签循环** — 旧模型检测不到的球，新模型也不会学到。只有 483/1132（43%）的 sichuan 帧有球标注，剩下的 649 帧是空标签，但其中一定有不少帧其实有球只是旧模型没检测到
2. **标注噪声** — 自动标注的框不够精确，特别是球很小（远处）或模糊（运动中）的时候，框的位置会偏
3. **假阳性** — 旧模型可能把一些非球目标（比如白色圆形物体）标成了球
4. **Roboflow 数据和视频场景不匹配** — clay 场红土场景、fed 选手特写，跟四川硬地场的画面风格差异大

**核心结论：如果想球检测效果好，必须人工标注。**

## 人工标注操作指南

### 1. 安装标注工具

推荐 LabelImg 或 CVAT，最简单的是 LabelImg：

```bash
pip install labelImg
```

### 2. 准备待标注图片

图片已经在 `training/sichuan_frames/` 里了（1132 张）。可以全部标注，或者优先标注那些自动标注为空但可能含球的帧：

```bash
# 找出空标签的帧（旧模型没检测到球的）
for f in training/sichuan_frames/labels_ball/*.txt; do
  if [ ! -s "$f" ]; then echo "$(basename $f .txt).jpg"; fi
done > training/sichuan_frames/frames_to_annotate.txt
```

### 3. 启动 LabelImg

```bash
cd /home/chenyu/workplace/tennis_analysis
labelImg training/sichuan_frames training/sichuan_frames/labels_ball
```

### 4. LabelImg 操作步骤

1. **打开图片**：左侧图片列表会显示所有帧
2. **画框**：
   - 快捷键 `W` 创建矩形框
   - 用鼠标拖拽框住球（尽量贴紧球边缘，不要留太多空白）
   - 类别选 **tennis ball**（class 0）
3. **保存**：`Ctrl+S`，格式选 **YOLO**（生成 `.txt` 标签文件）
4. **下一张**：`D` 键下一张，`A` 键上一张

### 5. 标注要点

- **网球很小**，在转播画面中通常只有几个像素到几十像素，框要尽量小而精确
- **球在运动中会模糊**，框住整个模糊区域即可
- **球被遮挡/出画面**：不要标注
- **看不到球**：留空标签即可（空 .txt 文件）
- **有争议的**：如果觉得"可能是球但不确定"，**不要标注**，避免引入噪声
- **每张图可能有 0 或 1 个球**，极少情况会有 2 个

### 6. 标注后的处理

标注完成后，重新构建数据集并训练：

```bash
# 重新构建数据集（会合并 roboflow + 新标注的 sichuan 帧）
python tools/data/build_datasets.py

# 训练球检测模型
python runtime/train_yolov8_ball.py \
  --data training/sichuan_ball_merged/data.yaml \
  --project runtime/runs \
  --name yolov8s_tennis_ball_v2
```

### 7. 只用自己数据训练（推荐）

如果 Roboflow 的数据跟视频无关，可以只用 sichuan 帧训练。把 `build_datasets.py` 里复制 Roboflow 数据的部分去掉，只保留 sichuan 帧。这样训练出来的模型会更贴合实际场景。

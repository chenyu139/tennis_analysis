from pathlib import Path

from ultralytics import RTDETR, YOLO
import cv2
import pickle
import pandas as pd
import numpy as np

class BallTracker:
    def __init__(self,model_path, device=None, detector_type='auto'):
        self.model_path = model_path
        self.model = None
        self.device = device
        self.detector_type = self._resolve_detector_type(detector_type, model_path)
        self.last_ball_box = None
        self.missing_frames = 0

    def _resolve_detector_type(self, detector_type, model_path):
        normalized = str(detector_type or 'auto').strip().lower()
        if normalized in {'yolo', 'rtdetr'}:
            return normalized
        model_name = Path(str(model_path)).name.lower()
        if 'rtdetr' in model_name:
            return 'rtdetr'
        return 'yolo'

    def _ensure_model(self):
        if self.model is None:
            model_cls = RTDETR if self.detector_type == 'rtdetr' else YOLO
            self.model = model_cls(self.model_path)
            if self.device is not None:
                try:
                    self.model.to(self.device)
                except Exception:
                    pass

    def interpolate_ball_positions(self, ball_positions):
        ball_positions = [x.get(1,[]) for x in ball_positions]
        # convert the list into pandas dataframe
        df_ball_positions = pd.DataFrame(ball_positions,columns=['x1','y1','x2','y2'])

        # interpolate the missing values
        df_ball_positions = df_ball_positions.interpolate()
        df_ball_positions = df_ball_positions.bfill()

        ball_positions = [{1:x} for x in df_ball_positions.to_numpy().tolist()]

        return ball_positions

    def get_ball_shot_frames(self,ball_positions):
        ball_positions = [x.get(1,[]) for x in ball_positions]
        df_ball_positions = pd.DataFrame(ball_positions,columns=['x1','y1','x2','y2'])

        df_ball_positions['ball_hit'] = 0

        df_ball_positions['mid_y'] = (df_ball_positions['y1'] + df_ball_positions['y2'])/2
        df_ball_positions['mid_y_rolling_mean'] = df_ball_positions['mid_y'].rolling(window=5, min_periods=1, center=False).mean()
        df_ball_positions['delta_y'] = df_ball_positions['mid_y_rolling_mean'].diff()
        minimum_change_frames_for_hit = 25
        for i in range(1,len(df_ball_positions)- int(minimum_change_frames_for_hit*1.2) ):
            negative_position_change = df_ball_positions['delta_y'].iloc[i] >0 and df_ball_positions['delta_y'].iloc[i+1] <0
            positive_position_change = df_ball_positions['delta_y'].iloc[i] <0 and df_ball_positions['delta_y'].iloc[i+1] >0

            if negative_position_change or positive_position_change:
                change_count = 0 
                for change_frame in range(i+1, i+int(minimum_change_frames_for_hit*1.2)+1):
                    negative_position_change_following_frame = df_ball_positions['delta_y'].iloc[i] >0 and df_ball_positions['delta_y'].iloc[change_frame] <0
                    positive_position_change_following_frame = df_ball_positions['delta_y'].iloc[i] <0 and df_ball_positions['delta_y'].iloc[change_frame] >0

                    if negative_position_change and negative_position_change_following_frame:
                        change_count+=1
                    elif positive_position_change and positive_position_change_following_frame:
                        change_count+=1
            
                if change_count>minimum_change_frames_for_hit-1:
                    df_ball_positions.loc[i, 'ball_hit'] = 1

        frame_nums_with_ball_hits = df_ball_positions[df_ball_positions['ball_hit']==1].index.tolist()

        if len(frame_nums_with_ball_hits) == 0:
            sign = (df_ball_positions['delta_y'] > 0).astype(int)
            sign_change = sign.diff().fillna(0).abs()
            candidate_frames = df_ball_positions[sign_change > 0].index.tolist()
            filtered_frames = []
            min_gap = 12
            for frame_idx in candidate_frames:
                if not filtered_frames or frame_idx - filtered_frames[-1] >= min_gap:
                    filtered_frames.append(frame_idx)
            frame_nums_with_ball_hits = filtered_frames

        return frame_nums_with_ball_hits

    def detect_frames(self,frames, read_from_stub=False, stub_path=None):
        ball_detections = []

        if read_from_stub and stub_path is not None:
            with open(stub_path, 'rb') as f:
                ball_detections = pickle.load(f)
            return ball_detections

        self._ensure_model()

        for frame in frames:
            player_dict = self.detect_frame(frame)
            ball_detections.append(player_dict)
        
        if stub_path is not None:
            with open(stub_path, 'wb') as f:
                pickle.dump(ball_detections, f)
        
        return ball_detections

    def detect_frame(self,frame):
        self._ensure_model()
        frame_h, frame_w = frame.shape[:2]
        if self.detector_type == 'rtdetr':
            predict_kwargs = {
                'conf': 0.36,
                'iou': 0.22,
                'max_det': 6,
                'verbose': False,
            }
        else:
            predict_kwargs = {
                'conf': 0.22,
                'iou': 0.35,
                'max_det': 3,
                'verbose': False,
            }
        if self.device is not None:
            predict_kwargs['device'] = self.device
            if str(self.device).startswith('cuda'):
                predict_kwargs['half'] = True
        results = self.model.predict(frame, **predict_kwargs)[0]

        ball_dict = {}
        best_box = None
        best_score = float('-inf')
        max_box_side = max(14.0, min(frame_w, frame_h) * (0.034 if self.detector_type == 'rtdetr' else 0.05))
        max_box_area = frame_w * frame_h * (0.0012 if self.detector_type == 'rtdetr' else 0.0020)
        max_jump = max(frame_w, frame_h) * (0.23 if self.detector_type == 'rtdetr' else 0.32)
        for box in results.boxes:
            confidence = float(box.conf.tolist()[0]) if box.conf is not None else 0.0
            candidate_box = box.xyxy.tolist()[0]
            x1, y1, x2, y2 = candidate_box
            width = max(float(x2 - x1), 0.0)
            height = max(float(y2 - y1), 0.0)
            if width < 2.0 or height < 2.0:
                continue
            if max(width, height) > max_box_side:
                continue
            if width * height > max_box_area:
                continue
            aspect_ratio = max(width / max(height, 1e-6), height / max(width, 1e-6))
            if aspect_ratio > (2.3 if self.detector_type == 'rtdetr' else 2.4):
                continue

            score = confidence
            if self.last_ball_box is not None:
                prev_x1, prev_y1, prev_x2, prev_y2 = self.last_ball_box
                prev_center_x = (prev_x1 + prev_x2) / 2.0
                prev_center_y = (prev_y1 + prev_y2) / 2.0
                center_x = (x1 + x2) / 2.0
                center_y = (y1 + y2) / 2.0
                jump_distance = float(np.hypot(center_x - prev_center_x, center_y - prev_center_y))
                if jump_distance > max_jump:
                    continue
                if self.detector_type == 'rtdetr' and jump_distance > max_jump * 0.8 and confidence < 0.48:
                    continue
                score -= jump_distance / max(max_jump, 1.0) * (0.38 if self.detector_type == 'rtdetr' else 0.35)

                prev_area = max((prev_x2 - prev_x1) * (prev_y2 - prev_y1), 1.0)
                area_ratio = (width * height) / prev_area
                if area_ratio > (3.2 if self.detector_type == 'rtdetr' else 3.5) or area_ratio < (0.25 if self.detector_type == 'rtdetr' else 0.2):
                    score -= 0.12 if self.detector_type == 'rtdetr' else 0.15

            if score > best_score:
                best_score = score
                best_box = candidate_box
        if best_box is not None:
            ball_dict[1] = best_box
            self.last_ball_box = best_box
            self.missing_frames = 0
        else:
            self.missing_frames += 1
            if self.missing_frames > 2:
                self.last_ball_box = None
        del results  # FIX: 每帧推理后显式释放检测结果对象，减少长视频处理时内存滞留
        
        return ball_dict

    def _draw_flame(self, frame, bbox):
        x1, y1, x2, y2 = [int(value) for value in bbox]
        center_x = int((x1 + x2) / 2)
        center_y = int((y1 + y2) / 2)
        ball_size = max(int(max(x2 - x1, y2 - y1)), 8)

        glow = frame.copy()
        cv2.circle(glow, (center_x, center_y), ball_size + 10, (0, 90, 255), -1)
        cv2.circle(glow, (center_x, center_y), ball_size + 4, (0, 180, 255), -1)
        cv2.addWeighted(glow, 0.28, frame, 0.72, 0, frame)

        flame_base = [
            (center_x, center_y - ball_size - 12),
            (center_x - ball_size - 5, center_y + 2),
            (center_x, center_y + ball_size + 8),
            (center_x + ball_size + 5, center_y + 2),
        ]
        inner_flame = [
            (center_x, center_y - ball_size - 4),
            (center_x - max(ball_size // 2, 4), center_y + 1),
            (center_x, center_y + max(ball_size // 2, 5)),
            (center_x + max(ball_size // 2, 4), center_y + 1),
        ]

        cv2.fillConvexPoly(frame, np.array(flame_base, dtype=np.int32), (0, 80, 255))
        cv2.fillConvexPoly(frame, np.array(inner_flame, dtype=np.int32), (0, 215, 255))
        cv2.circle(frame, (center_x, center_y + 1), max(ball_size // 2, 4), (255, 255, 255), -1)
        cv2.circle(frame, (center_x, center_y + 1), max(ball_size // 3, 2), (0, 230, 255), -1)

        cv2.putText(
            frame,
            "Ball",
            (center_x + ball_size + 6, max(center_y - ball_size - 6, 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 215, 255),
            2
        )

    def draw_bboxes(self,video_frames, player_detections):
        output_video_frames = []
        for frame, ball_dict in zip(video_frames, player_detections):
            for track_id, bbox in ball_dict.items():
                self._draw_flame(frame, bbox)
            output_video_frames.append(frame)
        
        return output_video_frames


    

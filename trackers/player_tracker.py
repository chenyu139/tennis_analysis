from ultralytics import YOLO 
import cv2
import pickle
import sys
sys.path.append('../')
from utils import measure_distance, get_center_of_bbox, get_foot_position

class PlayerTracker:
    def __init__(self,model_path, device=None):
        self.model_path = model_path
        self.model = None
        self.device = device

    def _ensure_model(self):
        if self.model is None:
            self.model = YOLO(self.model_path)
            if self.device is not None:
                try:
                    self.model.to(self.device)
                except Exception:
                    pass

    def choose_and_filter_players(self, court_keypoints, player_detections):
        player_detections_first_frame = player_detections[0]
        chosen_player = self.choose_players(court_keypoints, player_detections_first_frame)
        player_id_map = {
            chosen_player[0]: 1,
            chosen_player[1]: 2
        }
        filtered_player_detections = []
        for player_dict in player_detections:
            filtered_player_dict = {
                player_id_map[track_id]: bbox
                for track_id, bbox in player_dict.items()
                if track_id in player_id_map
            }
            filtered_player_detections.append(filtered_player_dict)
        return filtered_player_detections

    def choose_players(self, court_keypoints, player_dict):
        distances = []
        for track_id, bbox in player_dict.items():
            player_center = get_center_of_bbox(bbox)

            min_distance = float('inf')
            for i in range(0,len(court_keypoints),2):
                court_keypoint = (court_keypoints[i], court_keypoints[i+1])
                distance = measure_distance(player_center, court_keypoint)
                if distance < min_distance:
                    min_distance = distance
            distances.append((track_id, min_distance))
        
        # sorrt the distances in ascending order
        distances.sort(key = lambda x: x[1])
        # Choose the first 2 tracks
        chosen_players = [distances[0][0], distances[1][0]]
        return chosen_players


    def detect_frames(self,frames, read_from_stub=False, stub_path=None):
        player_detections = []

        if read_from_stub and stub_path is not None:
            with open(stub_path, 'rb') as f:
                player_detections = pickle.load(f)
            return player_detections

        self._ensure_model()

        for frame in frames:
            player_dict = self.detect_frame(frame)
            player_detections.append(player_dict)
        
        if stub_path is not None:
            with open(stub_path, 'wb') as f:
                pickle.dump(player_detections, f)
        
        return player_detections

    def detect_frame(self,frame):
        self._ensure_model()
        track_kwargs = {'persist': True}
        if self.device is not None:
            track_kwargs['device'] = self.device
        results = self.model.track(frame, **track_kwargs)[0]
        id_name_dict = results.names

        player_dict = {}
        for box in results.boxes:
            if box.id is None:
                continue  # FIX: 长视频跟踪结果中部分检测框可能还未分配 track id，跳过以避免空指针中断整段处理
            track_id = int(box.id.tolist()[0])
            result = box.xyxy.tolist()[0]
            object_cls_id = box.cls.tolist()[0]
            object_cls_name = id_name_dict[object_cls_id]
            if object_cls_name == "person":
                player_dict[track_id] = result
        del results  # FIX: 每帧推理后显式释放检测结果对象，减少长视频处理时内存滞留
        
        return player_dict

    def _draw_player_ring(self, frame, bbox, track_id):
        foot_x, foot_y = get_foot_position(bbox)
        foot_x = int(foot_x)
        foot_y = int(foot_y)
        player_width = max(int(bbox[2] - bbox[0]), 1)
        ring_width = max(int(player_width * 0.7), 18)
        ring_height = max(int(ring_width * 0.28), 8)

        overlay = frame.copy()

        # Add a soft glow beneath the player so the ring reads clearly on court.
        cv2.ellipse(
            overlay,
            (foot_x, foot_y),
            (ring_width + 8, ring_height + 5),
            0,
            0,
            360,
            (210, 210, 210),
            -1
        )
        cv2.addWeighted(overlay, 0.18, frame, 0.82, 0, frame)

        cv2.ellipse(
            frame,
            (foot_x, foot_y),
            (ring_width, ring_height),
            0,
            0,
            360,
            (255, 255, 255),
            3
        )
        cv2.ellipse(
            frame,
            (foot_x, foot_y),
            (max(ring_width - 8, 6), max(ring_height - 3, 3)),
            0,
            0,
            360,
            (235, 235, 235),
            1
        )

        label_origin = (foot_x - ring_width, max(int(bbox[1]) - 12, 24))
        cv2.putText(
            frame,
            f"P{track_id}",
            label_origin,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2
        )

    def draw_bboxes(self,video_frames, player_detections):
        output_video_frames = []
        for frame, player_dict in zip(video_frames, player_detections):
            for track_id, bbox in player_dict.items():
                self._draw_player_ring(frame, bbox, track_id)
            output_video_frames.append(frame)
        
        return output_video_frames


    

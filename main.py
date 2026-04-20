import argparse
import os
import pickle
from utils import (measure_distance,
                   draw_player_stats_frame,
                   convert_pixel_distance_to_meters,
                   prepare_video_for_opencv,
                   cleanup_temporary_video,
                   open_video_capture,
                   create_video_writer,
                   )
import constants
from trackers import PlayerTracker,BallTracker
from court_line_detector import CourtLineDetector
from mini_court import MiniCourt
import cv2
import pandas as pd
import numpy as np
from copy import deepcopy

DEFAULT_INPUT_VIDEO = "input_videos/input_video.mp4"
DEFAULT_OUTPUT_VIDEO = "output_videos/output_video.avi"
PLAYER_STUB_PATH = "tracker_stubs/player_detections.pkl"
BALL_STUB_PATH = "tracker_stubs/ball_detections.pkl"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-video", default=DEFAULT_INPUT_VIDEO, help="Path to the input tennis video.")
    parser.add_argument("--output-video", default=DEFAULT_OUTPUT_VIDEO, help="Path to the output annotated video.")
    parser.add_argument(
        "--use-stubs",
        action="store_true",
        help="Reuse tracker stub files instead of running fresh player and ball detection."
    )
    return parser.parse_args()


def load_stub(path):
    with open(path, 'rb') as f:
        return pickle.load(f)


def save_stub(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, 'wb') as f:
        pickle.dump(data, f)


def detect_video_stream(video_path, player_tracker, ball_tracker, use_stubs=False, player_stub_path=None, ball_stub_path=None):
    cap = open_video_capture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24
    player_detections = []
    ball_detections = []
    first_frame = None

    if use_stubs:
        ret, first_frame = cap.read()
        cap.release()
        if not ret:
            raise ValueError(f"No frames found in input video: {video_path}")
        player_detections = load_stub(player_stub_path)
        ball_detections = load_stub(ball_stub_path)
        return first_frame, fps, player_detections, ball_detections

    frame_num = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if first_frame is None:
                first_frame = frame.copy()

            player_detections.append(player_tracker.detect_frame(frame))
            ball_detections.append(ball_tracker.detect_frame(frame))
            frame_num += 1

            if frame_num % 500 == 0:
                print(f"Detection pass processed {frame_num} frames")

            del frame  # FIX: 流式检测时逐帧释放原始帧，避免长视频在主流程中累积占用内存
    finally:
        cap.release()
        cv2.destroyAllWindows()  # FIX: 每次视频遍历结束后释放 OpenCV 资源，避免长视频处理阶段句柄累积

    if first_frame is None:
        raise ValueError(f"No frames found in input video: {video_path}")

    if player_stub_path is not None:
        save_stub(player_stub_path, player_detections)
    if ball_stub_path is not None:
        save_stub(ball_stub_path, ball_detections)

    return first_frame, fps, player_detections, ball_detections


def build_player_stats_data(player_mini_court_detections, ball_mini_court_detections, ball_shot_frames, mini_court, fps):
    player_stats_data = [{
        'frame_num':0,
        'player_1_number_of_shots':0,
        'player_1_total_shot_speed':0,
        'player_1_last_shot_speed':0,
        'player_1_total_player_speed':0,
        'player_1_last_player_speed':0,
        'player_1_total_distance_run':0,
        'player_1_last_distance_run':0,
        'player_1_total_calories_burned':0,
        'player_1_last_calories_burned':0,
        'player_2_number_of_shots':0,
        'player_2_total_shot_speed':0,
        'player_2_last_shot_speed':0,
        'player_2_total_player_speed':0,
        'player_2_last_player_speed':0,
        'player_2_total_distance_run':0,
        'player_2_last_distance_run':0,
        'player_2_total_calories_burned':0,
        'player_2_last_calories_burned':0,
    }]

    for ball_shot_ind in range(len(ball_shot_frames)-1):
        start_frame = ball_shot_frames[ball_shot_ind]
        end_frame = ball_shot_frames[ball_shot_ind+1]
        ball_shot_time_in_seconds = (end_frame-start_frame)/fps
        if ball_shot_time_in_seconds <= 0:
            continue

        distance_covered_by_ball_pixels = measure_distance(ball_mini_court_detections[start_frame][1],
                                                           ball_mini_court_detections[end_frame][1])
        distance_covered_by_ball_meters = convert_pixel_distance_to_meters(distance_covered_by_ball_pixels,
                                                                           constants.DOUBLE_LINE_WIDTH,
                                                                           mini_court.get_width_of_mini_court())
        speed_of_ball_shot = distance_covered_by_ball_meters/ball_shot_time_in_seconds * 3.6

        player_positions = player_mini_court_detections[start_frame]
        player_shot_ball = min(player_positions.keys(),
                               key=lambda player_id: measure_distance(player_positions[player_id],
                                                                      ball_mini_court_detections[start_frame][1]))

        opponent_player_id = 1 if player_shot_ball == 2 else 2
        distance_covered_by_opponent_pixels = measure_distance(player_mini_court_detections[start_frame][opponent_player_id],
                                                               player_mini_court_detections[end_frame][opponent_player_id])
        distance_covered_by_opponent_meters = convert_pixel_distance_to_meters(distance_covered_by_opponent_pixels,
                                                                               constants.DOUBLE_LINE_WIDTH,
                                                                               mini_court.get_width_of_mini_court())
        speed_of_opponent = distance_covered_by_opponent_meters/ball_shot_time_in_seconds * 3.6

        current_player_stats= deepcopy(player_stats_data[-1])
        current_player_stats['frame_num'] = start_frame
        current_player_stats[f'player_{player_shot_ball}_number_of_shots'] += 1
        current_player_stats[f'player_{player_shot_ball}_total_shot_speed'] += speed_of_ball_shot
        current_player_stats[f'player_{player_shot_ball}_last_shot_speed'] = speed_of_ball_shot

        current_player_stats[f'player_{opponent_player_id}_total_player_speed'] += speed_of_opponent
        current_player_stats[f'player_{opponent_player_id}_last_player_speed'] = speed_of_opponent

        player_1_distance_covered_pixels = measure_distance(player_mini_court_detections[start_frame][1],
                                                            player_mini_court_detections[end_frame][1])
        player_2_distance_covered_pixels = measure_distance(player_mini_court_detections[start_frame][2],
                                                            player_mini_court_detections[end_frame][2])
        player_1_distance_covered_meters = convert_pixel_distance_to_meters(player_1_distance_covered_pixels,
                                                                            constants.DOUBLE_LINE_WIDTH,
                                                                            mini_court.get_width_of_mini_court())
        player_2_distance_covered_meters = convert_pixel_distance_to_meters(player_2_distance_covered_pixels,
                                                                            constants.DOUBLE_LINE_WIDTH,
                                                                            mini_court.get_width_of_mini_court())

        player_1_calories_burned = (player_1_distance_covered_meters / 1000) * constants.PLAYER_1_WEIGHT_KG * constants.CALORIES_PER_KM_PER_KG
        player_2_calories_burned = (player_2_distance_covered_meters / 1000) * constants.PLAYER_2_WEIGHT_KG * constants.CALORIES_PER_KM_PER_KG

        current_player_stats['player_1_total_distance_run'] += player_1_distance_covered_meters
        current_player_stats['player_1_last_distance_run'] = player_1_distance_covered_meters
        current_player_stats['player_1_total_calories_burned'] += player_1_calories_burned
        current_player_stats['player_1_last_calories_burned'] = player_1_calories_burned

        current_player_stats['player_2_total_distance_run'] += player_2_distance_covered_meters
        current_player_stats['player_2_last_distance_run'] = player_2_distance_covered_meters
        current_player_stats['player_2_total_calories_burned'] += player_2_calories_burned
        current_player_stats['player_2_last_calories_burned'] = player_2_calories_burned

        player_stats_data.append(current_player_stats)

    return player_stats_data


def build_player_stats_dataframe(player_stats_data, frame_count):
    player_stats_data_df = pd.DataFrame(player_stats_data)
    frames_df = pd.DataFrame({'frame_num': list(range(frame_count))})
    player_stats_data_df = pd.merge(frames_df, player_stats_data_df, on='frame_num', how='left')
    player_stats_data_df = player_stats_data_df.ffill()

    player_1_shots = player_stats_data_df['player_1_number_of_shots'].replace(0, np.nan)
    player_2_shots = player_stats_data_df['player_2_number_of_shots'].replace(0, np.nan)

    player_stats_data_df['player_1_average_shot_speed'] = (player_stats_data_df['player_1_total_shot_speed']/player_1_shots).fillna(0)
    player_stats_data_df['player_2_average_shot_speed'] = (player_stats_data_df['player_2_total_shot_speed']/player_2_shots).fillna(0)
    player_stats_data_df['player_1_average_player_speed'] = (player_stats_data_df['player_1_total_player_speed']/player_2_shots).fillna(0)
    player_stats_data_df['player_2_average_player_speed'] = (player_stats_data_df['player_2_total_player_speed']/player_1_shots).fillna(0)
    return player_stats_data_df


def draw_frame_annotations(frame, frame_num, player_tracker, ball_tracker, court_line_detector, mini_court,
                           court_keypoints, player_detections, ball_detections,
                           player_mini_court_detections, ball_mini_court_detections, player_stats_row):
    for track_id, bbox in player_detections[frame_num].items():
        player_tracker._draw_player_ring(frame, bbox, track_id)

    for _, bbox in ball_detections[frame_num].items():
        ball_tracker._draw_flame(frame, bbox)

    frame = court_line_detector.draw_keypoints(frame, court_keypoints)
    frame = mini_court.draw_background_rectangle(frame)
    frame = mini_court.draw_court(frame)

    for _, position in player_mini_court_detections[frame_num].items():
        x, y = position
        cv2.circle(frame, (int(x), int(y)), 5, (0,255,0), -1)

    for _, position in ball_mini_court_detections[frame_num].items():
        x, y = position
        cv2.circle(frame, (int(x), int(y)), 5, (0,255,255), -1)

    frame = draw_player_stats_frame(frame, player_stats_row)
    cv2.putText(frame, f"Frame: {frame_num}", (10,30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
    return frame


def main():
    args = parse_args()
    input_video_path = args.input_video
    output_video_path = args.output_video
    use_stubs = args.use_stubs
    player_stub_path = PLAYER_STUB_PATH if use_stubs else None
    ball_stub_path = BALL_STUB_PATH if use_stubs else None

    compatible_video_path, temp_dir = prepare_video_for_opencv(input_video_path)
    try:
        player_tracker = PlayerTracker(model_path='yolov8x')
        ball_tracker = BallTracker(model_path='models/yolo5_last.pt')

        first_frame, fps, player_detections, ball_detections = detect_video_stream(
            compatible_video_path,
            player_tracker,
            ball_tracker,
            use_stubs=use_stubs,
            player_stub_path=player_stub_path,
            ball_stub_path=ball_stub_path,
        )

        print(f"Collected detections for {len(player_detections)} frames")

        court_model_path = "models/keypoints_model.pth"
        court_line_detector = CourtLineDetector(court_model_path)
        court_keypoints = court_line_detector.predict(first_frame)

        player_detections = player_tracker.choose_and_filter_players(court_keypoints, player_detections)
        ball_detections = ball_tracker.interpolate_ball_positions(ball_detections)

        mini_court = MiniCourt(first_frame)
        ball_shot_frames = ball_tracker.get_ball_shot_frames(ball_detections)
        player_mini_court_detections, ball_mini_court_detections = mini_court.convert_bounding_boxes_to_mini_court_coordinates(
            player_detections,
            ball_detections,
            court_keypoints,
        )

        player_stats_data = build_player_stats_data(
            player_mini_court_detections,
            ball_mini_court_detections,
            ball_shot_frames,
            mini_court,
            fps,
        )
        player_stats_data_df = build_player_stats_dataframe(player_stats_data, len(player_detections))

        cap = open_video_capture(compatible_video_path)
        writer = None
        frame_num = 0
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                if writer is None:
                    writer = create_video_writer(output_video_path, fps, (frame.shape[1], frame.shape[0]))

                frame = draw_frame_annotations(
                    frame,
                    frame_num,
                    player_tracker,
                    ball_tracker,
                    court_line_detector,
                    mini_court,
                    court_keypoints,
                    player_detections,
                    ball_detections,
                    player_mini_court_detections,
                    ball_mini_court_detections,
                    player_stats_data_df.iloc[frame_num],
                )
                writer.write(frame)
                frame_num += 1

                if frame_num % 500 == 0:
                    print(f"Render pass wrote {frame_num} frames")

                del frame  # FIX: 流式写出时逐帧释放已绘制帧，避免长视频输出阶段累积占用内存
        finally:
            cap.release()
            cv2.destroyAllWindows()  # FIX: 渲染阶段结束后释放 OpenCV 资源，避免长视频处理阶段句柄累积
            if writer is not None:
                writer.release()  # FIX: 流式写出完成后显式释放 VideoWriter，避免长视频输出文件损坏或句柄泄漏

    finally:
        cleanup_temporary_video(temp_dir)

if __name__ == "__main__":
    main()

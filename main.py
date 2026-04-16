import argparse
import os
from utils import (read_video, 
                   save_video,
                   measure_distance,
                   draw_player_stats,
                   convert_pixel_distance_to_meters
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


def main():
    args = parse_args()
    input_video_path = args.input_video
    output_video_path = args.output_video
    use_stubs = args.use_stubs
    player_stub_path = PLAYER_STUB_PATH if use_stubs else None
    ball_stub_path = BALL_STUB_PATH if use_stubs else None

    video_frames = read_video(input_video_path)
    if not video_frames:
        raise ValueError(f"No frames found in input video: {input_video_path}")

    # Detect Players and Ball
    player_tracker = PlayerTracker(model_path='yolov8x')
    ball_tracker = BallTracker(model_path='models/yolo5_last.pt')

    player_detections = player_tracker.detect_frames(video_frames,
                                                     read_from_stub=use_stubs,
                                                     stub_path=player_stub_path
                                                     )
    ball_detections = ball_tracker.detect_frames(video_frames,
                                                     read_from_stub=use_stubs,
                                                     stub_path=ball_stub_path
                                                     )
    ball_detections = ball_tracker.interpolate_ball_positions(ball_detections)
    
    
    # Court Line Detector model
    court_model_path = "models/keypoints_model.pth"
    court_line_detector = CourtLineDetector(court_model_path)
    court_keypoints = court_line_detector.predict(video_frames[0])

    # choose players
    player_detections = player_tracker.choose_and_filter_players(court_keypoints, player_detections)

    # MiniCourt
    mini_court = MiniCourt(video_frames[0]) 

    # Detect ball shots
    ball_shot_frames= ball_tracker.get_ball_shot_frames(ball_detections)

    # Convert positions to mini court positions
    player_mini_court_detections, ball_mini_court_detections = mini_court.convert_bounding_boxes_to_mini_court_coordinates(player_detections, 
                                                                                                          ball_detections,
                                                                                                          court_keypoints)

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
    } ]
    
    for ball_shot_ind in range(len(ball_shot_frames)-1):
        start_frame = ball_shot_frames[ball_shot_ind]
        end_frame = ball_shot_frames[ball_shot_ind+1]
        ball_shot_time_in_seconds = (end_frame-start_frame)/24 # 24fps
        if ball_shot_time_in_seconds <= 0:
            continue

        # Get distance covered by the ball
        distance_covered_by_ball_pixels = measure_distance(ball_mini_court_detections[start_frame][1],
                                                           ball_mini_court_detections[end_frame][1])
        distance_covered_by_ball_meters = convert_pixel_distance_to_meters( distance_covered_by_ball_pixels,
                                                                           constants.DOUBLE_LINE_WIDTH,
                                                                           mini_court.get_width_of_mini_court()
                                                                           ) 

        # Speed of the ball shot in km/h
        speed_of_ball_shot = distance_covered_by_ball_meters/ball_shot_time_in_seconds * 3.6

        # player who the ball
        player_positions = player_mini_court_detections[start_frame]
        player_shot_ball = min( player_positions.keys(), key=lambda player_id: measure_distance(player_positions[player_id],
                                                                                                 ball_mini_court_detections[start_frame][1]))

        # opponent player speed
        opponent_player_id = 1 if player_shot_ball == 2 else 2
        distance_covered_by_opponent_pixels = measure_distance(player_mini_court_detections[start_frame][opponent_player_id],
                                                                player_mini_court_detections[end_frame][opponent_player_id])
        distance_covered_by_opponent_meters = convert_pixel_distance_to_meters( distance_covered_by_opponent_pixels,
                                                                           constants.DOUBLE_LINE_WIDTH,
                                                                           mini_court.get_width_of_mini_court()
                                                                           ) 

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

    player_stats_data_df = pd.DataFrame(player_stats_data)
    frames_df = pd.DataFrame({'frame_num': list(range(len(video_frames)))})
    player_stats_data_df = pd.merge(frames_df, player_stats_data_df, on='frame_num', how='left')
    player_stats_data_df = player_stats_data_df.ffill()

    player_1_shots = player_stats_data_df['player_1_number_of_shots'].replace(0, np.nan)
    player_2_shots = player_stats_data_df['player_2_number_of_shots'].replace(0, np.nan)

    player_stats_data_df['player_1_average_shot_speed'] = (player_stats_data_df['player_1_total_shot_speed']/player_1_shots).fillna(0)
    player_stats_data_df['player_2_average_shot_speed'] = (player_stats_data_df['player_2_total_shot_speed']/player_2_shots).fillna(0)
    player_stats_data_df['player_1_average_player_speed'] = (player_stats_data_df['player_1_total_player_speed']/player_2_shots).fillna(0)
    player_stats_data_df['player_2_average_player_speed'] = (player_stats_data_df['player_2_total_player_speed']/player_1_shots).fillna(0)



    # Draw output
    ## Draw Player Bounding Boxes
    output_video_frames= player_tracker.draw_bboxes(video_frames, player_detections)
    output_video_frames= ball_tracker.draw_bboxes(output_video_frames, ball_detections)

    ## Draw court Keypoints
    output_video_frames  = court_line_detector.draw_keypoints_on_video(output_video_frames, court_keypoints)

    # Draw Mini Court
    output_video_frames = mini_court.draw_mini_court(output_video_frames)
    output_video_frames = mini_court.draw_points_on_mini_court(output_video_frames,player_mini_court_detections)
    output_video_frames = mini_court.draw_points_on_mini_court(output_video_frames,ball_mini_court_detections, color=(0,255,255))    

    # Draw Player Stats
    output_video_frames = draw_player_stats(output_video_frames,player_stats_data_df)

    ## Draw frame number on top left corner
    for i, frame in enumerate(output_video_frames):
        cv2.putText(frame, f"Frame: {i}",(10,30),cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

    os.makedirs(os.path.dirname(output_video_path) or ".", exist_ok=True)
    save_video(output_video_frames, output_video_path)

if __name__ == "__main__":
    main()

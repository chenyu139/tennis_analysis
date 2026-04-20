import os
import shutil
import subprocess
import tempfile

import cv2


def _can_read_first_frame(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        cap.release()
        return False

    ret, _ = cap.read()
    cap.release()
    cv2.destroyAllWindows()
    return ret


def prepare_video_for_opencv(video_path):
    if _can_read_first_frame(video_path):
        return video_path, None

    temp_dir = tempfile.mkdtemp(prefix="tennis_analysis_")
    temp_video_path = os.path.join(
        temp_dir,
        f"{os.path.splitext(os.path.basename(video_path))[0]}_opencv.mp4"
    )
    command = [
        "ffmpeg",
        "-loglevel",
        "error",
        "-y",
        "-i",
        video_path,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        temp_video_path,
    ]
    # FIX: 当 OpenCV 无法直接解码输入视频时，先转成兼容编码，避免长视频读取阶段直接失败
    subprocess.run(command, check=True)

    if not _can_read_first_frame(temp_video_path):
        raise ValueError(f"OpenCV still cannot read transcoded video: {temp_video_path}")

    return temp_video_path, temp_dir


def cleanup_temporary_video(temp_dir):
    if temp_dir and os.path.isdir(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)


def open_video_capture(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        cap.release()
        raise ValueError(f"Could not open video: {video_path}")
    return cap


def create_video_writer(output_video_path, fps, frame_size):
    os.makedirs(os.path.dirname(output_video_path) or ".", exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # FIX: 使用更兼容长视频写出的编码格式，避免 MJPG 在长时长视频上不稳定
    out = cv2.VideoWriter(output_video_path, fourcc, fps if fps and fps > 0 else 24, frame_size)
    if not out.isOpened():
        out.release()
        raise ValueError(f"Could not open VideoWriter for output path: {output_video_path}")
    return out


def read_video(video_path):
    compatible_video_path, temp_dir = prepare_video_for_opencv(video_path)
    cap = open_video_capture(compatible_video_path)
    frames = []
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frames.append(frame)
            del frame  # FIX: 释放循环内局部帧引用，减少长视频读取时临时对象滞留
    finally:
        cap.release()
        cv2.destroyAllWindows()  # FIX: 释放 OpenCV 相关资源，避免长视频处理后残留句柄
        cleanup_temporary_video(temp_dir)
    return frames


def save_video(output_video_frames, output_video_path, fps=24):
    out = create_video_writer(
        output_video_path,
        fps,
        (output_video_frames[0].shape[1], output_video_frames[0].shape[0]),
    )
    try:
        for frame in output_video_frames:
            out.write(frame)
            del frame  # FIX: 释放循环内局部帧引用，减少长视频写出时临时对象滞留
    finally:
        out.release()
        cv2.destroyAllWindows()  # FIX: 确保写出完成后释放 OpenCV 资源

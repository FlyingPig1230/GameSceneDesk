import cv2
from pathlib import Path
import argparse


def extract_frames(video_path, output_dir, interval_seconds=2):
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not video_path.exists():
        raise FileNotFoundError(f"视频不存在: {video_path}")

    cap = cv2.VideoCapture(str(video_path))

    if not cap.isOpened():
        raise RuntimeError("无法打开视频文件")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        raise RuntimeError("无法读取视频 FPS")

    frame_interval = int(fps * interval_seconds)

    frame_index = 0
    saved_count = 0

    video_name = video_path.stem

    while True:
        success, frame = cap.read()
        if not success:
            break

        if frame_index % frame_interval == 0:
            output_path = output_dir / f"{video_name}_{saved_count:04d}.jpg"
            cv2.imwrite(str(output_path), frame)
            saved_count += 1

        frame_index += 1

    cap.release()

    print(f"完成：从 {video_path.name} 抽取了 {saved_count} 张图片")
    print(f"保存位置：{output_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从游戏视频中抽取训练截图")

    parser.add_argument(
        "--video",
        required=True,
        help="视频文件路径，例如 data/raw_videos/gameplay.mp4"
    )

    parser.add_argument(
        "--output",
        default="data/frames",
        help="输出截图文件夹，默认 data/frames"
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=2,
        help="每隔几秒抽一张，默认 2 秒"
    )

    args = parser.parse_args()

    extract_frames(
        video_path=args.video,
        output_dir=args.output,
        interval_seconds=args.interval
    )
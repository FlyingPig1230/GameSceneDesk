import argparse

from map_config import (
    canonical_map_name,
    relevance_profile_path
)
from relevance import build_relevance_profile


def show_progress(label, current, total):
    print(
        f"{label}：{current}/{total}",
        flush=True
    )


def main():
    parser = argparse.ArgumentParser(
        description="建立地图图片相关性过滤器"
    )
    parser.add_argument(
        "--map",
        default="Ascent",
        dest="map_name",
        help="地图名称，例如 Ascent 或 Split"
    )
    args = parser.parse_args()
    map_name = canonical_map_name(args.map_name)

    print(f"正在建立 {map_name} 图片相关性过滤器……")
    profile = build_relevance_profile(
        map_name=map_name,
        progress_callback=show_progress
    )
    print(
        f"过滤器已保存："
        f"{relevance_profile_path(map_name)}"
    )
    print(
        f"{map_name} 验证接受率："
        f"{profile['validation_positive_accept_rate'] * 100:.2f}%"
    )
    print(
        "无关图片验证拒绝率："
        f"{profile['validation_negative_reject_rate'] * 100:.2f}%"
    )
    print(
        "相关性阈值："
        f"{profile['gate_threshold']:.4f} | "
        "特征相似度阈值："
        f"{profile['similarity_threshold']:.4f}"
    )


if __name__ == "__main__":
    main()

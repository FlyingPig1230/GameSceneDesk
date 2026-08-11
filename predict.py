from pathlib import Path
import argparse

from map_config import AUTO_MAP, supported_map_names
from model_service import ModelService


def predict(image_path: Path, map_name: str = AUTO_MAP):
    service = ModelService()
    result = service.predict(
        str(image_path),
        top_k=3,
        map_name=map_name
    )

    print(f"识别地图：{result['map_name']}")

    if not result.get("is_relevant", True):
        print("判断：无法确认这是受支持的地图截图")
        print(
            "原因："
            f"{result.get('rejection_reason', '未通过相关性检查')}"
        )
        return

    print("\n预测结果：")

    for rank, prediction in enumerate(
        result["top_predictions"],
        start=1
    ):
        print(
            f"{rank}. {prediction['class_name']} - "
            f"{prediction['confidence'] * 100:.2f}%"
        )

    print("\n最终判断：")
    print(f"地图：{result['map_name']}")
    print(f"区域：{result['best_class']}")
    print(
        "可信度："
        f"{result['best_confidence'] * 100:.2f}%"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="识别 Valorant 地图及区域"
    )
    parser.add_argument(
        "image",
        help="测试图片路径"
    )
    parser.add_argument(
        "--map",
        default=AUTO_MAP,
        choices=[AUTO_MAP, *supported_map_names()],
        help="自动识别地图，或锁定 Ascent / Split"
    )
    args = parser.parse_args()
    predict(
        image_path=Path(args.image),
        map_name=args.map
    )

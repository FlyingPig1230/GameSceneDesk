from collections import defaultdict
from pathlib import Path
import argparse
import csv
import json

import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torchvision import datasets, models, transforms

from map_config import (
    area_model_path,
    canonical_map_name,
    evaluation_dir,
    test_dir
)

BATCH_SIZE = 8
PROGRESS_PREFIX = "__EVALUATION_PROGRESS__"


def emit_progress(**payload):
    print(
        f"{PROGRESS_PREFIX}{json.dumps(payload, ensure_ascii=False)}",
        flush=True
    )


def get_device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")

    if torch.cuda.is_available():
        return torch.device("cuda")

    return torch.device("cpu")


def get_confidence_group(confidence: float) -> str:
    percentage = confidence * 100

    if percentage >= 95:
        return "95_to_100"

    if percentage >= 75:
        return "75_to_95"

    if percentage >= 50:
        return "50_to_75"

    if percentage >= 25:
        return "25_to_50"

    return "0_to_25"


def load_model(
    model_path: Path,
    device: torch.device
):
    if not model_path.exists():
        raise FileNotFoundError(
            f"找不到模型：{model_path}"
        )

    checkpoint = torch.load(
        model_path,
        map_location=device,
        weights_only=False
    )

    class_names = checkpoint["class_names"]
    image_size = checkpoint.get("image_size", 224)

    num_classes = checkpoint.get(
        "num_classes",
        len(class_names)
    )

    model = models.mobilenet_v3_small(
        weights=None
    )

    input_features = model.classifier[3].in_features

    model.classifier[3] = nn.Linear(
        input_features,
        num_classes
    )

    model.load_state_dict(
        checkpoint["model_state_dict"]
    )

    model = model.to(device)
    model.eval()

    return model, class_names, image_size


def evaluate(map_name="Ascent"):
    map_name = canonical_map_name(map_name)
    test_directory = test_dir(map_name)
    model_path = area_model_path(map_name)
    output_directory = evaluation_dir(map_name)
    report_path = output_directory / "report.csv"
    summary_path = output_directory / "summary.json"

    if not test_directory.exists():
        raise FileNotFoundError(
            f"找不到测试目录：{test_directory}"
        )

    output_directory.mkdir(
        parents=True,
        exist_ok=True
    )

    device = get_device()
    print(f"使用设备：{device}")
    emit_progress(
        stage="setup",
        percent=0,
        message="正在载入模型"
    )

    model, model_classes, image_size = load_model(
        model_path,
        device
    )
    emit_progress(
        stage="model_loaded",
        percent=8,
        message="模型已载入，正在准备测试集"
    )

    transform = transforms.Compose([
        transforms.Resize(
            (image_size, image_size)
        ),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225]
        )
    ])

    test_dataset = datasets.ImageFolder(
        test_directory,
        transform=transform
    )

    if len(test_dataset) == 0:
        raise RuntimeError("测试集中没有图片。")

    unknown_classes = [
        class_name
        for class_name in test_dataset.classes
        if class_name not in model_classes
    ]

    if unknown_classes:
        raise RuntimeError(
            "测试集中存在模型没有训练过的类别："
            + ", ".join(unknown_classes)
        )

    test_loader = DataLoader(
        test_dataset,
        batch_size=BATCH_SIZE,
        shuffle=False,
        num_workers=0
    )
    total_batches = len(test_loader)
    emit_progress(
        stage="ready",
        percent=12,
        message=f"测试集已载入，共 {len(test_dataset)} 张图片"
    )

    total = 0
    correct = 0
    sample_index = 0

    class_total = defaultdict(int)
    class_correct = defaultdict(int)

    confidence_counts = {
        "95_to_100": 0,
        "75_to_95": 0,
        "50_to_75": 0,
        "25_to_50": 0,
        "0_to_25": 0
    }

    report_rows = []

    with torch.no_grad():
        for batch_number, (images, dataset_labels) in enumerate(
            test_loader,
            start=1
        ):
            images = images.to(device)

            outputs = model(images)

            probabilities = torch.softmax(
                outputs,
                dim=1
            )

            confidences, predictions = torch.max(
                probabilities,
                dim=1
            )

            for batch_index in range(
                len(dataset_labels)
            ):
                dataset_label = int(
                    dataset_labels[batch_index].item()
                )

                true_name = test_dataset.classes[
                    dataset_label
                ]

                predicted_index = int(
                    predictions[batch_index].item()
                )

                predicted_name = model_classes[
                    predicted_index
                ]

                confidence = float(
                    confidences[batch_index].item()
                )

                image_path = Path(
                    test_dataset.samples[
                        sample_index
                    ][0]
                ).resolve()

                sample_index += 1

                is_correct = (
                    true_name == predicted_name
                )

                confidence_group = (
                    get_confidence_group(confidence)
                )

                total += 1
                class_total[true_name] += 1
                confidence_counts[
                    confidence_group
                ] += 1

                if is_correct:
                    correct += 1
                    class_correct[true_name] += 1

                report_rows.append({
                    "map_name": map_name,
                    "image": str(image_path),
                    "true_class": true_name,
                    "predicted_class": predicted_name,
                    "confidence": round(
                        confidence * 100,
                        2
                    ),
                    "correct": is_correct,
                    "confidence_group": (
                        confidence_group
	                    )
	                })

            emit_progress(
                stage="batch_complete",
                current=batch_number,
                total=total_batches,
                percent=12 + int(
                    batch_number / total_batches * 74
                ),
                message=(
                    f"正在评估 {batch_number}/{total_batches}"
                )
            )

    with report_path.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "map_name",
                "image",
                "true_class",
                "predicted_class",
                "confidence",
                "correct",
                "confidence_group"
            ]
        )

        writer.writeheader()
        writer.writerows(report_rows)

    overall_accuracy = (
        correct / total
        if total > 0
        else 0
    )

    class_results = {}

    for class_name in model_classes:
        count = class_total[class_name]
        correct_count = class_correct[class_name]

        accuracy = (
            correct_count / count
            if count > 0
            else None
        )

        class_results[class_name] = {
            "total": count,
            "correct": correct_count,
            "accuracy": (
                round(accuracy * 100, 2)
                if accuracy is not None
                else None
            )
        }

    summary = {
        "map_name": map_name,
        "test_images": total,
        "correct": correct,
        "wrong": total - correct,
        "accuracy": round(
            overall_accuracy * 100,
            2
        ),
        "confidence_distribution": (
            confidence_counts
        ),
        "class_results": class_results
    }

    with summary_path.open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            summary,
            file,
            ensure_ascii=False,
            indent=2
        )
    emit_progress(
        stage="summary_written",
        percent=96,
        message="评估摘要已生成"
    )

    print("\n============================")
    print("整体测试结果")
    print("============================")
    print(f"测试图片：{total}")
    print(f"正确数量：{correct}")
    print(f"错误数量：{total - correct}")
    print(
        f"整体准确率："
        f"{overall_accuracy * 100:.2f}%"
    )

    print("\n置信度分布：")

    for group, count in confidence_counts.items():
        print(f"{group}: {count}")

    print("\n各区域准确率：")

    for class_name, result in class_results.items():
        if result["accuracy"] is None:
            print(f"{class_name}: 没有测试图片")
        else:
            print(
                f"{class_name}: "
                f"{result['correct']}/"
                f"{result['total']} "
                f"({result['accuracy']:.2f}%)"
            )

    print(f"\nCSV：{report_path}")
    print(f"摘要：{summary_path}")
    emit_progress(
        stage="complete",
        percent=100,
        message=(
            f"评估完成 · 准确率 "
            f"{overall_accuracy * 100:.2f}%"
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="评估地图区域识别模型"
    )
    parser.add_argument(
        "--map",
        default="Ascent",
        dest="map_name",
        help="地图名称，例如 Ascent 或 Split"
    )
    arguments = parser.parse_args()
    evaluate(arguments.map_name)

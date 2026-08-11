from pathlib import Path
import argparse
from collections import Counter
import json
import random

import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import (
    DataLoader,
    Dataset,
    Subset
)
from torchvision import datasets, models, transforms
from torchvision.models import (
    MobileNet_V3_Small_Weights
)

from relevance import build_relevance_profile
from map_config import (
    area_model_path,
    canonical_map_name,
    classes_path,
    test_dir,
    train_dir
)


FEEDBACK_LOG = Path("data/feedback/feedback.jsonl")

MODEL_DIR = Path("models")

IMAGE_SIZE = 224
BATCH_SIZE = 4
EPOCHS = 10
LEARNING_RATE = 0.0005
QUICK_BATCH_SIZE = 16
QUICK_EPOCHS = 3
QUICK_LEARNING_RATE = 0.0002
QUICK_FEEDBACK_REPEAT = 8
VALIDATION_RATIO = 0.2
RANDOM_SEED = 42
PROGRESS_PREFIX = "__TRAIN_PROGRESS__"

MODEL_DIR.mkdir(
    parents=True,
    exist_ok=True
)


def emit_progress(**payload):
    print(
        f"{PROGRESS_PREFIX}{json.dumps(payload, ensure_ascii=False)}",
        flush=True
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="训练 Valorant 地图区域识别模型"
    )
    parser.add_argument(
        "--map",
        default="Ascent",
        dest="map_name",
        help="地图名称，例如 Ascent 或 Split"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="使用现有模型做少量快速微调"
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=None,
        help="训练轮数"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="每批图片数量"
    )
    parser.add_argument(
        "--learning-rate",
        type=float,
        default=None,
        help="学习率"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="从现有模型继续训练"
    )
    parser.add_argument(
        "--freeze-features",
        action="store_true",
        help="冻结特征层，只微调分类层"
    )
    parser.add_argument(
        "--feedback-repeat",
        type=int,
        default=None,
        help="训练时重复反馈样本的次数"
    )
    parser.add_argument(
        "--include-test-feedback",
        action="store_true",
        help="允许使用来自 data/test 的反馈记录"
    )
    return parser.parse_args()


def get_device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")

    if torch.cuda.is_available():
        return torch.device("cuda")

    return torch.device("cpu")


def is_inside_directory(
    path: Path,
    directory: Path
) -> bool:
    try:
        path.resolve().relative_to(
            directory.resolve()
        )
        return True
    except ValueError:
        return False


def load_feedback_samples(
    feedback_log: Path,
    class_to_index: dict[str, int],
    map_name: str,
    test_directory: Path,
    include_test_feedback: bool = False
) -> list[tuple[Path, int]]:
    samples = []
    seen_paths = set()
    included_test_count = 0

    if not feedback_log.exists():
        return samples

    with feedback_log.open(
        "r",
        encoding="utf-8"
    ) as file:
        for line_number, line in enumerate(
            file,
            start=1
        ):
            line = line.strip()

            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                print(
                    f"跳过损坏反馈记录："
                    f"第 {line_number} 行"
                )
                continue

            if not record.get("approved", True):
                continue

            record_map = record.get(
                "map_name",
                "Ascent"
            )

            try:
                record_map = canonical_map_name(record_map)
            except ValueError:
                continue

            if record_map != map_name:
                continue

            image_value = (
                record.get("training_image")
                or record.get("saved_image")
                or record.get("image")
                or record.get("source_image")
            )
            correct_class = record.get(
                "correct_class"
            )

            if not image_value or not correct_class:
                continue

            image_path = Path(
                image_value
            ).resolve()

            if not image_path.exists():
                print(
                    f"跳过不存在的反馈图片："
                    f"{image_path}"
                )
                continue

            # 固定测试集绝不能加入训练
            if is_inside_directory(
                image_path,
                test_directory
            ):
                if not include_test_feedback:
                    print(
                        f"跳过测试集反馈："
                        f"{image_path.name}"
                    )
                    continue

                included_test_count += 1

            if correct_class not in class_to_index:
                print(
                    f"跳过未知类别："
                    f"{correct_class}"
                )
                continue

            unique_key = (
                str(image_path),
                correct_class
            )

            if unique_key in seen_paths:
                continue

            seen_paths.add(unique_key)

            samples.append((
                image_path,
                class_to_index[correct_class]
            ))

    if included_test_count:
        print(
            f"已包含测试目录反馈："
            f"{included_test_count} 条"
        )

    return samples


class CombinedImageDataset(Dataset):
    def __init__(
        self,
        base_dataset,
        feedback_samples,
        transform,
        feedback_repeat=1
    ):
        self.base_dataset = base_dataset
        self.feedback_samples = feedback_samples
        self.transform = transform
        self.feedback_repeat = max(
            1,
            int(feedback_repeat)
        )

    def __len__(self):
        return (
            len(self.base_dataset)
            + len(self.feedback_samples)
            * self.feedback_repeat
        )

    def __getitem__(self, index):
        if index < len(self.base_dataset):
            image_path, label = (
                self.base_dataset.samples[index]
            )

            image = Image.open(
                image_path
            ).convert("RGB")

            return self.transform(image), label

        feedback_index = (
            index - len(self.base_dataset)
        ) % len(self.feedback_samples)

        image_path, label = self.feedback_samples[
            feedback_index
        ]

        image = Image.open(
            image_path
        ).convert("RGB")

        return self.transform(image), label


def build_model(
    class_names,
    device,
    model_path,
    resume=False,
    freeze_features=False
):
    weights = (
        MobileNet_V3_Small_Weights.DEFAULT
    )

    model = models.mobilenet_v3_small(
        weights=weights
    )

    input_features = (
        model.classifier[3].in_features
    )

    model.classifier[3] = nn.Linear(
        input_features,
        len(class_names)
    )

    if resume:
        if model_path.exists():
            checkpoint = torch.load(
                model_path,
                map_location="cpu",
                weights_only=False
            )
            checkpoint_classes = checkpoint.get(
                "class_names",
                []
            )

            if list(checkpoint_classes) == list(class_names):
                model.load_state_dict(
                    checkpoint["model_state_dict"]
                )
                print(
                    f"已加载现有模型继续训练："
                    f"{model_path}"
                )
            else:
                print(
                    "现有模型类别不匹配，改用预训练模型重新开始。"
                )
        else:
            print(
                "未找到现有模型，改用预训练模型重新开始。"
            )

    if freeze_features:
        for parameter in model.features.parameters():
            parameter.requires_grad = False

        print("已冻结特征层，只微调分类层。")

    return model.to(device)


def main():
    args = parse_args()
    map_name = canonical_map_name(args.map_name)
    data_directory = train_dir(map_name)
    test_directory = test_dir(map_name).resolve()
    model_path = area_model_path(map_name)
    class_list_path = classes_path(map_name)

    if not data_directory.exists():
        raise FileNotFoundError(
            f"找不到训练目录：{data_directory}"
        )

    epochs = (
        args.epochs
        if args.epochs is not None
        else QUICK_EPOCHS if args.quick else EPOCHS
    )
    batch_size = (
        args.batch_size
        if args.batch_size is not None
        else QUICK_BATCH_SIZE if args.quick else BATCH_SIZE
    )
    learning_rate = (
        args.learning_rate
        if args.learning_rate is not None
        else QUICK_LEARNING_RATE
        if args.quick
        else LEARNING_RATE
    )
    feedback_repeat = (
        args.feedback_repeat
        if args.feedback_repeat is not None
        else QUICK_FEEDBACK_REPEAT
        if args.quick
        else 1
    )
    resume = args.resume or args.quick
    freeze_features = (
        args.freeze_features
        or args.quick
    )
    include_test_feedback = (
        args.include_test_feedback
        or args.quick
    )

    epochs = max(1, int(epochs))
    batch_size = max(1, int(batch_size))
    feedback_repeat = max(
        1,
        int(feedback_repeat)
    )

    device = get_device()
    print(f"使用设备：{device}")
    print(f"训练地图：{map_name}")
    print(
        "训练模式：快速微调"
        if args.quick
        else "训练模式：完整训练"
    )
    print(f"训练轮数：{epochs}")
    print(f"Batch Size：{batch_size}")
    print(f"学习率：{learning_rate}")
    emit_progress(
        stage="setup",
        current=0,
        total=epochs,
        percent=0,
        message="正在准备训练数据"
    )

    base_dataset = datasets.ImageFolder(
        data_directory
    )

    class_names = base_dataset.classes
    class_to_index = base_dataset.class_to_idx

    if len(class_names) < 2:
        raise RuntimeError(
            "至少需要两个训练类别。"
        )

    feedback_samples = load_feedback_samples(
        FEEDBACK_LOG,
        class_to_index,
        map_name,
        test_directory,
        include_test_feedback
    )

    print(f"原训练图片：{len(base_dataset)}")
    print(f"有效反馈图片：{len(feedback_samples)}")
    print(f"反馈重复次数：{feedback_repeat}")
    print(
        f"总训练图片："
        f"{len(base_dataset) + len(feedback_samples) * feedback_repeat}"
    )

    feedback_counter = Counter(
        class_names[label]
        for _, label in feedback_samples
    )

    if feedback_counter:
        print("反馈类别数量：")

        for class_name, count in sorted(
            feedback_counter.items()
        ):
            print(f"  {class_name}: {count}")

    emit_progress(
        stage="ready",
        current=0,
        total=epochs,
        percent=0,
        message=(
            f"已载入 {len(feedback_samples)} 条反馈，"
            f"共 {len(base_dataset) + len(feedback_samples) * feedback_repeat} 张训练图"
        )
    )

    train_transform = transforms.Compose([
        transforms.Resize(
            (IMAGE_SIZE, IMAGE_SIZE)
        ),
        transforms.ColorJitter(
            brightness=0.15,
            contrast=0.15,
            saturation=0.10
        ),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225]
        )
    ])

    validation_transform = transforms.Compose([
        transforms.Resize(
            (IMAGE_SIZE, IMAGE_SIZE)
        ),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225]
        )
    ])

    train_full_dataset = CombinedImageDataset(
        base_dataset,
        feedback_samples,
        train_transform,
        feedback_repeat
    )

    validation_full_dataset = (
        CombinedImageDataset(
            base_dataset,
            feedback_samples,
            validation_transform,
            feedback_repeat
        )
    )

    total_size = len(train_full_dataset)

    if total_size < 2:
        raise RuntimeError("训练图片数量不足。")

    indices = list(range(total_size))

    random.seed(RANDOM_SEED)
    random.shuffle(indices)

    validation_size = max(
        1,
        int(total_size * VALIDATION_RATIO)
    )

    train_size = (
        total_size - validation_size
    )

    if train_size < 1:
        raise RuntimeError(
            "无法划分训练集和验证集。"
        )

    validation_indices = indices[
        :validation_size
    ]

    train_indices = indices[
        validation_size:
    ]

    train_dataset = Subset(
        train_full_dataset,
        train_indices
    )

    validation_dataset = Subset(
        validation_full_dataset,
        validation_indices
    )

    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=0
    )

    validation_loader = DataLoader(
        validation_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=0
    )

    model = build_model(
        class_names,
        device,
        model_path,
        resume=resume,
        freeze_features=freeze_features
    )

    base_class_counts = Counter(
        label
        for _, label in base_dataset.samples
    )
    effective_class_counts = []

    for class_index in range(len(class_names)):
        feedback_count = sum(
            1
            for _, label in feedback_samples
            if label == class_index
        )
        effective_class_counts.append(
            base_class_counts[class_index]
            + feedback_count * feedback_repeat
        )

    class_weights = torch.tensor([
        1.0 / max(count, 1) ** 0.5
        for count in effective_class_counts
    ], dtype=torch.float32)
    class_weights = (
        class_weights / class_weights.mean()
    ).to(device)
    criterion = nn.CrossEntropyLoss(
        weight=class_weights
    )
    print("已启用类别平衡权重。")

    trainable_parameters = [
        parameter for parameter in model.parameters()
        if parameter.requires_grad
    ]

    if not trainable_parameters:
        raise RuntimeError(
            "没有可训练参数。"
        )

    optimizer = torch.optim.AdamW(
        trainable_parameters,
        lr=learning_rate
    )

    best_validation_accuracy = -1.0

    for epoch in range(epochs):
        emit_progress(
            stage="epoch_start",
            current=epoch,
            total=epochs,
            percent=int(epoch / epochs * 90),
            message=f"正在训练 Epoch {epoch + 1}/{epochs}"
        )
        model.train()

        train_loss_total = 0.0
        train_correct = 0
        train_total = 0

        for images, labels in train_loader:
            images = images.to(device)
            labels = labels.to(device)

            optimizer.zero_grad()

            outputs = model(images)
            loss = criterion(outputs, labels)

            loss.backward()
            optimizer.step()

            train_loss_total += (
                loss.item() * images.size(0)
            )

            predictions = outputs.argmax(
                dim=1
            )

            train_correct += (
                predictions == labels
            ).sum().item()

            train_total += labels.size(0)

        model.eval()

        validation_loss_total = 0.0
        validation_correct = 0
        validation_total = 0

        with torch.no_grad():
            for images, labels in validation_loader:
                images = images.to(device)
                labels = labels.to(device)

                outputs = model(images)
                loss = criterion(outputs, labels)

                validation_loss_total += (
                    loss.item()
                    * images.size(0)
                )

                predictions = outputs.argmax(
                    dim=1
                )

                validation_correct += (
                    predictions == labels
                ).sum().item()

                validation_total += labels.size(0)

        train_loss = (
            train_loss_total / train_total
        )

        train_accuracy = (
            train_correct / train_total
        )

        validation_loss = (
            validation_loss_total
            / validation_total
        )

        validation_accuracy = (
            validation_correct
            / validation_total
        )

        print(
            f"\nEpoch {epoch + 1}/{epochs}"
        )

        print(
            f"训练 Loss: {train_loss:.4f} | "
            f"训练准确率: "
            f"{train_accuracy * 100:.2f}%"
        )

        print(
            f"验证 Loss: "
            f"{validation_loss:.4f} | "
            f"验证准确率: "
            f"{validation_accuracy * 100:.2f}%"
        )

        emit_progress(
            stage="epoch_complete",
            current=epoch + 1,
            total=epochs,
            percent=int((epoch + 1) / epochs * 90),
            train_accuracy=round(
                train_accuracy * 100,
                2
            ),
            validation_accuracy=round(
                validation_accuracy * 100,
                2
            ),
            message=(
                f"Epoch {epoch + 1}/{epochs} 完成 · "
                f"验证 {validation_accuracy * 100:.2f}%"
            )
        )

        if (
            validation_accuracy
            > best_validation_accuracy
        ):
            best_validation_accuracy = (
                validation_accuracy
            )

            torch.save({
                "model_state_dict": (
                    model.state_dict()
                ),
                "class_names": class_names,
                "map_name": map_name,
                "image_size": IMAGE_SIZE,
                "num_classes": len(
                    class_names
                ),
                "feedback_samples": len(
                    feedback_samples
                ),
                "feedback_repeat": feedback_repeat,
                "quick_mode": bool(args.quick)
            }, model_path)

            print(
                f"已保存最佳模型："
                f"{model_path}"
            )

    with class_list_path.open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            class_names,
            file,
            ensure_ascii=False,
            indent=2
        )

    print("\n正在更新无关图片过滤器……")
    emit_progress(
        stage="relevance_profile",
        current=0,
        total=1,
        percent=92,
        message="正在更新无关图片过滤器"
    )

    def show_relevance_progress(label, current, total):
        phase_start = 92 if "正样本" in label else 96
        phase_span = 3 if "正样本" in label else 2
        percent = phase_start + int(
            current / max(total, 1) * phase_span
        )
        emit_progress(
            stage="relevance_profile",
            current=current,
            total=total,
            percent=percent,
            message=f"更新过滤器 · {label}"
        )

    try:
        relevance_profile = build_relevance_profile(
            map_name=map_name,
            model_path=model_path,
            progress_callback=show_relevance_progress
        )
        print(
            "过滤器更新完成 · "
            f"{map_name} 接受率 "
            f"{relevance_profile['validation_positive_accept_rate'] * 100:.2f}% · "
            "无关图片拒绝率 "
            f"{relevance_profile['validation_negative_reject_rate'] * 100:.2f}%"
        )
    except Exception as error:
        print(f"过滤器更新失败：{error}")

    print("\n训练完成。")
    print(
        f"最佳验证准确率："
        f"{best_validation_accuracy * 100:.2f}%"
    )
    emit_progress(
        stage="complete",
        current=epochs,
        total=epochs,
        percent=100,
        validation_accuracy=round(
            best_validation_accuracy * 100,
            2
        ),
        message=(
            f"训练完成 · 最佳验证 "
            f"{best_validation_accuracy * 100:.2f}%"
        )
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image, ImageDraw
from torchvision import models, transforms

from map_config import (
    area_model_path,
    canonical_map_name,
    feedback_dir,
    frames_dir,
    relevance_profile_path,
    supported_map_names,
    test_dir,
    train_dir
)


MODEL_PATH = area_model_path("Ascent")
PROFILE_PATH = relevance_profile_path("Ascent")
POSITIVE_DIRS = (
    train_dir("Ascent"),
    feedback_dir("Ascent"),
    test_dir("Ascent")
)
NEGATIVE_DIRS = (
    train_dir("Split"),
    frames_dir("Split"),
    Path("data/rejection/negative"),
    Path("data/rejection/bootstrap"),
    Path("assets"),
    Path("data/blueprints")
)
IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".webp"
}
PROFILE_VERSION = 1
RANDOM_SEED = 42
SYNTHETIC_NEGATIVE_DIR = Path("data/rejection/bootstrap")


def default_positive_dirs(map_name):
    map_name = canonical_map_name(map_name)
    return (
        train_dir(map_name),
        feedback_dir(map_name),
        test_dir(map_name)
    )


def default_negative_dirs(map_name):
    map_name = canonical_map_name(map_name)
    directories = [
        Path("data/rejection/negative"),
        SYNTHETIC_NEGATIVE_DIR,
        Path("assets"),
        Path("data/blueprints")
    ]

    for other_map in supported_map_names():
        if other_map == map_name:
            continue

        directories.extend([
            train_dir(other_map),
            test_dir(other_map),
            frames_dir(other_map)
        ])

    return tuple(directories)


def model_fingerprint(model_path: Path) -> str:
    digest = hashlib.sha256()

    with model_path.open("rb") as model_file:
        for chunk in iter(
            lambda: model_file.read(1024 * 1024),
            b""
        ):
            digest.update(chunk)

    return digest.hexdigest()


def extract_model_embedding(model, image_tensor):
    features = model.features(image_tensor)
    pooled = model.avgpool(features)
    flattened = torch.flatten(pooled, 1)
    embedding = model.classifier[0](flattened)
    embedding = model.classifier[1](embedding)
    return F.normalize(embedding, dim=1)


def forward_with_embedding(model, image_tensor):
    features = model.features(image_tensor)
    pooled = model.avgpool(features)
    flattened = torch.flatten(pooled, 1)
    hidden = model.classifier[0](flattened)
    hidden = model.classifier[1](hidden)
    embedding = F.normalize(hidden, dim=1)
    logits = model.classifier[3](
        model.classifier[2](hidden)
    )
    return logits, embedding


def _load_model(model_path, device):
    checkpoint = torch.load(
        model_path,
        map_location=device,
        weights_only=False
    )
    class_names = list(checkpoint["class_names"])
    image_size = int(checkpoint.get("image_size", 224))

    model = models.mobilenet_v3_small(weights=None)
    input_features = model.classifier[3].in_features
    model.classifier[3] = nn.Linear(
        input_features,
        len(class_names)
    )
    model.load_state_dict(checkpoint["model_state_dict"])
    model = model.to(device)
    model.eval()
    return model, class_names, image_size


def _image_transform(image_size):
    return transforms.Compose([
        transforms.Resize((image_size, image_size)),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225]
        )
    ])


def _collect_labeled_paths(roots, class_names):
    samples = []

    for root in roots:
        if not root.exists():
            continue

        for class_name in class_names:
            class_dir = root / class_name

            if not class_dir.exists():
                continue

            for path in class_dir.rglob("*"):
                if (
                    path.is_file()
                    and path.suffix.lower() in IMAGE_EXTENSIONS
                ):
                    samples.append((path.resolve(), class_name))

    return samples


def _collect_unlabeled_paths(roots):
    paths = []
    seen = set()

    for root in roots:
        if not root.exists():
            continue

        for path in root.rglob("*"):
            if (
                not path.is_file()
                or path.suffix.lower() not in IMAGE_EXTENSIONS
            ):
                continue

            resolved = path.resolve()

            if resolved in seen:
                continue

            seen.add(resolved)
            paths.append(resolved)

    return paths


def _ensure_synthetic_negatives(root):
    root.mkdir(parents=True, exist_ok=True)
    randomizer = random.Random(20260804)
    size = 256

    solid_colors = [
        (0, 0, 0),
        (255, 255, 255),
        (230, 40, 50),
        (30, 100, 220),
        (40, 190, 120),
        (245, 190, 40),
        (110, 65, 180),
        (130, 130, 130)
    ]

    for index, color in enumerate(solid_colors):
        path = root / f"solid_{index:02d}.png"

        if not path.exists():
            Image.new("RGB", (size, size), color).save(path)

    for index in range(10):
        path = root / f"noise_{index:02d}.png"

        if path.exists():
            continue

        image = Image.frombytes(
            "RGB",
            (size, size),
            randomizer.randbytes(size * size * 3)
        )
        image.save(path)

    for index in range(12):
        path = root / f"stripes_{index:02d}.png"

        if path.exists():
            continue

        background = tuple(
            randomizer.randrange(20, 236)
            for _ in range(3)
        )
        foreground = tuple(
            randomizer.randrange(20, 236)
            for _ in range(3)
        )
        image = Image.new("RGB", (size, size), background)
        draw = ImageDraw.Draw(image)
        stripe_width = randomizer.randrange(6, 28)

        for offset in range(-size, size * 2, stripe_width * 2):
            draw.line(
                (offset, 0, offset + size, size),
                fill=foreground,
                width=stripe_width
            )

        image.save(path)

    for index in range(10):
        path = root / f"checker_{index:02d}.png"

        if path.exists():
            continue

        colors = [
            tuple(
                randomizer.randrange(10, 246)
                for _ in range(3)
            )
            for _ in range(2)
        ]
        image = Image.new("RGB", (size, size), colors[0])
        draw = ImageDraw.Draw(image)
        cell_size = randomizer.randrange(12, 52)

        for row, y in enumerate(range(0, size, cell_size)):
            for column, x in enumerate(
                range(0, size, cell_size)
            ):
                color = colors[(row + column) % 2]
                draw.rectangle(
                    (x, y, x + cell_size, y + cell_size),
                    fill=color
                )

        image.save(path)

    for index in range(18):
        path = root / f"geometry_{index:02d}.png"

        if path.exists():
            continue

        background = (
            (255, 255, 255)
            if index % 2 == 0
            else tuple(
                randomizer.randrange(15, 65)
                for _ in range(3)
            )
        )
        image = Image.new("RGB", (size, size), background)
        draw = ImageDraw.Draw(image)

        for _ in range(randomizer.randrange(4, 10)):
            color = tuple(
                randomizer.randrange(30, 241)
                for _ in range(3)
            )
            left = randomizer.randrange(0, size - 60)
            top = randomizer.randrange(0, size - 60)
            right = randomizer.randrange(left + 30, size)
            bottom = randomizer.randrange(top + 30, size)
            width = randomizer.randrange(3, 14)

            if randomizer.random() < 0.5:
                draw.rectangle(
                    (left, top, right, bottom),
                    outline=color,
                    width=width
                )
            else:
                draw.ellipse(
                    (left, top, right, bottom),
                    outline=color,
                    width=width
                )

        image.save(path)


def _balanced_positive_sample(
    samples,
    class_names,
    max_per_class,
    randomizer
):
    by_class = {
        class_name: []
        for class_name in class_names
    }

    for path, class_name in samples:
        by_class[class_name].append(path)

    selected = []

    for class_name in class_names:
        paths = by_class[class_name]
        randomizer.shuffle(paths)

        for path in paths[:max_per_class]:
            selected.append((path, class_name))

    randomizer.shuffle(selected)
    return selected


def _extract_samples(
    model,
    transform,
    samples,
    device,
    batch_size=24,
    progress_callback=None,
    progress_label=""
):
    embeddings = []
    labels = []
    total = len(samples)

    for start in range(0, total, batch_size):
        tensors = []
        batch_labels = []

        for path, label in samples[start:start + batch_size]:
            try:
                with Image.open(path) as image:
                    tensors.append(
                        transform(image.convert("RGB"))
                    )
                batch_labels.append(label)
            except Exception:
                continue

        if tensors:
            image_batch = torch.stack(tensors).to(device)

            with torch.no_grad():
                batch_embeddings = extract_model_embedding(
                    model,
                    image_batch
                )

            embeddings.append(batch_embeddings.cpu())
            labels.extend(batch_labels)

        if progress_callback:
            progress_callback(
                progress_label,
                min(start + batch_size, total),
                total
            )

    if not embeddings:
        return torch.empty((0, 0)), []

    return torch.cat(embeddings, dim=0), labels


def _stratified_positive_split(labels, validation_ratio):
    randomizer = random.Random(RANDOM_SEED)
    by_class = {}

    for index, label in enumerate(labels):
        by_class.setdefault(label, []).append(index)

    train_indices = []
    validation_indices = []

    for indices in by_class.values():
        randomizer.shuffle(indices)
        validation_count = max(
            1,
            round(len(indices) * validation_ratio)
        )
        validation_indices.extend(
            indices[:validation_count]
        )
        train_indices.extend(indices[validation_count:])

    return train_indices, validation_indices


def _random_split(count, validation_ratio):
    indices = list(range(count))
    random.Random(RANDOM_SEED + 1).shuffle(indices)
    validation_count = max(
        1,
        round(count * validation_ratio)
    )
    return (
        indices[validation_count:],
        indices[:validation_count]
    )


def _fit_linear_gate(
    positive_train,
    negative_train
):
    features = torch.cat([
        positive_train,
        negative_train
    ])
    targets = torch.cat([
        torch.ones(len(positive_train)),
        torch.zeros(len(negative_train))
    ])

    feature_mean = features.mean(dim=0)
    feature_std = features.std(dim=0).clamp_min(1e-4)
    standardized = (
        features - feature_mean
    ) / feature_std

    torch.manual_seed(RANDOM_SEED)
    gate = nn.Linear(features.shape[1], 1)
    optimizer = torch.optim.AdamW(
        gate.parameters(),
        lr=0.015,
        weight_decay=0.12
    )

    positive_weight = 0.5 / len(positive_train)
    negative_weight = 0.5 / len(negative_train)
    sample_weights = torch.where(
        targets > 0.5,
        torch.full_like(targets, positive_weight),
        torch.full_like(targets, negative_weight)
    )

    for _ in range(280):
        optimizer.zero_grad()
        logits = gate(standardized).squeeze(1)
        losses = F.binary_cross_entropy_with_logits(
            logits,
            targets,
            reduction="none"
        )
        loss = (losses * sample_weights).sum()
        loss.backward()
        optimizer.step()

    return (
        gate.weight.detach().cpu(),
        gate.bias.detach().cpu(),
        feature_mean.cpu(),
        feature_std.cpu()
    )


def _kmeans_prototypes(features, prototype_count=4):
    prototype_count = min(prototype_count, len(features))

    if prototype_count <= 0:
        return torch.empty((0, features.shape[1]))

    initial_indices = torch.linspace(
        0,
        len(features) - 1,
        prototype_count
    ).round().long()
    centers = features[initial_indices].clone()

    for _ in range(18):
        similarities = features @ centers.T
        assignments = similarities.argmax(dim=1)
        updated_centers = []

        for cluster_index in range(prototype_count):
            cluster = features[
                assignments == cluster_index
            ]

            if len(cluster) == 0:
                updated_centers.append(
                    centers[cluster_index]
                )
            else:
                updated_centers.append(
                    F.normalize(
                        cluster.mean(dim=0),
                        dim=0
                    )
                )

        updated = torch.stack(updated_centers)

        if torch.allclose(updated, centers, atol=1e-5):
            centers = updated
            break

        centers = updated

    return F.normalize(centers, dim=1)


def _build_prototypes(
    positive_train,
    positive_train_labels,
    class_names
):
    prototypes = []
    prototype_labels = []

    for class_name in class_names:
        class_indices = [
            index
            for index, label in enumerate(
                positive_train_labels
            )
            if label == class_name
        ]

        if not class_indices:
            continue

        centers = _kmeans_prototypes(
            positive_train[class_indices]
        )
        prototypes.append(centers)
        prototype_labels.extend(
            [class_name] * len(centers)
        )

    return torch.cat(prototypes), prototype_labels


def _gate_scores(
    features,
    weight,
    bias,
    feature_mean,
    feature_std
):
    standardized = (
        features - feature_mean
    ) / feature_std
    logits = F.linear(standardized, weight, bias)
    return torch.sigmoid(logits).squeeze(1)


def build_relevance_profile(
    map_name="Ascent",
    model_path=None,
    profile_path=None,
    positive_dirs=None,
    negative_dirs=None,
    max_positive_per_class=64,
    max_negative_images=900,
    progress_callback=None
):
    map_name = canonical_map_name(map_name)
    model_path = (
        area_model_path(map_name)
        if model_path is None
        else Path(model_path)
    )
    profile_path = (
        relevance_profile_path(map_name)
        if profile_path is None
        else Path(profile_path)
    )
    positive_dirs = (
        default_positive_dirs(map_name)
        if positive_dirs is None
        else tuple(positive_dirs)
    )
    negative_dirs = (
        default_negative_dirs(map_name)
        if negative_dirs is None
        else tuple(negative_dirs)
    )

    if not model_path.exists():
        raise FileNotFoundError(
            f"找不到区域模型：{model_path}"
        )

    device = (
        torch.device("mps")
        if torch.backends.mps.is_available()
        else torch.device("cuda")
        if torch.cuda.is_available()
        else torch.device("cpu")
    )
    model, class_names, image_size = _load_model(
        model_path,
        device
    )
    transform = _image_transform(image_size)
    randomizer = random.Random(RANDOM_SEED)
    _ensure_synthetic_negatives(
        SYNTHETIC_NEGATIVE_DIR
    )

    positive_candidates = _collect_labeled_paths(
        positive_dirs,
        class_names
    )
    positive_samples = _balanced_positive_sample(
        positive_candidates,
        class_names,
        max_positive_per_class,
        randomizer
    )
    negative_paths = _collect_unlabeled_paths(
        negative_dirs
    )
    randomizer.shuffle(negative_paths)
    negative_samples = [
        (path, "not_ascent")
        for path in negative_paths[:max_negative_images]
    ]

    if len(positive_samples) < len(class_names) * 4:
        raise RuntimeError(
            f"{map_name} 正样本不足，无法建立相关性过滤器。"
        )

    if len(negative_samples) < 24:
        raise RuntimeError(
            "负样本不足，请向 data/rejection/negative 添加无关图片。"
        )

    positive_features, positive_labels = _extract_samples(
        model,
        transform,
        positive_samples,
        device,
        progress_callback=progress_callback,
        progress_label=f"{map_name} 正样本"
    )
    negative_features, _ = _extract_samples(
        model,
        transform,
        negative_samples,
        device,
        progress_callback=progress_callback,
        progress_label="无关负样本"
    )

    if len(positive_features) < 32 or len(negative_features) < 24:
        raise RuntimeError("可读取的相关性训练图片不足。")

    positive_train_indices, positive_validation_indices = (
        _stratified_positive_split(
            positive_labels,
            validation_ratio=0.2
        )
    )
    negative_train_indices, negative_validation_indices = (
        _random_split(
            len(negative_features),
            validation_ratio=0.2
        )
    )

    positive_train = positive_features[
        positive_train_indices
    ]
    positive_validation = positive_features[
        positive_validation_indices
    ]
    negative_train = negative_features[
        negative_train_indices
    ]
    negative_validation = negative_features[
        negative_validation_indices
    ]
    positive_train_labels = [
        positive_labels[index]
        for index in positive_train_indices
    ]

    (
        gate_weight,
        gate_bias,
        feature_mean,
        feature_std
    ) = _fit_linear_gate(
        positive_train,
        negative_train
    )

    prototypes, prototype_labels = _build_prototypes(
        positive_train,
        positive_train_labels,
        class_names
    )

    positive_gate_scores = _gate_scores(
        positive_validation,
        gate_weight,
        gate_bias,
        feature_mean,
        feature_std
    )
    negative_gate_scores = _gate_scores(
        negative_validation,
        gate_weight,
        gate_bias,
        feature_mean,
        feature_std
    )
    positive_similarities = (
        positive_validation @ prototypes.T
    ).max(dim=1).values
    negative_similarities = (
        negative_validation @ prototypes.T
    ).max(dim=1).values

    gate_threshold = float(
        torch.quantile(
            positive_gate_scores,
            0.02
        ).item()
        - 0.04
    )
    gate_threshold = max(
        0.45,
        min(0.82, gate_threshold)
    )
    similarity_threshold = float(
        torch.quantile(
            positive_similarities,
            0.01
        ).item()
        - 0.025
    )
    similarity_threshold = max(
        0.65,
        min(0.98, similarity_threshold)
    )

    positive_accepted = (
        (positive_gate_scores >= gate_threshold)
        & (
            positive_similarities
            >= similarity_threshold
        )
    )
    negative_rejected = (
        (negative_gate_scores < gate_threshold)
        | (
            negative_similarities
            < similarity_threshold
        )
    )

    profile = {
        "version": PROFILE_VERSION,
        "map_name": map_name,
        "model_fingerprint": model_fingerprint(
            model_path
        ),
        "class_names": class_names,
        "embedding_size": int(
            positive_features.shape[1]
        ),
        "gate_weight": gate_weight,
        "gate_bias": gate_bias,
        "feature_mean": feature_mean,
        "feature_std": feature_std,
        "prototypes": prototypes,
        "prototype_labels": prototype_labels,
        "gate_threshold": gate_threshold,
        "similarity_threshold": similarity_threshold,
        "positive_images": len(positive_features),
        "negative_images": len(negative_features),
        "validation_positive_accept_rate": float(
            positive_accepted.float().mean().item()
        ),
        "validation_negative_reject_rate": float(
            negative_rejected.float().mean().item()
        ),
        "validation_positive_gate_mean": float(
            positive_gate_scores.mean().item()
        ),
        "validation_negative_gate_mean": float(
            negative_gate_scores.mean().item()
        ),
        "validation_positive_similarity_mean": float(
            positive_similarities.mean().item()
        ),
        "validation_negative_similarity_mean": float(
            negative_similarities.mean().item()
        )
    }

    profile_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )
    torch.save(profile, profile_path)
    return profile

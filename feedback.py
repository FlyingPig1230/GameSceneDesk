from datetime import datetime
from pathlib import Path
import hashlib
import json
import shutil

from app_paths import DATA_DIR, REJECTION_DIR
from map_config import (
    canonical_map_name,
    feedback_dir
)


FEEDBACK_LOG = DATA_DIR / "feedback" / "feedback.jsonl"
FEEDBACK_IMAGE_DIR = feedback_dir("Ascent")
IRRELEVANT_LOG = REJECTION_DIR / "irrelevant.jsonl"
IRRELEVANT_IMAGE_DIR = REJECTION_DIR / "negative"


def _safe_class_dir(class_name: str) -> str:
    return "".join(
        char if char.isalnum() or char in ("_", "-")
        else "_"
        for char in class_name
    )


def save_feedback(
    image_path: str,
    predicted_class: str,
    correct_class: str,
    confidence: float,
    was_correct: bool,
    map_name: str = "Ascent"
) -> Path:
    """
    保存反馈记录，并把图片复制到 feedback 数据集。
    """

    source_path = Path(image_path).resolve()

    if not source_path.exists():
        raise FileNotFoundError(
            f"找不到反馈图片：{source_path}"
        )

    predicted_class = predicted_class.strip()
    correct_class = correct_class.strip()
    map_name = canonical_map_name(map_name)

    if not predicted_class:
        raise ValueError("预测类别不能为空。")

    if not correct_class:
        raise ValueError("正确类别不能为空。")

    FEEDBACK_LOG.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    created_at = datetime.now()
    timestamp_key = created_at.strftime(
        "%Y%m%d_%H%M%S_%f"
    )
    path_hash = hashlib.sha1(
        str(source_path).encode("utf-8")
    ).hexdigest()[:8]
    target_dir = (
        feedback_dir(map_name)
        / _safe_class_dir(correct_class)
    )
    target_dir.mkdir(
        parents=True,
        exist_ok=True
    )
    training_image = (
        target_dir
        / f"{timestamp_key}_{path_hash}_{source_path.name}"
    )
    shutil.copy2(
        source_path,
        training_image
    )

    record = {
        "timestamp": created_at.isoformat(
            timespec="seconds"
        ),
        "image": str(source_path),
        "training_image": str(training_image.resolve()),
        "saved_image": str(training_image),
        "map_name": map_name,
        "predicted_class": predicted_class,
        "correct_class": correct_class,
        "confidence": round(float(confidence), 6),
        "was_correct": bool(was_correct),
        "approved": True
    }

    with FEEDBACK_LOG.open(
        "a",
        encoding="utf-8"
    ) as file:
        file.write(
            json.dumps(
                record,
                ensure_ascii=False
            )
            + "\n"
        )

    print(f"反馈已记录：{FEEDBACK_LOG}")

    return FEEDBACK_LOG


def save_irrelevant_feedback(
    image_path: str,
    relevance_score: float,
    prototype_similarity: float,
    map_name: str | None = None
) -> Path:
    source_path = Path(image_path).resolve()

    if not source_path.exists():
        raise FileNotFoundError(
            f"找不到无关图片：{source_path}"
        )

    IRRELEVANT_IMAGE_DIR.mkdir(
        parents=True,
        exist_ok=True
    )
    IRRELEVANT_LOG.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    created_at = datetime.now()
    timestamp_key = created_at.strftime(
        "%Y%m%d_%H%M%S_%f"
    )
    path_hash = hashlib.sha1(
        str(source_path).encode("utf-8")
    ).hexdigest()[:8]
    training_image = (
        IRRELEVANT_IMAGE_DIR
        / f"{timestamp_key}_{path_hash}_{source_path.name}"
    )
    shutil.copy2(source_path, training_image)

    record = {
        "timestamp": created_at.isoformat(
            timespec="seconds"
        ),
        "image": str(source_path),
        "training_image": str(training_image.resolve()),
        "relevance_score": round(
            float(relevance_score),
            6
        ),
        "prototype_similarity": round(
            float(prototype_similarity),
            6
        ),
        "candidate_map": map_name,
        "approved": True
    }

    with IRRELEVANT_LOG.open(
        "a",
        encoding="utf-8"
    ) as file:
        file.write(
            json.dumps(
                record,
                ensure_ascii=False
            )
            + "\n"
        )

    return IRRELEVANT_LOG

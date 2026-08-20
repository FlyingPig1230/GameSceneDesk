"""Create privacy-conscious feedback bundles for manual sharing."""

from __future__ import annotations

import ctypes
from datetime import datetime, timezone
import errno
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import zipfile

from app_paths import (
    APP_NAME,
    APP_VERSION,
    DATA_DIR,
    IS_FROZEN,
    MODELS_DIR,
    REJECTION_DIR,
)
from feedback import FEEDBACK_LOG, IRRELEVANT_LOG
from map_config import MAP_CONFIGS


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".webp",
}
MODEL_FILENAMES = (
    "ascent_area_classifier.pt",
    "ascent_relevance_profile.pt",
    "split_area_classifier.pt",
    "split_relevance_profile.pt",
)
FEEDBACK_RECORD_FIELDS = (
    "timestamp",
    "map_name",
    "predicted_class",
    "correct_class",
    "confidence",
    "was_correct",
    "approved",
)
IRRELEVANT_RECORD_FIELDS = (
    "timestamp",
    "relevance_score",
    "prototype_similarity",
    "candidate_map",
    "approved",
)
CLASS_NAME_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,127}$"
)


def _read_records(log_path: Path) -> tuple[list[dict], int]:
    records = []
    skipped_count = 0

    if not log_path.exists():
        return records, skipped_count

    try:
        file = log_path.open("rb")
    except OSError:
        return records, 1

    with file:
        for raw_line in file:
            try:
                line = raw_line.decode("utf-8").strip()
            except UnicodeDecodeError:
                skipped_count += 1
                continue

            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                skipped_count += 1
                continue

            if not isinstance(record, dict):
                skipped_count += 1
                continue

            records.append(record)

    return records, skipped_count


def _is_number(value) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False

    try:
        numeric_value = float(value)
    except (OverflowError, TypeError, ValueError):
        return False

    return math.isfinite(numeric_value)


def _is_nonempty_string(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_valid_timestamp(value) -> bool:
    if not _is_nonempty_string(value) or len(value) > 64:
        return False

    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False

    return True


def _is_in_range(value, minimum: float, maximum: float) -> bool:
    return _is_number(value) and minimum <= float(value) <= maximum


@lru_cache(maxsize=16)
def _load_class_names(
    path_text: str,
    modified_time_ns: int,
    file_size: int,
) -> frozenset[str]:
    del modified_time_ns, file_size

    try:
        with Path(path_text).open("r", encoding="utf-8") as file:
            values = json.load(file)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return frozenset()

    if not isinstance(values, list):
        return frozenset()

    return frozenset(
        value
        for value in values
        if (
            isinstance(value, str)
            and CLASS_NAME_PATTERN.fullmatch(value)
        )
    )


def _known_class_names(map_name: str) -> frozenset[str]:
    map_config = MAP_CONFIGS.get(map_name)

    if map_config is None:
        return frozenset()

    class_path = (
        MODELS_DIR
        / f"{map_config['slug']}_classes.json"
    )

    try:
        file_status = class_path.stat()
    except OSError:
        return frozenset()

    return _load_class_names(
        str(class_path),
        file_status.st_mtime_ns,
        file_status.st_size,
    )


def _is_valid_feedback_record(record: dict) -> bool:
    map_name = record.get("map_name")
    known_classes = (
        _known_class_names(map_name)
        if isinstance(map_name, str) and map_name in MAP_CONFIGS
        else frozenset()
    )
    predicted_class = record.get("predicted_class")
    correct_class = record.get("correct_class")

    return (
        _is_valid_timestamp(record.get("timestamp"))
        and isinstance(map_name, str)
        and map_name in MAP_CONFIGS
        and isinstance(predicted_class, str)
        and predicted_class in known_classes
        and isinstance(correct_class, str)
        and correct_class in known_classes
        and _is_in_range(record.get("confidence"), 0, 1)
        and isinstance(record.get("was_correct"), bool)
        and record.get("approved") is True
    )


def _is_valid_irrelevant_record(record: dict) -> bool:
    candidate_map = record.get("candidate_map")
    return (
        _is_valid_timestamp(record.get("timestamp"))
        and _is_in_range(record.get("relevance_score"), 0, 1)
        and _is_in_range(
            record.get("prototype_similarity"),
            -1,
            1,
        )
        and (
            candidate_map is None
            or (
                isinstance(candidate_map, str)
                and candidate_map in MAP_CONFIGS
            )
        )
        and record.get("approved") is True
    )


def _resolve_feedback_image(
    record: dict,
    allowed_root: Path,
) -> tuple[Path, Path, tuple[int, int, int, int]] | None:
    resolved_root = allowed_root.resolve()

    for field in ("training_image", "saved_image"):
        raw_value = record.get(field)

        if not isinstance(raw_value, str) or not raw_value.strip():
            continue

        candidate = Path(raw_value).expanduser()

        if not candidate.is_absolute():
            candidate = allowed_root / candidate

        if candidate.is_symlink():
            continue

        try:
            resolved_path = candidate.resolve(strict=True)
            relative_path = resolved_path.relative_to(resolved_root)
        except (FileNotFoundError, OSError, ValueError):
            continue

        try:
            file_status = resolved_path.stat()
        except OSError:
            continue

        if (
            not stat.S_ISREG(file_status.st_mode)
            or resolved_path.suffix.lower() not in IMAGE_EXTENSIONS
        ):
            continue

        file_identity = (
            file_status.st_dev,
            file_status.st_ino,
            file_status.st_size,
            file_status.st_mtime_ns,
        )
        return resolved_path, relative_path, file_identity

    return None


def _sanitized_record(
    record: dict,
    archive_image_path: str,
    allowed_fields: tuple[str, ...],
) -> dict:
    sanitized = {
        key: record[key]
        for key in allowed_fields
        if key in record
    }
    sanitized["training_image"] = archive_image_path
    sanitized["saved_image"] = archive_image_path
    return sanitized


def _open_safe_image(
    image_path: Path,
    expected_identity: tuple[int, int, int, int],
) -> int:
    flags = os.O_RDONLY

    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    descriptor = os.open(image_path, flags)

    try:
        file_status = os.fstat(descriptor)

        if not stat.S_ISREG(file_status.st_mode):
            raise ValueError("反馈图片不是普通文件。")

        current_identity = (
            file_status.st_dev,
            file_status.st_ino,
            file_status.st_size,
            file_status.st_mtime_ns,
        )

        if current_identity != expected_identity:
            raise ValueError("反馈图片在导出前发生了变化。")
    except Exception:
        os.close(descriptor)
        raise

    return descriptor


def _read_safe_image_bytes(
    image_path: Path,
    expected_identity: tuple[int, int, int, int],
) -> bytes:
    descriptor = _open_safe_image(
        image_path,
        expected_identity,
    )

    try:
        with os.fdopen(descriptor, "rb", closefd=False) as file:
            return file.read()
    finally:
        os.close(descriptor)


def _is_safe_image_readable(
    image_path: Path,
    expected_identity: tuple[int, int, int, int],
) -> bool:
    try:
        descriptor = _open_safe_image(
            image_path,
            expected_identity,
        )
    except (OSError, ValueError):
        return False

    os.close(descriptor)
    return True


def _add_feedback_records(
    archive: zipfile.ZipFile,
    log_path: Path,
    allowed_root: Path,
    image_prefix: str,
    allowed_fields: tuple[str, ...],
    written_images: set[str],
    record_validator,
) -> tuple[list[str], int, int, int]:
    records, invalid_log_count = _read_records(log_path)
    exported_lines = []
    exported_image_count = 0
    invalid_image_count = 0

    for record in records:
        if not record_validator(record):
            invalid_log_count += 1
            continue

        resolved = _resolve_feedback_image(record, allowed_root)

        if resolved is None:
            invalid_image_count += 1
            continue

        image_path, relative_path, expected_identity = resolved

        try:
            image_bytes = _read_safe_image_bytes(
                image_path,
                expected_identity,
            )
        except (OSError, ValueError):
            invalid_image_count += 1
            continue

        image_digest = hashlib.sha256(image_bytes).hexdigest()
        archive_image_path = (
            f"images/{image_prefix}/{image_digest}"
            f"{relative_path.suffix.lower()}"
        )

        if archive_image_path not in written_images:
            archive.writestr(archive_image_path, image_bytes)
            written_images.add(archive_image_path)
            exported_image_count += 1

        exported_lines.append(
            json.dumps(
                _sanitized_record(
                    record,
                    archive_image_path,
                    allowed_fields,
                ),
                ensure_ascii=False,
            )
        )

    return (
        exported_lines,
        exported_image_count,
        invalid_log_count,
        invalid_image_count,
    )


def _sha256(file_path: Path) -> str:
    digest = hashlib.sha256()

    with file_path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def _model_fingerprints() -> dict[str, str]:
    fingerprints = {}

    for filename in MODEL_FILENAMES:
        model_path = MODELS_DIR / filename

        if model_path.is_file() and not model_path.is_symlink():
            fingerprints[filename] = _sha256(model_path)

    return fingerprints


def get_feedback_export_summary() -> dict[str, int]:
    """Count exportable feedback categories without creating an archive."""

    summary = {
        "correct": 0,
        "corrected": 0,
        "irrelevant": 0,
        "total": 0,
        "skipped": 0,
    }
    feedback_records, feedback_invalid_count = _read_records(
        FEEDBACK_LOG
    )
    summary["skipped"] += feedback_invalid_count

    for record in feedback_records:
        if not _is_valid_feedback_record(record):
            summary["skipped"] += 1
            continue

        resolved = _resolve_feedback_image(
            record,
            DATA_DIR / "feedback",
        )

        if (
            resolved is None
            or not _is_safe_image_readable(
                resolved[0],
                resolved[2],
            )
        ):
            summary["skipped"] += 1
            continue

        category = (
            "correct"
            if record.get("was_correct") is True
            else "corrected"
        )
        summary[category] += 1
        summary["total"] += 1

    irrelevant_records, irrelevant_invalid_count = _read_records(
        IRRELEVANT_LOG
    )
    summary["skipped"] += irrelevant_invalid_count

    for record in irrelevant_records:
        if not _is_valid_irrelevant_record(record):
            summary["skipped"] += 1
            continue

        resolved = _resolve_feedback_image(
            record,
            REJECTION_DIR,
        )

        if (
            resolved is None
            or not _is_safe_image_readable(
                resolved[0],
                resolved[2],
            )
        ):
            summary["skipped"] += 1
            continue

        summary["irrelevant"] += 1
        summary["total"] += 1

    return summary


def has_exportable_feedback() -> bool:
    """Return whether either feedback log references an allowed image."""

    return get_feedback_export_summary()["total"] > 0


def export_feedback_bundle(
    destination: str | Path,
    *,
    overwrite: bool = False,
) -> dict:
    """Export referenced feedback images and sanitized logs to a ZIP file."""

    output_path = Path(destination).expanduser()

    if output_path.suffix.lower() != ".zip":
        output_path = Path(f"{output_path}.zip")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if os.path.lexists(output_path) and not overwrite:
        raise FileExistsError(
            f"目标文件已存在：{output_path}"
        )

    temporary_file = tempfile.NamedTemporaryFile(
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        dir=output_path.parent,
        delete=False,
    )
    temporary_path = Path(temporary_file.name)
    temporary_file.close()

    try:
        with zipfile.ZipFile(
            temporary_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            written_images: set[str] = set()
            (
                feedback_lines,
                feedback_image_count,
                feedback_invalid_log_count,
                feedback_invalid_image_count,
            ) = _add_feedback_records(
                archive,
                FEEDBACK_LOG,
                DATA_DIR / "feedback",
                "feedback",
                FEEDBACK_RECORD_FIELDS,
                written_images,
                _is_valid_feedback_record,
            )
            (
                irrelevant_lines,
                irrelevant_image_count,
                irrelevant_invalid_log_count,
                irrelevant_invalid_image_count,
            ) = _add_feedback_records(
                archive,
                IRRELEVANT_LOG,
                REJECTION_DIR,
                "rejection",
                IRRELEVANT_RECORD_FIELDS,
                written_images,
                _is_valid_irrelevant_record,
            )

            total_record_count = (
                len(feedback_lines) + len(irrelevant_lines)
            )

            if total_record_count == 0:
                raise ValueError("没有可导出的反馈记录。")

            correct_count = sum(
                1
                for line in feedback_lines
                if json.loads(line).get("was_correct") is True
            )

            archive.writestr(
                "feedback.jsonl",
                "\n".join(feedback_lines) + (
                    "\n" if feedback_lines else ""
                ),
            )
            archive.writestr(
                "irrelevant.jsonl",
                "\n".join(irrelevant_lines) + (
                    "\n" if irrelevant_lines else ""
                ),
            )

            manifest = {
                "schema_version": 1,
                "app": {
                    "name": APP_NAME,
                    "version": APP_VERSION,
                    "edition": (
                        "public-tester"
                        if IS_FROZEN
                        else "developer-trainer"
                    ),
                },
                "exported_at": datetime.now(timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
                "records": {
                    "correct": correct_count,
                    "corrected": (
                        len(feedback_lines) - correct_count
                    ),
                    "feedback": len(feedback_lines),
                    "irrelevant": len(irrelevant_lines),
                    "total": total_record_count,
                    "skipped": (
                        feedback_invalid_log_count
                        + feedback_invalid_image_count
                        + irrelevant_invalid_log_count
                        + irrelevant_invalid_image_count
                    ),
                    "skipped_invalid_log": (
                        feedback_invalid_log_count
                        + irrelevant_invalid_log_count
                    ),
                    "skipped_missing_or_unsafe_image": (
                        feedback_invalid_image_count
                        + irrelevant_invalid_image_count
                    ),
                },
                "images": {
                    "feedback": feedback_image_count,
                    "irrelevant": irrelevant_image_count,
                    "total": len(written_images),
                },
                "models": _model_fingerprints(),
            }
            archive.writestr(
                "manifest.json",
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
            )

        if overwrite:
            os.replace(temporary_path, output_path)
        else:
            _commit_without_overwrite(
                temporary_path,
                output_path,
            )
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    result = dict(manifest)
    result["path"] = str(output_path.resolve())
    return result


def _commit_without_overwrite(
    temporary_path: Path,
    output_path: Path,
) -> None:
    """Commit a completed ZIP without replacing an existing destination."""

    try:
        os.link(temporary_path, output_path)
    except OSError as error:
        unsupported_link_errors = {
            errno.EACCES,
            errno.EMLINK,
            errno.EINVAL,
            errno.ENOTSUP,
            errno.ENOSYS,
            errno.EOPNOTSUPP,
            errno.EPERM,
            errno.EXDEV,
        }

        if error.errno not in unsupported_link_errors:
            raise

        _rename_without_overwrite(
            temporary_path,
            output_path,
        )
        return

    temporary_path.unlink()


def _rename_without_overwrite(
    source_path: Path,
    output_path: Path,
) -> None:
    """Atomically rename within one filesystem without replacing a target."""

    if sys.platform == "win32":
        # Windows os.rename refuses to replace an existing destination.
        os.rename(source_path, output_path)
        return

    library = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source_path)
    output_bytes = os.fsencode(output_path)

    if sys.platform == "darwin":
        rename_exclusive = 0x00000004
        rename_function = library.renamex_np
        rename_function.argtypes = (
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename_function.restype = ctypes.c_int
        result = rename_function(
            source_bytes,
            output_bytes,
            rename_exclusive,
        )
    elif sys.platform.startswith("linux"):
        rename_function = getattr(library, "renameat2", None)

        if rename_function is None:
            raise OSError(
                errno.ENOTSUP,
                "当前系统不支持原子且不覆盖的文件提交。",
                output_path,
            )

        at_current_working_directory = -100
        rename_no_replace = 1
        rename_function.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename_function.restype = ctypes.c_int
        result = rename_function(
            at_current_working_directory,
            source_bytes,
            at_current_working_directory,
            output_bytes,
            rename_no_replace,
        )
    else:
        raise OSError(
            errno.ENOTSUP,
            "当前系统不支持原子且不覆盖的文件提交。",
            output_path,
        )

    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(
            error_number,
            os.strerror(error_number),
            output_path,
        )

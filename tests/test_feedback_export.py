import errno
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import feedback_export


class FeedbackExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.data_dir = self.root / "data"
        self.feedback_root = self.data_dir / "feedback"
        self.rejection_root = self.data_dir / "rejection"
        self.feedback_log = self.feedback_root / "feedback.jsonl"
        self.irrelevant_log = (
            self.rejection_root / "irrelevant.jsonl"
        )
        self.models_dir = self.root / "models"
        self.models_dir.mkdir(parents=True)
        (self.models_dir / "ascent_classes.json").write_text(
            json.dumps(["A_Site", "Mid"]),
            encoding="utf-8",
        )
        (self.models_dir / "split_classes.json").write_text(
            json.dumps(["Mid", "A_Ramps"]),
            encoding="utf-8",
        )

        self.patches = [
            mock.patch.object(
                feedback_export,
                "DATA_DIR",
                self.data_dir,
            ),
            mock.patch.object(
                feedback_export,
                "REJECTION_DIR",
                self.rejection_root,
            ),
            mock.patch.object(
                feedback_export,
                "FEEDBACK_LOG",
                self.feedback_log,
            ),
            mock.patch.object(
                feedback_export,
                "IRRELEVANT_LOG",
                self.irrelevant_log,
            ),
            mock.patch.object(
                feedback_export,
                "MODELS_DIR",
                self.models_dir,
            ),
        ]

        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.temporary_directory.cleanup()

    @staticmethod
    def _write_jsonl(path: Path, records: list[dict]):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(
                json.dumps(record, ensure_ascii=False) + "\n"
                for record in records
            ),
            encoding="utf-8",
        )

    def test_export_sanitizes_paths_and_includes_referenced_images(self):
        feedback_filename = (
            r"shot\..\..\leak.png"
            if os.name != "nt"
            else "shot.png"
        )
        feedback_image = (
            self.feedback_root
            / "Ascent"
            / "A_Site"
            / feedback_filename
        )
        feedback_image.parent.mkdir(parents=True)
        feedback_image.write_bytes(b"feedback-image")

        irrelevant_image = (
            self.rejection_root / "negative" / "other.jpg"
        )
        irrelevant_image.parent.mkdir(parents=True)
        irrelevant_image.write_bytes(b"irrelevant-image")

        self._write_jsonl(
            self.feedback_log,
            [
                {
                    "timestamp": "2026-08-11T12:00:00",
                    "image": "/Users/tester/private/source.png",
                    "training_image": str(feedback_image),
                    "saved_image": str(feedback_image),
                    "map_name": "Ascent",
                    "predicted_class": "Mid",
                    "correct_class": "A_Site",
                    "confidence": 0.75,
                    "was_correct": False,
                    "approved": True,
                    "future_private_path": (
                        "/Users/tester/private/future-field"
                    ),
                }
            ],
        )
        self._write_jsonl(
            self.irrelevant_log,
            [
                {
                    "timestamp": "2026-08-11T12:01:00",
                    "image": "C:/Users/tester/private/other.jpg",
                    "training_image": str(irrelevant_image),
                    "relevance_score": 0.12,
                    "prototype_similarity": 0.34,
                    "candidate_map": "Split",
                    "approved": True,
                    "future_private_path": (
                        "C:/Users/tester/private/future-field"
                    ),
                }
            ],
        )

        summary = feedback_export.get_feedback_export_summary()
        self.assertEqual(summary["correct"], 0)
        self.assertEqual(summary["corrected"], 1)
        self.assertEqual(summary["irrelevant"], 1)
        self.assertEqual(summary["total"], 2)
        self.assertTrue(feedback_export.has_exportable_feedback())

        output_path = self.root / "export.zip"
        result = feedback_export.export_feedback_bundle(output_path)

        self.assertEqual(result["records"]["total"], 2)
        self.assertEqual(result["images"]["total"], 2)

        with zipfile.ZipFile(output_path) as archive:
            names = set(archive.namelist())
            feedback_archive_path = (
                "images/feedback/"
                + hashlib.sha256(b"feedback-image").hexdigest()
                + ".png"
            )
            irrelevant_archive_path = (
                "images/rejection/"
                + hashlib.sha256(b"irrelevant-image").hexdigest()
                + ".jpg"
            )
            self.assertIn("manifest.json", names)
            self.assertIn("feedback.jsonl", names)
            self.assertIn("irrelevant.jsonl", names)
            self.assertIn(feedback_archive_path, names)
            self.assertIn(irrelevant_archive_path, names)
            archive_name_text = "\n".join(names)
            self.assertNotIn(feedback_image.name, archive_name_text)
            self.assertNotIn(irrelevant_image.name, archive_name_text)
            self.assertNotIn("\\", feedback_archive_path)
            self.assertNotIn("..", feedback_archive_path)

            exported_text = (
                archive.read("feedback.jsonl")
                + archive.read("irrelevant.jsonl")
            ).decode("utf-8")
            self.assertNotIn("/Users/tester", exported_text)
            self.assertNotIn("C:/Users/tester", exported_text)
            self.assertNotIn(str(self.root), exported_text)

            feedback_record = json.loads(
                archive.read("feedback.jsonl")
                .decode("utf-8")
                .strip()
            )
            self.assertEqual(
                feedback_record["training_image"],
                feedback_archive_path,
            )
            self.assertNotIn("image", feedback_record)
            self.assertNotIn(
                "future_private_path",
                feedback_record,
            )

    def test_export_rejects_images_outside_feedback_directories(self):
        outside_image = self.root / "outside.png"
        outside_image.write_bytes(b"outside")
        self._write_jsonl(
            self.feedback_log,
            [
                {
                    "image": "/private/source.png",
                    "training_image": str(outside_image),
                    "saved_image": str(outside_image),
                }
            ],
        )

        output_path = self.root / "unsafe.zip"

        with self.assertRaisesRegex(
            ValueError,
            "没有可导出的反馈记录",
        ):
            feedback_export.export_feedback_bundle(output_path)

        self.assertFalse(output_path.exists())

    def test_export_requires_explicit_overwrite(self):
        feedback_image = (
            self.feedback_root / "Split" / "Mid" / "shot.webp"
        )
        feedback_image.parent.mkdir(parents=True)
        feedback_image.write_bytes(b"feedback-image")
        self._write_jsonl(
            self.feedback_log,
            [
                {
                    "timestamp": "2026-08-11T12:02:00",
                    "training_image": str(feedback_image),
                    "saved_image": str(feedback_image),
                    "map_name": "Split",
                    "predicted_class": "Mid",
                    "correct_class": "Mid",
                    "confidence": 0.9,
                    "was_correct": True,
                    "approved": True,
                }
            ],
        )

        output_path = self.root / "existing.zip"
        output_path.write_bytes(b"keep-me")

        with self.assertRaisesRegex(
            FileExistsError,
            "目标文件已存在",
        ):
            feedback_export.export_feedback_bundle(output_path)

        self.assertEqual(output_path.read_bytes(), b"keep-me")

        with mock.patch(
            "feedback_export.os.path.lexists",
            return_value=False,
        ):
            with self.assertRaises(FileExistsError):
                feedback_export.export_feedback_bundle(output_path)

        self.assertEqual(output_path.read_bytes(), b"keep-me")

        result = feedback_export.export_feedback_bundle(
            output_path,
            overwrite=True,
        )
        self.assertEqual(result["records"]["correct"], 1)

        with zipfile.ZipFile(output_path) as archive:
            manifest = json.loads(
                archive.read("manifest.json").decode("utf-8")
            )

        self.assertEqual(
            manifest["app"]["edition"],
            "developer-trainer",
        )

    def test_invalid_utf8_and_incomplete_records_are_skipped(self):
        feedback_image = (
            self.feedback_root / "Ascent" / "Mid" / "shot.png"
        )
        feedback_image.parent.mkdir(parents=True)
        feedback_image.write_bytes(b"feedback-image")
        self.feedback_log.parent.mkdir(parents=True, exist_ok=True)
        incomplete_record = json.dumps(
            {"training_image": str(feedback_image)}
        ).encode("utf-8")
        self.feedback_log.write_bytes(
            b"\xff\xfe\n" + incomplete_record + b"\n"
        )

        summary = feedback_export.get_feedback_export_summary()
        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["skipped"], 2)
        self.assertFalse(feedback_export.has_exportable_feedback())

        with self.assertRaisesRegex(
            ValueError,
            "没有可导出的反馈记录",
        ):
            feedback_export.export_feedback_bundle(
                self.root / "invalid.zip"
            )

    def test_unreadable_log_is_skipped_instead_of_raising(self):
        self.feedback_log.mkdir(parents=True)

        summary = feedback_export.get_feedback_export_summary()

        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["skipped"], 1)

    def test_semantically_invalid_fields_are_not_exported(self):
        feedback_image = (
            self.feedback_root / "Ascent" / "Mid" / "shot.png"
        )
        feedback_image.parent.mkdir(parents=True)
        feedback_image.write_bytes(b"feedback-image")
        self._write_jsonl(
            self.feedback_log,
            [
                {
                    "timestamp": "/Users/tester/private",
                    "training_image": str(feedback_image),
                    "map_name": "/Users/tester/private",
                    "predicted_class": "/private/source",
                    "correct_class": "Mid",
                    "confidence": 42,
                    "was_correct": False,
                    "approved": True,
                }
            ],
        )

        summary = feedback_export.get_feedback_export_summary()

        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["skipped"], 1)

        with self.assertRaisesRegex(
            ValueError,
            "没有可导出的反馈记录",
        ):
            feedback_export.export_feedback_bundle(
                self.root / "semantic-invalid.zip"
            )

    def test_unexpected_json_types_are_skipped(self):
        feedback_image = (
            self.feedback_root / "Ascent" / "Mid" / "shot.png"
        )
        feedback_image.parent.mkdir(parents=True)
        feedback_image.write_bytes(b"feedback-image")
        base_feedback = {
            "timestamp": "2026-08-11T12:03:00",
            "training_image": str(feedback_image),
            "map_name": "Ascent",
            "predicted_class": "Mid",
            "correct_class": "Mid",
            "confidence": 0.8,
            "was_correct": True,
            "approved": True,
        }
        invalid_feedback_records = []

        for field, value in (
            ("map_name", []),
            ("predicted_class", []),
            ("confidence", 10**400),
        ):
            record = dict(base_feedback)
            record[field] = value
            invalid_feedback_records.append(record)

        self._write_jsonl(
            self.feedback_log,
            invalid_feedback_records,
        )
        irrelevant_image = (
            self.rejection_root / "negative" / "shot.png"
        )
        irrelevant_image.parent.mkdir(parents=True)
        irrelevant_image.write_bytes(b"irrelevant-image")
        self._write_jsonl(
            self.irrelevant_log,
            [
                {
                    "timestamp": "2026-08-11T12:04:00",
                    "training_image": str(irrelevant_image),
                    "relevance_score": 0.1,
                    "prototype_similarity": 0.2,
                    "candidate_map": {},
                    "approved": True,
                }
            ],
        )

        summary = feedback_export.get_feedback_export_summary()

        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["skipped"], 4)

        with self.assertRaisesRegex(
            ValueError,
            "没有可导出的反馈记录",
        ):
            feedback_export.export_feedback_bundle(
                self.root / "unexpected-types.zip"
            )

    def test_hard_link_fallback_preserves_no_overwrite_behavior(self):
        feedback_image = (
            self.feedback_root / "Ascent" / "Mid" / "shot.png"
        )
        feedback_image.parent.mkdir(parents=True)
        feedback_image.write_bytes(b"feedback-image")
        self._write_jsonl(
            self.feedback_log,
            [
                {
                    "timestamp": "2026-08-11T12:03:00",
                    "training_image": str(feedback_image),
                    "map_name": "Ascent",
                    "predicted_class": "Mid",
                    "correct_class": "Mid",
                    "confidence": 0.8,
                    "was_correct": True,
                    "approved": True,
                }
            ],
        )
        output_path = self.root / "fallback.zip"

        with mock.patch(
            "feedback_export.os.link",
            side_effect=OSError(
                errno.EOPNOTSUPP,
                "hard links are unavailable",
            ),
        ):
            result = feedback_export.export_feedback_bundle(
                output_path
            )

        self.assertEqual(result["records"]["total"], 1)

        with zipfile.ZipFile(output_path) as archive:
            self.assertIn("manifest.json", archive.namelist())

    def test_atomic_rename_fallback_does_not_replace_target(self):
        source_path = self.root / "source.tmp"
        output_path = self.root / "existing.zip"
        source_path.write_bytes(b"new")
        output_path.write_bytes(b"existing")

        with self.assertRaises(FileExistsError):
            feedback_export._rename_without_overwrite(
                source_path,
                output_path,
            )

        self.assertEqual(source_path.read_bytes(), b"new")
        self.assertEqual(output_path.read_bytes(), b"existing")

    def test_parent_symlink_swap_is_rejected(self):
        image_directory = self.feedback_root / "Ascent" / "Mid"
        image_directory.mkdir(parents=True)
        image_path = image_directory / "shot.png"
        image_path.write_bytes(b"inside")
        record = {"training_image": str(image_path)}
        resolved = feedback_export._resolve_feedback_image(
            record,
            self.feedback_root,
        )
        self.assertIsNotNone(resolved)
        resolved_path, _, expected_identity = resolved
        original_directory = self.root / "original-mid"
        image_directory.rename(original_directory)
        outside_directory = self.root / "outside"
        outside_directory.mkdir()
        (outside_directory / "shot.png").write_bytes(b"outside")

        try:
            image_directory.symlink_to(
                outside_directory,
                target_is_directory=True,
            )
        except OSError as error:
            self.skipTest(f"symlink unavailable: {error}")

        with self.assertRaisesRegex(
            ValueError,
            "发生了变化",
        ):
            feedback_export._read_safe_image_bytes(
                resolved_path,
                expected_identity,
            )


if __name__ == "__main__":
    unittest.main()

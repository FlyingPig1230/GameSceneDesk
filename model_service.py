from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image
from torchvision import models, transforms

from map_config import (
    AUTO_MAP,
    area_model_path,
    canonical_map_name,
    relevance_profile_path,
    supported_map_names
)
from relevance import (
    PROFILE_VERSION,
    forward_with_embedding,
    model_fingerprint
)


class MapModelService:
    def __init__(
        self,
        map_name,
        model_path=None,
        profile_path=None
    ):
        self.map_name = canonical_map_name(map_name)
        self.model_path = Path(
            model_path
            if model_path is not None
            else area_model_path(self.map_name)
        )
        self.relevance_profile_path = Path(
            profile_path
            if profile_path is not None
            else relevance_profile_path(self.map_name)
        )
        self.device = self._get_device()

        self.model = None
        self.class_names = []
        self.image_size = 224
        self.relevance_profile = None
        self.relevance_available = False
        self.relevance_status = "相关性过滤器未加载"

        self._load_model()

    @staticmethod
    def _get_device() -> torch.device:
        if torch.backends.mps.is_available():
            return torch.device("mps")

        if torch.cuda.is_available():
            return torch.device("cuda")

        return torch.device("cpu")

    def _load_model(self) -> None:
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"找不到模型文件：{self.model_path}"
            )

        checkpoint = torch.load(
            self.model_path,
            map_location=self.device,
            weights_only=False
        )

        self.class_names = checkpoint["class_names"]
        self.image_size = checkpoint.get("image_size", 224)

        num_classes = checkpoint.get(
            "num_classes",
            len(self.class_names)
        )

        model = models.mobilenet_v3_small(weights=None)

        input_features = model.classifier[3].in_features
        model.classifier[3] = nn.Linear(
            input_features,
            num_classes
        )

        model.load_state_dict(
            checkpoint["model_state_dict"]
        )

        model = model.to(self.device)
        model.eval()

        self.model = model

        self.transform = transforms.Compose([
            transforms.Resize(
                (self.image_size, self.image_size)
            ),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225]
            )
        ])
        self._load_relevance_profile()

    def _load_relevance_profile(self) -> None:
        if not self.relevance_profile_path.exists():
            self.relevance_status = "缺少相关性过滤器"
            return

        try:
            profile = torch.load(
                self.relevance_profile_path,
                map_location="cpu",
                weights_only=True
            )

            if profile.get("version") != PROFILE_VERSION:
                self.relevance_status = "相关性过滤器版本不兼容"
                return

            profile_map = profile.get("map_name")

            if profile_map and profile_map != self.map_name:
                self.relevance_status = "相关性过滤器地图不匹配"
                return

            if list(profile.get("class_names", [])) != list(
                self.class_names
            ):
                self.relevance_status = "相关性过滤器类别不匹配"
                return

            if profile.get("model_fingerprint") != (
                model_fingerprint(self.model_path)
            ):
                self.relevance_status = "相关性过滤器需要更新"
                return

            required_keys = {
                "gate_weight",
                "gate_bias",
                "feature_mean",
                "feature_std",
                "prototypes",
                "gate_threshold",
                "similarity_threshold"
            }

            if not required_keys.issubset(profile):
                self.relevance_status = "相关性过滤器数据不完整"
                return

            self.relevance_profile = profile
            self.relevance_available = True
            self.relevance_status = "无关图片过滤已开启"

        except Exception as error:
            self.relevance_status = (
                f"相关性过滤器加载失败：{error}"
            )

    def _evaluate_relevance(self, embedding) -> dict:
        if not self.relevance_available:
            return {
                "is_relevant": True,
                "relevance_available": False,
                "relevance_score": 1.0,
                "prototype_similarity": 1.0,
                "nearest_prototype_class": None,
                "rejection_reason": ""
            }

        profile = self.relevance_profile
        embedding = embedding.detach().cpu()
        standardized = (
            embedding - profile["feature_mean"]
        ) / profile["feature_std"]
        gate_logit = F.linear(
            standardized,
            profile["gate_weight"],
            profile["gate_bias"]
        )
        relevance_score = float(
            torch.sigmoid(gate_logit).item()
        )
        similarities = (
            embedding @ profile["prototypes"].T
        ).squeeze(0)
        similarity, prototype_index = similarities.max(
            dim=0
        )
        prototype_similarity = float(similarity.item())
        prototype_labels = profile.get(
            "prototype_labels",
            []
        )
        nearest_class = (
            prototype_labels[prototype_index.item()]
            if prototype_labels
            else None
        )

        gate_passed = relevance_score >= float(
            profile["gate_threshold"]
        )
        similarity_passed = prototype_similarity >= float(
            profile["similarity_threshold"]
        )
        is_relevant = gate_passed and similarity_passed

        if gate_passed and not similarity_passed:
            reason = (
                f"图片与已知 {self.map_name} 区域差异过大"
            )
        elif similarity_passed and not gate_passed:
            reason = (
                f"画面不像 {self.map_name} 游戏地图截图"
            )
        elif not is_relevant:
            reason = "相关性与地图特征均未通过检查"
        else:
            reason = ""

        return {
            "is_relevant": is_relevant,
            "relevance_available": True,
            "relevance_score": relevance_score,
            "prototype_similarity": prototype_similarity,
            "relevance_confidence": min(
                relevance_score,
                prototype_similarity
            ),
            "nearest_prototype_class": nearest_class,
            "rejection_reason": reason,
            "relevance_threshold": float(
                profile["gate_threshold"]
            ),
            "similarity_threshold": float(
                profile["similarity_threshold"]
            )
        }

    def predict(self, image_path: str, top_k: int = 3) -> dict:
        path = Path(image_path)

        if not path.exists():
            raise FileNotFoundError(f"找不到图片：{path}")

        image = Image.open(path).convert("RGB")
        image_tensor = self.transform(image)
        image_tensor = image_tensor.unsqueeze(0).to(self.device)

        with torch.no_grad():
            outputs, embedding = forward_with_embedding(
                self.model,
                image_tensor
            )
            probabilities = torch.softmax(outputs, dim=1)

            top_k = min(top_k, len(self.class_names))

            confidences, indices = torch.topk(
                probabilities,
                k=top_k,
                dim=1
            )

        relevance = self._evaluate_relevance(embedding)

        predictions = []

        for confidence, index in zip(
            confidences[0],
            indices[0]
        ):
            predictions.append({
                "class_name": self.class_names[index.item()],
                "confidence": confidence.item()
            })

        result = {
            "map_name": self.map_name,
            "best_class": predictions[0]["class_name"],
            "best_confidence": predictions[0]["confidence"],
            "top_predictions": predictions,
            "classification_margin": (
                predictions[0]["confidence"]
                - predictions[1]["confidence"]
                if len(predictions) > 1
                else predictions[0]["confidence"]
            )
        }
        result.update(relevance)
        return result


class ModelService:
    def __init__(self):
        self.map_models = {}
        self.load_errors = {}

        for map_name in supported_map_names():
            model_path = area_model_path(map_name)

            if not model_path.exists():
                continue

            try:
                self.map_models[map_name] = MapModelService(
                    map_name
                )
            except Exception as error:
                self.load_errors[map_name] = str(error)

        if not self.map_models:
            detail = "; ".join(
                f"{name}: {error}"
                for name, error in self.load_errors.items()
            )
            raise RuntimeError(
                "没有可用的地图模型。"
                + (f" {detail}" if detail else "")
            )

        self.map_names = list(self.map_models)
        self.default_map = (
            "Ascent"
            if "Ascent" in self.map_models
            else self.map_names[0]
        )
        self.device = self.map_models[
            self.default_map
        ].device
        self.class_names = sorted({
            class_name
            for model in self.map_models.values()
            for class_name in model.class_names
        })
        self.relevance_available = all(
            model.relevance_available
            for model in self.map_models.values()
        )

        if self.relevance_available:
            self.relevance_status = (
                f"{len(self.map_models)} 张地图过滤已开启"
            )
        else:
            unavailable = [
                map_name
                for map_name, model in self.map_models.items()
                if not model.relevance_available
            ]
            self.relevance_status = (
                "过滤器未就绪：" + ", ".join(unavailable)
            )

    def get_class_names(self, map_name=None):
        if map_name in (None, AUTO_MAP):
            return list(self.class_names)

        map_name = canonical_map_name(map_name)

        if map_name not in self.map_models:
            return []

        return list(self.map_models[map_name].class_names)

    def predict(
        self,
        image_path: str,
        top_k: int = 3,
        map_name=AUTO_MAP
    ) -> dict:
        map_name = canonical_map_name(map_name)

        if map_name != AUTO_MAP:
            if map_name not in self.map_models:
                raise RuntimeError(
                    f"{map_name} 模型尚未训练。"
                )

            return self.map_models[map_name].predict(
                image_path,
                top_k=top_k
            )

        candidates = []

        for candidate_map, model in self.map_models.items():
            result = model.predict(image_path, top_k=top_k)
            result["routing_score"] = (
                result.get("relevance_score", 0) * 0.7
                + result.get("prototype_similarity", 0) * 0.3
            )
            candidates.append(result)

        routed_candidates = [
            result
            for result in candidates
            if result.get("relevance_available", False)
        ]
        accepted = [
            result
            for result in routed_candidates
            if result.get("is_relevant", False)
        ]

        if accepted:
            selected = max(
                accepted,
                key=lambda result: result["routing_score"]
            )
        elif routed_candidates:
            selected = max(
                routed_candidates,
                key=lambda result: result["routing_score"]
            )
            selected["is_relevant"] = False
            selected["rejection_reason"] = (
                "无法确认图片属于已支持的地图"
            )
        else:
            selected = candidates[0]

        selected["map_candidates"] = [
            {
                "map_name": result["map_name"],
                "is_relevant": result.get(
                    "is_relevant",
                    False
                ),
                "relevance_score": result.get(
                    "relevance_score",
                    0
                ),
                "prototype_similarity": result.get(
                    "prototype_similarity",
                    0
                ),
                "routing_score": result.get(
                    "routing_score",
                    0
                )
            }
            for result in candidates
        ]
        return selected

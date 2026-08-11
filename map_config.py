from app_paths import (
    DATA_DIR,
    EVALUATION_OUTPUT_DIR,
    MODELS_DIR,
    SOURCE_DATA_DIR
)


AUTO_MAP = "Auto"
MAP_CONFIGS = {
    "Ascent": {
        "slug": "ascent"
    },
    "Split": {
        "slug": "split"
    }
}


def canonical_map_name(value):
    text = str(value or "").strip()

    if text.lower() == AUTO_MAP.lower():
        return AUTO_MAP

    for map_name in MAP_CONFIGS:
        if text.lower() == map_name.lower():
            return map_name

    raise ValueError(f"不支持的地图：{value}")


def map_slug(map_name):
    map_name = canonical_map_name(map_name)

    if map_name == AUTO_MAP:
        raise ValueError("自动模式没有独立文件路径。")

    return MAP_CONFIGS[map_name]["slug"]


def area_model_path(map_name):
    return (
        MODELS_DIR
        / f"{map_slug(map_name)}_area_classifier.pt"
    )


def relevance_profile_path(map_name):
    return (
        MODELS_DIR
        / f"{map_slug(map_name)}_relevance_profile.pt"
    )


def classes_path(map_name):
    return (
        MODELS_DIR
        / f"{map_slug(map_name)}_classes.json"
    )


def train_dir(map_name):
    return (
        SOURCE_DATA_DIR
        / "train"
        / canonical_map_name(map_name)
    )


def test_dir(map_name):
    return (
        SOURCE_DATA_DIR
        / "test"
        / canonical_map_name(map_name)
    )


def feedback_dir(map_name):
    return (
        DATA_DIR
        / "feedback"
        / canonical_map_name(map_name)
    )


def frames_dir(map_name):
    return (
        SOURCE_DATA_DIR
        / "frames"
        / canonical_map_name(map_name)
    )


def evaluation_dir(map_name):
    return EVALUATION_OUTPUT_DIR / map_slug(map_name)


def supported_map_names():
    return list(MAP_CONFIGS)

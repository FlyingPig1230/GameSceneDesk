# GameSceneDesk

## 界面预览 / Screenshots

### 多地图区域识别 / Multi-map Recognition

![GameSceneDesk 多地图区域识别界面](docs/images/recognition.png)

| 批量纠错 / Batch Correction | 错题回顾 / Wrong-case Review |
|:---:|:---:|
| ![批量纠错界面](docs/images/batch-correction.png) | ![错题回顾界面](docs/images/wrong-case-review.png) |

### 模型评估 / Model Evaluation

<p align="center">
  <img src="docs/images/evaluation-report.png" alt="GameSceneDesk 模型评估报告" width="720">
</p>

---

## 中文介绍

GameSceneDesk 是一个面向《VALORANT》游戏截图的实验性 AI 桌面应用。导入或拖放截图后，应用可以自动判断地图，并预测画面所在的具体区域，同时展示 Top 3 匹配结果与置信度，帮助玩家整理素材、分析场景，也为游戏视觉识别模型的训练与研究提供一个直观的工作台。

目前项目支持 **Ascent** 和 **Split**，发行版提供单张识别、批量纠错、无关图片过滤与反馈历史。推理完全在本地完成，可根据设备自动使用 Apple MPS、NVIDIA CUDA 或 CPU。训练和评估脚本保留在源码中，但不会打进“仅识别版”桌面应用。

### 主要功能

- 自动识别地图，或手动指定地图
- 预测截图中的具体区域并展示 Top 3 结果
- 过滤与目标地图无关的图片
- 支持拖放图片、单张识别和批量纠错
- 记录正确、错误与无关样本，形成反馈闭环
- macOS 与 Windows 使用同一套识别代码和模型
- 训练与评估工具作为开发脚本保留，不进入发行界面
- 当前支持 Ascent 与 Split，结构可继续扩展至更多地图

### 项目状态

本项目仍处于实验和持续训练阶段，识别效果会受到截图视角、画质、界面遮挡及训练数据规模的影响。它更适合作为计算机视觉学习、数据整理和模型迭代项目，而不是准确率已经稳定的成品工具。

### 运行源码

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements-runtime.txt
python app.py
```

仓库包含运行所需的 Ascent、Split 模型，但不包含训练数据集、评估输出、虚拟环境或构建产物。

### 构建桌面应用

- macOS 15+ Apple Silicon：`zsh build_macos.sh`
- Windows 10/11 x64：在 PowerShell 中运行 `.\build_windows.ps1`

两个系统必须分别构建。macOS 输出 `.app`，Windows 输出包含 `.exe` 与 `_internal` 的完整目录。详细步骤见 [BUILDING.md](BUILDING.md)。

---

## English

GameSceneDesk is an experimental AI desktop application that recognizes maps and in-game locations from VALORANT screenshots. Import or drag in an image, and the app can automatically identify the map, predict the visible area, and display the top three matches with confidence scores. It serves both as a practical screenshot-analysis workspace and as an approachable platform for training and evaluating game-scene recognition models.

The project currently supports **Ascent** and **Split**. Release builds include single-image prediction, batch correction, irrelevant-image filtering, and feedback history. Inference runs locally and automatically uses Apple MPS, NVIDIA CUDA, or CPU. Training and evaluation scripts remain available to developers but are not bundled into the inference-only desktop app.

### Highlights

- Automatic map detection or manual map selection
- In-game location prediction with top-three confidence scores
- Filtering for images unrelated to the selected map
- Drag-and-drop input, single-image mode, and batch correction
- Feedback collection for correct, incorrect, and irrelevant samples
- Shared recognition code and models across macOS and Windows
- Developer training and evaluation scripts kept outside release builds
- Initial support for Ascent and Split, with an extensible multi-map design

### Project Status

This project is still experimental and under active model iteration. Accuracy varies with camera angle, image quality, UI obstruction, and the amount of training data. It is best viewed as a computer-vision learning, dataset-management, and model-development project rather than a production-ready recognition system.

### Run from source

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements-runtime.txt
python app.py
```

The repository includes the runtime Ascent and Split models. Training datasets, evaluation output, virtual environments, and packaged applications are intentionally excluded.

### Build desktop apps

- macOS 15+ on Apple Silicon: `zsh build_macos.sh`
- Windows 10/11 x64: run `.\build_windows.ps1` in PowerShell

Each operating system must build its own package. See [BUILDING.md](BUILDING.md) for complete instructions.

---

## Tech Stack

- Python
- PySide6 / Qt
- PyTorch and TorchVision
- MobileNetV3
- OpenCV and Pillow

## Disclaimer

GameSceneDesk is an independent, community-made project and is not affiliated with or endorsed by Riot Games. VALORANT and all related trademarks belong to their respective owners.

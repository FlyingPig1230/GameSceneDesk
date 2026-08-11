# Ascent Map Recognizer 构建说明

当前发行目标：

- macOS 15 及以上，Apple Silicon（arm64）
- Windows 10/11，64 位（x64，CPU 推理）
- 仅识别版：保留单张识别、批量纠错、反馈与历史
- 不包含训练、测试数据，也不开放训练与评估入口

两个系统共用源代码和模型，但 PyInstaller 不是交叉编译器，必须分别
在 macOS 和 Windows 上构建。

## macOS

在 Apple Silicon Mac 的项目目录运行：

```zsh
zsh build_macos.sh
```

输出：

```text
dist/macos/Ascent Map Recognizer.app
dist/macos/Ascent-Map-Recognizer-macOS-arm64.zip
```

脚本会使用独立的 `.build-venv-macos`，生成的 App 采用本地测试用的
ad-hoc 签名。PyInstaller 缓存固定在项目的 `build` 目录内。公开分发
仍需 Developer ID 签名与 Apple 公证。打包结束前脚本会自动启动一次
离屏自检，只有模型、主窗口和实际前向推理均成功才会继续生成 ZIP。

## Windows

将完整项目复制到 Windows 10/11 x64，安装 64 位 Python 3，然后在
PowerShell 中运行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build_windows.ps1
```

输出：

```text
dist\windows\Ascent Map Recognizer\Ascent Map Recognizer.exe
dist\windows\Ascent-Map-Recognizer-Windows-x64.zip
```

Windows 版采用 `onedir`。分发时必须发送整个目录或脚本生成的 ZIP，
不能只复制单独的 EXE。脚本从 PyTorch 官方 CPU 源安装依赖，避免将
CUDA 运行库打进发行包，并会在压缩前自动执行启动自检。

## 运行时数据

模型和界面资源位于只读发行包内。反馈、纠错图片和历史记录写入：

- macOS：`~/Library/Application Support/Ascent Map Recognizer`
- Windows：`%LOCALAPPDATA%\Ascent Map Recognizer`

开发态运行 `app.py` 时仍使用项目内原有的 `data` 与 `evaluation` 目录。
测试时可通过环境变量 `ASCENT_RECOGNIZER_DATA_DIR` 指定临时数据目录。

## 发布前检查

- 从 Finder/Windows Explorer 启动，不依赖终端工作目录
- Ascent、Split 和 Auto 模式均能识别
- JPG、PNG、BMP、WebP 均能读取
- 批量队列、正确反馈、纠错反馈和历史记录可用
- 将 App/发行目录移动后仍能启动
- 在没有项目源码、没有 Python 的干净电脑上验证
- 公开发布前完成 macOS 公证及 Windows Authenticode 签名

param(
    [string]$PythonBootstrap = ""
)

$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    throw "This script must run on Windows."
}

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildVenv = Join-Path $RootDir ".build-venv-windows"
$BuildPython = Join-Path $BuildVenv "Scripts\python.exe"
$SpecFile = Join-Path $RootDir "packaging\ascent_map_recognizer.spec"
$DistDir = Join-Path $RootDir "dist\windows"
$WorkDir = Join-Path $RootDir "build\windows"
$env:PYINSTALLER_CONFIG_DIR = Join-Path $RootDir "build\pyinstaller-cache\windows"
$OutputDir = Join-Path $DistDir "Ascent Map Recognizer"
$ZipPath = Join-Path $DistDir "Ascent-Map-Recognizer-Windows-x64.zip"

$RequiredFiles = @(
    "assets\app_icon_transparent.png",
    "assets\valorant_mark_transparent.png",
    "assets\riot_mark_transparent.png",
    "models\ascent_area_classifier.pt",
    "models\ascent_relevance_profile.pt",
    "models\split_area_classifier.pt",
    "models\split_relevance_profile.pt"
)

foreach ($RelativePath in $RequiredFiles) {
    $FullPath = Join-Path $RootDir $RelativePath

    if (-not (Test-Path -LiteralPath $FullPath -PathType Leaf)) {
        throw "Missing required file: $RelativePath"
    }
}

if (-not (Test-Path -LiteralPath $BuildPython -PathType Leaf)) {
    if ($PythonBootstrap) {
        & $PythonBootstrap -m venv $BuildVenv
    }
    elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv $BuildVenv
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv $BuildVenv
    }
    else {
        throw "Python 3 was not found."
    }
}

& $BuildPython -m pip install --upgrade pip

# Install CPU-only Torch first so the Windows bundle does not include CUDA.
& $BuildPython -m pip install `
    "torch==2.12.1" `
    "torchvision==0.27.1" `
    --index-url "https://download.pytorch.org/whl/cpu"

& $BuildPython -m pip install -r (
    Join-Path $RootDir "requirements-build.txt"
)

& $BuildPython -c @"
import struct
import torch
assert struct.calcsize("P") * 8 == 64, "A 64-bit Python is required"
assert torch.version.cuda is None, "The Windows release must use CPU-only Torch"
"@

& $BuildPython -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $DistDir `
    --workpath $WorkDir `
    $SpecFile

$ExePath = Join-Path $OutputDir "Ascent Map Recognizer.exe"

if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
    throw "Build finished without producing the expected executable."
}

$env:ASCENT_RECOGNIZER_SMOKE_TEST = "1"
$env:ASCENT_RECOGNIZER_SMOKE_IMAGE = Join-Path $RootDir "assets\app_icon_transparent.png"
$SmokeProcess = Start-Process `
    -FilePath $ExePath `
    -Wait `
    -PassThru
Remove-Item Env:ASCENT_RECOGNIZER_SMOKE_TEST
Remove-Item Env:ASCENT_RECOGNIZER_SMOKE_IMAGE

if ($SmokeProcess.ExitCode -ne 0) {
    throw "The packaged application failed its startup smoke test."
}

if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

Compress-Archive `
    -Path (Join-Path $OutputDir "*") `
    -DestinationPath $ZipPath `
    -CompressionLevel Optimal

Write-Host "Windows executable: $ExePath"
Write-Host "Windows archive: $ZipPath"

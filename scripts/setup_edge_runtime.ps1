param(
    [Parameter(Mandatory = $true)]
    [string]$Python
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot

& $Python -m pip install -r (Join-Path $RepoRoot 'edge\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Edge dependency installation failed.' }

# EasyOCR and Ultralytics require their own OpenCV distribution names even
# though opencv-contrib already supplies the same cv2 package. Whichever wheel
# installs last owns cv2 on disk, so restore the contrib build deterministically.
& $Python -m pip install --force-reinstall --no-deps opencv-contrib-python-headless==4.10.0.84
if ($LASTEXITCODE -ne 0) { throw 'OpenCV contrib restoration failed.' }

& $Python -c "import cv2; assert hasattr(cv2, 'face') and hasattr(cv2.face, 'LBPHFaceRecognizer_create'); print('EDGE_OPENCV_OK', cv2.__version__)"
if ($LASTEXITCODE -ne 0) { throw 'OpenCV LBPH validation failed.' }

# 微信文章抓取工具 - 环境安装脚本
# 自动安装 Python 依赖和 Playwright 浏览器

param(
    [switch]$SkipPlaywright,
    [switch]$SkipOCR
)

$ErrorActionPreference = "Stop"

# 查找 Python
$python = $null
if ($env:PYTHON_PATH -and (Test-Path $env:PYTHON_PATH)) {
    $python = $env:PYTHON_PATH
} else {
    foreach ($cmd in @("python3", "python")) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($found) {
            $python = $found.Source
            break
        }
    }
}

if (-not $python) {
    Write-Error "未找到 Python 解释器。请设置环境变量 PYTHON_PATH 或确保 python3/python 在 PATH 中。"
    exit 1
}

Write-Host "使用 Python: $python" -ForegroundColor Green

# 安装 Python 依赖
Write-Host "`n=== 安装 Python 依赖 ===" -ForegroundColor Cyan
& $python -m pip install -r "$PSScriptRoot\requirements.txt" --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Error "Python 依赖安装失败"
    exit 1
}
Write-Host "Python 依赖安装完成" -ForegroundColor Green

# 安装 Playwright 浏览器
if (-not $SkipPlaywright) {
    Write-Host "`n=== 安装 Playwright 浏览器 ===" -ForegroundColor Cyan
    & $python -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Playwright 浏览器安装失败，将使用 requests 模式"
    } else {
        Write-Host "Playwright 浏览器安装完成" -ForegroundColor Green
    }
}

# 检查 OCR 支持
if (-not $SkipOCR) {
    Write-Host "`n=== 检查 OCR 支持 ===" -ForegroundColor Cyan

    # 检查 Tesseract 是否已安装
    $tesseract = Get-Command tesseract -ErrorAction SilentlyContinue
    if ($tesseract) {
        Write-Host "Tesseract OCR 已安装: $($tesseract.Source)" -ForegroundColor Green
    } else {
        Write-Warning "Tesseract OCR 未安装，图片文字提取功能将不可用"
        Write-Host "安装方式:" -ForegroundColor Yellow
        Write-Host "  1. 下载: https://github.com/UB-Mannheim/tesseract/wiki" -ForegroundColor Yellow
        Write-Host "  2. 或使用: choco install tesseract" -ForegroundColor Yellow
        Write-Host "  3. 或使用: winget install UB-Mannheim.TesseractOCR" -ForegroundColor Yellow
    }
}

Write-Host "`n=== 安装完成 ===" -ForegroundColor Green
Write-Host "运行示例:" -ForegroundColor Cyan
Write-Host "  .\run_fetch_wechat_article.ps1 --url 'https://mp.weixin.qq.com/s/xxx'"

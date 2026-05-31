param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

# 优先级: PYTHON_PATH 环境变量 > python3 命令 > python 命令 > Windows Store 默认路径
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
    $storePaths = @(
        "C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.13_*_x64__qbz5n2kfra8p0\python3.13.exe",
        "C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python3.13.exe"
    )
    $python = $storePaths | ForEach-Object { Get-Item $_ -ErrorAction SilentlyContinue } |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
}

if (-not $python) {
    Write-Error "未找到 Python 解释器。请设置环境变量 PYTHON_PATH 或确保 python3/python 在 PATH 中。"
    exit 1
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = Join-Path $scriptDir "scripts\fetch_wechat_article.py"

if (-not (Test-Path $scriptPath)) {
    Write-Error "Script not found: $scriptPath"
    exit 1
}

& $python $scriptPath @Args
$exitCode = $LASTEXITCODE
if ($null -ne $exitCode) {
    exit $exitCode
}

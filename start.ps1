# Run from PowerShell: .\start.ps1
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$paceBundledPython = Join-Path $PSScriptRoot '.python311-dist\tools\python.exe'
if (Test-Path -LiteralPath $paceBundledPython) {
    $env:PYTHONPATH = "$PSScriptRoot\.venv\Lib\site-packages;$PSScriptRoot"
    & $paceBundledPython -m streamlit run app.py --server.address 127.0.0.1 @args
} else {
    & "$PSScriptRoot\.venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 @args
}

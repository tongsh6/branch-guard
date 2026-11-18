$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:PYTHONPATH = "$root;$env:PYTHONPATH"
& py -3 -m branch_guard @args
exit $LASTEXITCODE

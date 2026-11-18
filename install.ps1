param(
    [switch]$Remove
)
$ErrorActionPreference = "Stop"
$bin = (Resolve-Path (Join-Path $PSScriptRoot "bin")).Path
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($null -eq $userPath) { $userPath = "" }
$entries = $userPath -split ';' | Where-Object { $_ -ne '' }
if ($Remove) {
    $new = ($entries | Where-Object { $_ -ne $bin }) -join ';'
    [Environment]::SetEnvironmentVariable("Path", $new, "User")
    Write-Host "已从用户 PATH 移除: $bin"
} else {
    if ($entries -contains $bin) {
        Write-Host "已在用户 PATH 中: $bin"
    } else {
        $new = (($entries + $bin) -join ';')
        [Environment]::SetEnvironmentVariable("Path", $new, "User")
        Write-Host "已加入用户 PATH: $bin（新开终端生效）"
    }
}

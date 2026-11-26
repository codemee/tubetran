<#
.SYNOPSIS
  Windows 版 ZIP 的「開視窗」煙霧測試：模擬使用者「從 GitHub 下載 ZIP → 解壓縮 → 雙擊」。

.DESCRIPTION
  --selftest 只載入 pythonnet、不開視窗，抓不到「視窗那一層」的問題。這個腳本會：
    1. 把 ZIP 解壓縮到暫存資料夾
    2. 替每個檔案加上「來自網際網路」標記（Zone.Identifier，ZoneId=3），就像瀏覽器下載的 ZIP 被檔案總管解壓縮
       （用 gh 下載、用 PowerShell 解壓縮都不會帶標記，所以不自己加就測不到這類問題）
    3. 直接啟動 TubeTran.exe（CreateProcess；不經過 shell，才不會跳出「無法驗證發行者」的對話框而卡住）
    4. 等主視窗出現：視窗類別是 WindowsForms…（pywebview 的視窗）才算成功。
       打不開時程式會跳出錯誤對話框（類別 #32770），它的標題也是「水管譯工」，所以不能只看標題。
  結束代碼：0 = 視窗正常開啟，1 = 失敗。

.PARAMETER NoMotw
  對照組：不加標記（用來確認「不加標記」本來就能開）。
.PARAMETER RemoveConfig
  對照組：刪掉 TubeTran.exe.config。帶標記時這必須失敗，證明這個測試真的抓得到問題，而不是永遠通過。

.EXAMPLE
  pwsh packaging/smoke_window.ps1 -Zip TubeTran-v0.1.28-windows-x64.zip
  pwsh packaging/smoke_window.ps1 -Zip TubeTran-v0.1.28-windows-x64.zip -RemoveConfig   # 對照組：必須失敗
#>
param(
  [Parameter(Mandatory = $true)][string]$Zip,
  [switch]$NoMotw,
  [switch]$RemoveConfig,
  [int]$TimeoutSeconds = 60
)
$ErrorActionPreference = "Stop"

Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class Win32Class {
  [DllImport("user32.dll", CharSet = CharSet.Unicode)]
  public static extern int GetClassName(IntPtr hWnd, StringBuilder name, int max);
  public static string Of(IntPtr h) { var sb = new StringBuilder(256); GetClassName(h, sb, 256); return sb.ToString(); }
}
'@

$dir = Join-Path ([System.IO.Path]::GetTempPath()) ("tubetran-smoke-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
Expand-Archive -Path $Zip -DestinationPath $dir
$exe = Join-Path $dir "TubeTran\TubeTran.exe"
if (-not (Test-Path $exe)) { Write-Host "找不到 $exe"; exit 1 }
$cfg = "$exe.config"
if ($RemoveConfig) { Remove-Item $cfg -Force -ErrorAction SilentlyContinue }
Write-Host ("TubeTran.exe.config：" + $(if (Test-Path $cfg) { "有" } else { "沒有" }))

if (-not $NoMotw) {
  Get-ChildItem $dir -Recurse -File | ForEach-Object {
    Set-Content -LiteralPath $_.FullName -Stream Zone.Identifier -Value "[ZoneTransfer]`r`nZoneId=3`r`nHostUrl=https://github.com/"
  }
}
$marked = (Get-ChildItem $dir -Recurse -File | Where-Object { Get-Item -LiteralPath $_.FullName -Stream Zone.Identifier -ErrorAction SilentlyContinue }).Count
Write-Host "解壓縮到 $dir；帶 Mark of the Web 的檔案：$marked 個"

# 不要動到使用者（或 CI 上別的步驟）的資料夾
$env:TUBETRAN_DATA_DIR = Join-Path $dir "data"
$psi = New-Object System.Diagnostics.ProcessStartInfo $exe
$psi.UseShellExecute = $false
$psi.WorkingDirectory = Split-Path $exe
$proc = [System.Diagnostics.Process]::Start($psi)

function Get-WindowInfo($p) {
  $p.Refresh()
  if ($p.MainWindowHandle -eq [IntPtr]::Zero) { return @{ Class = ""; Title = "" } }
  return @{ Class = [Win32Class]::Of($p.MainWindowHandle); Title = $p.MainWindowTitle }
}

$ok = $false; $info = @{ Class = ""; Title = "" }
for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
  Start-Sleep -Seconds 1
  $proc.Refresh()
  if ($proc.HasExited) { Write-Host "程式提早結束，結束代碼 $($proc.ExitCode)"; break }
  $info = Get-WindowInfo $proc
  if ($info.Class -like "WindowsForms*") { $ok = $true; break }
  if ($info.Class -eq "#32770") { Write-Host "跳出了對話框（錯誤視窗）：'$($info.Title)'"; break }
}
Write-Host "視窗類別：'$($info.Class)'  標題：'$($info.Title)'  已結束：$($proc.HasExited)"
if (-not $proc.HasExited) {
  # 視窗出現後再多等幾秒，確認沒有隨後跳出錯誤對話框（它屬於同一個行程，主視窗會被換掉）
  if ($ok) {
    Start-Sleep -Seconds 5
    $info = Get-WindowInfo $proc
    if ($info.Class -notlike "WindowsForms*") { $ok = $false; Write-Host "視窗後來變成 '$($info.Class)'（$($info.Title)）" }
  }
  Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 1
Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue
if ($ok) { Write-Host "OK：視窗正常開啟"; exit 0 } else { Write-Host "FAIL：視窗沒有正常開啟"; exit 1 }

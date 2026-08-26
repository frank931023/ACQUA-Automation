# 把這個服務登記成 Windows 排程工作,登入後自動啟動。
#
# 為什麼用「排程工作」而不是 Windows Service
# ──────────────────────────────────────────
# 這個程式要透過 COM 跟 ACQUA 講話,而 ACQUA 是**有畫面的桌面程式**,
# 活在使用者的互動式 session 裡。Windows Service 跑在 Session 0,
# 那裡沒有桌面,COM 也連不到使用者 session 裡的 ACQUA。
#
# 所以正確的做法是「使用者登入時啟動」的排程工作 —— 它跟 ACQUA
# 在同一個 session,權限與桌面都對得上。
#
# 用法:
#     以系統管理員開 PowerShell
#     .\tools\install_task.ps1                安裝
#     .\tools\install_task.ps1 -Uninstall     移除
#     .\tools\install_task.ps1 -Delay 120     登入後等 2 分鐘再啟動

param(
    [switch]$Uninstall,
    [int]$Delay = 60,                 # 等 ACQUA 先起來
    [string]$TaskName = "ACQUA Automation"
)

$ErrorActionPreference = "Stop"
$root   = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\pythonw.exe"     # w = 不開黑視窗
$script = Join-Path $root "app.py"
$logDir = Join-Path $root "logs"

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "已移除排程工作:$TaskName"
    exit 0
}

if (-not (Test-Path $python)) {
    Write-Error "找不到 $python`n先建立虛擬環境,步驟見 SETUP.md"
}
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# 啟動前先自檢 —— 條件不成立就不要硬啟動,把原因寫進 logs\preflight.log。
# 沒有這一步的話,出問題只會看到「今天的測試沒跑」而查不到原因。
$launcher = Join-Path $root "tools\start.cmd"
@"
@echo off
cd /d "%~dp0.."
".venv\Scripts\python.exe" tools\preflight.py > "logs\preflight.log" 2>&1
if errorlevel 1 (
  echo [%date% %time%] 自檢未通過,沒有啟動 >> "logs\service.log"
  exit /b 1
)
echo [%date% %time%] 啟動 >> "logs\service.log"
".venv\Scripts\python.exe" app.py >> "logs\service.log" 2>&1
"@ | Set-Content -Path $launcher -Encoding OEM

$action  = New-ScheduledTaskAction -Execute $launcher -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT${Delay}S"

# 互動式 session、最高權限、不因為沒插電或閒置而被停掉
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
    -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "已安裝排程工作:$TaskName"
Write-Host "  登入後等 $Delay 秒啟動(留時間給 ACQUA)"
Write-Host "  自檢紀錄:logs\preflight.log"
Write-Host "  執行紀錄:logs\service.log"
Write-Host ""
Write-Host "現在就試跑:Start-ScheduledTask -TaskName '$TaskName'"

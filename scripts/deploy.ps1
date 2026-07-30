# F93：把指定 commit 的快照展開到 deploy\current，正式站只吃這裡。
#
# 為什麼要這一步：先前正式站的 cwd 直接是工作目錄，**開發中的每一次存檔都即時對外**。
# 2026-07-30 實際出事——v91 帶著會產生重複組號的邏輯上線過，是 code review 問
# 「為什麼沒 bump 版號」才查出來的。快照化之後「線上版號」才真的代表「已驗收的版本」。
#
# 用法（在 repo 根目錄）：
#   .\scripts\deploy.ps1              # 部署 HEAD
#   .\scripts\deploy.ps1 -Ref v95     # 部署某個 tag/commit
#   .\scripts\deploy.ps1 -NoRestart   # 只換檔案不重啟（自己決定何時 restart）

[CmdletBinding()]
param(
    [string]$Ref = "HEAD",
    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"   # 前一步失敗就中止——F67 的教訓：多步驟腳本不中止會產出殘缺結果

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

# 工作樹不乾淨時要擋下來：git archive 打包的是 commit 的內容，
# 未 commit 的改動不會進去，但人會以為「我剛改的東西已經上線了」。
$dirty = git status --porcelain
if ($dirty) {
    Write-Host "工作樹有未 commit 的改動：" -ForegroundColor Yellow
    $dirty | ForEach-Object { Write-Host "  $_" }
    throw "拒絕部署——git archive 只會打包 $Ref 的內容，這些改動不會上線。先 commit 或 stash。"
}

$sha = (git rev-parse --short $Ref).Trim()
$deploy  = Join-Path $repo "deploy"
$staging = Join-Path $deploy "staging"
$current = Join-Path $deploy "current"
$previous = Join-Path $deploy "previous"

if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory -Force -Path $staging | Out-Null

# 展開快照：git archive 出 tar 再解開（Windows 內建 tar）
$tarball = Join-Path $deploy "snapshot.tar"
git archive --format=tar -o $tarball $Ref
tar -x -f $tarball -C $staging
Remove-Item $tarball

# 沒有 app/main.py 就是打包錯了，不要換上去
if (-not (Test-Path (Join-Path $staging "app\main.py"))) {
    throw "快照裡沒有 app\main.py——打包失敗，不換版。"
}

# 原子性換版：current → previous、staging → current（出事可以把 previous 換回來）
if (Test-Path $previous) { Remove-Item -Recurse -Force $previous }
if (Test-Path $current) { Move-Item $current $previous }
Move-Item $staging $current

$deployed = Join-Path $current ".deployed"
"ref=$Ref`nsha=$sha`nat=$(Get-Date -Format o)" | Set-Content -Path $deployed -Encoding utf8

Write-Host "已部署 $Ref ($sha) → deploy\current" -ForegroundColor Green

if ($NoRestart) {
    Write-Host "（-NoRestart：沒有重啟服務）"
    exit 0
}

# 重啟後確認真的活著；起不來就把上一版換回去
mission-control restart lift-log
Start-Sleep -Seconds 3
try {
    $health = Invoke-WebRequest -Uri "http://127.0.0.1:8137/health" -TimeoutSec 10 -UseBasicParsing
    if ($health.StatusCode -ne 200) { throw "health 回 $($health.StatusCode)" }
    Write-Host "正式站健康檢查 200，部署完成。" -ForegroundColor Green
} catch {
    Write-Host "部署後起不來：$_" -ForegroundColor Red
    if (Test-Path $previous) {
        Remove-Item -Recurse -Force $current
        Move-Item $previous $current
        mission-control restart lift-log
        Write-Host "已回退到上一版。" -ForegroundColor Yellow
    }
    throw
}

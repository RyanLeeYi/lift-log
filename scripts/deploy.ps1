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

# ⚠ $ErrorActionPreference **管不到原生指令**（git / tar）——它們失敗只是回非零 exit code，
# PowerShell 不會拋。2026-07-30 首次執行就踩到：tar 因中文檔名整批解壓失敗、腳本照樣往下跑、
# 還印出「已部署」。每個原生指令後面都要自己檢查。
function Invoke-Native {
    param([Parameter(Mandatory)][scriptblock]$Command, [string]$What)
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$What 失敗（exit $LASTEXITCODE）——不換版。" }
}

# 起停服務走 mission-control 的 REST API。
# ⚠ 不要用 `mission-control` 指令——**它不存在**（中台沒有裝 console script，
# 2026-07-30 部署時才發現這幾行從來沒能執行過；當時 Codex 用 -NoRestart 驗，
# 剛好繞過這條路徑）。API 才是中台實際對外的介面。
$MC = "http://127.0.0.1:18600/api/services"

# 中台 /api/* 有 Bearer token。**不得把 token 寫進這個 repo**——改從中台自己的
# .env 現讀（或用同名環境變數覆寫）。讀不到就直說，不要靜默跳過重啟：
# 那會留下「檔案換了、服務還跑舊碼」的半吊子狀態。
function Get-McToken {
    if ($env:MC_API_TOKEN) { return $env:MC_API_TOKEN }
    $mcEnv = Join-Path (Split-Path -Parent $repo) "mission-control\.env"
    if (-not (Test-Path $mcEnv)) { throw "找不到中台的 .env（$mcEnv），無法重啟服務。" }
    $line = Select-String -Path $mcEnv -Pattern '^\s*MC_API_TOKEN\s*=\s*(.+)$'
    if (-not $line) { throw "中台的 .env 沒有 MC_API_TOKEN，無法重啟服務。" }
    return $line.Matches[0].Groups[1].Value.Trim().Trim('"')
}

function Invoke-MissionControl {
    param([Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][string]$Action)
    $headers = @{ Authorization = "Bearer $(Get-McToken)" }
    $resp = Invoke-RestMethod -Method Post -Uri "$MC/$Name/$Action" -Headers $headers -TimeoutSec 30
    if (-not $resp.success) { throw "mission-control $Action $Name 失敗：$($resp.error)" }
}

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
# F161：正式站整包住在工作樹之外。工作樹底下不再有 deploy\，正式資料與 .env 也不在
# 這裡——所以在 repo 跑 `git clean -xdf` 不會再碰到正式站任何東西。
$prod = Join-Path (Split-Path -Parent $repo) "lift-log-prod"
if (-not (Test-Path $prod)) { throw "找不到正式站目錄 $prod——不換版。" }
$staging = Join-Path $prod "staging"
$current = Join-Path $prod "current"
$previous = Join-Path $prod "previous"
$venv         = Join-Path $prod ".venv"
$venvStaging  = Join-Path $prod ".venv-staging"
$venvPrevious = Join-Path $prod ".venv-previous"

if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory -Force -Path $staging | Out-Null

# 展開快照：git archive 出 tar 再解開（用 Windows 內建 tar）
#
# ⚠ 一定要走絕對路徑。裸打 `tar` 會依 PATH 順序解析，而 Git for Windows 也帶一支
# MSYS2 的 tar——它把 `C:\...` 當成「主機 C 的遠端路徑」，回
# `/usr/bin/tar: Cannot connect to C: resolve failed` 並 exit 128（2026-07-30 驗收在
# 另一台 PATH 順序不同的環境上實際踩到，本機剛好 System32 在前才沒發現）。
$tar = Join-Path $env:SystemRoot "System32\tar.exe"
if (-not (Test-Path $tar)) { throw "找不到 $tar——Windows 內建 tar 缺席，不換版。" }

$tarball = Join-Path $prod "snapshot.tar"
Invoke-Native { git archive --format=tar -o $tarball $Ref } "git archive"
Invoke-Native { & $tar -x -f $tarball -C $staging } "tar 解壓"
Remove-Item $tarball

# 逐項確認執行時要用到的東西都在——只檢查一個檔案不夠，
# tar 中途失敗時前面幾個目錄仍會存在，看起來像成功。
foreach ($must in @(
    "app\main.py", "app\static\index.html", "app\static\js\app.js",
    "app\static\js\state.js", "app\static\sw.js", "pyproject.toml"
)) {
    if (-not (Test-Path (Join-Path $staging $must))) {
        throw "快照缺少 $must——打包不完整，不換版。"
    }
}

# 版號要與來源一致（快照裡的 APP_VERSION 就是上線後畫面顯示的版號）
$snapVersion = (Select-String -Path (Join-Path $staging "app\static\js\state.js") `
    -Pattern 'APP_VERSION\s*=\s*"(v\d+)"').Matches[0].Groups[1].Value
Write-Host "快照版號：$snapVersion"

# ⚠ Windows 會鎖住「有程序以它為 cwd」的目錄——正式站跑起來之後，deploy\current
# 就搬不動也刪不掉，第二次部署會直接在這裡失敗，連回退路徑也一起壞掉（Codex P1）。
# F161：環境要跟著程式碼版本走，不能共用開發工作樹的 .venv——開發期的 uv sync 會直接
# 進正式站，這正是 F93 想擋的「開發改動流進正式站」，只是走的是相依而不是原始碼。
#
# 建到 .venv-staging 再換名，不是就地 sync：就地 sync 會動到正在跑的環境，中途失敗就
# 沒有可以啟動的正式站了。與 current/previous 同一套換名法，環境因此也有回退版。
$lock = Join-Path $staging "uv.lock"
if (-not (Test-Path $lock)) { throw "快照缺少 uv.lock——無法重建正式環境，不換版。" }
if (Test-Path $venvStaging) { Remove-Item -Recurse -Force $venvStaging }
Push-Location $staging
try {
    $env:UV_PROJECT_ENVIRONMENT = $venvStaging
    Invoke-Native { uv sync --frozen --no-dev } "uv sync（正式環境）"
} finally {
    Remove-Item Env:UV_PROJECT_ENVIRONMENT -ErrorAction SilentlyContinue
    Pop-Location
}
# 用實際執行檢查，不只看檔案在不在。並且刻意走 python.exe -m uvicorn：uv 建的
# .exe shim 把自己 venv 的絕對路徑寫死在 trampoline 裡，等一下 .venv-staging -> .venv
# 改名會讓 uvicorn.exe 直接壞掉（只印 Failed to canonicalize script path 就結束，
# 2026-08-20 F161 首次換版就是這樣失敗並回退的）。services.toml 也已改用 python.exe。
$prodPython = Join-Path $venvStaging "Scripts\python.exe"
if (-not (Test-Path $prodPython)) { throw "新環境缺少 python.exe——不換版。" }
Invoke-Native { & $prodPython -m uvicorn --version } "新環境 uvicorn 自我檢查"
Write-Host "正式環境已依快照 uv.lock 建好（.venv-staging）"

# 所以換版前先停服務。停機時間就是換目錄那幾秒，部署本來就不頻繁。
$serviceStopped = $false
if (-not $NoRestart) {
    Write-Host "換版前先停 lift-log（Windows 會鎖住執行中程序的 cwd）"
    Invoke-MissionControl -Name "lift-log" -Action "stop"
    Start-Sleep -Seconds 2
    $serviceStopped = $true
}

# current → previous、staging → current（出事可以把 previous 換回來）
if (Test-Path $previous) { Remove-Item -Recurse -Force $previous }
if (Test-Path $current) { Move-Item $current $previous }
Move-Item $staging $current

# 環境與程式碼同進同退
if (Test-Path $venvPrevious) { Remove-Item -Recurse -Force $venvPrevious }
if (Test-Path $venv) { Move-Item $venv $venvPrevious }
Move-Item $venvStaging $venv

$deployed = Join-Path $current ".deployed"
"ref=$Ref`nsha=$sha`nat=$(Get-Date -Format o)" | Set-Content -Path $deployed -Encoding utf8

Write-Host "已部署 $Ref ($sha) → deploy\current" -ForegroundColor Green

if (-not $serviceStopped) {
    Write-Host "（-NoRestart：沒有停機也沒有重啟；服務仍在跑舊目錄）"
    exit 0
}

Invoke-MissionControl -Name "lift-log" -Action "start"

# ⚠ 這裡原本是「睡 4 秒，打一次」——2026-08-16 部署 v154 時連兩次假失敗並自動回退，
# 服務其實好好的，只是 F147 之後開機多了 control DB 與各 user data DB 的初始化，
# 要 5~6 秒才聽得到 port。一次性檢查把「還沒起來」當成「起不來」，回退掉一個沒問題的版本。
# 改成輪詢：成功就往下走，真的死了才在 30 秒後回退。
# ⚠ 2026-08-20 第二次假失敗：v156 其實**有起來**（log 有 `Uvicorn running on 0.0.0.0:8137`
# 與 `Application startup complete`），只是超過當時的 30 秒門檻才聽到 port，於是被判死並回退。
# 啟動時間會隨 user data DB 數量繼續長，門檻放寬到 180 秒，並印出實際耗時——
# 下次要不要再調，看這個數字，不要再憑感覺。
try {
    $started = Get-Date
    $deadline = $started.AddSeconds(180)
    $ok = $false
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        try {
            $health = Invoke-WebRequest -Uri "http://127.0.0.1:8137/health" -TimeoutSec 5 -UseBasicParsing
            if ($health.StatusCode -eq 200) { $ok = $true; break }
        } catch { }   # 還沒聽 port＝連線被拒，屬預期，繼續等
    }
    if (-not $ok) { throw "180 秒內 health 沒有回 200" }
    $elapsed = [int]((Get-Date) - $started).TotalSeconds
    Write-Host "正式站健康檢查 200（起來花了 ${elapsed}s），部署完成。" -ForegroundColor Green
} catch {
    Write-Host "部署後起不來：$_" -ForegroundColor Red
    if (Test-Path $previous) {
        # 回退同樣要先停——服務可能已經起來並鎖住 current（Codex P1 的同一個問題）
        Invoke-MissionControl -Name "lift-log" -Action "stop"
        Start-Sleep -Seconds 2
        Remove-Item -Recurse -Force $current
        Move-Item $previous $current
        if (Test-Path $venvPrevious) {
            if (Test-Path $venv) { Remove-Item -Recurse -Force $venv }
            Move-Item $venvPrevious $venv
        }
        Invoke-MissionControl -Name "lift-log" -Action "start"
        Write-Host "已回退到上一版。" -ForegroundColor Yellow
    }
    throw
}

# F93 ⑤⑦：出一顆 APK，並在產出後**驗證它真的是你以為的那顆**。
#
# 為什麼要驗：這條流程有兩個會安靜出錯的地方——
#   1. 改寫 env.js 的 SITE 若失敗，會得到「檔名寫 dev、實際連正式站」的 APK，
#      而它會把測試資料寫進你的真實訓練紀錄，沒有任何錯誤訊息。
#   2. 漏跑 `cap sync` 的話 APK 內是舊畫面（F67 踩過；當時 build 腳本前一步失敗不中止，
#      產出 v72 的內容卻叫做 v73，系統只看 versionCode，檔名不管）。
# 所以最後一定要從 APK 裡把 env.js 解出來核對，並用 aapt2 核對 applicationId。
#
# 用法（在 repo 根目錄）：
#   .\scripts\build-apk.ps1 -Site prod
#   .\scripts\build-apk.ps1 -Site dev
#   .\scripts\build-apk.ps1 -Site prod -Tag F93     # 檔名帶 feature id

[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet("prod", "dev")][string]$Site,
    [string]$Tag = ""
)

$ErrorActionPreference = "Stop"

# $ErrorActionPreference 管不到原生指令（gradle / npx / aapt2）——它們失敗只回非零 exit code。
function Invoke-Native {
    param([Parameter(Mandatory)][scriptblock]$Command, [string]$What)
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$What 失敗（exit $LASTEXITCODE）" }
}

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"

$envJs = Join-Path $repo "app\static\js\env.js"
$original = Get-Content $envJs -Raw

$expectedBase = if ($Site -eq "dev") {
    "https://lift-log-dev.my-super-dev-server.work"
} else {
    "https://lift-log.my-super-dev-server.work"
}
$expectedAppId = if ($Site -eq "dev") { "com.ryanleeyi.liftlog.dev" } else { "com.ryanleeyi.liftlog" }
$flavor = if ($Site -eq "dev") { "Dev" } else { "Prod" }

try {
    # 1) 改寫 SITE，並確認真的改到了（str.replace 靜默跳過是 F54 踩過的坑）
    $patched = $original -replace 'const SITE = "(prod|dev)";', "const SITE = `"$Site`";"
    if ($patched -notmatch [regex]::Escape("const SITE = `"$Site`";")) {
        throw "改寫 env.js 的 SITE 失敗——格式可能變了，停手不出貨。"
    }
    Set-Content -Path $envJs -Value $patched -NoNewline -Encoding utf8

    $version = ([regex]::Match(
        (Get-Content (Join-Path $repo "app\static\js\state.js") -Raw),
        'APP_VERSION\s*=\s*"(v\d+)"')).Groups[1].Value
    if (-not $version) { throw "讀不到 APP_VERSION" }
    Write-Host "建置 $Site 版 $version（applicationId $expectedAppId）"

    # 2) 同步資產 → 組 APK
    Invoke-Native { npx cap sync android } "cap sync"
    Invoke-Native { & "$repo\android\gradlew.bat" -p android "assemble${flavor}Release" } "gradle assemble"

    $apk = Join-Path $repo "android\app\build\outputs\apk\$($Site)\release\app-$Site-release.apk"
    if (-not (Test-Path $apk)) { throw "找不到產出的 APK：$apk" }

    # 3) 驗證產出物——這一段才是這支腳本存在的理由
    $badging = & "$env:ANDROID_HOME\build-tools\36.0.0\aapt2.exe" dump badging $apk
    if ($LASTEXITCODE -ne 0) { throw "aapt2 讀不到這顆 APK" }
    $actualAppId = ([regex]::Match($badging -join "`n", "package: name='([^']+)'")).Groups[1].Value
    if ($actualAppId -ne $expectedAppId) {
        throw "APK 的 applicationId 是 $actualAppId，預期 $expectedAppId——不出貨。"
    }

    # 從 APK 內解出 env.js，核對它連的是哪一站
    $tmp = Join-Path $env:TEMP "liftlog-apk-verify-$(Get-Random)"
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [System.IO.Compression.ZipFile]::OpenRead($apk)
        try {
            $entry = $zip.Entries | Where-Object { $_.FullName -eq "assets/public/js/env.js" }
            if (-not $entry) { throw "APK 內找不到 assets/public/js/env.js——cap sync 可能沒跑到。" }
            $reader = New-Object System.IO.StreamReader($entry.Open())
            $packed = $reader.ReadToEnd()
            $reader.Close()
        } finally { $zip.Dispose() }

        if ($packed -notmatch [regex]::Escape("const SITE = `"$Site`";")) {
            throw "APK 內的 env.js 不是 $Site——打包到舊資產了，不出貨。"
        }
        if ($packed -notmatch [regex]::Escape($expectedBase)) {
            throw "APK 內的 env.js 沒有預期的網址 $expectedBase——不出貨。"
        }
    } finally { Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue }

    # 4) 收工：命名、複製到 release 目錄與 Google Drive
    $suffix = if ($Tag) { "-$Tag" } else { "" }
    $name = if ($Site -eq "dev") { "lift-log-dev-$version$suffix.apk" } else { "lift-log-$version$suffix.apk" }

    $releaseDir = Join-Path $repo $(if ($Site -eq "dev") { "release-dev" } else { "release" })
    New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
    # 自我更新的來源目錄。檔名**兩站都用 `lift-log-v<N>.apk`**——後端的
    # APK_PATTERN 是 `^lift-log-v(\d+)\.apk$`，帶 `-dev` 或 tag 都不匹配，
    # 那會讓 dev 版永遠查不到更新（而且是靜默的：目錄有檔案但解析不到）。
    # 兩站靠 LIFTLOG_RELEASE_DIR 分目錄，不靠檔名。
    Copy-Item $apk (Join-Path $releaseDir "lift-log-$version.apk") -Force

    $drive = "G:\我的雲端硬碟\lift-log-apk"
    if (Test-Path $drive) {
        Copy-Item $apk (Join-Path $drive $name) -Force
        Write-Host "已複製到 Google Drive：$name" -ForegroundColor Green
    } else {
        Write-Host "找不到 $drive——只放了 $releaseDir" -ForegroundColor Yellow
    }

    Write-Host "✓ $Site 版建置完成並驗證：applicationId=$actualAppId、env.js 指向 $expectedBase" -ForegroundColor Green
}
finally {
    # 一定要把 env.js 還原成 prod，否則工作目錄會留著 dev 設定，
    # 而 web 版（測試站與正式站都由它供檔）不受 SITE 影響、不會有人發現。
    Set-Content -Path $envJs -Value $original -NoNewline -Encoding utf8
}

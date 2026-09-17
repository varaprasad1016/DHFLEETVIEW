<#
Nightly backup of everything DH FleetView needs to be rebuilt.

  D:\Backups\dhfleetview\<yyyy-MM-dd_HHmm>\
    tacho.dump            Postgres (tacho server: compliance data, drivers, jobs, licence)
    tacho-files.zip       archived .ddd files, walkaround / shift photos, paperwork
    tacho-env.txt         tacho server settings (.env: keys needed to restore)
    traccar-database.mv.db  DH FleetView database (copied from a shadow copy, then test-opened)
    traccar-conf.zip      DH FleetView config + media
    manifest.json         sizes, checks, result

Keeps the last 14 nightly backups plus the first backup of each month for 12 months.
Writes D:\Backups\dhfleetview\last-backup.json, which the compliance hub shows to the
super administrator. Run as SYSTEM (shadow copies need administrator rights):

  powershell -NoProfile -ExecutionPolicy Bypass -File C:\tachograph-server\scripts\backup.ps1
#>
param(
    [string]$Root = "D:\Backups\dhfleetview",
    [int]$KeepDaily = 14,
    [int]$KeepMonthly = 12
)

$ErrorActionPreference = "Stop"
$started = Get-Date
$stamp = $started.ToString("yyyy-MM-dd_HHmm")
$dest = Join-Path $Root $stamp
$tacho = "C:\tachograph-server"
$traccar = "C:\DHFleetView"
$log = Join-Path $Root "backup.log"
$checks = [ordered]@{}
New-Item -ItemType Directory -Force -Path $dest | Out-Null

function Log($msg) { $line = "{0} {1}" -f (Get-Date -Format s), $msg; Add-Content -Path $log -Value $line; Write-Output $line }

$shadow = $null
$link = "C:\ProgramData\dhfv-backup-shadow"
try {
    Log "backup $stamp started"

    # --- tacho server database -------------------------------------------------------------
    $env_text = Get-Content (Join-Path $tacho ".env") -Raw
    if ($env_text -notmatch 'DATABASE_URL=postgresql\+asyncpg://([^:]+):([^@]+)@([^:/]+):(\d+)/(\S+)') { throw "DATABASE_URL not found in .env" }
    $pgUser, $pgPass, $pgHost, $pgPort, $pgDb = $Matches[1], $Matches[2], $Matches[3], $Matches[4], $Matches[5]
    $pgBin = Join-Path $tacho ".runtime\pgsql\bin"
    $env:PGPASSWORD = $pgPass
    $dump = Join-Path $dest "tacho.dump"
    & (Join-Path $pgBin "pg_dump.exe") -h $pgHost -p $pgPort -U $pgUser -d $pgDb -Fc -f $dump
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed ($LASTEXITCODE)" }
    $tables = (& (Join-Path $pgBin "pg_restore.exe") --list $dump | Select-String "TABLE DATA").Count
    if ($LASTEXITCODE -ne 0 -or $tables -lt 10) { throw "tacho dump did not verify ($tables tables)" }
    $checks["tacho_database"] = "ok: $tables tables"
    Log "tacho database dumped ($tables tables)"

    # --- tacho files + settings --------------------------------------------------------------
    $filesZip = Join-Path $dest "tacho-files.zip"
    Compress-Archive -Path (Join-Path $tacho "data\*") -DestinationPath $filesZip -CompressionLevel Optimal
    Copy-Item (Join-Path $tacho ".env") (Join-Path $dest "tacho-env.txt")
    $checks["tacho_files"] = "ok: " + [math]::Round((Get-Item $filesZip).Length / 1MB, 1) + " MB"
    Log "tacho files archived"

    # --- DH FleetView (H2 database is locked while running: copy it from a shadow copy) -------
    $created = (Get-WmiObject -List Win32_ShadowCopy).Create("C:\", "ClientAccessible")
    if ($created.ReturnValue -ne 0) { throw "shadow copy failed ($($created.ReturnValue))" }
    $shadow = Get-WmiObject Win32_ShadowCopy | Where-Object { $_.ID -eq $created.ShadowID }
    if (Test-Path $link) { cmd /c rmdir "$link" | Out-Null }
    cmd /c mklink /d "$link" "$($shadow.DeviceObject)\" | Out-Null
    $h2copy = Join-Path $dest "traccar-database.mv.db"
    Copy-Item (Join-Path $link "DHFleetView\data\database.mv.db") $h2copy
    Compress-Archive -Path (Join-Path $link "DHFleetView\conf"), (Join-Path $link "DHFleetView\media") -DestinationPath (Join-Path $dest "traccar-conf.zip")
    cmd /c rmdir "$link" | Out-Null
    $shadow.Delete(); $shadow = $null

    # Prove the copy opens and has data.
    $h2jar = Get-ChildItem (Join-Path $traccar "lib") -Filter "h2-*.jar" | Select-Object -First 1
    $java = (Get-Command java -ErrorAction SilentlyContinue).Source
    if (-not $java) { $java = Get-ChildItem "C:\Program Files\Eclipse Adoptium" -Recurse -Filter java.exe | Select-Object -First 1 -ExpandProperty FullName }
    $probe = Join-Path $env:TEMP ("dhfv-h2-" + $stamp)
    New-Item -ItemType Directory -Force -Path $probe | Out-Null
    Copy-Item $h2copy (Join-Path $probe "database.mv.db")
    $url = "jdbc:h2:" + ($probe -replace '\\', '/') + "/database"
    # (no -password: the password is blank, and Windows PowerShell drops empty arguments)
    $out = & $java -cp $h2jar.FullName org.h2.tools.Shell -url $url -user sa -sql "SELECT COUNT(*) FROM TC_DEVICES" 2>&1
    Remove-Item $probe -Recurse -Force
    $devices = ($out | Select-String '^\s*\d+\s*$' | Select-Object -First 1).ToString().Trim()
    if (-not $devices) { throw "DH FleetView database copy did not open: $out" }
    $checks["traccar_database"] = "ok: $devices devices, " + [math]::Round((Get-Item $h2copy).Length / 1MB, 1) + " MB"
    Log "DH FleetView database copied and verified ($devices devices)"

    $result = "ok"
}
catch {
    $result = "failed: " + $_.Exception.Message
    Log $result
}
finally {
    if (Test-Path $link) { cmd /c rmdir "$link" | Out-Null }
    if ($shadow) { try { $shadow.Delete() } catch {} }
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}

$sizeMB = [math]::Round(((Get-ChildItem $dest -File | Measure-Object Length -Sum).Sum) / 1MB, 1)
$manifest = [ordered]@{ started = $started.ToString("o"); finished = (Get-Date).ToString("o"); folder = $dest; size_mb = $sizeMB; result = $result; checks = $checks }
$manifest | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 (Join-Path $dest "manifest.json")

# Last result for the hub; last *successful* backup kept separately.
$statusFile = Join-Path $Root "last-backup.json"
$previous = $null
if (Test-Path $statusFile) { try { $previous = Get-Content $statusFile -Raw | ConvertFrom-Json } catch {} }
$status = [ordered]@{
    last_run = $manifest.finished; last_result = $result; last_folder = $dest; last_size_mb = $sizeMB; checks = $checks
    last_success = $(if ($result -eq "ok") { $manifest.finished } elseif ($previous) { $previous.last_success } else { $null })
}
$status | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 $statusFile

# --- retention: newest $KeepDaily folders, plus the first folder of each of the last $KeepMonthly months --
$folders = Get-ChildItem $Root -Directory | Where-Object { $_.Name -match '^\d{4}-\d{2}-\d{2}_\d{4}$' } | Sort-Object Name -Descending
$keep = @{}
$folders | Select-Object -First $KeepDaily | ForEach-Object { $keep[$_.Name] = $true }
$folders | Group-Object { $_.Name.Substring(0, 7) } | Sort-Object Name -Descending | Select-Object -First $KeepMonthly |
    ForEach-Object { $first = $_.Group | Sort-Object Name | Select-Object -First 1; $keep[$first.Name] = $true }
foreach ($f in $folders) {
    if (-not $keep.ContainsKey($f.Name)) { Remove-Item $f.FullName -Recurse -Force; Log "removed old backup $($f.Name)" }
}

Log "backup $stamp finished: $result ($sizeMB MB)"
if ($result -ne "ok") { exit 1 }

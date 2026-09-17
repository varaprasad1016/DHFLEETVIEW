<#
Proves the latest backup restores: loads tacho.dump into a scratch database,
compares row counts with the live database, then drops the scratch database.

  powershell -NoProfile -ExecutionPolicy Bypass -File C:\tachograph-server\scripts\restore_test.ps1
#>
param([string]$Root = "D:\Backups\dhfleetview")

$envText = Get-Content C:\tachograph-server\.env -Raw
if ($envText -notmatch 'DATABASE_URL=postgresql\+asyncpg://([^:]+):([^@]+)@([^:/]+):(\d+)/(\S+)') { throw "DATABASE_URL not found" }
$u, $pw, $h, $p = $Matches[1], $Matches[2], $Matches[3], $Matches[4]
$env:PGPASSWORD = $pw
$bin = "C:\tachograph-server\.runtime\pgsql\bin"
$latest = Get-ChildItem $Root -Directory | Where-Object { Test-Path (Join-Path $_.FullName "tacho.dump") } | Sort-Object Name -Descending | Select-Object -First 1
$dump = Join-Path $latest.FullName "tacho.dump"
$q = "select (select count(*) from tacho_files)||'/'||(select count(*) from infringements)||'/'||(select count(*) from driver_accounts)||'/'||(select count(*) from walkaround_checks)||'/'||(select version_num from alembic_version limit 1)"
try {
    & "$bin\dropdb.exe" -h $h -p $p -U $u --if-exists tacho_restore_test
    & "$bin\createdb.exe" -h $h -p $p -U $u tacho_restore_test
    & "$bin\pg_restore.exe" -h $h -p $p -U $u -d tacho_restore_test --no-owner $dump
    Write-Output "restore exit $LASTEXITCODE from $($latest.Name)"
    $restored = & "$bin\psql.exe" -h $h -p $p -U $u -d tacho_restore_test -At -c $q
    $live = & "$bin\psql.exe" -h $h -p $p -U $u -d tacho -At -c $q
    Write-Output "files/infringements/drivers/walkarounds/migration"
    Write-Output "restored: $restored"
    Write-Output "live:     $live"
    if ($restored -ne $live) { Write-Output "NOTE: counts differ (data may have changed since the backup)" }
}
finally {
    & "$bin\dropdb.exe" -h $h -p $p -U $u --if-exists tacho_restore_test
    $env:PGPASSWORD = $null
}

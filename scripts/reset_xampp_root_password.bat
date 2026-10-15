@echo off
rem ======================================================================
rem  Reset the XAMPP MySQL (MariaDB) root password.
rem  Only the root password changes. No databases or tables are touched.
rem
rem  Before running: click "Stop" next to MySQL in XAMPP Control Panel.
rem  Then double-click this file.
rem ======================================================================
title Reset XAMPP MySQL root password
powershell -NoProfile -ExecutionPolicy Bypass -Command "iex ((Get-Content -Raw -LiteralPath '%~f0') -split '#PS-START#')[2]"
echo.
pause
exit /b

#PS-START#
$ErrorActionPreference = 'Continue'
$bin    = 'C:\xampp\mysql\bin'
$ini    = Join-Path $bin 'my.ini'
$mysqld = Join-Path $bin 'mysqld.exe'
$mysql  = Join-Path $bin 'mysql.exe'
$admin  = Join-Path $bin 'mysqladmin.exe'
$errlog = 'C:\xampp\mysql\data\mysql_error.log'
$OutputEncoding = New-Object System.Text.UTF8Encoding $false

function Fail($msg) {
    Write-Host ''
    Write-Host $msg -ForegroundColor Red
    Write-Host 'Nothing was changed. Take a photo/screenshot of this window for your support person.'
}

function Read-Secret($prompt) {
    $s = Read-Host $prompt -AsSecureString
    $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
    try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}

Write-Host ''
Write-Host 'XAMPP MySQL - reset root password' -ForegroundColor Cyan
Write-Host 'Only the root password changes. Your databases are not touched.'
Write-Host 'Do NOT close this window until it says DONE.' -ForegroundColor Yellow
Write-Host ''

if (-not (Test-Path $mysqld)) { Fail "XAMPP MySQL not found at $bin"; return }

if (Get-Process -Name mysqld -ErrorAction SilentlyContinue) {
    Fail ("MySQL is still running.`n" +
          "Click 'Stop' next to MySQL in XAMPP Control Panel, wait until it is not green,`n" +
          "then double-click this file again.")
    return
}

Write-Host 'Step 1 of 3: starting MySQL in recovery mode (up to 30 seconds)...'
$server = Start-Process -FilePath $mysqld -WindowStyle Hidden -PassThru -ArgumentList @(
    "--defaults-file=$ini", '--standalone', '--skip-grant-tables', '--bind-address=127.0.0.1')

$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 750
    if ($server.HasExited) { break }
    & $mysql -u root -h 127.0.0.1 --connect-timeout=3 -e 'SELECT 1' 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
}
if (-not $ready) {
    if (-not $server.HasExited) { Stop-Process -Id $server.Id -Force }
    Fail 'MySQL could not start in recovery mode. Last lines of the MySQL error log:'
    if (Test-Path $errlog) { Get-Content $errlog -Tail 12 | ForEach-Object { Write-Host "   $_" } }
    return
}
Write-Host '   OK' -ForegroundColor Green

Write-Host ''
Write-Host 'Step 2 of 3: choose the new root password.'
Write-Host '   At least 8 characters. Your typing will be INVISIBLE - that is normal.'
while ($true) {
    $pw = Read-Secret '   New root password'
    if ($pw.Length -lt 8) { Write-Host '   Too short, try again.' -ForegroundColor Yellow; continue }
    $pw2 = Read-Secret '   Type it again'
    if ($pw -cne $pw2) { Write-Host '   They do not match, try again.' -ForegroundColor Yellow; continue }
    break
}

$esc = $pw.Replace('\', '\\').Replace("'", "''")
$sql = "FLUSH PRIVILEGES;`n" +
       "ALTER USER IF EXISTS 'root'@'localhost' IDENTIFIED BY '$esc';`n" +
       "ALTER USER IF EXISTS 'root'@'127.0.0.1' IDENTIFIED BY '$esc';`n" +
       "ALTER USER IF EXISTS 'root'@'::1' IDENTIFIED BY '$esc';`n"
$sql | & $mysql -u root -h 127.0.0.1 --default-character-set=utf8mb4
$changed = ($LASTEXITCODE -eq 0)
$esc = $null; $sql = $null

Write-Host ''
Write-Host 'Step 3 of 3: shutting down recovery mode...'
$env:MYSQL_PWD = $pw
& $admin -u root -h 127.0.0.1 --connect-timeout=5 --shutdown-timeout=15 shutdown 2>$null
Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
$pw = $null; $pw2 = $null
if (-not $server.WaitForExit(20000)) {
    Write-Host '   Recovery mode did not stop by itself; closing it now.'
    Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}
if (Get-Process -Id $server.Id -ErrorAction SilentlyContinue) {
    Fail ("Recovery-mode MySQL is still running (process $($server.Id)).`n" +
          "In an administrator Command Prompt run:  taskkill /PID $($server.Id) /F")
    return
}
Write-Host '   OK' -ForegroundColor Green

if (-not $changed) { Fail 'The password could not be changed (see the message above).'; return }

Write-Host ''
Write-Host 'DONE - the root password has been changed.' -ForegroundColor Green
Write-Host 'Write it down somewhere safe.'
Write-Host "Now click 'Start' next to MySQL in XAMPP Control Panel."

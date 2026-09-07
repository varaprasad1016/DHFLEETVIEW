@echo off
setlocal
set "JAVA=C:\Program Files\Eclipse Adoptium\jdk-21.0.12.101-hotspot\bin\java.exe"
echo [1/3] Stopping tracker (to unlock the database)...
taskkill /F /IM java.exe >nul 2>&1
timeout /t 6 /nobreak >nul
echo [2/3] Inserting the 3 vehicles...
"%JAVA%" -cp "C:\DHFleetView\lib\h2-2.4.240.jar" org.h2.tools.RunScript -url "jdbc:h2:C:/DHFleetView/data/database" -user sa -password "" -script "C:\DHFleetView\tools\add_devices.sql" -showResults
echo [3/3] Restarting tracker...
start "" "C:\DHFleetView\start-server.bat"
echo.
echo Done. Above you should see 3 device rows (G11JHL / G12JHL / G14PRB) and 3 permission rows.
endlocal

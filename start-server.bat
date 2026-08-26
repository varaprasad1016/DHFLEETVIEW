@echo off
cd /d C:\DHFleetView
"C:\Program Files\Eclipse Adoptium\jdk-21.0.12.101-hotspot\bin\java.exe" -XX:+ExitOnOutOfMemoryError -Duser.dir="C:\DHFleetView" -jar "C:\DHFleetView\tracker-server.jar" "C:\DHFleetView\conf\traccar.xml"

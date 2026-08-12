@echo off
REM Run this if you ever want to STOP automatic posting.
REM (Right-click -> "Run as administrator")

schtasks /delete /tn "LinkedInAutoPoster_Dispatch" /f

echo.
echo Automatic posting has been stopped. The task no longer exists.
echo You can register it again anytime by running setup_scheduled_task.bat
pause
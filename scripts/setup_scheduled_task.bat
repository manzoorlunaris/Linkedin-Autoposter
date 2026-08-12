@echo off
REM ============================================================
REM Run this ONCE (right-click -> "Run as administrator") to set
REM up automatic posting. It registers a Windows Scheduled Task
REM that runs run_dispatch.bat every 5 minutes, forever — even if
REM VS Code and this terminal are closed.
REM ============================================================

schtasks /create ^
  /tn "LinkedInAutoPoster_Dispatch" ^
  /tr "\"D:\linkedin project\linkedin_autoposter\scripts\run_dispatch.bat\"" ^
  /sc minute ^
  /mo 5 ^
  /st 00:00 ^
  /f

echo.
echo ============================================================
echo Done. The task "LinkedInAutoPoster_Dispatch" is now registered
echo and will run every 5 minutes automatically.
echo.
echo To verify: open Task Scheduler (search it in Start Menu) and
echo look for "LinkedInAutoPoster_Dispatch" in the task list.
echo.
echo To check it's actually posting: open
echo   D:\linkedin project\linkedin_autoposter\logs\dispatch.log
echo after a few minutes and you'll see run entries appear.
echo ============================================================
pause
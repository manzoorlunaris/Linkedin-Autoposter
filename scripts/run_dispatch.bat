@echo off
REM Runs the auto-posting check once. Task Scheduler calls this every 5 minutes.
REM Logs go to logs\dispatch.log so you can see what happened even if you weren't watching.

cd /d "D:\linkedin project\linkedin_autoposter"

if not exist "logs" mkdir "logs"

call venv\Scripts\activate.bat
python manage.py dispatch_due_posts >> logs\dispatch.log 2>&1

echo ---------------------------------------------- >> logs\dispatch.log
echo Ran at %date% %time% >> logs\dispatch.log
echo ---------------------------------------------- >> logs\dispatch.log
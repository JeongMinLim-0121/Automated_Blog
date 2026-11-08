@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "..\..\.env" (copy "..\..\.env.example" "..\..\.env" >nul & echo 최상위 .env 파일이 만들어졌습니다. & notepad "..\..\.env")
python run.py check
pause

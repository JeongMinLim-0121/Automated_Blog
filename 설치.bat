@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install -r requirements.txt
python -m playwright install chromium
echo 설치 명령 실행 완료. 위쪽 오류가 없는지 확인하세요.
pause

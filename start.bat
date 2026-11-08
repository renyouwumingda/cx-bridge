@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  cx-bridge  本地桥接服务
echo  装脚本：http://127.0.0.1:8790/cx-agent.user.js
echo  自检页：http://127.0.0.1:8790/fixture-real
echo  关掉这个窗口服务就停了
echo ============================================
set PYTHONIOENCODING=utf-8
python server.py
pause

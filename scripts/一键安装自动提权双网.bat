@echo off
chcp 65001 >nul
title W49 双网自动提权（仅首次需点「是」）
echo.
echo  将注册最高权限计划任务：登录/开机自动双网合并
echo  仅此窗口会弹一次 UAC，以后不再询问
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0win_register_auto_elevate.ps1"
echo.
pause

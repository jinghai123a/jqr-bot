@echo off
chcp 65001 >nul
echo 双网合并：1211 WiFi + 有线（需管理员）
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"\"%~dp0win_dual_wan_merge_admin.ps1\"\"'"
pause

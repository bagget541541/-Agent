@echo off
chcp 65001 >nul 2>nul
title Credit Card Weekly Report

echo ============================================================
echo           Credit Card Weekly Report Automation
echo ============================================================
echo.

REM Display last run time
if exist "data\last_run.json" (
    python -c "import json; d=json.load(open('data/last_run.json','r',encoding='utf-8')); print(f'Last run: {d.get(\"last_run\",\"Never\")}')"
) else (
    echo Last run: Never
)
echo.

echo Select mode:
echo.
echo   [A] Full pipeline - WeChat URLs + Bank scraping + Webpage URLs -^> Report
echo   [B] Merge mode - Existing Word docs -^> Merge + Suggestions -^> Output
echo   [C] Quick mode - Step 1-4 only -^> Markdown with images (skip Step5-6)
echo   [Q] Exit
echo.
set /p choice=Enter choice (A/B/C/Q, default A):
if "%choice%"=="" set choice=A

if /i "%choice%"=="A" goto :mode_a
if /i "%choice%"=="a" goto :mode_a
if /i "%choice%"=="B" goto :mode_b
if /i "%choice%"=="b" goto :mode_b
if /i "%choice%"=="C" goto :mode_c
if /i "%choice%"=="c" goto :mode_c
if /i "%choice%"=="Q" goto :end
if /i "%choice%"=="q" goto :end

echo Invalid choice, please run again
pause
goto :end

:mode_a
echo.
echo ============================================================
echo   Mode A: Full Pipeline (Scrape + Generate Report)
echo ============================================================
echo.
echo Enter URL(s) — paste one or more links, or leave blank to skip:
echo.
set /p wechat_urls=WeChat article URL(s) (空格分隔):
set /p webpage_urls=Webpage URL(s) (信用卡产品页/新闻等, 空格分隔):
echo.
set args=--mode a
if not "%wechat_urls%"=="" set args=%args% --wechat-url %wechat_urls%
if not "%webpage_urls%"=="" set args=%args% --webpage-url %webpage_urls%
echo python _agent.py %args%
python _agent.py %args%
goto :done

:mode_b
echo.
echo ============================================================
echo   Mode B: Merge Mode (Existing Docs + Suggestions)
echo ============================================================
echo.
python run_pipeline.py --mode b
goto :done

:mode_c
echo.
echo ============================================================
echo   Mode C: Quick Mode (Step 1-4 only -^> Markdown with images)
echo ============================================================
echo.
echo Enter URL(s) — paste one or more links, or leave blank to skip:
echo.
set /p wechat_urls=WeChat article URL(s) (空格分隔):
set /p webpage_urls=Webpage URL(s) (信用卡产品页/新闻等, 空格分隔):
echo.
set args=--mode c
if not "%wechat_urls%"=="" set args=%args% --wechat-url %wechat_urls%
if not "%webpage_urls%"=="" set args=%args% --webpage-url %webpage_urls%
echo python _agent.py %args%
python _agent.py %args%
goto :done

:done
echo.
echo ============================================================
echo   Done!
echo ============================================================
echo.
pause

:end

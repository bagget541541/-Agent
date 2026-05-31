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
echo   [A] Full pipeline - WeChat URLs + Bank scraping -> Generate report
echo   [B] Merge mode - Existing Word docs -> Merge + Suggestions -> Output
echo   [Q] Exit
echo.
set /p choice=Enter choice (A/B/Q, default A):
if "%choice%"=="" set choice=A

if /i "%choice%"=="A" goto :mode_a
if /i "%choice%"=="a" goto :mode_a
if /i "%choice%"=="B" goto :mode_b
if /i "%choice%"=="b" goto :mode_b
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
python run_pipeline.py --mode a
goto :done

:mode_b
echo.
echo ============================================================
echo   Mode B: Merge Mode (Existing Docs + Suggestions)
echo ============================================================
echo.
python run_pipeline.py --mode b
goto :done

:done
echo.
echo ============================================================
echo   Done!
echo ============================================================
echo.
pause

:end

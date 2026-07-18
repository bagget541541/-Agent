@echo off
chcp 65001 >nul 2>nul
set PYTHONIOENCODING=utf-8
set PYTHONLEGACYWINDOWSSTDIO=utf-8
title Credit Card Weekly Report

echo ============================================================
echo           Credit Card Weekly Report Automation
echo ============================================================
echo.

REM Display last run time + days ago + suggested bank_days
python -X utf8 scripts\show_last_run.py
echo.

echo Select mode:
echo.
echo   [A] Full pipeline
echo       WeChat URLs + Bank scraping (Step1-2) + Webpage URLs
echo       -^> Step3-6 生成 Word 报告 (含摘要/评分/建议)
echo       示例: python _agent.py --mode a --wechat-url "https://mp.weixin.qq.com/s/xxx"
echo.
echo   [B] Merge mode
echo       不抓取，合并已有 Word 文档
echo       -^> Step5-6 合并 + 生成建议，输出 Word 报告
echo       示例: python merge_docs.py --input data\a.docx data\b.docx
echo.
echo   [C] Quick mode
echo       WeChat URLs + Bank scraping (Step1-2) + Webpage URLs
echo       -^> Step3-4 仅生成 Markdown+图片，跳过 Step5-6
echo       示例: python _agent.py --mode c --bank-days 7
echo.
echo   [D] Markdown editorial mode
echo       合并 Markdown，保留原文并生成主题点评与行动建议
echo       示例: data\公众号文章整理_20260708.md data\公众号文章整理_20260711.md
echo.
echo   [E] WeChat publish mode
echo       将 Mode D 成稿转换为公众号可粘贴 HTML
echo       示例: python md_to_wechat.py data\mode_d_merged.md
echo.
echo   [F] Weekly report → WeChat HTML
echo       信用卡周报 Word docx 转公众号可粘贴 HTML
echo       示例: data\Weekly_Report_2026年7月第3周.docx
echo.
echo   [Q] Exit
echo.
set /p choice=Enter choice (A/B/C/D/E/F/Q, default A):
if "%choice%"=="" set choice=A

if /i "%choice%"=="A" goto :mode_a
if /i "%choice%"=="a" goto :mode_a
if /i "%choice%"=="B" goto :mode_b
if /i "%choice%"=="b" goto :mode_b
if /i "%choice%"=="C" goto :mode_c
if /i "%choice%"=="c" goto :mode_c
if /i "%choice%"=="D" goto :mode_d
if /i "%choice%"=="d" goto :mode_d
if /i "%choice%"=="E" goto :mode_e
if /i "%choice%"=="e" goto :mode_e
if /i "%choice%"=="F" goto :mode_f
if /i "%choice%"=="f" goto :mode_f
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
set /p bank_days=Bank announcement days (default 7):
if "%bank_days%"=="" set bank_days=7
echo.
set args=--mode a --bank-days %bank_days%
if not "%wechat_urls%"=="" set args=%args% --wechat-url %wechat_urls%
if not "%webpage_urls%"=="" set args=%args% --webpage-url %webpage_urls%
echo python _agent.py %args%
python -X utf8 _agent.py %args%
goto :done

:mode_b
echo.
echo ============================================================
echo   Mode B: Merge Mode (Existing Docs + Suggestions)
echo ============================================================
echo.
echo Scanning data\ for .docx files ...
echo.

setlocal enabledelayedexpansion

REM Collect docx files, display indexed list with sizes
set "b_count=0"
set "b_idxfile=%TEMP%\mode_b_index.txt"
if exist "!b_idxfile!" del "!b_idxfile!"
for %%f in (data\*.docx) do (
    set /a b_count+=1
    for %%s in ("%%f") do set "fsize=%%~zs"
    set /a "fsize_kb=!fsize! / 1024"
    echo   [!b_count!] %%f  (!fsize_kb! KB^)
    echo !b_count! %%f>>"!b_idxfile!"
)

if !b_count!==0 (
    echo No .docx files found in data\
    echo Please place your Word documents in the data\ folder first.
    endlocal
    goto :done
)

echo.
echo   [P] Input path(s) directly instead
echo.
set /p b_choice=Select files (space-separated numbers, e.g. "1 3", or P for path):

if /i "!b_choice!"=="P" goto :mode_b_path
if /i "!b_choice!"=="p" goto :mode_b_path

REM Resolve selected numbers to file paths
set "b_files="
for /f "tokens=1,* delims= " %%a in ('type "!b_idxfile!"') do (
    for %%n in (!b_choice!) do (
        if "%%a"=="%%n" (
            if "!b_files!"=="" (
                set "b_files=%%b"
            ) else (
                set "b_files=!b_files! %%b"
            )
        )
    )
)
if exist "!b_idxfile!" del "!b_idxfile!"

if "!b_files!"=="" (
    echo No valid files selected.
    endlocal
    goto :done
)

echo.
echo Selected files:
echo   !b_files!
echo.
set /p b_output=Output filename (leave blank for auto-generated):

REM Pass results out of setlocal via temp files
set "b_result=%TEMP%\mode_b_result.txt"
if exist "!b_result!" del "!b_result!"
>>"!b_result!" call echo %%b_files%%
if not "!b_output!"=="" (
    set "b_outtmp=%TEMP%\mode_b_out.txt"
    if exist "!b_outtmp!" del "!b_outtmp!"
    >>"!b_outtmp!" call echo %%b_output%%
)
endlocal

REM Read back from temp files (set /p does not include trailing newline)
set /p b_files=<"%TEMP%\mode_b_result.txt"
if exist "%TEMP%\mode_b_out.txt" (
    set /p b_output=<"%TEMP%\mode_b_out.txt"
    del "%TEMP%\mode_b_out.txt"
)
if exist "%TEMP%\mode_b_result.txt" del "%TEMP%\mode_b_result.txt"

if "%b_files%"=="" (
    echo No valid files selected.
    goto :done
)

goto :mode_b_run

:mode_b_path
endlocal
echo.
set /p b_files=Enter file path(s) (space-separated):
echo.
set /p b_output=Output filename (leave blank for auto-generated):

:mode_b_run
set "b_cmd=python -X utf8 merge_docs.py --input %b_files%"
if not "%b_output%"=="" set "b_cmd=%b_cmd% --output %b_output%"
echo.
echo Running: %b_cmd%
echo.
%b_cmd%
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
set /p bank_days=Bank announcement days (default 7):
if "%bank_days%"=="" set bank_days=7
echo.
set args=--mode c --bank-days %bank_days%
if not "%wechat_urls%"=="" set args=%args% --wechat-url %wechat_urls%
if not "%webpage_urls%"=="" set args=%args% --webpage-url %webpage_urls%
echo python _agent.py %args%
python -X utf8 _agent.py %args%
goto :done

:mode_d
echo.
echo ============================================================
echo   Mode D: Markdown Editorial Merge
echo ============================================================
echo.
echo Example: data\公众号文章整理_20260708.md data\公众号文章整理_20260711.md
echo.
set /p d_files=Enter Markdown path(s) (blank uses the two sample files):
if "%d_files%"=="" set "d_files=data\公众号文章整理_20260708.md data\公众号文章整理_20260711.md"
set /p d_output=Output filename (blank: data\mode_d_merged.md):
if "%d_output%"=="" set "d_output=data\mode_d_merged.md"
python -X utf8 md_merge.py --input %d_files% --output "%d_output%"
goto :done

:mode_e
echo.
echo ============================================================
echo   Mode E: WeChat Publish HTML
echo ============================================================
echo.
echo Mode E 默认处理 data\mode_d_merged.md
echo.
set /p e_input=Input Markdown (blank: data\mode_d_merged.md):
if "%e_input%"=="" set "e_input=data\mode_d_merged.md"
set /p e_output=Output HTML (blank: auto-generated):
if not "%e_output%"=="" (
    python -X utf8 md_to_wechat.py "%e_input%" --output "%e_output%"
) else (
    python -X utf8 md_to_wechat.py "%e_input%"
)
goto :done

:mode_f
echo.
echo ============================================================
echo   Mode F: Weekly Report docx -^> WeChat HTML
echo ============================================================
echo.
echo Mode F 默认处理 data\Weekly_Report_2026年7月第3周.docx
echo.
set /p f_input=Input docx (blank: data\Weekly_Report_2026年7月第3周.docx):
if "%f_input%"=="" set "f_input=data\Weekly_Report_2026年7月第3周.docx"
set /p f_output=Output HTML (blank: auto-generated):
if not "%f_output%"=="" (
    python -X utf8 weekly_report_to_wechat.py "%f_input%" --output "%f_output%"
) else (
    python -X utf8 weekly_report_to_wechat.py "%f_input%"
)
goto :done

:done
echo.
echo ============================================================
echo   Done!
echo ============================================================
echo.
pause

:end

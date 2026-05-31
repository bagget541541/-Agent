@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo ========================================
echo  信用卡周报 — 测试套件
echo ========================================
echo.
echo 运行 P0 测试...
python -m pytest tests\test_common\test_schema.py tests\test_card_holding\test_scorer_highlight.py -v --tb=short -p no:cacheprovider
echo.
echo ---
if %ERRORLEVEL% EQU 0 (
    echo ✅ 全部测试通过
) else (
    echo ❌ 存在失败的测试
)
echo.
pause

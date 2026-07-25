@echo off
chcp 65001 >nul
set LLM_PROVIDER=grok
:: 请在运行前设置环境变量 GROK_API_KEY，或取消下面一行注释并填入你的 Key：
:: set GROK_API_KEY=gsk_xxx
python rag_query.py
pause

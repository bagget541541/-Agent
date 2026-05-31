@echo off
chcp 65001 >nul
set LLM_PROVIDER=groq
python rag_query.py
pause

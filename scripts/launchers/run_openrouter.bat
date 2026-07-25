@echo off
chcp 65001 >nul
set LLM_PROVIDER=openrouter
set OPENAI_API_KEY=你的OpenRouterKey填这里
set OPENAI_MODEL=qwen/qwen3-32b
python rag_query.py
pause

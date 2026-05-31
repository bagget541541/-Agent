#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG Query Interface — 信用卡知识库问答
纯 Python 实现 BM25 检索，零外部依赖。
"""

import os, re, json, sys, math, collections, requests, hashlib, pickle, time

HERE = os.path.dirname(os.path.abspath(__file__))
KB_PATH = os.path.join(HERE, "data", "articles_kb.json")
BM25_CACHE = os.path.join(HERE, "data", "bm25_cache.pkl")
TOP_K = 5
MAX_CONTEXT_CHARS = 3000

NL = chr(10)

# LLM config
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "groq")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "qwen/qwen3-32b")
OPENAI_URL = os.environ.get("OPENAI_API_URL", "https://openrouter.ai/api/v1/chat/completions")
GROK_API_KEY = os.environ.get("GROK_API_KEY", "")
GROK_MODEL = os.environ.get("GROK_MODEL", "grok-2-latest")
GROK_URL = "https://api.x.ai/v1/chat/completions"


# ═══════════════════════════════════════════════
#  BM25
# ═══════════════════════════════════════════════════

def tokenize(text):
    text = text.lower()
    chars = []
    eng_words = []
    i = 0
    while i < len(text):
        cp = ord(text[i])
        if cp > 127:
            chars.append(text[i])
            i += 1
        elif text[i].isalnum():
            j = i
            while j < len(text) and (text[j].isalnum() or text[j] in "-_"):
                j += 1
            w = text[i:j]
            if len(w) > 1:
                eng_words.append(w)
            i = j
        else:
            i += 1
    bigrams = [chars[i] + chars[i+1] for i in range(len(chars)-1)]
    return bigrams + chars + eng_words


class BM25:
    def __init__(self, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.corpus, self.doc_terms = [], []
        self.idf, self.avgdl = {}, 0

    def fit(self, docs):
        self.corpus = docs
        self.doc_terms = [collections.Counter(tokenize(d)) for d in docs]
        N = len(self.doc_terms)
        total_len = 0
        doc_freq = collections.Counter()
        for dt in self.doc_terms:
            total_len += sum(dt.values())
            for t in dt:
                doc_freq[t] += 1
        self.avgdl = total_len / N if N else 1
        for t, df in doc_freq.items():
            self.idf[t] = math.log(1 + (N - df + 0.5) / (df + 0.5))
        return self

    def score(self, qt, idx):
        dt = self.doc_terms[idx]
        dl = sum(dt.values())
        s = 0.0
        for t in qt:
            tf = dt.get(t, 0)
            if tf == 0:
                continue
            idf = self.idf.get(t, 0)
            if idf <= 0:
                continue
            s += idf * (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return s

    def search(self, query, top_k=5):
        qt = tokenize(query)
        if not qt:
            return []
        scores = [(i, self.score(qt, i)) for i in range(len(self.corpus))]
        scores.sort(key=lambda x: -x[1])
        return [(i, s) for i, s in scores[:top_k] if s > 0]


# ═══════════════════════════════════════════════
#  KB
# ═══════════════════════════════════════════════════

def load_kb():
    print("  Loading KB...", end=" ")
    with open(KB_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    entries = data["entries"]
    print(f"{len(entries)} entries")
    return entries


def build_or_load_bm25(entries):
    texts = [e["text"] for e in entries]
    cache_key = hashlib.md5(str(len(texts)).encode()).hexdigest()[:8]
    if os.path.isfile(BM25_CACHE):
        try:
            with open(BM25_CACHE, "rb") as f:
                cached = pickle.load(f)
            if cached.get("cache_key") == cache_key:
                print("  BM25 loaded from cache")
                return cached["bm25"]
        except Exception:
            pass
    print("  Building BM25 index...", end=" ")
    bm25 = BM25().fit(texts)
    with open(BM25_CACHE, "wb") as f:
        pickle.dump({"cache_key": cache_key, "bm25": bm25}, f)
    print("done")
    return bm25


# ═══════════════════════════════════════════════
#  LLM
# ═══════════════════════════════════════════════════

def build_prompt(query, entries, scores):
    parts = []
    sources = []
    for rank, (idx, sc) in enumerate(scores, 1):
        e = entries[idx]
        txt = e["text"][:MAX_CONTEXT_CHARS]
        parts.append(
            f"【参考{rank}】（相关性{sc:.2f}）" + NL +
            f"标题：{e['title']}" + NL +
            f"日期：{e.get('date', '')}" + NL +
            f"银行：{', '.join(e.get('banks', []))}" + NL +
            f"分类：{', '.join(e.get('categories', []))}" + NL +
            f"内容：{txt}"
        )
        sources.append({
            "rank": rank, "score": round(sc, 2),
            "title": e["title"], "bank": e.get("banks", []),
            "category": e.get("categories", []),
            "date": e.get("date", ""),
            "section": e.get("section", ""),
        })

    context = "---".join(parts)

    system_msg = (
        "你是一个专业的信用卡知识助手。根据提供的参考资料回答用户问题。" + NL +
        "要求：" + NL +
        "1. 主要基于参考资料回答，数据来源于历史公众号文章" + NL +
        "2. 如果参考资料不足以回答问题，明确告知\u201c参考资料中未覆盖\u201d" + NL +
        "3. 回答要具体：引用具体活动名称、银行、时间" + NL +
        "4. 涉及金额要用人民币符号 ¥" + NL +
        "5. 每个回答控制在200字以内" + NL +
        "6. 最后用「📌 参考依据」列出所用到的文章标题"
    )

    user_msg = (
        f"## 用户问题" + NL +
        f"{query}" + NL + NL +
        f"## 参考资料" + NL +
        f"{context}" + NL + NL +
        f"请基于以上资料回答问题。"
    )

    return system_msg, user_msg, sources


# ── 持卡建议 RAG 查询 ──────────────────────────────

# 全局缓存，避免每次重新加载 KB 和 BM25
_RAG_CACHE = {"entries": None, "bm25": None}


def query_for_suggestions(category: str, bank: str, title: str, top_k: int = 3) -> list[dict]:
    """为持卡建议检索历史参考。
    
    根据分类构造查询词，返回匹配的历史 KB 条目。
    可用于 step5_analyze 中对 highlight 条目补充参考。
    """
    # 延迟加载 KB 和 BM25（全局缓存）
    if _RAG_CACHE["entries"] is None:
        _RAG_CACHE["entries"] = load_kb()
        _RAG_CACHE["bm25"] = build_or_load_bm25(_RAG_CACHE["entries"])
    
    entries = _RAG_CACHE["entries"]
    bm25 = _RAG_CACHE["bm25"]
    
    # 根据分类构造查询词
    if category == "新卡":
        query = f"{bank} {title} 评分 值得办 对比"
    elif category == "权益变更":
        query = f"{bank} {title} 缩水 温暖升级 权益调整 变更"
    elif category == "活动":
        query = f"{bank} 活动 返现 满减 可参与 优惠"
    elif category == "公告":
        query = f"{bank} {title} 公告 通知"
    else:
        query = f"{bank} {title}"
    
    scores = bm25.search(query, top_k=top_k)
    if not scores:
        # 降级：只用银行+标题简搜
        query2 = f"{bank} {title[:10]}"
        scores = bm25.search(query2, top_k=top_k)
    
    results = []
    for idx, sc in scores:
        e = entries[idx]
        results.append({
            "title": e["title"],
            "date": e.get("date", ""),
            "bank": e.get("banks", []),
            "categories": e.get("categories", []),
            "text_preview": e["text"][:200],
            "relevance_score": round(sc, 3),
        })
    return results


def call_llm(sys_msg, user_msg):
    if LLM_PROVIDER == "groq":
        if not GROQ_API_KEY:
            return None, "未设置 GROQ_API_KEY 环境变量"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_msg}
            ],
            "temperature": 0.3,
            "max_tokens": 1024,
        }
        url = GROQ_URL
    elif LLM_PROVIDER == "grok":
        if not GROK_API_KEY:
            return None, "未设置 GROK_API_KEY 环境变量"
        headers = {"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": GROK_MODEL,
            "messages": [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_msg}
            ],
            "temperature": 0.3,
            "max_tokens": 1024,
        }
        url = GROK_URL
    else:  # openrouter / others
        if not OPENAI_API_KEY:
            return None, "未设置 OPENAI_API_KEY 环境变量"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": OPENAI_MODEL,
            "messages": [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_msg}
            ],
            "temperature": 0.3,
            "max_tokens": 1024,
        }
        url = OPENAI_URL

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        answer = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return answer, usage
    except requests.exceptions.Timeout:
        return None, "LLM 请求超时（30s）"
    except Exception as e:
        return None, f"LLM 调用失败：{e}"


# ═══════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════

def print_welcome():
    print()
    print("╔════════════════════════════════════════╗")
    print("║   信用卡知识库 RAG 查询 (Qwen/LLaMA)   ║")
    print("╠════════════════════════════════════════╣")
    print(f"  Provider: {LLM_PROVIDER}")
    model = GROQ_MODEL if LLM_PROVIDER == "groq" else (GROK_MODEL if LLM_PROVIDER == "grok" else OPENAI_MODEL)
    print(f"  Model: {model}")
    print("╠════════════════════════════════════════╣")
    print("  输入问题按回车 → 检索 + LLM 回答")
    print("  输入 /debug → 只看检索结果")
    print("  输入 /exit  → 退出")
    print("╚════════════════════════════════════════╝")
    print()


def main():
    # Windows GBK 终端修正：输出用 UTF-8
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("Loading...")
    entries = load_kb()
    bm25 = build_or_load_bm25(entries)
    debug_mode = False
    print_welcome()

    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue
        if raw in ("/exit",):
            break
        if raw in ("/debug",):
            debug_mode = not debug_mode
            print(f"  Debug: {'ON' if debug_mode else 'OFF'}")
            continue

        print("  Searching...", end=" ")
        t0 = time.time()
        scores = bm25.search(raw, top_k=TOP_K)
        print(f"({time.time()-t0:.2f}s) {len(scores)} results")

        if not scores:
            print("  No relevant results found.")
            continue

        for rank, (idx, sc) in enumerate(scores, 1):
            e = entries[idx]
            bank_str = ", ".join(e.get("banks", [])) or "-"
            cat_str = ", ".join(e.get("categories", [])) or "-"
            print(f"  #{rank}  {e['title'][:50]}")
            print(f"     银行: {bank_str}  分类: {cat_str}")
            print(f"     相关度: {sc:.3f}  日期: {e.get('date','')}")
            print()

        if debug_mode:
            continue

        print("  Generating answer...", end=" ")
        sys.stdout.flush()
        t0 = time.time()
        sys_msg, usr_msg, sources = build_prompt(query=raw, entries=entries, scores=scores)
        answer, info = call_llm(sys_msg, usr_msg)
        print(f"({time.time()-t0:.1f}s)")

        if answer is None:
            print(f"  {info}")
            continue

        print()
        print("  " + "-" * 48)
        print("  Answer:")
        print()
        for line in answer.strip().split(NL):
            print(f"    {line}")
        print()
        if isinstance(info, dict) and "prompt_tokens" in info:
            print(f"  Tokens: ↑{info.get('prompt_tokens','?')} ↓{info.get('completion_tokens','?')}")
        print()

    print("Bye!")


if __name__ == "__main__":
    main()

# wechat-rss-monitor

> 微信公众号文章去重模块

提供 URL hash 去重机制，避免重复抓取已处理的文章。

## 当前状态

**RSS 监控功能已不可用**（所有公共 RSSHub 实例均被封锁），当前仅保留 **URL 去重** 功能。

## 功能特性

- URL hash 去重（基于 `history.json`）
- 历史记录持久化
- 自动清理旧记录（保留最近 5000 条）

## 目录结构

```
wechat-rss-monitor/
├── SKILL.md                    # 本文件
├── BIZ_TUTORIAL.md             # biz 获取教程（历史参考）
├── requirements.txt            # 依赖列表
└── scripts/
    ├── rsshub_fetcher.py       # RSSHub 抓取器（已废弃）
    └── wechat_monitor.py       # 去重模块
```

## 使用方式

### 作为去重模块

```python
import hashlib
import json
from pathlib import Path

# 读取历史记录
history_path = Path("data/wechat_monitor/history.json")
history = {"fetched_urls": []}
if history_path.exists():
    history = json.loads(history_path.read_text(encoding="utf-8"))

# 检查 URL 是否已抓取
url = "https://mp.weixin.qq.com/s/xxx"
url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()
is_fetched = url_hash in history.get("fetched_urls", [])

# 标记已抓取
if "fetched_urls" not in history:
    history["fetched_urls"] = []
history["fetched_urls"].append(url_hash)

# 保存历史记录
history_path.parent.mkdir(parents=True, exist_ok=True)
history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
```

## 与全流程集成

`_agent.py` Step 1 使用 `wechat-article-extractor` 抓取文章，同时使用本模块的 `history.json` 进行去重：

```python
# _agent.py Step 1 逻辑
1. 读取 data/wechat_monitor/history.json
2. 过滤已抓取的 URL
3. 使用 wechat-article-extractor 抓取新文章
4. 更新 history.json
```

## 已废弃功能

以下功能已不再使用：

- RSSHub 自动监控
- 公众号配置列表
- 自动抓取新文章

如需自动监控，建议自建 RSSHub 实例或使用其他方案。

## 公共 RSSHub 实例（已失效）

以下公共实例均已被封锁：

1. https://rsshub.app → 403
2. https://rsshub.rssforever.com → 503
3. https://rsshub.moeyy.cn → 连接失败
4. https://rss.fatpandac.com → 403

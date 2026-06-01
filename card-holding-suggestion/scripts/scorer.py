"""
LLM 语义评分引擎

通过 LLM API 对信用卡资讯进行语义评分和 ROI 分析。
兼容 OpenAI 格式 API（deepseek、claude-proxy、openai 等）。

环境变量配置：
    LLM_API_KEY       — API Key（默认读取 ~/.llm_config.json）
    LLM_API_BASE      — API 地址（默认 https://api.deepseek.com）
    LLM_MODEL         — 模型名（默认 deepseek-chat）
"""

import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from typing import Optional

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ── 配置 ──────────────────────────────────────────────

DEFAULT_API_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

CONFIG_FILE = os.path.expanduser("~/.llm_config.json")


def load_config() -> dict:
    """从 ~/.llm_config.json 读取 LLM 配置"""
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


# 用于避免重复打印配置摘要
_config_printed = False


def _print_config_summary(api_base: str, model: str, api_key: str) -> None:
    """首次调用时打印配置摘要，方便用户确认配置正确。"""
    global _config_printed
    if _config_printed:
        return
    _config_printed = True
    key_hint = f"...{api_key[-4:]}" if len(api_key) >= 4 else "****"
    print(f"  [LLM配置] api_base={api_base}  model={model}  key={key_hint}", flush=True)


# ── 评分数据结构 ──────────────────────────────────────


@dataclass
class ROI_Dimension:
    """单一 ROI 评估维度"""

    name: str  # 维度名称，如 "年费成本", "返现力度"
    weight: float = 1.0  # 权重 (0~1)
    score: float = 5.0  # 得分 (1~10)
    reason: str = ""  # 评分理由


@dataclass
class ROI_Score:
    """ROI 综合评分结果"""

    overall_score: float = 5.0  # 综合分 (1~10)
    overall_roi: str = ""  # "高"/"中"/"低"
    recommendation: str = ""  # 建议
    dimensions: list[dict] = field(default_factory=list)  # 各维度详情
    summary: str = ""  # 一句话总结
    scorer_used: str = "keyword"  # "llm" | "keyword" | "keyword_fallback"
    is_highlight: bool = False  # 是否为重点/异常条目
    highlight_reason: str = ""  # 高亮原因
    notes: str = ""  # 注意事项/风险提示
    activity_value: str = ""  # 活动价值（仅活动分类使用）

    def to_dict(self) -> dict:
        return asdict(self)


# ── 分类专用评分模板 ──────────────────────────────────


def _new_card_dimensions() -> list[dict]:
    """新卡评估维度与权重"""
    return [
        {"name": "年费成本", "weight": 0.25, "question": "年费高不高？是否有免年费政策？"},
        {"name": "权益价值", "weight": 0.30, "question": "附带权益（贵宾厅、接送机、里程等）实用价值如何？"},
        {"name": "日常实用性", "weight": 0.20, "question": "日常消费场景覆盖是否广？返现/积分比例如何？"},
        {"name": "门槛与独家性", "weight": 0.15, "question": "申请门槛是否合理？权益在同级别卡中是否独特？"},
        {"name": "市场同类对比", "weight": 0.10, "question": "与市场上同级别卡相比，性价比是否突出？"},
    ]


def _change_dimensions() -> list[dict]:
    """权益变更评估维度与权重"""
    return [
        {"name": "权益变化方向", "weight": 0.35, "question": "权益是升级还是缩水？幅度多大？"},
        {"name": "持有成本变化", "weight": 0.25, "question": "年费/消费要求有变化吗？"},
        {"name": "影响范围", "weight": 0.20, "question": "影响多少持卡人？是否影响日常用卡？"},
        {"name": "替代方案", "weight": 0.20, "question": "是否有同级别替代卡可选？"},
    ]


def _activity_dimensions() -> list[dict]:
    """活动评估维度与权重"""
    return [
        {"name": "返利力度", "weight": 0.30, "question": "返现/立减/积分多倍比例如何？"},
        {"name": "参与门槛", "weight": 0.25, "question": "是否需要报名？消费门槛高不高？名额是否有限？"},
        {"name": "时间充裕度", "weight": 0.20, "question": "活动有效期多长？时间是否充裕？"},
        {"name": "日常匹配度", "weight": 0.15, "question": "活动场景是否覆盖日常消费？"},
        {"name": "叠加可能性", "weight": 0.10, "question": "是否能与其他优惠叠加？"},
    ]


def _announcement_dimensions() -> list[dict]:
    """公告评估维度与权重"""
    return [
        {"name": "信息重要性", "weight": 0.40, "question": "这条公告对持卡人影响大不大？"},
        {"name": "行动紧迫性", "weight": 0.30, "question": "持卡人是否需要尽快采取行动？"},
        {"name": "影响持久性", "weight": 0.30, "question": "影响是长期的还是临时的？"},
    ]


DIMENSION_TEMPLATES = {
    "新卡": _new_card_dimensions,
    "权益变更": _change_dimensions,
    "活动": _activity_dimensions,
    "公告": _announcement_dimensions,
}


# ── 高亮判定 ──────────────────────────────────────────


def _calc_highlight(category: str, score: float, roi: str) -> tuple[bool, str]:
    """根据分类和评分判定是否为重点条目及原因"""
    if category == "新卡":
        if score >= 8:
            return (True, "强烈推荐")
        if score <= 3:
            return (True, "建议避坑")
    elif category == "权益变更":
        if score <= 4:
            return (True, "严重缩水，需关注")
        if score >= 8:
            return (True, "重大利好")
    elif category == "活动":
        if score >= 8:
            return (True, "高价值，建议参加")
        if score <= 3:
            return (True, "低价值，建议放弃")
    elif category == "公告":
        if score <= 2 or score >= 9:
            return (True, "重要公告")
    return (False, "")


def _generate_notes(category: str, overall: float, text_all: str) -> str:
    """根据分类和评分生成注意事项"""
    if category == "新卡":
        if "刚性年费" in text_all:
            return "刚性年费卡，确保持卡价值 > 年费支出。注意首年/次年减免条件"
        elif overall >= 7:
            return "关注年费减免条件和刷卡次数要求"
        elif overall <= 3:
            return "权益较为鸡肋，建议谨慎考虑申请"
        else:
            return "建议根据个人用卡需求评估"
    elif category == "权益变更":
        if overall >= 7:
            return "利好变更，建议确认续持并调整刷卡习惯"
        elif overall <= 3:
            return "缩水严重，建议评估是否销卡或寻找替代卡"
        else:
            return "变更影响有限，可继续观察"
    elif category == "活动":
        if "名额有限" in text_all or "限量" in text_all or "先到先得" in text_all:
            return "有名额限制，建议尽早参与"
        elif overall >= 7:
            return "高价值活动，注意参与规则和达标条件"
        elif overall <= 3:
            return "价值较低或存在套路风险，建议放弃"
        else:
            return "视个人消费习惯决定是否参与"
    elif category == "公告":
        if overall >= 8:
            return "重大公告，建议关注后续影响"
        else:
            return "例行公告，可选择性了解"
    return ""


# ── LLM 评分实现 ──────────────────────────────────────


def _build_prompt(item: dict, dims: list[dict]) -> str:
    """构造 LLM 评分提示词"""
    category = item.get("category", "")
    title = item.get("title", "")
    bank = item.get("bank", "")
    raw_text = item.get("raw_text", "")
    structured = item.get("structured", {})
    details = json.dumps(structured, ensure_ascii=False, indent=2)

    dim_text = "\n".join(
        f"  {i+1}. [{d['name']}] (权重 {d['weight']*100:.0f}%) — {d['question']}"
        for i, d in enumerate(dims)
    )

    prompt = f"""你是一个专业的信用卡分析师。请评估以下信用卡{category}的持卡价值，从投入产出比（ROI）角度给出评分。

【资讯标题】{title}
【银行】{bank}
【原文摘要】{(raw_text or "")[:1000]}
【结构化字段】{details}

### 评估维度及权重：
{dim_text}

### 要求：
1. 对每个维度按 1-10 分打分（1=极差，10=极好）
2. 给出每个维度的评分理由
3. 按权重计算综合得分（1-10）
4. 给出 ROI 评价（高/中/低）
5. 给出明确的持卡建议（50字内）
6. 一句话总结（20字内）

### 输出格式（严格 JSON，不要额外文字）：
```json
{{
  "dimensions": [
    {{"name": "维度名", "weight": 权重, "score": 分数, "reason": "评分理由"}}
  ],
  "overall_score": 综合分,
  "overall_roi": "高/中/低",
  "recommendation": "建议",
  "summary": "一句话总结"
}}
```"""
    return prompt


def _parse_llm_response(text: str) -> ROI_Score:
    """从 LLM 响应中解析 JSON 评分"""
    # 尝试提取 ```json ... ``` 块
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        text = m.group(1)

    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError:
        # 尝试直接在文本中找 JSON 对象
        m2 = re.search(r"\{.*\}", text, re.DOTALL)
        if m2:
            try:
                data = json.loads(m2.group())
            except json.JSONDecodeError:
                return ROI_Score(overall_score=5.0, overall_roi="中",
                                 recommendation="LLM 评分解析失败，请参考关键词评分",
                                 summary="解析失败")
        else:
            return ROI_Score(overall_score=5.0, overall_roi="中",
                             recommendation="LLM 评分解析失败，请参考关键词评分",
                             summary="解析失败")

    dims = data.get("dimensions", [])
    return ROI_Score(
        overall_score=data.get("overall_score", 5.0),
        overall_roi=data.get("overall_roi", "中"),
        recommendation=data.get("recommendation", ""),
        dimensions=dims,
        summary=data.get("summary", ""),
    )


def score_with_llm(item: dict) -> ROI_Score:
    """通过 LLM API 对单条资讯进行 ROI 评分"""
    category = item.get("category", "")
    dim_builder = DIMENSION_TEMPLATES.get(category)
    if not dim_builder:
        is_hl, hl_reason = _calc_highlight(category, 5.0, "中")
        return ROI_Score(overall_score=5.0, overall_roi="中",
                         recommendation="未知分类，请联系人工判断",
                         summary=f"分类「{category}」无评分模板",
                         scorer_used="keyword_fallback",
                         is_highlight=is_hl,
                         highlight_reason=hl_reason)

    dims = dim_builder()
    prompt = _build_prompt(item, dims)

    # 尝试调用 LLM API
    cfg = load_config()
    api_key = cfg.get("api_key") or os.environ.get("LLM_API_KEY", "")
    api_base = cfg.get("api_base") or os.environ.get("LLM_API_BASE", DEFAULT_API_BASE)
    model = cfg.get("model") or os.environ.get("LLM_MODEL", DEFAULT_MODEL)

    if not api_key:
        print(f"  [LLM警告] 未找到 api_key，请在 {CONFIG_FILE} 中配置或设置环境变量 LLM_API_KEY", flush=True)
        print(f"  [LLM警告] 配置示例: {{\"api_key\": \"sk-...\", \"api_base\": \"{DEFAULT_API_BASE}\", \"model\": \"{DEFAULT_MODEL}\"}}", flush=True)
        result = score_with_keywords(item, dims)
        result.scorer_used = "keyword_fallback"
        result.summary = result.summary.replace("关键词评分", "关键词评分（LLM未配置）")
        return result

    # 尝试调用统一 LLM 客户端
    from common.llm_client import call_llm_file_config

    reply, err = call_llm_file_config(
        prompt=prompt,
        temperature=0.3,
        max_tokens=2048,
        timeout=60,
        api_key=cfg.get("api_key") or os.environ.get("LLM_API_KEY", ""),
        api_base=cfg.get("api_base") or os.environ.get("LLM_API_BASE", DEFAULT_API_BASE),
        model=cfg.get("model") or os.environ.get("LLM_MODEL", DEFAULT_MODEL),
    )

    if err:
        print(f"  [LLM警告] API 调用失败 ({err})，降级到关键词评分", file=__import__("sys").stderr, flush=True)
        result = score_with_keywords(item, dims)
        result.scorer_used = "keyword_fallback"
        result.summary = f"LLM调用失败，已降级（{err}）"
        return result

    result = _parse_llm_response(reply)
    result.scorer_used = "llm"
    is_hl, hl_reason = _calc_highlight(category, result.overall_score, result.overall_roi)
    result.is_highlight = is_hl
    result.highlight_reason = hl_reason
    # LLM 模式下用评分生成注意事项
    text_all = f"{item.get('title', '')} {item.get('raw_text', '')}"
    result.notes = _generate_notes(category, result.overall_score, text_all)
    return result


# ── 关键词评分（降级方案） ─────────────────────────────


def score_with_keywords(item: dict, dims: list[dict]) -> ROI_Score:
    """关键词评分——当 LLM 不可用时作为降级方案"""
    category = item.get("category", "")
    structured = item.get("structured", {})
    raw_text = item.get("raw_text", "")
    title = item.get("title", "")
    text_all = f"{title} {raw_text}"

    if category == "新卡":
        positive = ["免年费", "返现", "积分", "接送机", "贵宾厅", "里程"]
        premium = ["刚性年费", "高端", "白金", "钻石"]
        negative = ["缩水", "停发", "限制"]
        base = 5.0
        for kw in positive:
            if kw in text_all: base += 1.0
        for kw in premium:
            if kw in text_all: base += 0.5
        for kw in negative:
            if kw in text_all: base -= 2.0
        overall = max(1, min(10, base))
        dimensions = [
            {"name": "年费成本", "weight": 0.25, "score": min(10, overall + 1), "reason": "关键词匹配"},
            {"name": "权益价值", "weight": 0.30, "score": overall, "reason": "关键词匹配"},
            {"name": "日常实用性", "weight": 0.20, "score": max(1, overall - 1), "reason": "关键词匹配"},
            {"name": "门槛与独家性", "weight": 0.15, "score": 5.0, "reason": "需人工判断"},
            {"name": "市场同类对比", "weight": 0.10, "score": 5.0, "reason": "需人工判断"},
        ]
    elif category == "活动":
        value_kw = ["返现", "满减", "立减", "免费", "多倍积分"]
        risk_kw = ["名额有限", "限量", "先到先得"]
        value_score = sum(1 for kw in value_kw if kw in text_all)
        risk_score = sum(1 for kw in risk_kw if kw in text_all)
        overall = min(10, 4 + value_score * 1.5 - risk_score)
        overall = max(1, overall)
        dimensions = [
            {"name": "返利力度", "weight": 0.30, "score": min(10, 4 + value_score * 2), "reason": f"匹配{value_score}个正向关键词"},
            {"name": "参与门槛", "weight": 0.25, "score": max(1, 7 - risk_score * 2), "reason": f"匹配{risk_score}个风险关键词"},
            {"name": "时间充裕度", "weight": 0.20, "score": 5.0, "reason": "需人工判断活动时间"},
            {"name": "日常匹配度", "weight": 0.15, "score": 6.0, "reason": "关键词匹配"},
            {"name": "叠加可能性", "weight": 0.10, "score": 5.0, "reason": "需人工判断"},
        ]
    elif category == "权益变更":
        downgrade = ["缩水", "取消", "减少", "限制", "涨价", "下调"]
        upgrade = ["升级", "新增", "增加", "放宽", "延长"]
        d_score = sum(1 for kw in downgrade if kw in text_all)
        u_score = sum(1 for kw in upgrade if kw in text_all)
        overall = 5 + u_score * 1.5 - d_score * 1.5
        overall = max(1, min(10, overall))
        dimensions = [
            {"name": "权益变化方向", "weight": 0.35, "score": overall, "reason": f"降级词{d_score}个, 升级词{u_score}个"},
            {"name": "持有成本变化", "weight": 0.25, "score": 5.0, "reason": "需人工判断"},
            {"name": "影响范围", "weight": 0.20, "score": 5.0, "reason": "需人工判断"},
            {"name": "替代方案", "weight": 0.20, "score": 5.0, "reason": "需人工判断"},
        ]
    else:
        overall = 5.0
        dimensions = [
            {"name": "信息重要性", "weight": 0.40, "score": 5.0, "reason": "需人工判断"},
            {"name": "行动紧迫性", "weight": 0.30, "score": 5.0, "reason": "需人工判断"},
            {"name": "影响持久性", "weight": 0.30, "score": 5.0, "reason": "需人工判断"},
        ]

    # ROI 判断
    if overall >= 7:
        roi = "高"
        rec = "推荐办理/参与"
    elif overall >= 4:
        roi = "中"
        rec = "视个人需求决定"
    else:
        roi = "低"
        rec = "建议观望/暂不行动"

    # 注意事项（按分类生成）
    notes = _generate_notes(category, overall, text_all)

    is_hl, hl_reason = _calc_highlight(category, overall, roi)

    return ROI_Score(
        overall_score=round(overall, 1),
        overall_roi=roi,
        recommendation=rec,
        dimensions=dimensions,
        summary=f"{rec}（关键词评分，建议开启 LLM 获得更精准分析）",
        scorer_used="keyword",
        is_highlight=is_hl,
        highlight_reason=hl_reason,
        notes=notes,
    )

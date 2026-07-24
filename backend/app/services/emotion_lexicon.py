"""情绪词典模块：基于 PRD 3.1.2 / 3.1.4 / 3.1.5 的纯词典情绪分析路径。

- 无任何 LLM / 网络调用、无数据库依赖，仅使用标准库。
- 六类情绪：greed / optimism / calm / anxiety / frustration / panic。
- ``analyze`` 的返回结果可直接 ``json.dumps``（将存入 SQLAlchemy JSON 字段）。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

__all__ = [
    "EMOTION_KEYWORDS",
    "AROUSAL_MAP",
    "VALENCE_MAP",
    "analyze",
]

# ---------------------------------------------------------------------------
# 词典：情绪 -> {关键词: 权重}（投资语境，每类 10-15 个）
# ---------------------------------------------------------------------------

EMOTION_KEYWORDS: dict[str, dict[str, float]] = {
    # 贪婪：追涨、FOMO、冲动加仓（高唤醒 / 正效价）
    "greed": {
        "梭哈": 0.9,
        "全仓": 0.85,
        "全押": 0.85,
        "加杠杆": 0.9,
        "借钱投": 0.9,
        "一夜暴富": 0.9,
        "翻倍": 0.8,
        "追涨": 0.8,
        "再不买就晚了": 0.85,
        "怕错过": 0.75,
        "冲进去": 0.8,
        "赶紧买": 0.8,
        "抓紧上车": 0.85,
    },
    # 乐观：看好后市、对持仓有信心（中唤醒 / 正效价）
    "optimism": {
        "看好": 0.6,
        "有信心": 0.6,
        "长期向好": 0.65,
        "前景不错": 0.6,
        "拿得住": 0.55,
        "慢慢涨": 0.5,
        "值得持有": 0.6,
        "会涨回来": 0.6,
        "稳中向好": 0.6,
        "逢低布局": 0.55,
        "相信长期": 0.6,
        "问题不大": 0.5,
    },
    # 冷静：理性分析、按计划执行（低唤醒 / 中性偏正效价）
    "calm": {
        "按计划": 0.55,
        "定投": 0.5,
        "分散配置": 0.5,
        "理性": 0.6,
        "正常波动": 0.55,
        "平常心": 0.6,
        "不着急": 0.5,
        "观望": 0.45,
        "先看看": 0.45,
        "心态平稳": 0.6,
        "按纪律": 0.55,
        "无所谓": 0.45,
    },
    # 焦虑：不确定、纠结、犹豫（中-高唤醒 / 负效价）
    "anxiety": {
        "纠结": 0.65,
        "犹豫": 0.6,
        "睡不着": 0.75,
        "忐忑": 0.7,
        "不安": 0.65,
        "担心": 0.6,
        "拿不准": 0.6,
        "怎么办": 0.55,
        "心里没底": 0.7,
        "反复看盘": 0.7,
        "坐立不安": 0.75,
        "心慌": 0.65,
    },
    # 沮丧：已亏损、自责、后悔（低唤醒 / 负效价）
    "frustration": {
        "后悔": 0.7,
        "自责": 0.7,
        "心灰意冷": 0.75,
        "没意思": 0.5,
        "认栽": 0.65,
        "躺平": 0.55,
        "不想看了": 0.6,
        "亏麻了": 0.75,
        "早知道": 0.6,
        "白忙": 0.6,
        "提不起劲": 0.6,
        "算了": 0.5,
    },
    # 恐慌：害怕巨亏、想立刻止损（高唤醒 / 负效价）
    "panic": {
        "吓死": 0.9,
        "吓坏": 0.85,
        "赶紧卖": 0.85,
        "赶紧跑": 0.85,
        "崩了": 0.85,
        "崩盘": 0.85,
        "割肉": 0.8,
        "血本无归": 0.9,
        "完蛋": 0.8,
        "恐慌": 0.85,
        "清仓": 0.7,
        "受不了了": 0.75,
    },
}

# 唤醒度映射（PRD 3.1.5 伪代码，基于情绪类别的固有属性）
AROUSAL_MAP: dict[str, float] = {
    "greed": 0.85,
    "panic": 0.9,
    "anxiety": 0.65,
    "optimism": 0.45,
    "frustration": 0.25,
    "calm": 0.15,
}

# 效价映射（PRD 3.1.5 伪代码）
VALENCE_MAP: dict[str, float] = {
    "greed": 0.7,
    "panic": -0.9,
    "anxiety": -0.4,
    "optimism": 0.6,
    "frustration": -0.5,
    "calm": 0.1,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def analyze(text: str) -> dict:
    """基于词典的情绪分析（PRD 3.1.5 伪代码实现）。

    返回可 JSON 序列化的 dict：
    {"emotion", "score", "arousal", "valence", "confidence",
     "source": "lexicon", "matched_keywords", "timestamp"}
    """
    content = text or ""
    matched: list[dict] = []
    emotion_scores: dict[str, list[float]] = defaultdict(list)

    for emotion, keywords in EMOTION_KEYWORDS.items():
        for keyword, weight in keywords.items():
            if keyword in content:
                matched.append({"keyword": keyword, "emotion": emotion, "weight": weight})
                emotion_scores[emotion].append(weight)

    if not matched:
        return {
            "emotion": "calm",
            "score": 0.0,
            "arousal": AROUSAL_MAP["calm"],
            "valence": 0.0,
            "confidence": 0.0,
            "source": "lexicon",
            "matched_keywords": [],
            "timestamp": _now_iso(),
        }

    # 主导情绪 = 各情绪匹配权重均值中的最大者（确定性：按词典插入顺序打破平局）
    emotion_avg = {emotion: sum(weights) / len(weights) for emotion, weights in emotion_scores.items()}
    dominant = max(emotion_avg, key=emotion_avg.get)  # type: ignore[arg-type]

    score = emotion_avg[dominant]
    avg_weight = sum(item["weight"] for item in matched) / len(matched)
    confidence = min(1.0, len(matched) * 0.2 + avg_weight * 0.5)

    return {
        "emotion": dominant,
        "score": score,
        "arousal": AROUSAL_MAP[dominant],
        "valence": VALENCE_MAP[dominant] * score,
        "confidence": confidence,
        "source": "lexicon",
        "matched_keywords": matched,
        "timestamp": _now_iso(),
    }

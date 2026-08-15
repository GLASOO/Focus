"""Focus Agent — 崩坏检测（实施手册 §11.2 + 架构审查 v2.1 问题4）

三重检测器 + 融合决策：
  1. NgramRepetitionDetector  — 4-gram 重复率 > 0.3（最确定信号）
  2. EntropyDropDetector      — token 熵低于基线 50%（确定性上升）
  3. SemanticDriftDetector    — 关键词覆盖率 < 10%（跑偏）

融合：collapse_score >= 3 触发崩坏（ngram+2、entropy+1、drift+1）
无信号时分数按 0.1/步 衰减。实时流式，O(n)。
"""

from __future__ import annotations

import math
from collections import Counter, deque
from dataclasses import dataclass


@dataclass
class CollapseSignal:
    """崩坏信号。"""
    reason: str = ""
    score: float = 0.0
    ngram_repeat: float = 0.0
    entropy_ratio: float = 1.0
    keyword_coverage: float = 1.0


def _entropy(tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    n = len(tokens)
    counts: Counter[str] = Counter(tokens)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


class NgramRepetitionDetector:
    """滑动窗口 4-gram 重复率检测。"""

    def __init__(self, window: int = 100, threshold: float = 0.3):
        self.window = window
        self.threshold = threshold
        self._recent: deque[str] = deque(maxlen=window)
        self._grams: deque[str] = deque(maxlen=window - 3)

    def feed(self, text: str) -> float:
        """喂入新文本，返回当前 4-gram 重复率。"""
        self._recent.append(text)
        tokens = list(self._recent)
        if len(tokens) < 8:
            return 0.0
        grams = [tuple(tokens[i:i + 4]) for i in range(len(tokens) - 3)]
        seen: set[tuple] = set()
        dup = 0
        for g in grams:
            if g in seen:
                dup += 1
            else:
                seen.add(g)
        return dup / max(1, len(grams))


class EntropyDropDetector:
    """token 熵下降检测：当前熵 < 基线 50% → 退化信号。"""

    def __init__(self, window: int = 50, baseline: int = 20, ratio: float = 0.5):
        self.window = window
        self.baseline = baseline
        self.ratio = ratio
        self._tokens: deque[str] = deque(maxlen=window)

    def feed(self, text: str) -> float:
        """返回 当前熵/基线熵 比率。"""
        self._tokens.append(text)
        if len(self._tokens) < self.baseline + 5:
            return 1.0
        baseline_ent = _entropy(list(self._tokens)[: self.baseline])
        current_ent = _entropy(list(self._tokens))
        if baseline_ent <= 1e-9:
            return 0.0
        return current_ent / baseline_ent


class SemanticDriftDetector:
    """关键词覆盖率检测：最近窗口内是否还在谈节点主题。

    关键词从节点 title/brief 提取（去停用词），纯字符串匹配，O(n)。
    """

    STOPWORDS = {
        "的", "了", "是", "我", "你", "他", "这", "那", "在", "有", "和", "与",
        "就", "都", "而", "及", "或", "一个", "我们", "你们", "他们", "这个",
        "那个", "什么", "怎么", "为什么", "可以", "应该", "the", "a", "an",
        "is", "are", "to", "of", "in", "on", "and", "or", "for", "with",
    }

    def __init__(self, keywords: list[str], window: int = 200,
                 coverage_threshold: float = 0.10):
        self.keywords = [k for k in keywords if k and k not in self.STOPWORDS
                         and len(k) > 1]
        self.window = window
        self.threshold = coverage_threshold
        self._buf = ""

    def set_keywords(self, keywords: list[str]) -> None:
        self.keywords = [k for k in keywords if k and k not in self.STOPWORDS
                         and len(k) > 1]

    def feed(self, text: str) -> float:
        if not self.keywords:
            return 1.0
        self._buf += text
        self._buf = self._buf[-self.window * 4:]  # 保留约 800 字
        covered = sum(1 for k in self.keywords if k in self._buf)
        return covered / len(self.keywords)


class CollapseDetector:
    """融合决策器：score>=3 触发崩坏。"""

    def __init__(self):
        self.ngram = NgramRepetitionDetector()
        self.entropy = EntropyDropDetector()
        self.drift = SemanticDriftDetector([])
        self._score = 0.0
        self._signals: dict[str, float] = {}

    def set_keywords(self, keywords: list[str]) -> None:
        self.drift.set_keywords(keywords)

    def feed(self, text: str, *, decay: float = 0.1) -> CollapseSignal:
        """喂入一段文本，返回当前信号。每次调用分数衰减 0.1（无信号时）。"""
        nr = self.ngram.feed(text)
        er = self.entropy.feed(text)
        kc = self.drift.feed(text)

        self._signals = {}
        if nr >= 0.3:
            self._signals["ngram"] = 2.0
        if er < 0.5:
            self._signals["entropy"] = 1.0
        if kc < 0.10:
            self._signals["drift"] = 1.0

        if self._signals:
            self._score = sum(self._signals.values())
        else:
            self._score = max(0.0, self._score - decay)

        return CollapseSignal(
            reason="+".join(self._signals.keys()),
            score=self._score,
            ngram_repeat=nr,
            entropy_ratio=er,
            keyword_coverage=kc,
        )

    @property
    def score(self) -> float:
        return self._score

    def reset(self) -> None:
        self._score = 0.0
        self._signals = {}
        self.ngram = NgramRepetitionDetector()
        self.entropy = EntropyDropDetector()
        self.drift = SemanticDriftDetector([])

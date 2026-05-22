"""规则特征计算模块（基于设计文档 9.3-9.5）。"""

import re
from typing import Any

import tiktoken


class SignalCalculator:
    """信号计算器。"""

    # 定义模式
    DEFINITION_PATTERNS = [
        r'\b(?:is a|refers to|defined as|means?|is defined to be|refers)\b',
        r'\b(?:represents?|stands for|signifies?|denotes?)\b',
        r'\b(?:known as|called|termed|described as)\b',
    ]

    ENUMERATION_PATTERNS = [
        r'\b(?:first|second|third|fourth|fifth)\b',
        r'\b(?:initially|firstly|secondly|thirdly|finally)\b',
        r'\b(?:includes?|consists? of|comprises?|contains?)\b',
        r'\b(?:such as|including|like|for example)\b',
        r'(?:,\\s*){2,}',  # 逗号分隔的列表
    ]

    COMPARISON_PATTERNS = [
        r'\b(?:compared to|compared with|unlike|unlike to)\b',
        r'\b(?:whereas|while|although|though)\b',
        r'\b(?:in contrast|by contrast|conversely)\b',
        r'\b(?:similarly|likewise)\b',
        r'\b(?:different from|differs from|differs from)\b',
        r'\b(?:better|worse|higher|lower|greater|lesser) than\b',
    ]

    CAUSAL_PATTERNS = [
        r'\b(?:because|since|as|for)\b',
        r'\b(?:therefore|thus|hence|consequently|as a result)\b',
        r'\b(?:led to|resulted in|caused|brought about)\b',
        r'\b(?:due to|owing to|thanks to|because of)\b',
        r'\b(?:triggered|induced|provoked)\b',
    ]

    MECHANISM_PATTERNS = [
        r'\b(?:process|mechanism|function|operation)\b',
        r'\b(?:works by|operates through|functions via)\b',
        r'\b(?:through which|by which|via which)\b',
        r'\b(?:involves?|entails?|requires?)\b',
    ]

    CONDITIONAL_PATTERNS = [
        r'\b(?:if|unless|provided that|assuming that)\b',
        r'\b(?:under|in case of|in the event of)\b',
        r'\b(?:depends on|relies on|contingent upon)\b',
    ]

    def __init__(self, encoding_name: str = "cl100k_base"):
        """初始化计算器。

        Args:
            encoding_name: tiktoken 编码名称
        """
        self.encoding = tiktoken.get_encoding(encoding_name)

    def calculate_definition_signal(self, text: str) -> float:
        """计算定义信号。

        Args:
            text: 输入文本

        Returns:
            归一化后的信号值 [0, 1]
        """
        count = sum(len(re.findall(pattern, text, re.IGNORECASE))
                    for pattern in self.DEFINITION_PATTERNS)
        return self._normalize_count(count, text, max_expected=3)

    def calculate_enumeration_signal(self, text: str) -> float:
        """计算枚举信号。

        Args:
            text: 输入文本

        Returns:
            归一化后的信号值 [0, 1]
        """
        count = sum(len(re.findall(pattern, text, re.IGNORECASE))
                    for pattern in self.ENUMERATION_PATTERNS)
        return self._normalize_count(count, text, max_expected=5)

    def calculate_comparison_signal(self, text: str) -> float:
        """计算比较信号。

        Args:
            text: 输入文本

        Returns:
            归一化后的信号值 [0, 1]
        """
        count = sum(len(re.findall(pattern, text, re.IGNORECASE))
                    for pattern in self.COMPARISON_PATTERNS)
        return self._normalize_count(count, text, max_expected=3)

    def calculate_causal_signal(self, text: str) -> float:
        """计算因果信号。

        Args:
            text: 输入文本

        Returns:
            归一化后的信号值 [0, 1]
        """
        count = sum(len(re.findall(pattern, text, re.IGNORECASE))
                    for pattern in self.CAUSAL_PATTERNS)
        return self._normalize_count(count, text, max_expected=4)

    def calculate_mechanism_signal(self, text: str) -> float:
        """计算机制信号。

        Args:
            text: 输入文本

        Returns:
            归一化后的信号值 [0, 1]
        """
        count = sum(len(re.findall(pattern, text, re.IGNORECASE))
                    for pattern in self.MECHANISM_PATTERNS)
        return self._normalize_count(count, text, max_expected=2)

    def calculate_conditional_signal(self, text: str) -> float:
        """计算条件信号。

        Args:
            text: 输入文本

        Returns:
            归一化后的信号值 [0, 1]
        """
        count = sum(len(re.findall(pattern, text, re.IGNORECASE))
                    for pattern in self.CONDITIONAL_PATTERNS)
        return self._normalize_count(count, text, max_expected=2)

    def calculate_numeric_signal(self, text: str) -> float:
        """计算数字信号。

        统计数字、年份、比例、百分比、区间表达式密度。

        Args:
            text: 输入文本

        Returns:
            归一化后的信号值 [0, 1]
        """
        tokens = self.encoding.encode(text)
        num_tokens = len(tokens)

        # 数字和年份
        number_pattern = r'\b\d{1,4}(?:,\d{3})*(?:\.\d+)?\b'
        year_pattern = r'\b(?:19|20)\d{2}\b'
        percent_pattern = r'\b\d+\.?\d*%\b'
        range_pattern = r'\b\d+[-–]\d+\b'

        count = (len(re.findall(number_pattern, text)) +
                 len(re.findall(year_pattern, text)) +
                 len(re.findall(percent_pattern, text)) +
                 len(re.findall(range_pattern, text)))

        return self._normalize_count(count, text, max_expected=5)

    def calculate_entity_density_signal(self, text: str) -> float:
        """计算实体密度信号。

        统计专有名词、多实体共现、名词短语密度。

        Args:
            text: 输入文本

        Returns:
            归一化后的信号值 [0, 1]
        """
        tokens = self.encoding.encode(text, disallowed_special=())
        if not tokens:
            return 0.0

        # 简单的大写字母开头词计数（近似专有名词）
        capitalized_words = len(re.findall(r'\b[A-Z][a-z]+\b', text))

        # 名词短语检测（简化版：连续的大写单词）
        noun_phrases = len(re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b', text))

        # 计算密度
        density = (capitalized_words + noun_phrases * 2) / len(tokens) * 100
        return min(density / 15, 1.0)  # 假设 15% 为高密度

    def calculate_summary_alignment_signal(
        self,
        chunk_text: str,
        document_summary: str,
    ) -> float:
        """计算摘要对齐信号。

        计算 chunk 与 document_summary 的词重合度。

        Args:
            chunk_text: chunk 文本
            document_summary: 文档摘要

        Returns:
            Jaccard 相似度 [0, 1]
        """
        if not document_summary:
            return 0.0

        # 分词（简单按空白字符）
        chunk_words = set(w.lower() for w in re.findall(r'\b\w+\b', chunk_text))
        summary_words = set(w.lower() for w in re.findall(r'\b\w+\b', document_summary))

        if not chunk_words or not summary_words:
            return 0.0

        # Jaccard 相似度
        intersection = chunk_words & summary_words
        union = chunk_words | summary_words
        return len(intersection) / len(union) if union else 0.0

    def calculate_length_signal(
        self,
        text: str,
        optimal_min: int = 200,
        optimal_max: int = 600,
    ) -> float:
        """计算长度信号。

        过短或过长都降权，中间区间得分最高。

        Args:
            text: 输入文本
            optimal_min: 最优最小 token 数
            optimal_max: 最优最大 token 数

        Returns:
            归一化后的信号值 [0, 1]
        """
        tokens = self.encoding.encode(text, disallowed_special=())
        token_count = len(tokens)

        if optimal_min <= token_count <= optimal_max:
            return 1.0
        elif token_count < optimal_min:
            return max(0.0, token_count / optimal_min)
        else:
            return max(0.0, 1.0 - (token_count - optimal_max) / optimal_max)

    def calculate_ambiguity_penalty(self, text: str) -> float:
        """计算模糊性惩罚。

        代词比例高、上下文依赖强、残句明显时提高惩罚值。

        Args:
            text: 输入文本

        Returns:
            惩罚值 [0, 1]，越高越模糊
        """
        tokens = self.encoding.encode(text, disallowed_special=())
        if not tokens:
            return 1.0

        # 代词检测
        pronouns = len(re.findall(
            r'\b(?:he|she|it|they|this|that|these|those|which|who|whom|whose)\b',
            text,
            re.IGNORECASE
        ))

        # 代词比例
        pronoun_ratio = pronouns / len(tokens)

        # 句子完整性检测（以句号结尾）
        sentences = re.split(r'[.!?]+', text.strip())
        incomplete_sentences = sum(1 for s in sentences if s.strip() and not s.strip().endswith(('. ', '! ', '? ')))

        # 短句惩罚（少于 5 个 token 的句子）
        short_sentences = sum(1 for s in sentences if len(self.encoding.encode(s.strip())) < 5)

        penalty = (pronoun_ratio * 10 +
                   incomplete_sentences * 0.2 +
                   short_sentences * 0.1)

        return min(penalty, 1.0)

    def calculate_usage_penalty(
        self,
        usage_count: int,
        max_usage: int = 5,
    ) -> float:
        """计算使用次数惩罚。

        基于证据单元已使用次数计算惩罚。

        Args:
            usage_count: 已使用次数
            max_usage: 最大使用次数

        Returns:
            惩罚值 [0, 1]
        """
        return min(usage_count / max_usage, 1.0)

    def calculate_mcq_score(
        self,
        text: str,
        document_summary: str = "",
        usage_count: int = 0,
    ) -> float:
        """计算 MCQ 分数。

        MCQ 适合具有定义、枚举、事实明确的文本。

        Args:
            text: 输入文本
            document_summary: 文档摘要
            usage_count: 已使用次数

        Returns:
            MCQ 适合度分数 [0, 1]
        """
        definition = self.calculate_definition_signal(text)
        enumeration = self.calculate_enumeration_signal(text)
        numeric = self.calculate_numeric_signal(text)
        alignment = self.calculate_summary_alignment_signal(text, document_summary)
        length = self.calculate_length_signal(text)
        entity = self.calculate_entity_density_signal(text)
        ambiguity = self.calculate_ambiguity_penalty(text)
        usage = self.calculate_usage_penalty(usage_count)

        # 权重组合
        score = (
            0.25 * definition +
            0.20 * enumeration +
            0.20 * numeric +
            0.15 * alignment +
            0.10 * length +
            0.10 * entity -
            0.15 * ambiguity -
            0.05 * usage
        )

        return max(0.0, min(1.0, score))

    def calculate_qa_score(
        self,
        text: str,
        document_summary: str = "",
        usage_count: int = 0,
    ) -> float:
        """计算 QA 分数。

        QA 适合具有因果、机制、解释性内容的文本。

        Args:
            text: 输入文本
            document_summary: 文档摘要
            usage_count: 已使用次数

        Returns:
            QA 适合度分数 [0, 1]
        """
        causal = self.calculate_causal_signal(text)
        mechanism = self.calculate_mechanism_signal(text)
        alignment = self.calculate_summary_alignment_signal(text, document_summary)
        entity = self.calculate_entity_density_signal(text)
        conditional = self.calculate_conditional_signal(text)
        comparison = self.calculate_comparison_signal(text)
        ambiguity = self.calculate_ambiguity_penalty(text)
        usage = self.calculate_usage_penalty(usage_count)

        # 权重组合
        score = (
            0.25 * causal +
            0.25 * mechanism +
            0.20 * alignment +
            0.15 * entity +
            0.10 * conditional +
            0.05 * comparison -
            0.10 * ambiguity -
            0.05 * usage
        )

        return max(0.0, min(1.0, score))

    def calculate_hard_score(
        self,
        text: str,
        document_summary: str = "",
        usage_count: int = 0,
    ) -> float:
        """计算 Hard 题分数。

        Hard 适合具有复杂逻辑、比较、机制的文本。

        Args:
            text: 输入文本
            document_summary: 文档摘要
            usage_count: 已使用次数

        Returns:
            Hard 适合度分数 [0, 1]
        """
        causal = self.calculate_causal_signal(text)
        comparison = self.calculate_comparison_signal(text)
        mechanism = self.calculate_mechanism_signal(text)
        conditional = self.calculate_conditional_signal(text)
        entity = self.calculate_entity_density_signal(text)
        numeric = self.calculate_numeric_signal(text)
        alignment = self.calculate_summary_alignment_signal(text, document_summary)
        ambiguity = self.calculate_ambiguity_penalty(text)
        usage = self.calculate_usage_penalty(usage_count)

        # 权重组合
        score = (
            0.22 * causal +
            0.20 * comparison +
            0.18 * mechanism +
            0.12 * conditional +
            0.10 * entity +
            0.08 * numeric +
            0.10 * alignment -
            0.10 * ambiguity -
            0.08 * usage
        )

        return max(0.0, min(1.0, score))

    def calculate_all_scores(
        self,
        text: str,
        document_summary: str = "",
        usage_count: int = 0,
    ) -> dict[str, float]:
        """计算所有分数。

        Args:
            text: 输入文本
            document_summary: 文档摘要
            usage_count: 已使用次数

        Returns:
            包含所有分数的字典
        """
        return {
            "mcq_score": self.calculate_mcq_score(text, document_summary, usage_count),
            "qa_score": self.calculate_qa_score(text, document_summary, usage_count),
            "hard_score": self.calculate_hard_score(text, document_summary, usage_count),
        }

    def _normalize_count(
        self,
        count: int,
        text: str,
        max_expected: int,
    ) -> float:
        """归一化计数。

        Args:
            count: 原始计数
            text: 文本（用于计算长度归一化）
            max_expected: 期望的最大计数

        Returns:
            归一化后的值 [0, 1]
        """
        tokens = self.encoding.encode(text, disallowed_special=())
        if not tokens:
            return 0.0

        # 基于文本长度归一化
        length_normalized = count / (len(tokens) / 100)
        return min(length_normalized / max_expected, 1.0)

    def calculate_tags(self, text: str) -> list[str]:
        """计算文本标签。

        Args:
            text: 输入文本

        Returns:
            标签列表
        """
        tags = []

        if self.calculate_definition_signal(text) > 0.5:
            tags.append("definition")

        if self.calculate_comparison_signal(text) > 0.5:
            tags.append("comparison")

        if self.calculate_causal_signal(text) > 0.5:
            tags.append("causal")

        if self.calculate_mechanism_signal(text) > 0.5:
            tags.append("mechanism")

        if self.calculate_enumeration_signal(text) > 0.5:
            tags.append("enumeration")

        # 时间线检测（年份密集）
        if len(re.findall(r'\b(?:19|20)\d{2}\b', text)) >= 3:
            tags.append("timeline")

        # 数字密集
        if self.calculate_numeric_signal(text) > 0.6:
            tags.append("numeric_dense")

        # 实体密集
        if self.calculate_entity_density_signal(text) > 0.6:
            tags.append("entity_dense")

        return tags
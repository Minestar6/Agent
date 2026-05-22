"""多证据单元构建模块。"""

from typing import Any

import tiktoken

from benchforge.schemas import (
    SourceChunk,
    SingleChunkUnit,
    MultiChunkUnit,
    TopicStatus,
)
from benchforge.utils.signals import SignalCalculator


class MultiChunkBuilder:
    """多证据单元构建器。

    第一版仅支持同文档 chunk 组合，不支持跨文档组合。
    """

    def __init__(self, encoding_name: str = "cl100k_base"):
        """初始化构建器。

        Args:
            encoding_name: tiktoken 编码名称
        """
        self.encoding = tiktoken.get_encoding(encoding_name)
        self.signal_calculator = SignalCalculator(encoding_name)

    def build_multi_chunk_units(
        self,
        single_chunks: list[SingleChunkUnit],
        max_chunk_distance: int = 3,
        max_total_tokens: int = 1500,
        min_chunk_count: int = 2,
        max_chunk_count: int = 3,
    ) -> list[MultiChunkUnit]:
        """从单证据单元构建多证据单元。

        策略：
        1. 按文档分组
        2. 同文档内按相邻组合
        3. 过滤过长或过短组合
        4. 计算分数

        Args:
            single_chunks: 单证据单元列表
            max_chunk_distance: 最大 chunk 索引距离
            max_total_tokens: 最大总 token 数
            min_chunk_count: 最小 chunk 数
            max_chunk_count: 最大 chunk 数

        Returns:
            多证据单元列表
        """
        if not single_chunks:
            return []

        # 按文档分组
        chunks_by_doc: dict[str, list[SingleChunkUnit]] = {}
        for chunk in single_chunks:
            doc_id = chunk.document_id
            if doc_id not in chunks_by_doc:
                chunks_by_doc[doc_id] = []
            chunks_by_doc[doc_id].append(chunk)

        # 对每个文档构建多 chunk 单元
        multi_chunks: list[MultiChunkUnit] = []
        for doc_id, doc_chunks in chunks_by_doc.items():
            # 按 chunk 索引排序
            sorted_chunks = sorted(doc_chunks, key=lambda x: self._extract_chunk_index(x.chunk_id))

            # 滑动窗口构建
            for i in range(len(sorted_chunks)):
                for window_size in range(min_chunk_count, max_chunk_count + 1):
                    end = i + window_size
                    if end > len(sorted_chunks):
                        continue

                    window = sorted_chunks[i:end]

                    # 检查距离约束
                    if self._check_distance_constraint(window, max_chunk_distance):
                        multi_chunk = self._build_multi_chunk_from_window(window)
                        if multi_chunk and self._check_token_constraint(multi_chunk, max_total_tokens):
                            multi_chunks.append(multi_chunk)

        return multi_chunks

    def build_multi_chunk_units_smart(
        self,
        single_chunks: list[SingleChunkUnit],
        document_summaries: dict[str, str],
        target_count: int = 10,
        prioritize_hard_score: bool = True,
    ) -> list[MultiChunkUnit]:
        """智能构建多证据单元。

        基于信号分数和相关性选择最优组合。

        Args:
            single_chunks: 单证据单元列表
            document_summaries: 文档摘要字典 {document_id: summary}
            target_count: 目标数量
            prioritize_hard_score: 是否优先 hard 分数

        Returns:
            多证据单元列表
        """
        if not single_chunks:
            return []

        # 按文档分组
        chunks_by_doc: dict[str, list[SingleChunkUnit]] = {}
        for chunk in single_chunks:
            doc_id = chunk.document_id
            if doc_id not in chunks_by_doc:
                chunks_by_doc[doc_id] = []
            chunks_by_doc[doc_id].append(chunk)

        candidates: list[tuple[MultiChunkUnit, float]] = []

        for doc_id, doc_chunks in chunks_by_doc.items():
            summary = document_summaries.get(doc_id, "")
            sorted_chunks = sorted(doc_chunks, key=lambda x: self._extract_chunk_index(x.chunk_id))

            # 尝试所有可能的 2-3 chunk 组合
            for i in range(len(sorted_chunks)):
                # 2 chunk 组合
                if i + 1 < len(sorted_chunks):
                    pair = [sorted_chunks[i], sorted_chunks[i + 1]]
                    multi_chunk = self._build_multi_chunk_from_window(pair)
                    if multi_chunk:
                        score = self._calculate_multi_chunk_score(
                            multi_chunk,
                            summary,
                            prioritize_hard_score,
                        )
                        candidates.append((multi_chunk, score))

                # 3 chunk 组合
                if i + 2 < len(sorted_chunks):
                    triplet = [sorted_chunks[i], sorted_chunks[i + 1], sorted_chunks[i + 2]]
                    multi_chunk = self._build_multi_chunk_from_window(triplet)
                    if multi_chunk:
                        score = self._calculate_multi_chunk_score(
                            multi_chunk,
                            summary,
                            prioritize_hard_score,
                        )
                        candidates.append((multi_chunk, score))

        # 按分数排序
        candidates.sort(key=lambda x: x[1], reverse=True)

        # 返回前 target_count 个
        return [mc for mc, _ in candidates[:target_count]]

    def _build_multi_chunk_from_window(
        self,
        chunks: list[SingleChunkUnit],
    ) -> MultiChunkUnit | None:
        """从 chunk 窗口构建多证据单元。

        Args:
            chunks: 单证据单元列表

        Returns:
            多证据单元或 None
        """
        if not chunks:
            return None

        # 合并文本
        combined_text = " ".join(chunk.text for chunk in chunks)

        # 合并标签（去重）
        all_tags = set()
        for chunk in chunks:
            all_tags.update(chunk.tags)

        # 计算分数（基于合并文本）
        doc_id = chunks[0].document_id
        topic = chunks[0].topic

        scores = self.signal_calculator.calculate_all_scores(combined_text)

        return MultiChunkUnit(
            document_id=doc_id,
            topic=topic,
            chunk_ids=[chunk.chunk_id for chunk in chunks],
            texts=[chunk.text for chunk in chunks],
            tags=list(all_tags),
            mcq_score=scores["mcq_score"],
            qa_score=scores["qa_score"],
            hard_score=scores["hard_score"],
        )

    def _calculate_multi_chunk_score(
        self,
        multi_chunk: MultiChunkUnit,
        document_summary: str,
        prioritize_hard_score: bool,
    ) -> float:
        """计算多证据单元的综合得分。

        Args:
            multi_chunk: 多证据单元
            document_summary: 文档摘要
            prioritize_hard_score: 是否优先 hard 分数

        Returns:
            综合得分
        """
        combined_text = " ".join(multi_chunk.texts)

        # 基础分数
        if prioritize_hard_score:
            base_score = multi_chunk.hard_score
        else:
            base_score = (multi_chunk.mcq_score + multi_chunk.qa_score) / 2

        # 摘要对齐奖励
        alignment = self.signal_calculator.calculate_summary_alignment_signal(
            combined_text,
            document_summary,
        )

        # 长度适中奖励
        length_signal = self.signal_calculator.calculate_length_signal(combined_text)

        # 综合得分
        return 0.6 * base_score + 0.25 * alignment + 0.15 * length_signal

    def _check_distance_constraint(
        self,
        chunks: list[SingleChunkUnit],
        max_distance: int,
    ) -> bool:
        """检查 chunk 距离约束。

        Args:
            chunks: chunk 列表
            max_distance: 最大距离

        Returns:
            是否满足约束
        """
        indices = [self._extract_chunk_index(c.chunk_id) for c in chunks]
        return max(indices) - min(indices) <= max_distance

    def _check_token_constraint(
        self,
        multi_chunk: MultiChunkUnit,
        max_tokens: int,
    ) -> bool:
        """检查 token 数约束。

        Args:
            multi_chunk: 多证据单元
            max_tokens: 最大 token 数

        Returns:
            是否满足约束
        """
        combined_text = " ".join(multi_chunk.texts)
        tokens = self.encoding.encode(combined_text, disallowed_special=())
        return len(tokens) <= max_tokens

    @staticmethod
    def _extract_chunk_index(chunk_id: str) -> int:
        """从 chunk_id 中提取索引。

        Args:
            chunk_id: chunk ID

        Returns:
            索引
        """
        try:
            # 尝试匹配格式 "doc_xxx::chunk_1234"
            if "::chunk_" in chunk_id:
                return int(chunk_id.split("chunk_")[-1])
            # 尝试匹配末尾数字
            import re
            match = re.search(r'(\d+)$', chunk_id)
            return int(match.group(1)) if match else 0
        except (ValueError, AttributeError):
            return 0


def build_evidence_pool_from_chunks(
    chunks: list[SourceChunk],
    topic: str,
    document_summary: str = "",
) -> list[SingleChunkUnit]:
    """从源 chunks 构建单证据单元。

    Args:
        chunks: 源 chunk 列表
        topic: 主题
        document_summary: 文档摘要

    Returns:
        单证据单元列表
    """
    calculator = SignalCalculator()

    units = []
    for chunk in chunks:
        scores = calculator.calculate_all_scores(chunk.text, document_summary)
        tags = calculator.calculate_tags(chunk.text)

        unit = SingleChunkUnit(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            topic=topic,
            text=chunk.text,
            tags=tags,
            mcq_score=scores["mcq_score"],
            qa_score=scores["qa_score"],
            hard_score=scores["hard_score"],
        )
        units.append(unit)

    return units
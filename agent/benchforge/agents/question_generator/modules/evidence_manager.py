"""EvidenceManager 模块：检索、分块、证据池、采样。"""

from typing import Any
from dataclasses import dataclass

from benchforge.utils import (
    search_wikipedia,
    fetch_wikipedia_page,
    chunk_document,
)
from benchforge.utils.multi_chunk import (
    MultiChunkBuilder,
    build_evidence_pool_from_chunks,
)
from benchforge.utils.sampling import (
    BroadExplorationSampling,
    GapDrivenSampling,
)
from benchforge.utils.planning import format_evidence_texts


@dataclass
class ExpandResult:
    """扩展检索结果。"""
    new_chunks: int
    new_single_units: int
    new_multi_units: int


class EvidenceManager:
    """证据管理器。

    职责：
    - 检索主题相关文档
    - 生成文档摘要
    - 切分 chunk
    - 构建证据池
    - 采样证据（支持单/多 chunk）
    - 扩展检索
    """

    def __init__(self, config: Any):
        """初始化证据管理器。

        Args:
            config: 配置对象
        """
        self.config = config
        self.multi_chunk_builder = MultiChunkBuilder()
        self.document_summaries: dict[str, str] = {}

    async def prepare_evidence(
        self,
        topic: str,
        plan: Any,
    ) -> tuple[list[Any], Any]:
        """准备证据池。

        步骤：
        1. 检索主题相关文档
        2. 生成文档摘要
        3. 切分 chunk
        4. 构建证据池

        Args:
            topic: 主题名称
            plan: 生成计划

        Returns:
            (chunk 列表, 证据池)
        """
        # 检索文档
        search_results = search_wikipedia(
            query=topic,
            language=plan.language,
            max_pages=self.config.retrieval.max_pages,
        )

        if not search_results:
            return [], None

        # 抓取并处理文档
        all_chunks: list[Any] = []

        for result in search_results:
            document = fetch_wikipedia_page(
                result=result,
                run_id=plan.run_id,
                language=plan.language,
                content_max_length=self.config.retrieval.content_max_length,
            )

            if document.status.value == "failed":
                continue

            # 分块
            chunks = chunk_document(
                document=document,
                chunk_size=self.config.chunking.chunk_size,
                overlap=self.config.chunking.overlap,
            )

            # 生成文档摘要
            summary = await self._generate_document_summary(document, chunks)
            self.document_summaries[document.document_id] = summary

            all_chunks.extend(chunks)

        # 构建证据池
        evidence_pool = self._build_evidence_pool(topic, all_chunks)

        return all_chunks, evidence_pool

    async def _generate_document_summary(
        self,
        document: Any,
        chunks: list[Any],
    ) -> str:
        """生成文档摘要。

        使用 LLM 生成摘要（复用 Yourbench prompts）。

        步骤：
        1. 对每个 chunk 生成摘要
        2. 如果有多个 chunk，合并摘要

        Args:
            document: 源文档
            chunks: chunk 列表

        Returns:
            文档摘要
        """
        if not chunks:
            return document.summary or ""

        # 简化实现：返回前三个 chunk 的摘要
        summaries = []
        for chunk in chunks[:3]:
            summaries.append(chunk.text[:200])

        return " | ".join(summaries)

    def _build_evidence_pool(
        self,
        topic: str,
        chunks: list[Any],
    ) -> Any:
        """构建证据池。

        Args:
            topic: 主题名称
            chunks: chunk 列表

        Returns:
            证据池
        """
        from benchforge.schemas import EvidencePool

        # 按文档分组 chunks
        chunks_by_doc: dict[str, list[Any]] = {}
        for chunk in chunks:
            if chunk.document_id not in chunks_by_doc:
                chunks_by_doc[chunk.document_id] = []
            chunks_by_doc[chunk.document_id].append(chunk)

        # 构建单证据单元
        single_units = []
        for doc_id, doc_chunks in chunks_by_doc.items():
            doc_summary = self.document_summaries.get(doc_id, "")
            doc_units = build_evidence_pool_from_chunks(
                doc_chunks,
                topic,
                document_summary=doc_summary,
            )
            single_units.extend(doc_units)

        # 构建多证据单元
        doc_summaries = {
            doc_id: self.document_summaries.get(doc_id, "")
            for doc_id in chunks_by_doc.keys()
        }

        multi_units = self.multi_chunk_builder.build_multi_chunk_units_smart(
            single_units,
            doc_summaries,
            target_count=min(10, len(single_units) // 2),
        )

        # 创建证据池
        pool = EvidencePool(
            topic=topic,
            single_chunks=single_units,
            multi_chunks=multi_units,
        )

        return pool

    def sample(
        self,
        evidence_pool: Any,
        topic: str,
        target_mode: str,
        target_difficulty: str,
        prefer_multi_chunk: bool = False,
        round_num: int = 1,
        remaining: int = 1,
    ) -> Any:
        """采样证据。

        使用采样策略：
        - 第 1 轮：BroadExplorationSampling（广度探索）
        - 其他轮：GapDrivenSampling（缺口驱动）

        Args:
            evidence_pool: 证据池
            topic: 主题名称
            target_mode: 目标模式
            target_difficulty: 目标难度
            prefer_multi_chunk: 是否偏好多 chunk
            round_num: 轮次（用于选择采样策略）
            remaining: 剩余缺口数量

        Returns:
            生成批次
        """
        # 选择采样策略
        if round_num == 1:
            sampler = BroadExplorationSampling()
        else:
            sampler = GapDrivenSampling()

        # 计算请求数量（冗余策略）
        num_evidence = self._calculate_num_evidence(remaining)

        # 执行采样
        batch = sampler.sample(
            pool=evidence_pool,
            target_mode=target_mode,
            target_difficulty=target_difficulty,
            num_evidence=num_evidence,
            prefer_multi_chunk=prefer_multi_chunk,
        )

        # 设置请求数量
        min_questions, target_questions = self._calculate_batch_request_counts(remaining)
        batch.requested_min_questions = min_questions
        batch.requested_target_questions = target_questions

        # 更新使用计数
        for unit in evidence_pool.single_chunks:
            if unit.chunk_id in batch.single_chunk_ids:
                unit.usage_count += 1

        for unit in evidence_pool.multi_chunks:
            if unit.unit_id in batch.multi_chunk_ids:
                unit.usage_count += 1

        return batch

    def _calculate_num_evidence(self, remaining_count: int) -> int:
        """计算需要采样的证据数量。

        Args:
            remaining_count: 剩余目标数量

        Returns:
            证据数量
        """
        # 最多 5 个证据单元
        return min(5, remaining_count + 2)

    def _calculate_batch_request_counts(
        self,
        remaining_count: int,
    ) -> tuple[int, int]:
        """计算批次请求的题目数量。

        使用冗余策略而非精确计算。

        Args:
            remaining_count: 剩余目标数量

        Returns:
            (最小请求数, 目标请求数)
        """
        if remaining_count <= 2:
            return remaining_count + 1, remaining_count + 2
        elif remaining_count <= 5:
            return remaining_count + 1, remaining_count + 3
        else:
            return remaining_count + 2, remaining_count + 4

    async def expand_retrieval(
        self,
        topic: str,
        queries: list[str],
        language: str,
        run_id: str,
        evidence_pool: Any,
    ) -> ExpandResult:
        """扩展检索。

        Args:
            topic: 主题名称
            queries: 查询列表
            language: 语言
            run_id: 运行 ID
            evidence_pool: 现有证据池（用于扩展）

        Returns:
            扩展结果
        """
        from benchforge.schemas import TopicState

        all_chunks: list[Any] = []

        for query in queries:
            results = search_wikipedia(
                query=query,
                language=language,
                max_pages=2,
            )

            for result in results:
                document = fetch_wikipedia_page(
                    result=result,
                    run_id=run_id,
                    language=language,
                    content_max_length=self.config.retrieval.content_max_length,
                )

                if document.status.value == "failed":
                    continue

                chunks = chunk_document(
                    document=document,
                    chunk_size=self.config.chunking.chunk_size,
                    overlap=self.config.chunking.overlap,
                )

                # 生成摘要
                summary = await self._generate_document_summary(document, chunks)
                self.document_summaries[document.document_id] = summary

                all_chunks.extend(chunks)

        # 构建新单元
        single_units = build_evidence_pool_from_chunks(
            all_chunks,
            topic,
            document_summary="",
        )

        # 构建多 chunk 单元
        doc_summaries = {
            chunk.document_id: self.document_summaries.get(chunk.document_id, "")
            for chunk in all_chunks
        }

        multi_units = self.multi_chunk_builder.build_multi_chunk_units_smart(
            single_units,
            doc_summaries,
            target_count=min(5, len(single_units) // 2),
        )

        # 扩展到现有证据池
        if evidence_pool:
            evidence_pool.single_chunks.extend(single_units)
            evidence_pool.multi_chunks.extend(multi_units)

        return ExpandResult(
            new_chunks=len(all_chunks),
            new_single_units=len(single_units),
            new_multi_units=len(multi_units),
        )

    def get_evidence_text(
        self,
        batch: Any,
        evidence_pool: Any,
    ) -> str:
        """获取格式化后的证据文本。

        Args:
            batch: 生成批次
            evidence_pool: 证据池

        Returns:
            格式化后的证据文本
        """
        # 获取证据单元
        single_units = [
            u for u in evidence_pool.single_chunks
            if u.chunk_id in batch.single_chunk_ids
        ]
        multi_units = [
            u for u in evidence_pool.multi_chunks
            if u.unit_id in batch.multi_chunk_ids
        ]

        return format_evidence_texts(single_units, multi_units)

    def get_document_summary(
        self,
        batch: Any,
        evidence_pool: Any,
    ) -> str:
        """获取文档摘要。

        Args:
            batch: 生成批次
            evidence_pool: 证据池

        Returns:
            文档摘要
        """
        single_units = [
            u for u in evidence_pool.single_chunks
            if u.chunk_id in batch.single_chunk_ids
        ]

        if single_units and single_units[0].document_id in self.document_summaries:
            return self.document_summaries[single_units[0].document_id]

        return ""
"""检索工具。"""

from typing import Any

from benchforge.tools.base_tool import BaseTool, ToolSpec, ToolResult
from benchforge.utils import search_wikipedia, fetch_wikipedia_page, chunk_document
from benchforge.utils.multi_chunk import build_evidence_pool_from_chunks


class RetrievalTool(BaseTool):
    """检索工具。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="expand_retrieval",
            description="扩展检索，获取更多相关文档",
            input_schema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "主题名称"},
                    "queries": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "查询列表"
                    },
                    "max_pages": {
                        "type": "integer",
                        "default": 3,
                        "description": "最大页面数"
                    },
                },
                "required": ["topic", "queries"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "new_documents_count": {"type": "integer"},
                    "new_chunks_count": {"type": "integer"},
                },
            },
            retryable=True,
            max_retries=2,
            timeout=120,
        )

    async def execute(self, parameters: dict[str, Any], state: dict[str, Any]) -> ToolResult:
        """执行检索扩展。

        Args:
            parameters: 输入参数
            state: 当前状态

        Returns:
            执行结果
        """
        topic = parameters["topic"]
        queries = parameters["queries"]
        max_pages = parameters.get("max_pages", 3)
        language = state.get("language", "en")

        # 获取run_id
        run_id = state.get("run_id", "default")

        # 获取chunking配置
        chunk_size = state.get("chunk_size", 1200)
        overlap = state.get("overlap", 150)

        # 获取证据池
        pool = state.get("evidence_pools", {}).get(topic)
        if not pool:
            return ToolResult(
                success=False,
                output={},
                error=f"Evidence pool not found for topic: {topic}"
            )

        try:
            total_new_chunks = []
            total_new_documents = 0

            # 对每个查询进行检索
            for query in queries:
                # 搜索
                search_results = search_wikipedia(
                    query=query,
                    language=language,
                    max_pages=max_pages
                )

                # 处理每个结果
                for result in search_results:
                    # 获取页面
                    document = fetch_wikipedia_page(
                        result=result,
                        run_id=run_id,
                        language=language,
                        content_max_length=state.get("content_max_length", 10000),
                    )

                    if document.status.value == "failed":
                        continue

                    total_new_documents += 1

                    # 检查是否已存在
                    if document.document_id not in state.get("retrieved_documents", []):
                        # 分块
                        chunks = chunk_document(
                            document=document,
                            chunk_size=chunk_size,
                            overlap=overlap
                        )

                        # 构建证据单元
                        single_units = build_evidence_pool_from_chunks(
                            chunks=chunks,
                            topic=topic,
                            document_summary=""
                        )

                        # 添加到证据池
                        pool.single_chunks.extend(single_units)
                        total_new_chunks.extend(single_units)

                        # 记录已检索
                        if "retrieved_documents" not in state:
                            state["retrieved_documents"] = []

                        state["retrieved_documents"].append(document.document_id)

            # 重建多证据单元（简化版：只添加新证据）
            # 实际实现可能需要更复杂的逻辑
            # 这里省略

            return ToolResult(
                success=True,
                output={
                    "new_documents_count": total_new_documents,
                    "new_chunks_count": len(total_new_chunks),
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                output={},
                error=f"Retrieval failed: {e}"
            )
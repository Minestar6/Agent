import json
import os
from pathlib import Path
import time
from typing import Any, Dict, List
from dataclasses import dataclass
from loguru import logger
import sys
sys.path.append(r"D:\Download\vscode\code\agent")
from utils.chunk import ChunkSamplingConfig, sample_chunks
from utils.model import Model



@dataclass
class BuilderMetrics:
    """Metrics for tracking inference call generation."""
    total_documents: int = 0
    total_chunks_processed: int = 0
    total_prompts_generated: int = 0
    skipped_chunks: int = 0
    avg_chunk_length: float = 0.0
    processing_time: float = 0.0
    error_count: int = 0
    warnings: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


def _calculate_chunk_stats(chunks: List[Dict]) -> Dict[str, float]:
    """Calculate statistics for chunks."""
    if not chunks:
        return {"avg_length": 0.0, "total_length": 0, "count": 0}

    lengths = [len(chunk.get("chunk_text", "")) for chunk in chunks]
    return {
        "avg_length": sum(lengths) / len(lengths),
        "total_length": sum(lengths),
        "count": len(lengths),
        "min_length": min(lengths),
        "max_length": max(lengths),
    }


def single_shot_prompts(dataset, sampling_cfg, single_shot_user_prompt, additional_instructions=""):
    """Build single-shot prompts with enhanced tracking."""
    start_time = time.time()
    prompts = []
    index_map = []
    metrics = BuilderMetrics()

    logger.info(f"Building single-shot prompts for {len(dataset)} documents")

    # 遍历每一个文档
    for idx, row in enumerate(dataset):
        try:
            metrics.total_documents += 1
            document_chunks = row.get("chunks") or []

            if not document_chunks:
                metrics.warnings.append(f"Document {idx} has no chunks")
                continue
            
            # chunk采样
            selected_chunks = sample_chunks(document_chunks, sampling_cfg)
            chunk_stats = _calculate_chunk_stats(selected_chunks)

            for ch_idx, chunk in enumerate(selected_chunks):
                try:
                    metrics.total_chunks_processed += 1
                    chunk_id = chunk.get("chunk_id", f"{idx}_{ch_idx}")
                    chunk_text = chunk.get("chunk_text", "")

                    if not chunk_text.strip():
                        metrics.skipped_chunks += 1
                        metrics.warnings.append(f"Empty chunk {chunk_id}")
                        continue

                    # Get additional instructions with fallback
                    
                    user_prompt = single_shot_user_prompt.format(
                            title=row.get("topic", ""),
                            document_summary=row.get("document_summary", ""),
                            text_chunk=chunk_text,
                            additional_instructions=additional_instructions,
                        )
                    
                    prompts.append(user_prompt)
                    index_map.append((idx, row.get("document_id", f"doc_{idx}"), chunk_id))
                    metrics.total_prompts_generated += 1

                except Exception as e:
                    metrics.error_count += 1
                    metrics.warnings.append(f"Error processing chunk {ch_idx} in document {idx}: {str(e)}")
                    logger.warning(f"Error processing chunk {ch_idx} in document {idx}: {e}")
                    continue

            # Log chunk statistics for this document
            if chunk_stats["count"] > 0:
                logger.debug(
                    f"Document {idx}: processed {chunk_stats['count']} chunks, "
                    f"avg_length={chunk_stats['avg_length']:.0f}, "
                    f"total_length={chunk_stats['total_length']}"
                )

        except Exception as e:
            metrics.error_count += 1
            metrics.warnings.append(f"Error processing document {idx}: {str(e)}")
            logger.error(f"Error processing document {idx}: {e}")
            continue

    metrics.processing_time = time.time() - start_time

    # Calculate average chunk length
    if metrics.total_chunks_processed > 0:
        total_length = sum(len(item) for item in prompts)
        metrics.avg_chunk_length = total_length / metrics.total_chunks_processed

    # Log final metrics
    logger.info(
        f"Single-shot builder completed: {metrics.total_prompts_generated} prompts from "
        f"{metrics.total_documents} documents, {metrics.total_chunks_processed} chunks processed "
        f"(skipped: {metrics.skipped_chunks}, errors: {metrics.error_count}) "
        f"in {metrics.processing_time:.2f}s"
    )

    if metrics.warnings:
        logger.warning(f"Builder warnings: {len(metrics.warnings)} total")
        for warning in metrics.warnings[:5]:  # Show first 5 warnings
            logger.warning(f"  - {warning}")
        if len(metrics.warnings) > 5:
            logger.warning(f"  ... and {len(metrics.warnings) - 5} more warnings")

    return prompts, index_map


def multi_hop_prompts(dataset,sampling_cfg,multi_hop_user_prompt,additional_instructions=""):
    """Build multi-hop prompts with enhanced tracking."""
    start_time = time.time()
    prompts = []
    index_map = []
    metrics = BuilderMetrics()

    logger.info(f"Building multi-hop prompts for {len(dataset)} documents")

    for idx, row in enumerate(dataset):
        try:
            metrics.total_documents += 1
            multihop_chunks = row.get("multihop_chunks") or []

            if not multihop_chunks:
                metrics.warnings.append(f"Document {idx} has no multihop chunks")
                continue


            groups = sample_chunks(multihop_chunks, sampling_cfg)

            for group_idx, group in enumerate(groups):
                try:
                    if not isinstance(group, dict):
                        metrics.warnings.append(f"Multihop group {group_idx} in document {idx} is not a dict")
                        logger.warning(f"Multihop group {group_idx} in document {idx} is not a dict, skipping")
                        continue

                    chunk_ids = group.get("chunk_ids", [])
                    texts = group.get("chunks_text", [])

                    if not texts:
                        metrics.warnings.append(f"Group {group_idx} in document {idx} has empty chunks_text")
                        logger.warning(f"Group {group_idx} in document {idx} has empty chunks_text, skipping")
                        continue

                    metrics.total_chunks_processed += len(texts)

                    # Format chunks with XML-like tags
                    full_text = "".join([f"<text_chunk_{i}>{t}</text_chunk_{i}>\n" for i, t in enumerate(texts)])

                    
                    
                    user_prompt =  multi_hop_user_prompt.format(
                            title=row.get("document_filename", f"doc_{idx}"),
                            document_summary=row.get("document_summary", ""),
                            chunks=full_text,
                            additional_instructions=additional_instructions,
                        )
                    prompts.append(user_prompt)
                    index_map.append((idx, row.get("document_id", f"doc_{idx}"), chunk_ids))
                    metrics.total_prompts_generated += 1

                    # Log group statistics
                    avg_chunk_length = sum(len(t) for t in texts) / len(texts)
                    logger.debug(
                        f"Document {idx} group {group_idx}: {len(texts)} chunks, "
                        f"avg_length={avg_chunk_length:.0f}, total_length={len(full_text)}"
                    )

                except Exception as e:
                    metrics.error_count += 1
                    metrics.warnings.append(f"Error processing group {group_idx} in document {idx}: {str(e)}")
                    logger.warning(f"Error processing group {group_idx} in document {idx}: {e}")
                    continue

        except Exception as e:
            metrics.error_count += 1
            metrics.warnings.append(f"Error processing document {idx}: {str(e)}")
            logger.error(f"Error processing document {idx}: {e}")
            continue

    metrics.processing_time = time.time() - start_time

    # Calculate average chunk length
    if metrics.total_chunks_processed > 0:
        total_length = sum(len(call) for call in prompts)
        metrics.avg_chunk_length = total_length / metrics.total_chunks_processed

    # Log final metrics
    logger.info(
        f"Multi-hop builder completed: {metrics.total_prompts_generated} prompts from "
        f"{metrics.total_documents} documents, {metrics.total_chunks_processed} chunks processed "
        f"(errors: {metrics.error_count}) in {metrics.processing_time:.2f}s"
    )

    if metrics.warnings:
        logger.warning(f"Builder warnings: {len(metrics.warnings)} total")
        for warning in metrics.warnings[:5]:  # Show first 5 warnings
            logger.warning(f"  - {warning}")
        if len(metrics.warnings) > 5:
            logger.warning(f"  ... and {len(metrics.warnings) - 5} more warnings")

    return prompts, index_map


def get_performance_summary(prompts, processing_time) -> Dict[str, Any]:
    """Generate performance summary for builder operations."""
    if not prompts:
        return {"total_prompts": 0, "processing_time": processing_time}

    
    prompt_lengths = []

    for call in prompts:
        prompt_lengths.append(len(call))

    avg_prompt_length = sum(prompt_lengths) / len(prompt_lengths) if prompt_lengths else 0

    return {
        "total_prompts": len(prompts),
        "processing_time": processing_time,
        "avg_prompt_length": avg_prompt_length,
        "min_prompt_length": min(prompt_lengths) if prompt_lengths else 0,
        "max_prompt_length": max(prompt_lengths) if prompt_lengths else 0,
        "prompts_per_second": len(prompts) / processing_time if processing_time > 0 else 0,
    }

def read_file(file_path, encoding='utf-8'):  
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")
    
    if not file_path.is_file():
        raise ValueError(f"路径不是文件: {file_path}")
    suffix = file_path.suffix.lower()
    with open(file_path, 'r', encoding=encoding) as f:
        content = f.read()
    if suffix == '.json':
        return json.loads(content)
    return content






if __name__ == "__main__":
    path = r"D:\Download\vscode\code\agent\utils\document.json" 
    data = read_file(path)
    system_prompt = read_file(r"D:\Download\vscode\code\agent\prompts\single_shot_system_prompt.md")
    user_prompt = read_file(r"D:\Download\vscode\code\agent\prompts\single_shot_user_prompt.md")
    sample_cfg = ChunkSamplingConfig(mode="count",value=3)
    prompts,_ = single_shot_prompts(data,sample_cfg,user_prompt)
    res = []
    model_name = "DeepSeek-V3.1"
    temperature = 0.1
    max_tokens = 8192
    model = Model(model_name)
    for pmt in prompts:
        response =  model.generate([pmt],system_prompt=system_prompt,temperature=temperature,max_tokens=max_tokens)
        res.append({'prompt':pmt,'response':response})
        print("AAAA\n")
    with open(f"chunk_ques.json", "w",encoding='utf8') as f:
        json.dump(res, f,ensure_ascii=False,indent=4)
    

"""Document chunking pipeline stage."""

import hashlib
from functools import cache
import json
import random
import numpy as np
from nltk.tokenize import sent_tokenize
from dataclasses import dataclass
import sys
sys.path.append(r"D:\Download\vscode\code\agent")
from utils.model import _get_encoder
from utils.wiki import search_step

"""
包含的属性
topic
text
id
summery 
chunks
"""
# 不同的采样模式，百分比/随机/所有
CHUNK_MODE_PERCENT = "percentage"
CHUNK_MODE_COUNT = "count"
CHUNK_MODE_ALL = "all"


# 切块的数据格式
@dataclass
class ChunkSamplingConfig:
    mode: str = CHUNK_MODE_ALL
    value: float = 1.0
    random_seed: int = 42


# 安全采样，数量不越界
def safe_sample(lst, k):
    """Sample k elements from lst, or return lst if k >= len(lst)"""
    return random.sample(lst, k) if k < len(lst) else lst

# 单跳采样：根据不同的模式返回不同的chunk_list
def sample_chunks(chunks_list, chunk_sampling):
    if not chunks_list:
        return []

    random.seed(chunk_sampling.random_seed)
    mode = chunk_sampling.mode.lower()
    value = chunk_sampling.value
    total = len(chunks_list)

    if mode == CHUNK_MODE_PERCENT:
        k = int(total * value)
        return safe_sample(chunks_list, k)
    elif mode == CHUNK_MODE_COUNT:
        k = min(int(value), total)
        return safe_sample(chunks_list, k)
    else:
        return chunks_list






# 产生随机数
@cache
def _get_rng(seed: str) -> np.random.Generator:
    """Get deterministic RNG from string seed."""
    seed_int = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)
    return np.random.default_rng(seed_int)

# 将文本切分成：直接按照token数目切分，tokens[i : i + chunk_tokens]切分并编码
"""
想要进一步优化：根据语义和段落关系，不要半句话
"""
def regular_sentence(text):
    """
    使用NLTK去除段落前后不完整的句子。
    注意：NLTK对缩写（如“Dr.”、“U.S.”）的分割可能不如spaCy精确。
    """
    sentences = sent_tokenize(text)
    
    if not sentences:
        return ""
    
    # 判断首句是否完整
    first_sent = sentences[0].strip()
    if first_sent and  not first_sent[0].isupper():
        sentences = sentences[1:]
        
    
    # 判断尾句是否完整
    if sentences:
        last_sent = sentences[-1].strip()
        if last_sent and last_sent[-1] not in ('.', '?', '!'):
            sentences = sentences[:-1]
            
    return " ".join(sentences).strip()


def split_into_token_chunks(
    text: str,
    chunk_tokens: int = 1024,
    overlap: int = 100,
    model_name: str = "DeepSeek-V3.1",
) -> list[str]:
    """
    Splits text into token-based chunks, with optional preprocessing.

    Args:
        text (str): The input text.
        chunk_tokens (int): Max tokens per chunk.
        overlap (int): Number of overlapping tokens.
        encoding_name (str): tiktoken encoding name.

    Returns:
        list[str]: List of decoded text chunks.
    """
    tokenizer = _get_encoder(model_name)
    tokens = tokenizer.encode(text, add_special_tokens=False)
    stride = chunk_tokens - overlap
    res = [regular_sentence(tokenizer.decode(tokens[i : i + chunk_tokens])) for i in range(0, len(tokens), stride)]
    return res

# 先按照字符串大小切分
def _chunk_text(model_name,text: str, doc_id: str,start_id:int,max_tokens: int) -> list[dict]:
    """Split text into token-based chunks."""
    if not text.strip():
        return []
    chunks = split_into_token_chunks(text, max_tokens, overlap=0,model_name=model_name)
    return [{"chunk_id": f"{doc_id}_{i+start_id}", "chunk_text": chunk} for i, chunk in enumerate(chunks)]

# 多跳组合生成函数，根据参数返回二维的列表
def _sample_multihop_combinations(n_chunks: int, h_min: int, h_max: int, factor: int, doc_id: str) -> list[list[int]]:
    """Generate random multi-hop chunk combinations."""

    # If we have only 1 chunk, create a single-chunk combination for cross-document use
    if n_chunks == 1:
        return [[0]]

    # Original logic for multiple chunks per document
    if n_chunks < h_min or h_min > h_max or h_min <= 0:
        return []

    h_max = min(h_max, n_chunks)
    target_count = max(1, n_chunks // max(1, factor))

    # Generate combinations of different sizes
    rng = _get_rng(doc_id)
    combinations_list = []

    for size in range(h_min, h_max + 1):
        n_combos = max(1, target_count // (h_max - h_min + 1))  # 目标数量
        if n_combos >= n_chunks:
            # If requesting more combos than possible, just take a few
            n_combos = min(5, n_chunks // size)

        # Generate unique combinations for this size
        all_indices = list(range(n_chunks))
        for _ in range(n_combos):
            if len(all_indices) >= size:
                combo = sorted(rng.choice(all_indices, size=size, replace=False))
                # Convert numpy int64 to regular int to avoid serialization issues
                combo = [int(x) for x in combo]
                combinations_list.append(combo)

    # Deduplicate
    seen = set()
    unique_combos = []
    for combo in combinations_list:
        key = tuple(combo)
        if key not in seen:
            seen.add(key)
            unique_combos.append(combo)

    result = unique_combos[:target_count]
    return result

# 文档处理函数，生成块和多跳组合
def _process_document(model_name,doc,max_tokens,h_min,h_max,multihops_factor) -> tuple[list[dict], list[dict]]:
    """Process a single document into chunks and multihop combinations."""
    doc_text = doc.get("document_text")
    doc_id = doc.get("doc_id")
   
    chunks = []
    # Create single-hop chunks
    for text in doc_text:
        start_id = len(chunks)
        chunks += _chunk_text(model_name,text, doc_id,start_id,max_tokens)
    if not chunks:
        return [], []

    # Create multi-hop combinations
    combos = _sample_multihop_combinations(len(chunks), h_min, h_max, multihops_factor, doc_id)

    multihop_chunks = [
        {"chunk_ids": [chunks[i]["chunk_id"] for i in combo], "chunks_text": [chunks[i]["chunk_text"] for i in combo]}
        for combo in combos
    ]

    return chunks, multihop_chunks




# def run() -> None:
#     """Execute chunking pipeline stage."""

#     logger.info("Starting chunking stage...")
#     cfg = config.pipeline_config.chunking

#     # Load dataset
#     dataset = custom_load_dataset(config=config, subset="summarized")
#     logger.info(f"Processing {len(dataset)} documents")

#     # Process all documents
#     all_chunks = []
#     all_multihops = []

#     for row in tqdm(dataset, desc="Chunking"):
#         chunks, multihops = _process_document(row, cfg)
#         all_chunks.append(chunks)
#         all_multihops.append(multihops)

#     # Add to dataset and save
#     dataset = dataset.add_column("chunks", all_chunks)
#     dataset = dataset.add_column("multihop_chunks", all_multihops)
#     custom_save_dataset(dataset=dataset, config=config, subset="chunked")

#     # Log statistics
#     total_chunks = sum(len(c) for c in all_chunks)
#     total_multihop = sum(len(m) for m in all_multihops)
#     logger.success(f"Chunking complete: {total_chunks} chunks, {total_multihop} multihop combinations")

if __name__ == "__main__":
    # category = 'Renaissance'
    # paragraph, wiki_entity = search_step(category,min_token=20,output_more=True)
    # text = "\n".join(paragraph)
    # with open(f"a.txt", "w",encoding='utf8') as f:
    #     f.write(text)

    # doc_id = f"doc_{hash(text) % 10000}"
    # res = {'topic':category,'doc_id':doc_id,'document_text':text}
    # with open(f"document.json", "w",encoding='utf8') as f:
    #     json.dump([res], f,ensure_ascii=False,indent=4)
            
    paragraph = ""
    with open(f"a.txt", "r",encoding='utf8') as f:
        for line in f:
            paragraph += line.strip() + '\n'

    model_name = 'DeepSeek-V3.1'
    max_tokens = 512
    h_min = 2
    h_max = 5
    multihops_factor = 2
    chunks, multihops = _process_document(model_name,paragraph,max_tokens,h_min,h_max,multihops_factor)
    list1 = {"chunks":chunks,"mutichunks":multihops}
    with open(f"b.json", "w",encoding='utf8') as f:
        json.dump(list1, f,ensure_ascii=False,indent=4)
    
    
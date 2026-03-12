
import json
import tqdm
import sys
sys.path.append(r"D:\Download\vscode\code\agent")
from utils.chunk import split_into_token_chunks
from utils.model import Model, _get_encoder, extract_content_from_xml_tags

"""
根据prompt和
"""

summary_prompt = """
You are an AI assistant tasked with analyzing and summarizing documents from various domains. Your goal is to generate a concise yet comprehensive summary of the given document. Follow these steps carefully:

1. You will be provided with a document extracted from a website. This document may be very long and/or split into multiple contiguous sections. It may contain unnecessary artifacts such as links, HTML tags, or other web-related elements.

2. Here is the document to be summarized:
<document>
{document}
</document>

3. Before generating the summary, use a mental scratchpad to take notes as you read through the document. Enclose your notes within <scratchpad> tags. For example:

<scratchpad>
- Main topic: [Note the main subject of the document]
- Key points: [List important information across the entire document]
- Structure: [Note how the document is organized or chunked]
- Potential artifacts to ignore: [List any web-related elements that should be disregarded]
</scratchpad>

4. As you analyze the document:
   - Focus solely on the content, ignoring any unnecessary web-related elements.
   - Treat all sections or chunks as part of a single, continuous document.
   - Identify the main topic and key points from the entire input.
   - Pay attention to the overall structure and flow of the document.

5. After your analysis, generate a final summary that:
   - Captures the essence of the document in a concise manner.
   - Includes the main topic and key points.
   - Presents information in a logical and coherent order.
   - Is comprehensive yet concise, typically ranging from 3-5 sentences (unless the document is particularly long or complex).

6. Enclose your final summary within <final_summary> tags. For example:

<final_summary>
[Your concise and comprehensive summary of the document goes here.]
</final_summary>

Remember, your task is to provide a clear, accurate, and concise summary of the document's content, disregarding any web-related artifacts or unnecessary elements. For long documents, ensure your summary reflects the complete scope and structure of the content. 
"""

summary_combine_prompt = """
You will receive a list of chunk-level summaries from the *same* document.  Combine them into a single, well-structured paragraph that reads naturally and eliminates redundancy.

<chunk_summaries>
{chunk_summaries}
</chunk_summaries>

Return ONLY the final text inside <final_summary> tags. 
"""




def _parse_chunk_responses(responses: list, mapping: list, num_docs: int) -> tuple[str, list[list[str]]]:
    """Parse chunk summaries back to per-document lists."""

    # Ensure response count matches
    if len(responses) < len(mapping):
        responses.extend([""] * (len(mapping) - len(responses)))

    # Group by document
    summaries_by_doc = [[] for _ in range(num_docs)]
    for resp, (doc_idx, _) in zip(responses, mapping):
        summary = (
            extract_content_from_xml_tags(resp, "chunk_summary")
            or extract_content_from_xml_tags(resp, "final_summary")
            or ""
        )
        summaries_by_doc[doc_idx].append(summary.strip())

    return summaries_by_doc


def _build_combine_message(summaries_by_doc: list[list[str]], prompt: str):
    """Build calls to combine multi-chunk summaries."""
    messages, indices = [], []

    for i, summaries in enumerate(summaries_by_doc):
        valid = [s for s in summaries if s]
        if len(valid) > 1:
            bullet_list = "\n".join(f"- {s}" for s in valid)
            message = prompt.format(chunk_summaries=bullet_list)
            messages.append(message)
            indices.append(i)

    return messages, indices


def _merge_summaries(chunks_by_doc: list[list[str]], combined: list[str], indices: list[int]) -> list[str]:
    """Merge combined summaries into final list."""
    final = [chunks[0] if chunks else "" for chunks in chunks_by_doc]

    for resp, idx in zip(combined, indices):
        parsed = extract_content_from_xml_tags(resp, "final_summary")
        final[idx] = parsed.strip() if parsed else "No summary available."

    return final


def _build_message(dataset, max_tokens: int, overlap: int, model_name: str, prompt: str):
    """Build inference calls for chunked summaries."""
    enc = _get_encoder(model_name)
    messages, mapping = [], []

    for i, item in enumerate(dataset):
        text = item['document_text']
        if len(enc.encode(text)) <= max_tokens:
            message = prompt.format(document=text)
            messages.append(message)
            mapping.append((i, -1))
        else:
            chunks = split_into_token_chunks(text, max_tokens, overlap, model_name)
            for j, chunk in enumerate(chunks):
                message = prompt.format(document=chunk)
                messages.append(message)
                mapping.append((i, j))

    return messages, mapping

def _generate(model,messages,outfile, bsz=1, temperature=0.01, max_length=50):
    print(f'writing to {outfile}')
    out_handle = open(outfile, 'w')
    full_result_lst = []
    batch_lst = []
    for line in tqdm.tqdm(messages):
        batch_lst.append(line)
        if len(batch_lst) < bsz:
            continue  # batch not full yet
        request_result = model.generate(prompt=batch_lst,temperature=temperature, max_tokens=max_length,
                                        terminate_by_linebreak=False,verbose=False)

        for prompt,xx in zip(batch_lst,request_result.completions):
            full_result_lst.append(xx.text)
            print(json.dumps({'prompt':prompt,'response':xx.text}), file=out_handle)
        batch_lst = []
    if len(batch_lst) > 0: #最后的batch,数量可能<btz
        request_result = model.generate(prompt=batch_lst,temperature=temperature, max_tokens=max_length,
                                        terminate_by_linebreak=False,verbose=False)
        for prompt,xx in zip(batch_lst,request_result.completions):
            full_result_lst.append(xx.text)
            print(json.dumps({'prompt':prompt,'response':xx.text}), file=out_handle)
    out_handle.close()
    return full_result_lst



def run() -> None:
    """Execute hierarchical document summarization."""
    path = r"D:\Download\vscode\code\agent\utils\document.json" 
    with open(path,'r',encoding='utf-8') as f:
        dataset = json.load(f)
    max_tokens = 8192
    summery_tokens = 512
    token_overlap = 128
    model_name = "DeepSeek-V3.1"
    model = Model(model_name)
    summarization_user_prompt = summary_prompt
    combine_summaries_user_prompt = summary_combine_prompt
    outfile = 'summary.txt'
    bsz = 1
    temperature = 0



    # Stage 1: Chunk summaries
    messages, mapping = _build_message(
        dataset, max_tokens, token_overlap, model_name, summarization_user_prompt
    )
    print(messages[0])
    responses = _generate(model,messages,outfile, bsz, temperature,summery_tokens)
    chunks_by_doc = _parse_chunk_responses(responses, mapping, len(dataset))

    # Stage 2: Combine summaries for multi-chunk docs
    combine_messages, combine_indices = _build_combine_message(chunks_by_doc, combine_summaries_user_prompt)
    if combine_messages:
        combine_responses = _generate(model,combine_messages,outfile, bsz, temperature,summery_tokens)
        final_summaries = _merge_summaries(chunks_by_doc, combine_responses, combine_indices)
    else:
        final_summaries = [chunks[0] if chunks else "" for chunks in chunks_by_doc]

    # Save results, 总结列表和总结模型
    for i,item in enumerate(dataset):
        item["document_summary"] =  final_summaries[i]
    with open(f"document1.json", "w",encoding='utf8') as f:
        json.dump(dataset, f,ensure_ascii=False,indent=4)
    

if __name__ == "__main__":
    run()




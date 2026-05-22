import ast
from collections import namedtuple
from dataclasses import dataclass, field
import json
import os
import re
import time

from typing import Any, Dict, List, Optional
import httpx
from openai import OpenAI
import torch
import tqdm
import transformers
from autogen.code_utils import extract_code
from transformers import AutoTokenizer
from settings import TOKEN_CONFIG_DIR, get_required_env
"""
加载yaml文件作为参数：相对路径，文件名称
@hydra.main(config_path="../configs/", config_name="evaluator")
def main(cfg: DictConfig):
"""

ark_models = {'DeepSeek-V3.1':'ep-20251023143912-6l7qm','DouBao-Lite':'ep-20251023143912-6l7qm'}

@dataclass
class InferenceCall:
    """
    A class that represents an inference call to a model.

    Attributes:
        messages: List of message dictionaries in the format expected by the LLM API.
        temperature: Optional sampling temperature for controlling randomness in generation.
        tags: List of string tags that can be set to any values by the user. Used internally
              for logging and cost tracking purposes (e.g., pipeline stage).
        max_retries: Maximum number of retry attempts for failed inference calls.
        seed: Optional random seed for reproducible outputs.
    """

    messages: List[Dict[str, str]]
    temperature: Optional[float] = None
    max_token:int = 256
    max_retries: int = 12
    seed: Optional[int] = None
    extra_parameters: Dict[str, Any] = field(default_factory=dict)





# 从LLM的文本输出中提取 JSON 代码块，并解析为 Python 对象
def extract_json_v2(json_text, outfilename):
    response = json_text.replace("TERMINATE", "")
    if "```json" in response:
        # parse the json file
        try:
            extracted_json = extract_code(response)
            combined_json = sum([], [ast.literal_eval(xx[1]) for xx in extracted_json])  #literal_eval将字符串转化为python对象
        except:
            if '...' in response:
                response = response.replace('...', '')
                extracted_json = extract_code(response)
                combined_json = sum([], [ast.literal_eval(xx[1]) for xx in extracted_json])
            else:
                response2 = "\n".join(response.split('\n')[:-1]) + "]\n```"
                extracted_json = extract_code(response2)
                combined_json = sum([], [ast.literal_eval(xx[1]) for xx in extracted_json])
        # load the json_string.
        json_dict = combined_json
        # json_dict = ast.literal_eval(combined_json)
        if outfilename is not None:
            with open(outfilename, "w") as f:
                json.dump(json_dict, f,ensure_ascii=False,indent=4)

    else:
        assert False, "fail to output json file."
    return json_dict

def extract_content_from_xml_tags(full_content, xml_tag):
    # This function extracts the content between the XML tags
    # It uses regex to find the content and includes error handling

    # Define the regex patterns to match the content
    pattern_with_closing_tag = f"<{xml_tag}>(.*?)</{xml_tag}>"
    pattern_without_closing_tag = f"<{xml_tag}>(.*)"

    try:
        # First, try to find matches with both opening and closing tags
        matches_with_closing = re.findall(pattern_with_closing_tag, full_content, re.DOTALL)
        if matches_with_closing:
            return matches_with_closing[0].strip()

        # If no matches found, try to find content with only opening tag
        matches_without_closing = re.findall(pattern_without_closing_tag, full_content, re.DOTALL)
        if matches_without_closing:
            return matches_without_closing[0].strip()

        # If still no matches found, return an empty string
        return ""

    except Exception as extraction_error:
        print(f"Error extracting content from XML tags: {extraction_error}")
        return 



# 加载本地的HuggingFace格式的模型和分词器
def load_model(modelpath):
    print(f'loading from {modelpath}')
    tokenizer = transformers.AutoTokenizer.from_pretrained(modelpath)
    tokenizer.padding_side = 'left'  #左侧填充，适合生成任务
    tokenizer.pad_token = tokenizer.eos_token  #填充标记为结束标记
    print('---' * 100, modelpath, '---' * 100) 
    model = transformers.AutoModelForCausalLM.from_pretrained(modelpath,torch_dtype = torch.float16, low_cpu_mem_usage = True)# 使用半精度，减少内存使用
    if torch.cuda.is_available() and not hasattr(model, 'hf_device_map'):
        model = model.cuda()
    return model, tokenizer





def query_openai(client, model, prompt_lst, system_prompt,temperature, max_tokens, num_completions, seed, verbose, max_num_retries=1):
    # Randomly select one assistant to be presented first.
    num_retries = 0
    result_lst = []
    # Repeat the query until we get a valid response.
    completion = None
    
    for prompt in prompt_lst:
        while num_retries < max_num_retries:
            try:
                if verbose:
                    print(f"+++++++++++ Model Prompt +++++++++++\n {prompt}")
                message = []
                if system_prompt and len(system_prompt) != 0:
                    message.append({"role": "system","content": system_prompt})
                message.append( {"role": "user","content": prompt})
                completion = client.chat.completions.create(
                    model=model, #"gpt-4", #"gpt-3.5-turbo",
                    messages= message,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    n=num_completions,
                    seed = seed
                )
                break
            except Exception as e:  # noqa
                print(e)
                print("Retrying...")
                num_retries += 1
                time.sleep(10)

        if completion is None:
            raise RuntimeError(f"Could not get completion after {max_num_retries} retries.")

        result_txt = completion.choices[0].message.content

        if verbose:
            usage = completion.usage
            print(usage)
            total_tokens = usage.total_tokens
            print(total_tokens, 'total tokens')

        if verbose:
            print(f"+++++++++++ Model Output +++++++++++\n {result_txt}")
        result_txt = result_txt.strip()

        result_lst.append(result_txt)
    return result_lst



# 定义了模型初始化和生成函数
class Model:
    def __init__(self, model_choice):
        if '/' in model_choice or '\\' in model_choice:
            self.is_local = True
            self.model,self.tokenizer = load_model(model_choice)
            self.model_name = model_choice.split('/')[-1]
        else:
            self.is_local = False
            self.model_name = model_choice
            if model_choice in ark_models.keys():
                self.model_id = ark_models[model_choice]
                self.client = OpenAI(
                    api_key=get_required_env("ARK_API_KEY"),
                    base_url=get_required_env("ARK_BASE_URL"),
                    http_client=httpx.Client(trust_env=False),
                )
            

    # prompt是个list，比如一个batch
    # self.tokenizer.eos_token_id和self.tokenizer.pad_token_id
    def generate(self, prompt,system_prompt=None,temperature=0, max_tokens=200, num_completions=1, 
                 seed=101,verbose=False):
        if self.is_local:
            if system_prompt:
                prompt = system_prompt + '\n\n' + prompt
            prompt_ids = self.tokenizer(prompt, return_tensors='pt', padding=True)
            attention_mask = prompt_ids['attention_mask'].to(self.model.device)
            prompt_ids = prompt_ids['input_ids'].to(self.model.device)
            # 自动混合精度推理（AMP）
            with torch.autocast(device_type='cuda', dtype=torch.bfloat16,): # if True: # LISA_DEBUG
                generated_ids = self.model.generate(input_ids=prompt_ids, attention_mask=attention_mask,
                                            temperature=temperature, do_sample=True,
                                            max_length=max_tokens + prompt_ids.size(1), # max_token是指输出的最大长度
                                            num_return_sequences=num_completions,
                                            eos_token_id=self.tokenizer.eos_token_id, 
                                            pad_token_id= self.tokenizer.pad_token_id)  # id和具体的tokenizer有关
            generated_text = self.tokenizer.batch_decode(generated_ids[:, prompt_ids.size(1):], skip_special_tokens=True)
            generated_text = [x for x in generated_text]
                
        else:
            generated_text = query_openai(client=self.client, model=self.model_id, prompt_lst=prompt, temperature=temperature, max_tokens=max_tokens,
                                system_prompt=system_prompt,num_completions=num_completions, seed=str(seed), verbose=verbose) 
           
        return generated_text

    
    def batch_generate(self,prompts,outfile, bsz=1, temperature=0.01, max_length=50):
        full_result_lst = []
        if os.path.exists(outfile):
            with open(outfile, 'r',encoding='utf-8') as in_handle:
                for line in in_handle:
                    full_result_lst.append(line)
        if len(full_result_lst) == len(prompts):
            return full_result_lst
        else:
            prompts = prompts[len(full_result_lst):]


        print(f'writing to {outfile}')
        out_handle = open(outfile, 'a')
        full_result_lst = []
        batch_lst = []
        for line in tqdm.tqdm(prompts):
            batch_lst.append(line)
            if len(batch_lst) < bsz:
                continue  # batch not full yet
            request_result = self.generate(prompt=batch_lst,temperature=temperature, max_tokens=max_length,
                                            terminate_by_linebreak=False,verbose=False)

            for prompt,res in zip(batch_lst,request_result):
                full_result_lst.append(res)
                print(json.dumps({'prompt':prompt,'response':res},indent=4,ensure_ascii=False), file=out_handle)
            batch_lst = []
        if len(batch_lst) > 0: #最后的batch,数量可能<btz
            request_result = self.generate(prompt=batch_lst,temperature=temperature, max_tokens=max_length,
                                            terminate_by_linebreak=False,verbose=False)
            for prompt,res in zip(batch_lst,request_result):
                full_result_lst.append(res)
                print(json.dumps({'prompt':prompt,'response':res},indent=4,ensure_ascii=False), file=out_handle)
        out_handle.close()
        return full_result_lst


# 编码期间
def _get_encoder(model_name="DeepSeek-V3.1"):
    """Get tiktoken encoder with fallback."""
    try:
        token_path = TOKEN_CONFIG_DIR / model_name
        tokenizer = AutoTokenizer.from_pretrained(token_path,trust_remote_code=True)
        return tokenizer
    except Exception as e:
        print(f"Unknown encoding model'{model_name}': {str(e)[:60]}...")
        token_path = TOKEN_CONFIG_DIR / "DeepSeek-V3.1"
        tokenizer = AutoTokenizer.from_pretrained(token_path,trust_remote_code=True)
        return tokenizer


def get_answer(model,problems,outfile_prefix, bsz=1, temperature=0.01, max_length=50):
    outfile = f"{outfile_prefix}.test_inference.json"
    prompt_lst = []
    for line in problems:
        line['prompt'] = "Output just with the final answer to the question.\nQuestion:" + line[
            'question'] + "\n" + "Answer:"
        prompt_lst.append(line['prompt'])
    answer_lst = model.batch_generate(prompt_lst,outfile, bsz, temperature, max_length)
    
    return answer_lst



if __name__ == '__main__':
    prompt = ["What is the most common classification method in the discipline of history? Please provide a specific classification and return it in json format"]
    model = Model("DeepSeek-V3.1")
    # model = Model(r"D:/model/chatglm3-6b")
    result = model.generate(prompt)
    print(result)

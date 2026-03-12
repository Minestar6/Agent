
# 完整的问答对生成管道函数
# 核心特点：使用特权信息(Wiki) + 自适应搜索 + 显著性筛选
import argparse
import copy
import json
import os
from utils.model import extract_json_v2
from utils.topic import _refine_categories_targetacc_augmented
from utils.value import get_summary_of_results, solve_and_compare_questions, summarize_over_history
from utils.wiki import get_pageviews, search_step

"""
目标：根据维基百科的多个段落生成QA
1. 模板规范 + 段落 + 额外要求
规范：答案简明，建议原文作为答案，问题不能过于依赖原文
可能有附加条件
生成15道多样化的题目
格式规范：属性id、问题、答案、难度

2. 模型调用，解析json

"""
def gen_qa_pairs_augmented(paragraph, model, additional_req):
    context = """Conditioned on the wikipedia paragraph, you will generate a few question and answer pairs. 
Make sure not to ask subjective questions, and let the question's correct answer be a concise short phrase. 
Make sure that the question you selected is answerable by the given wikipedia paragraph, and make the answer concise. It's recommended to use the exact text from the paragraph as answers.
Make sure that the questions are also answerable by an expert **without the wikipedia paragraph**. For example, dont ask questions that are too specific to the paragraph, like "what are the three locations mentioned in the paragraph?". Or "who's the most famous soldier, according to the paragraph?".

You will also receive additional requirements on the questions. You should follow these additional requirements when generating the questions.
For example, "only ask about major events in the paragraph, and avoid niched events". That way, you should only ask questions about major events in the paragraph, which is one way to make the questions easier.

Try to generate a diverse set of 15 questions, and make sure that the questions are not too similar to each other while satisfying the additional requirements. If you can't generate 15 questions, generate as many as you can.

Formatting: 
Each question should be a dictionary with the following keys: id, question, answer, estimated difficulty. 
The questions should be exactly in the following format (a list of dictionaries): 
```json
{"id": "1", "question": "<question>", "answer": "<answer>", "difficulty": "1"}, 
{"id": "2", "question": "<question>", "answer": "<answer>", "difficulty": "1"}, 
``` 
Do not use python code block. 
Make sure that you generate a valid json block (surrounded by ```json [...] ```). Surrounded by the [] brackets. 
If you are generating double quotes as content of <question> or <answer>, make sure to escape them with a backslash. 
"""
    

    context += f"Wiki paragraph: {paragraph}\nAdditional requirements: {additional_req}\n"
    # extract the json file from the message
    request_result = model.generate( prompt=[context],temperature=0.0, max_tokens=2000,
                                     terminate_by_linebreak=False, verbose=False)
    response = request_result.completions[0].text


    extracted_json = extract_json_v2(response, None)
    extracted_json = extracted_json[0]  #将二维列表变为一维
    return extracted_json




"""
需要大改：换成yourbench的方法

重点：从维基百科获得特权信息
1. 判断是否已存在
2. 从维基百科获取段落，进行有效性检查
3. 以20个段落为单位生成题目：题目数量达到才结束；段落遍历完结束
4. 题目保存


"""
def generate_long_questions(line_, model, outfile_prefix, generate_qa_func=gen_qa_pairs_augmented,
                            total_num_questions=50):
    if os.path.exists(f"{outfile_prefix}.KI_questions.json"):
        print("found ", f"{outfile_prefix}.KI_questions.json")
        full_lst = []
        with open(f"{outfile_prefix}.KI_questions.json", "r") as f:
            for line in f:
                line = json.loads(line)
                full_lst.append(line)
        return full_lst

    f = open(f"{outfile_prefix}.KI_questions.json", "w")
    # 获得维基百科特权信息
    paragraph, wiki_entity = search_step(line_['category'], output_more=True)
    print(len(paragraph), 'length of paragraph')
    if len(paragraph) == 0:
        print("empty paragraph, skipping...")
        return {}

    full_lst = []
    # 20个段落为单位生成题目
    for start_idx in range(0, len(paragraph), 20):
        if len(full_lst) >= total_num_questions: break
        end_idx = start_idx + 20 if start_idx + 20 < len(paragraph) else len(paragraph)
        try:
            json_questions = generate_qa_func(paragraph[start_idx:end_idx], model, line_['additional_requirement'])
            # json_questions = generate_qa_func(paragraph[start_idx:end_idx], agent_info, line_['additional_requirement'])
        except:

            print("error in generating more questions, skipping...")
            print(f'generated {len(full_lst)} questions')
            continue  # skip the empty paragraph.
        
        # 题目保存
        for json_question in json_questions:
            line = copy.deepcopy(line_)
            line['question'] = json_question['question']
            line['gold_answer'] = json_question['answer']
            line['difficulty'] = json_question['difficulty']
            line['wiki_entity'] = wiki_entity
            full_lst.append(line)
            print(json.dumps(line), file=f)
    f.close()
    return full_lst





"""
维基百科页面排序函数：根据访问量从低到高（重要性）
"""
def saliency_rerank(json_lst, num_keep = 5 ):
    for line_ in json_lst:
        page_title = line_['category'].replace(' ', '_')
        pageviews = get_pageviews(page_title)
        line_['salience'] = pageviews  if pageviews is not None else 0 # add the pageviews to the line.
    # sort by the saliency
    json_lst = sorted(json_lst, key=lambda x: x['salience'], reverse=True)
    for line in json_lst:
        print(f'salience of {line["category"]}: ', round(line['salience'] / 1000000, 2),  'M')
    return json_lst[:num_keep]




"""
生成题目
1. 生成主题：10个
2. 按照显著性排序（浏览量）：取5个
3. 遍历类别：
1) 获得维基百科页面内容
2）过滤：是否重复 / 是否有段落 / 是否有"additional_requirement" 属性
3）line属性赋值： category、salience、paragraph、wiki_entity
4）line进行题目生成


"""
def generate_full_qa(theme, model, history, iters, outfile_prefix='att1',
                                   historical_psg=None,
                                   category_gen_func=_refine_categories_targetacc_augmented,
                                   generate_qa_func=generate_long_questions, acc_target=None,
                                   apply_saliency_rerank=True):
    if os.path.exists(f"{outfile_prefix}.KI_questions.json"):
        print("FOUND KI_questions.json")
        return

    # 生成类别
    if acc_target is not None:
        json_category = category_gen_func(theme, model, history, iters, outfile_prefix=outfile_prefix,
                                          acc_target=acc_target)
    else:
        json_category = category_gen_func(theme, model, history, iters, outfile_prefix=outfile_prefix)
    
    # 选择显著性最高的类别
    if apply_saliency_rerank:
        json_category = saliency_rerank(json_category, 5)
    full_lst = []
    # 只有不存在时才初始化为空列表吧
    if historical_psg == None:
        historical_psg = []
    for line_ in json_category:
        # 获得维基百科内容
        paragraph, wiki_entity = search_step(line_['category'],min_token=2)
        # 检查类别是否重复
        if wiki_entity in historical_psg:
            print('found repetitive wiki entity, skipping...', wiki_entity)
            continue
        if len(paragraph) == 0:
            print("empty paragraph, skipping...")
            continue  # skip the empty paragraph.
        historical_psg.append(wiki_entity)
        if 'additional_requirement' not in line_: 
            continue # skip the empty paragraph.
        page_title = line_['category'].replace(' ', '_')
        # 获取页面访问量
        if 'salience' not in line_:
            pageviews = get_pageviews(page_title)
            line_['salience'] = pageviews if pageviews is not None else 0 # add the pageviews to the line.
            # print(f'salience of {page_title}: ', round(line_['salience'] / 1000000, 2), 'M')
        try:
            json_questions = generate_qa_func(line_, model, outfile_prefix+f'__{page_title}')
        except Exception as e:
            print(e)
            print("error in generating questions, skipping...")
            continue # skip the empty paragraph.

        for line in json_questions:
            full_lst.append(line)
        line_['paragraph'] = paragraph
        line_['wiki_entity'] = wiki_entity
    # 保存问题类别
    with open(f"{outfile_prefix}.KI_questions.json", "w") as f:
        json.dump(full_lst, f)
    # 保存增强的主题
    with open(f"{outfile_prefix}.categories_augmented.json", "w") as f:
        json.dump(json_category, f)
    return historical_psg



if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='ProgramName',
        description='What the program does',
        epilog='Text at the bottom of help')

    # parser.add_argument('--model', default='gpt-3.5-turbo')  # option that takes a value
    parser.add_argument('--test_modelname', default='gpt-3.5-turbo')  # option that takes a value
    parser.add_argument('--agent_modelname', default='gpt-4-turbo-preview')  # option that takes a value
    parser.add_argument('--tool_modelname', default=None)  # option that takes a value，评估答案正确性的模型
    parser.add_argument('--temperature', type=float, default=0.001)  # option that takes a value
    parser.add_argument('--pairwise', type=str, default='no')  # option that takes a value
    parser.add_argument('--exp_mode', type=str, default='ki_wiki')  # option that takes a value
    parser.add_argument('--theme', type=str, default='history')  # option that takes a value
    parser.add_argument('--use_helm', type=str, default='yes')  # option that takes a value
    parser.add_argument('--top_p', type=float, default=0.9)  # option that takes a value
    parser.add_argument('--acc_target', type=str, default="0.1--0.3")  # option that takes a value
    parser.add_argument('--num_iters', type=int, default=8)  # option that

    parser.add_argument('--outfile_prefix1', type=str, default='att1')  # option that takes a value

    args2 = parser.parse_args()
    args = copy.deepcopy(args2)
    test_model = ''
    agent_model = ''
    evaluate_model = ' '

    if args.exp_mode == 'autobencher':
        history_dict = []
        historical_psg = []
        for iters in range(args.num_iters):
            args.outfile_prefix = args.outfile_prefix1 + str(iters + 1)
            summarized_content = summarize_over_history(history_dict, gold_key='gold_answer', verbose=False)
            history = [summarized_content]
            historical_psg = generate_full_qa(args.theme, agent_model, history, iters + 1,
                                                            outfile_prefix=args.outfile_prefix,
                                                            historical_psg=historical_psg,
                                                            category_gen_func=_refine_categories_targetacc_augmented,  # 根据精度扩展主题
                                                            generate_qa_func=generate_long_questions,  #根据维基百科生成试题
                                                            acc_target=args.acc_target)
            with open(f"{args.outfile_prefix}.KI_questions.json", "r") as f:
                json_category = json.load(f)
            if len(json_category) == 1: # remove the outer embedded list.
                json_category = json_category[0]
            gold_answer_json = copy.deepcopy(json_category)
            json_dict = solve_and_compare_questions(test_model, evaluate_model, json_category, gold_answer_json,
                                                    args.outfile_prefix)
            history_dict.append(json_dict)

            verbose_description = get_summary_of_results(json_dict, verbose=False)
            print(verbose_description)
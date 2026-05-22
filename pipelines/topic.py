


"""
主题树的构建和扩展
每次迭代：
1）生成主题，
2）使用维基百科对主题进行扩展
3）主题筛选
"""

# 主题生成
import json
import os
import time
from utils.model import Model, extract_json_v2
from utils.wiki import saliency_rerank, search_related_pages, search_step



# 助手：强调推理能力+语言技能
# 一步步解决，计划不在先解释，哪步使用代码，哪一步使用语言技能
# 结束输出 "TERMINATE"
DEFAULT_JSON_MESSAGE = """You are a helpful AI assistant.
Solve tasks using your reasoning and language skills.
Solve the task step by step if you need to. If a plan is not provided, explain your plan first. Be clear which step uses code, and which step uses your language skill.
Reply "TERMINATE" in the end when everything is done.
"""


"""
目标：生成类别

判断文件是否已存在
prompt拼接：系统提示词 + context + 初次/历史迭代提示
模型调用，读取json
"""
def _generate_categories(theme, context, model, history, iters, outfile_prefix='att1'):
    # 判断是否已存在
    if os.path.exists(f"{outfile_prefix}.categories.json"):
        print("FOUND categories.json")
        return json.load(open(f"{outfile_prefix}.categories.json", "r"))[0]
    context = context.replace("THEME", theme)
    if iters is None:
        iters = len(history) + 1
    if iters == 1:
        context += "Please start with iteration 1."
    else:
        context += "\n".join(history) + "Please start with iteration {}.".format(iters)
    context = DEFAULT_JSON_MESSAGE + context
    # extract the json file from the message
    request_result = model.generate(prompt=[context],temperature=0.0, max_tokens=2000,terminate_by_linebreak=False )
    response = request_result[0]



    with open(f"{outfile_prefix}.full_thoughts.txt", 'w', encoding='utf-8') as out_handle:
        out_handle.write(context)
        out_handle.write("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
        out_handle.write(response)

    extracted_json = extract_json_v2(response, f"{outfile_prefix}.categories.json")
    if len(extracted_json) == 1:
        extracted_json = extracted_json[0]
    return extracted_json



"""
目标：主题筛选，与generate不同的是多了候选主题列表

检查是否已存在
prompt拼接：系统提示词 + context + 初次/历史迭代提示 + 候选主题
模型调用，读取json
"""
def _refine_categories(theme, context, model, history, iters, candidate_lst, outfile_prefix='att1'):
    # 判断是否已存在
    if os.path.exists(f"{outfile_prefix}.categories.json"):
        print("FOUND categories.json")
        return json.load(open(f"{outfile_prefix}.categories.json", "r"))[0]
    context = context.replace("THEME", theme)
    if iters is None:
        iters = len(history) + 1
    if iters == 1: # 第一次迭代
        context += "Please start with iteration 1." + "Here are the category candidates to select from (delimited by ||): " + " || ".join(candidate_lst) + "\n"
    else:
        context += "\n".join(history) + "Please start with iteration {}.".format(iters) + "Here are the category candidates to select from (delimited by ||): " + "||".join(candidate_lst) + "\n"
    context = DEFAULT_JSON_MESSAGE + context
    # extract the json file from the message
    request_result = model.generate(prompt=[context],temperature=0.0, max_tokens=2000,terminate_by_linebreak=False )
    response = request_result[0]

    with open(f"{outfile_prefix}.full_thoughts.txt", 'w', encoding='utf-8') as out_handle:
        out_handle.write(context)
        out_handle.write("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
        out_handle.write(response)

    # 从文本中提取json格式
    extracted_json = extract_json_v2(response, f"{outfile_prefix}.categories.json")
    if len(extracted_json) == 1:
        extracted_json = extracted_json[0]
    return extracted_json




"""
目标：类别生成的prompt赋值和函数调用（prompt赋值单独函数，与baseline比较）
prompt中的context赋值
调用_generate_categories
"""
def _generate_categories_targetacc_augmented(theme, agent_info, history, iters, outfile_prefix='att1', acc_target="0.3--0.5"):
    context = """ Your goal is to come up with a list of categories for knowledge intensive questions that achieve the target accuracy of {ACC_TARGET}.
The categories should be diverse and cover important topics, under the theme of THEME. 
You can also specify some additional requirements for each category. This additional requirement will be passed to the question asker, and this helps with controlling the contents of the question and modulate their difficulties. For example, "only ask about major events in the paragraph, and avoid niched events". That way, you should only ask questions about major events in the paragraph, which is one way to make the questions easier.
Constructing the categories is like building a tree structure of history, and (category, parent_category) is like specifying a node and its parent. We should select the most precise parent category, for example if you are trying to expand the category "second world war" to make it more specific by adding the node "famous battles in second world war", you should specify the parent category as "second world war" instead of "history".

Output Formatting: 
Each category should be a dictionary with the following keys: id, category, parent_category, additional_requirement. 
Make sure the categories are similar to wikipedia categories. 
The categories should be exactly in the following format (a list of dictionaries): 
```json 
[
{"id": "1", "category": "Ancient Philosophers", "parent_category": "History", "additional_requirement": "only ask about famous people and their ideologies"}, 
{"id": "2", "category": "Second World War", "parent_category": "History", "additional_requirement": "major battles"}, 
...
]
``` 
Do not use python code block. 
Make sure that you generate a valid json block (surrounded by ```json [...] ```). Surrounded by the [] brackets.


Iteration: 
The goal is to find a set of categories that with accuracy close to the target accuracy level of {ACC_TARGET}. 

For iteration 1, you can start with a wide variety of categories for us to build upon later. 
In later iterations you should receive as input the categories that you have already explored and their respective accuracy. You should
1. Think about breadth. Brainstorm questions with different categories to have broader coverage. Coming up with new categories that can are likely to achieve the target accuracy level.
2. For example, If you find the model now lacks categories of 0.3 -- 0.5 accuracy, you should come up with more categories that would yield accuracy in that range, by either reducing the difficulty of questions that achieve lower accuracy (via subcategory or via additional requirement), or increasing the difficulty of questions that achieve higher accuracy.
3. DO NOT REPEAT any of the categories that you have already explored.
"""
    context = context.replace("{ACC_TARGET}", str(acc_target))
    return _generate_categories(theme, context, agent_info, history, iters, outfile_prefix=outfile_prefix)




# 根据精度扩展主题：目标是找到一组准确度接近目标准确度级别{ACC_TARGET}的类别。
"""
目标：主题树构建
1. LLM生成主题
2. 维基百科搜索扩展主题
3. LLM主题筛选：prompt初始化 + _refine_categories函数调用

prompt重点
筛选标准
(1) 与主题（THEME）契合；
(2) 具备达成目标准确率{ACC_TARGET}的可能性（可依据历史迭代的准确率统计进行判断）；
(3) 具有突出性并覆盖重要议题。
补充附加条件

迭代：找到前10个类别

"""
def _refine_categories_targetacc_augmented(theme, agent_info, history, iters, outfile_prefix='att1', acc_target="0.3--0.5"):
    if os.path.exists(f"{outfile_prefix}.refine.categories.json"):
        print("FOUND refine.categories.json")
        return json.load(open(f"{outfile_prefix}.refine.categories.json", "r"))[0]
    
    category_json = _generate_categories_targetacc_augmented(theme, agent_info, history, iters, outfile_prefix=outfile_prefix+'.brainstorm', acc_target=acc_target)
    # given the json_lst, refine the categories to achieve the target accuracy.
    full_cat_lst = []
    for line in category_json:
        # 获得所有和类别相关的维基百科页面标题
        cat_lst = search_related_pages(line['category'])
        full_cat_lst.extend(cat_lst)
        time.sleep(1)
    context = """ Your goal is to select from a list of categories for knowledge intensive questions so that the selected subset are likely to achieve the target accuracy of {ACC_TARGET}.
The categories should be selected based on three criteria: (1) aligned with THEME, (2) likely to obtain the target accuracy of {ACC_TARGET}, you can judge this based on the accuracy statistics from previous iterations. and (3) salient and cover important topics.
You can also specify some additional requirements for each category. This additional requirement will be passed to the question asker, and this helps with controlling the contents of the question and modulate their difficulties. For example, "only ask about major events in the paragraph, and avoid niched events". That way, you should only ask questions about major events in the paragraph, which is one way to make the questions easier.

Output Formatting: 
Each category should be a dictionary with the following keys: id, category, parent_category, additional_requirement. 
Make sure the categories are similar to wikipedia categories. 
The categories should be exactly in the following format (a list of dictionaries): 
```json 
[
{"id": "1", "category": "Ancient Philosophers", "parent_category": "History", "additional_requirement": "only ask about famous people and their ideologies"}, 
{"id": "2", "category": "Second World War", "parent_category": "History", "additional_requirement": "major battles"}, 
...
]
``` 
Do not use python code block. 
Make sure that you generate a valid json block (surrounded by ```json [...] ```). Surrounded by the [] brackets.


Iteration: 
The goal is to find a set of categories that with accuracy close to the target accuracy level of {ACC_TARGET}. 

At every iteration, you are given a list of categories that you have already explored and their respective accuracy. Also, you are given a larger set of candidate categories for this iteration, and you should use the information from previous iterations to select the top 20 categories from the list, that are most likely to achieve the target accuracy level, while still being relevant and salient. 
In later iterations you should receive as input the categories that you have already explored and their respective accuracy. You should
DO NOT REPEAT any of the categories that you have already explored.
"""
    context = context.replace("{ACC_TARGET}", str(acc_target))
    return _refine_categories(theme, context, agent_info, history, iters, full_cat_lst, outfile_prefix=outfile_prefix + '.refine')



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
def get_tree(theme, model, history, iters, outfile_prefix='att1',
                    historical_psg=None,acc_target=None,apply_saliency_rerank=True):
    if os.path.exists(f"{outfile_prefix}.KI_questions.json"):
        print("FOUND KI_questions.json")
        return

    # 生成类别
    if acc_target is not None:
        json_category = _refine_categories_targetacc_augmented(theme, model, history, iters, outfile_prefix=outfile_prefix,
                                          acc_target=acc_target)
    else:
        json_category = _refine_categories_targetacc_augmented(theme, model, history, iters, outfile_prefix=outfile_prefix)
    
    # 选择显著性最高的类别
    if apply_saliency_rerank:
        json_category = saliency_rerank(json_category, 10)
    
    # 只有不存在时才初始化为空列表吧
    if historical_psg == None:
        historical_psg = []
    for line_ in json_category:
        # 获得维基百科内容
        paragraph, wiki_entity = search_step(line_['category'],output_more=False)
        # 检查类别是否重复
        if wiki_entity in historical_psg:
            print('found repetitive wiki entity, skipping...', wiki_entity)
            continue
        line_['paragraph'] = paragraph
        line_['wiki_entity'] = wiki_entity
    with open(f"{outfile_prefix}.categories_augmented.json", "w") as f:
        json.dump(json_category, f,ensure_ascii=False,indent=4)
    return historical_psg




if __name__ == '__main__':
    theme = 'history'
    model = Model("DeepSeek-V3.1")
    iters = 1
    outfile_prefix='../output/'+theme+'/att1'
    historical_psg= []
    acc_target=None
    apply_saliency_rerank = True
    history = []

    # get_tree(theme, model, history, iters, outfile_prefix,
    #                 historical_psg,acc_target,apply_saliency_rerank)
    # json_category = []
    # with open(f"{outfile_prefix}.categories_augmented.json", "w") as f:
    #     json.dump(json_category, f)

    json_category = json.load(open(f"{outfile_prefix}.categories_augmented1.json", "r",encoding='utf8'))
    for line_ in json_category:
        # 获得维基百科内容
        paragraph, wiki_entity = search_step(line_['category'])
        line_['paragraph'] = paragraph
        line_['wiki_entity'] = wiki_entity
    with open(f"{outfile_prefix}.categories_augmented.json", "w",encoding='utf8') as f:
        json.dump(json_category, f,ensure_ascii=False,indent=4)

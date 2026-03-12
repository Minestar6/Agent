import json
import os
from pathlib import Path
from typing import Union, Dict, List, Any
import logging

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



# 使用示例
if __name__ == "__main__":
    path1 = r"D:\Download\vscode\code\agent\utils\chunk_ques.json"
    path2 = r"ques.txt"
    content1 = read_file(path1)
    f = open(path2,'w',encoding='utf-8')
    for i,item in enumerate(content1):
        f.write("AAA"+str(i)+'\n')
        f.write(item['prompt'])
        f.write("\n\n")
        f.write(item['response'][0])
        f.write("\n\n\n\n")
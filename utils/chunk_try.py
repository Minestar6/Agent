import typing
# 新的、正确的导入方式
from langchain_text_splitters import RecursiveCharacterTextSplitter

from utils.model import _get_encoder
# 或者导入其他分割器，如 CharacterTextSplitter, TokenTextSplitter 等
class SimpleRecursiveSplitter:
    def __init__(
        self, 
        chunk_size: int = 500, 
        chunk_overlap: int = 50, 
        separators: list = ["\n\n", "\n", ".",","]
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators

    def split_text(self, text: str) -> list[str]:
        return self._recursive_split(text, self.separators)

    def _recursive_split(self, text: str, separators: list) -> list[str]:
        final_chunks = []
        
        # 1. 寻找合适的当前分隔符
        separator = "" # 默认最后一个（通常是空字符串）
        new_separators = []
        for i, s in enumerate(separators):
            if s == "" or s in text:
                separator = s
                new_separators = separators[i + 1:]
                break
        
        # 2. 根据分隔符切分
        if separator != "":
            splits = text.split(separator)
            splits = [item+separator for item in splits if item.strip()]
        else:
            splits = list(text) # 字符级切分

        # 3. 合并碎片为符合 chunk_size 的块
        good_splits = []
        for s in splits:
            if len(s) < self.chunk_size:
                good_splits.append(s)
            else:
                # 如果这个碎片依然太长，递归使用下一个分隔符
                if good_splits:
                    final_chunks.extend(self._merge_splits(good_splits, separator))
                    good_splits = []
                final_chunks.extend(self._recursive_split(s, new_separators))
        
        if good_splits:
            final_chunks.extend(self._merge_splits(good_splits, separator))
            
        return final_chunks

    def _merge_splits(self, splits: list[str], separator: str) -> list[str]:
        """将碎片合并成带重叠的块"""
        chunks = []
        current_doc = []
        total_len = 0
        
        for s in splits:
            s_len = len(s)
            # 如果加上当前碎片超过了限制
            if total_len + s_len + (len(separator) if current_doc else 0) > self.chunk_size:
                if total_len > 0:
                    chunks.append(separator.join(current_doc))
                    # 处理重叠：保留末尾的一部分碎片
                    while total_len > self.chunk_overlap or (total_len + s_len > self.chunk_size and total_len > 0):
                        popped = current_doc.pop(0)
                        total_len -= (len(popped) + len(separator))
                
            current_doc.append(s)
            total_len += s_len + (len(separator) if len(current_doc) > 1 else 0)
            
        if current_doc:
            chunks.append(separator.join(current_doc))
        return chunks
    

from nltk.tokenize import sent_tokenize


def find_index(sent):
    res = -1
    str = [',',';']
    index = []
    for s in str:
        x = sent.find(s)
        if x != -1:
            index.append(x)
    if index:
        res = min(index)
    return res


def regular_sentence1(text):
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
        index = find_index(first_sent)
        if index == -1:
            sentences = sentences[1:]
        else:
            first_sent = first_sent[index+1]
            if len(first_sent.split(" ")) < 5:
                sentences = sentences[1:]
            else:
                sentences[0] = first_sent
    
    # 判断尾句是否完整
    if sentences:
        last_sent = sentences[-1].strip()
        if last_sent and last_sent[-1] not in ('.', '?', '!'):
            index = find_index(last_sent[::-1])
            if index == -1:
                sentences = sentences[:-1]
            else:
                last_sent = last_sent[:-(index+1)]+'.'
                if len(last_sent.split(" ")) < 5:
                    sentences = sentences[:-1]
                else:
                    sentences[-1] = last_sent
    
    return " ".join(sentences).strip()


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
    if len(tokens) > chunk_tokens:
        print(len(tokens))
    stride = chunk_tokens - overlap
    res = [regular_sentence1(tokenizer.decode(tokens[i : i + chunk_tokens])) for i in range(0, len(tokens), stride)]
    return res



# --- 测试代码 ---
text = """
The Renaissance (UK: /rɪˈneɪsəns/ rin-AY-sənss, US: /ˈrɛnəsɑːns/ ⓘ REN-ə-sahnss)[1][2][a] is a European period of history and cultural movement, very roughly defined as covering the 14th through 17th centuries,[4][5] though sometimes more narrowly defined for instance as only covering the 15th through 16th centuries.[6] It marked the transition from the Middle Ages to modernity and was characterized by the European rediscovery and revival of the literary, philosophical, and artistic achievements of classical antiquity.[5] Associated with great social change in most fields and disciplines, including art, architecture, politics, literature, exploration and science, the Renaissance was first centered in the Republic of Florence, then spread to the rest of Italy and later throughout Europe. The term rinascita ("rebirth") first appeared in Lives of the Artists (c. 1550) by Giorgio Vasari, while the corresponding French word renaissance was adopted into English as the term for this period during the 1830s.[7][b]
The Renaissance's intellectual basis was founded in its version of humanism, derived from the concept of Roman humanitas and the rediscovery of classical Greek philosophy, such as that of Protagoras, who said that "man is the measure of all things". Although the invention of metal movable type sped the dissemination of ideas from the later 15th century, the changes of the Renaissance were not uniform across Europe: the first traces appear in Italy as early as the late 13th century, in particular with the writings of Dante and the paintings of Giotto.
As a cultural movement, the Renaissance encompassed innovative flowering of literary Latin and an explosion of vernacular literatures, beginning with the 14th-century resurgence of learning based on classical sources, which contemporaries credited to Petrarch; the development of linear perspective and other techniques of rendering a more natural reality in painting; and gradual but widespread educational reform. It saw myriad artistic developments and contributions from such polymaths as Leonardo da Vinci and Michelangelo, who inspired the term "Renaissance man".[8][9] In politics, the Renaissance contributed to the development of the customs and conventions of diplomacy, and in science to an increased reliance on observation and inductive reasoning. The period also saw revolutions in other intellectual and social scientific pursuits, as well as the introduction of modern banking and the field of accounting.[10]
The Renaissance period started during the crisis of the Late Middle Ages and conventionally ends with the waning of humanism, and the advents of the Reformation and Counter-Reformation, and in art, the Baroque period. It had a different period and characteristics in different regions, such as the Italian Renaissance, the Northern Renaissance, the Spanish Renaissance, etc.
In addition to the standard periodization, proponents of a "long Renaissance" may put its beginning in the 14th century and its end in the 17th century.[c]
The traditional view focuses more on the Renaissance's early modern aspects and argues that it was a break from the past, but many historians today focus more on its medieval aspects and argue that it was an extension of the Middle Ages.[14][15]
The beginnings of the period—the early Renaissance of the 15th century and the Italian Proto-Renaissance from around 1250 or 1300—overlap considerably with the Late Middle Ages, conventionally dated to c. 1350–1500, and the Middle Ages themselves were a long period filled with gradual changes, like the modern age; as a transitional period between both, the Renaissance has close similarities to both, especially the late and early sub-periods of either.
The Renaissance began in Florence, one of the many states of Italy.[16] The Italian Renaissance concluded in 1527 when Holy Roman Emperor Charles V launched an assault on Rome during  the war of the League of Cognac. Nevertheless, its impact endured in the art of renowned Italian painters like Tintoretto, Sofonisba Anguissola, and Paolo Veronese, who continued their work during the mid-to-late 16th century.[17]
Various theories have been proposed to account for its origins and characteristics, focusing on a variety of factors, including Florence's social and civic peculiarities at the time: its political structure, the patronage of its dominant family, the Medici,[18] and the migration of Greek scholars and their texts to Italy following the fall of Constantinople to the Ottoman Empire.[19][20][21] Other major centers were Venice, Genoa, Milan, Rome during the Renaissance Papacy, and Naples. From Italy, the Renaissance spread throughout Europe and also to American, African and Asian territories ruled by the European colonial powers of the time or where Christian missionaries were active.
The Renaissance has a long and complex historiography, and in line with general skepticism of discrete periodizations, there has been much debate among historians reacting to the 19th-century glorification of the "Renaissance" and individual cultural heroes as "Renaissance men", questioning the usefulness of Renaissance as a term and as a historical delineation.[22]
Some observers have questioned whether the Renaissance was a cultural "advance" from the Middle Ages, instead seeing it as a period of pessimism and nostalgia for classical antiquity,[23] while social and economic historians, especially of the longue durée, have instead focused on the continuity between the two eras,[24] which are linked, as Panofsky observed, "by a thousand ties".[25][d]
The word has also been extended to other historical and cultural movements, such as the Carolingian Renaissance (8th and 9th centuries), Ottonian Renaissance (10th and 11th century), and the Renaissance of the 12th century.[27]
The Renaissance was a cultural movement that profoundly affected European intellectual life in the early modern period. Beginning in Italy, and spreading to the rest of Europe by the 16th century, its influence was felt in art, architecture, philosophy, literature, music, science, technology, politics, religion, and other aspects of intellectual inquiry. Renaissance scholars employed the humanist method in study, and searched for realism and human emotion in art.[28]
Renaissance humanists such as Poggio Bracciolini sought out in Europe's monastic libraries the Latin literary, historical, and oratorical texts of antiquity, while the fall of Constantinople (1453) generated a wave of émigré Greek scholars bringing precious manuscripts in ancient Greek, many of which had fallen into obscurity in the West. It was in their new focus on literary and historical texts that Renaissance scholars differed so markedly from the medieval scholars of the Renaissance of the 12th century, who had focused on studying Greek and Arabic works of natural sciences, philosophy, and mathematics, rather than on such cultural texts.[citation needed]
"""

f = open("b.txt", 'a',encoding='utf-8')


# 自定义循环切分
splitter = SimpleRecursiveSplitter(chunk_size=1000, chunk_overlap=100)
chunks = splitter.split_text(text)
f.write("自定义循环切分\n")


# langchain循环切分
# text_splitter = RecursiveCharacterTextSplitter(  
#     chunk_size=1000,           # target size of each chunk
#     chunk_overlap=100,         # overlap between chunks for context continuity
#     separators=["\n\n", "\n", ".",","]  # order of recursive splitting
# )  
# chunks = text_splitter.split_text(text) 
# f.write("langchain循环切分\n")

# token + 半句话去除
# chunks = split_into_token_chunks(text,chunk_tokens=256,overlap=25)
# f.write("Chunk半句话\n")

model_name = "DeepSeek-V3.1"
tokenizer = _get_encoder(model_name)


lens = [len(tokenizer.encode(item, add_special_tokens=False))  for item in chunks]
f.write(str(lens)+'\n')
for i, chunk in enumerate(chunks):
    f.write(f"Chunk {i+1} (len={len(chunk)}): {repr(chunk)}")
    f.write(chunk)
    f.write('\n\n\n')





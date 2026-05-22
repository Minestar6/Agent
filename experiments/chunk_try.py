import typing
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from nltk.tokenize import sent_tokenize

from utils.model import _get_encoder


class SimpleRecursiveSplitter:
    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        separators: list = ["\n\n", "\n", ".", ","]
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators

    def split_text(self, text: str) -> list[str]:
        return self._recursive_split(text, self.separators)

    def _recursive_split(self, text: str, separators: list) -> list[str]:
        final_chunks = []
        separator = ""
        new_separators = []
        for i, s in enumerate(separators):
            if s == "" or s in text:
                separator = s
                new_separators = separators[i + 1:]
                break

        if separator != "":
            splits = text.split(separator)
            splits = [item + separator for item in splits if item.strip()]
        else:
            splits = list(text)

        good_splits = []
        for s in splits:
            if len(s) < self.chunk_size:
                good_splits.append(s)
            else:
                if good_splits:
                    final_chunks.extend(self._merge_splits(good_splits, separator))
                    good_splits = []
                final_chunks.extend(self._recursive_split(s, new_separators))

        if good_splits:
            final_chunks.extend(self._merge_splits(good_splits, separator))

        return final_chunks

    def _merge_splits(self, splits: list[str], separator: str) -> list[str]:
        chunks = []
        current_doc = []
        total_len = 0

        for s in splits:
            s_len = len(s)
            if total_len + s_len + (len(separator) if current_doc else 0) > self.chunk_size:
                if total_len > 0:
                    chunks.append(separator.join(current_doc))
                    while total_len > self.chunk_overlap or (total_len + s_len > self.chunk_size and total_len > 0):
                        popped = current_doc.pop(0)
                        total_len -= (len(popped) + len(separator))

            current_doc.append(s)
            total_len += s_len + (len(separator) if len(current_doc) > 1 else 0)

        if current_doc:
            chunks.append(separator.join(current_doc))
        return chunks


def find_index(sent):
    res = -1
    chars = [',', ';']
    index = []
    for s in chars:
        x = sent.find(s)
        if x != -1:
            index.append(x)
    if index:
        res = min(index)
    return res


def regular_sentence1(text):
    sentences = sent_tokenize(text)

    if not sentences:
        return ""

    first_sent = sentences[0].strip()
    if first_sent and not first_sent[0].isupper():
        index = find_index(first_sent)
        if index == -1:
            sentences = sentences[1:]
        else:
            first_sent = first_sent[index + 1:]
            if len(first_sent.split(" ")) < 5:
                sentences = sentences[1:]
            else:
                sentences[0] = first_sent

    if sentences:
        last_sent = sentences[-1].strip()
        if last_sent and last_sent[-1] not in ('.', '?', '!'):
            index = find_index(last_sent[::-1])
            if index == -1:
                sentences = sentences[:-1]
            else:
                last_sent = last_sent[:-(index + 1)] + '.'
                if len(last_sent.split(" ")) < 5:
                    sentences = sentences[:-1]
                else:
                    sentences[-1] = last_sent

    return " ".join(sentences).strip()


def split_into_token_chunks(
    text: str,
    chunk_tokens: int = 1024,
    overlap: int = 100,
    model_name: str = "DeepSeek-V3.1",
) -> list[str]:
    tokenizer = _get_encoder(model_name)
    tokens = tokenizer.encode(text, add_special_tokens=False)
    stride = chunk_tokens - overlap
    return [regular_sentence1(tokenizer.decode(tokens[i:i + chunk_tokens])) for i in range(0, len(tokens), stride)]


if __name__ == "__main__":
    text = """
The Renaissance (UK: /rɪˈneɪsəns/ rin-AY-sənss, US: /ˈrɛnəsɑːns/ ⓘ REN-ə-sahnss)[1][2][a] is a European period of history and cultural movement, very roughly defined as covering the 14th through 17th centuries,[4][5] though sometimes more narrowly defined for instance as only covering the 15th through 16th centuries.[6] It marked the transition from the Middle Ages to modernity and was characterized by the European rediscovery and revival of the literary, philosophical, and artistic achievements of classical antiquity.[5] Associated with great social change in most fields and disciplines, including art, architecture, politics, literature, exploration and science, the Renaissance was first centered in the Republic of Florence, then spread to the rest of Italy and later throughout Europe. The term rinascita ("rebirth") first appeared in Lives of the Artists (c. 1550) by Giorgio Vasari, while the corresponding French word renaissance was adopted into English as the term for this period during the 1830s.[7][b]
The Renaissance's intellectual basis was founded in its version of humanism, derived from the concept of Roman humanitas and the rediscovery of classical Greek philosophy, such as that of Protagoras, who said that "man is the measure of all things". Although the invention of metal movable type sped the dissemination of ideas from the later 15th century, the changes of the Renaissance were not uniform across Europe: the first traces appear in Italy as early as the late 13th century, in particular with the writings of Dante and the paintings of Giotto.
"""
    output_path = Path(__file__).resolve().with_name("chunk_try_output.txt")
    splitter = SimpleRecursiveSplitter(chunk_size=1000, chunk_overlap=100)
    chunks = splitter.split_text(text)
    tokenizer = _get_encoder("DeepSeek-V3.1")
    lens = [len(tokenizer.encode(item, add_special_tokens=False)) for item in chunks]

    with open(output_path, 'a', encoding='utf-8') as f:
        f.write("自定义循环切分\n")
        f.write(str(lens) + '\n')
        for i, chunk in enumerate(chunks):
            f.write(f"Chunk {i + 1} (len={len(chunk)}): {repr(chunk)}")
            f.write(chunk)
            f.write('\n\n\n')

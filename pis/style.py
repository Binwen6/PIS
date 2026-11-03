"""House style for everything the model writes, plus a deterministic clean-up pass."""
from __future__ import annotations

import re

WRITING_STYLE = """## 写作要求
- 风格参考 Andrej Karpathy 和 Kaiming He：像一位懂行的研究者跟同行聊天，平实、自然、具体，有真人的语感。
- 每句话都要有信息量，用详细、准确的 claim，不说空话套话，不泛泛而谈。
- 少用防御性句式。不要反复写“需要注意的是”“值得一提的是”“在一定程度上”“某种意义上”“诚实地说”“客观来看”“不可否认”。确实不确定的地方，用一句话直接说清哪里不确定、为什么。
- 不要用“不是……而是……”“与其说……不如说……”“不在于……而在于……”这类肯定否定对仗句式，直接说它是什么。
- 不要用花哨的比喻和修辞，不要做机械的跨领域类比（比如把模型比作大脑、厨房、交响乐团、高速公路）。只有当一个类比真能帮助理解技术细节时才用，而且要说清它在哪里不成立。
- 不要用生活化、拟人化的说法代替技术描述：不写“记账”“车间”“接口”“长出了一个解”“救命稻草”“抢容量”这类词，直接用术语说清楚（比如写“参数量是否对齐”“模型收敛到了另一个解”）。
- 提到“N 个”“几类”“三点”时，必须当场列出具体是哪些，并说明各自是什么；不要反复用一个数字指代一组没交代清楚的东西，数字本身没有信息量。
- 涉及算力、数据量、实验规模时，给出原文的具体数字（参数量、token 数、GPU 数或 GPU 小时）；原文没有就直接说没有，可以给出带假设的估算，不要用“一批”“大量”“可观的”含糊带过。
- 不要刻意追求对仗工整和排比，句子的长短和结构要有变化，段落之间自然衔接。
- 用常见的双音节或多音节词，避免翻译腔的单音节词。写“这个/这种”而不是“此/该”，写“所以/因此”而不是“故”，写“需要”而不是“需”，写“只有/仅仅”而不是“仅”，写“它的”而不是“其”，写“都”而不是“均”，写“也”而不是“亦”，写“如果”而不是“若”。英文术语可以直接保留英文，不要硬译成一个单字。
- 标点只用中文写作里常见的：引号用“”，不要用「」『』；倍数写成“3 倍”，不要写 ×；并列用顿号或逗号，不要用中间圆点；不要用 ✓ ✗ 之类的符号；破折号尽量少用。"""

# keep code, math, inline code and URLs untouched
_PROTECT = re.compile(r"```.*?```|\$\$.*?\$\$|\$[^$\n]+\$|`[^`\n]+`|https?://\S+", re.S)


def _fix(s: str) -> str:
    s = s.replace("「", "“").replace("」", "”").replace("『", "‘").replace("』", "’")
    s = re.sub(r"(\d)\s*[×✕]\s*(\d)", r"\1x\2", s)            # 3×3 -> 3x3
    s = re.sub(r"(\d(?:\.\d+)?)\s*[×✕]", r"\1 倍", s)          # 2.6× -> 2.6 倍
    s = re.sub(r"(?<=\S)[ \t]*[·・][ \t]*(?=\S)", "、", s)       # A · B -> A、B
    s = s.replace("✓", "").replace("✗", "").replace("✔", "").replace("✘", "")
    return s


def sanitize(text: str) -> str:
    if not text:
        return text
    out, pos = [], 0
    for m in _PROTECT.finditer(text):
        out.append(_fix(text[pos:m.start()]))
        out.append(m.group())
        pos = m.end()
    out.append(_fix(text[pos:]))
    return "".join(out)


def sanitize_obj(obj):
    """Recursively clean every string in a JSON-like structure."""
    if isinstance(obj, str):
        return sanitize(obj)
    if isinstance(obj, list):
        return [sanitize_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {k: sanitize_obj(v) for k, v in obj.items()}
    return obj

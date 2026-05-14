# src/libriscribe/utils/academic_prompt.py
"""固定学术专著写作规范与自检工具。"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple


ACADEMIC_MONOGRAPH_SYSTEM_PROMPT = """# 学术专著分章生成系统提示词（全书统一版）

## 一、角色定位
你是一个严谨的学术专著写作专家，负责按照既定全书目录逐章生成内容，生成前先了解老板所有要求，必须按照章节要求的字数不超过5%，否则你将被扣除绩效，扣工资，甚至被开除。你的任务不是写论文、报告或小说，而是生成风格统一、术语统一、结构统一、可继续编辑出版的学术专著正文。

## 二、全书统一原则
1. 全书必须保持统一的学术语体、术语体系、章节编号、标题层级、段落缩进和论述节奏。
2. 所有章节必须服从全书主题、全书目录和前文摘要，不得自创章节、不跳章、不合并章、不改变用户目录。
3. 普通章节只完成本章论述，不输出全书性附录；末章才输出全书参考文献和术语表附录。
4. 章节之间允许承接前文，但普通章的“本章小结”只总结本章，不预告后续章节，不写“下一章将……”等表述。
5. 系统内部可能使用 Markdown 标题保存章节结构；模型正文不得输出 HTML/XML/JSON/代码/调试信息/网页错误页。

## 三、普通章与末章输出结构
### 1. 普通章（非末章）
普通章只能包含以下内容：
- 章标题（由系统插入）
- 可选章首导语（由系统插入或按用户要求生成）
- 按目录逐节展开的正文

## 四、反幻觉与引用规则
1. 禁止编造任何数据、案例、文献、法规、标准编号、人名、机构名、时间、地点、模型指标、政策条款。
2. 只有用户资料、RAG片段或项目 citation 记录中明确给出真实来源时，才允许正文出现 [1] 式引用。
3. 没有真实来源时，不得写“已有研究表明[1]”“某报告指出”“某标准规定”等参考文献式句子。
4. 信息不足时必须写明：“【信息缺失】需要您提供……”。可以基于通用学术知识做审慎、非数据化的概念论述，但不得把通用判断包装成可引用事实。
5. 内部资料不得列入参考文献；使用时应标注“（资料来源：内部资料）”。无法判断公开性的资料，默认视为内部资料。
6. 禁止输出“请搜索”“请查询”“详见某网页”“根据最新检索结果”等虚假操作表述。

## 五、章节编号、格式与语言
1. 章节编号必须与用户目录一致，章、节、三级、四级标题连续且不重复，禁止出现"第0章"。
2. 每个自然段开头必须使用两个全角空格（\u3000\u3000），段落之间空行分隔。
3. 使用第三人称和客观学术表达，不出现"我""我们""笔者"。
4. 避免口语化、营销化、小说化和过度主观表述。
5. 专业术语首次出现时应采用全书统一写法；若项目术语表给出定义，以项目术语表为准。
6. 公历世纪、年代、年、月、日、时刻用阿拉伯数字；定型词语中的数字按中文出版惯例使用。
7. **段落规范**：若正文超过约450字或超过6个完整句子，可根据论证自然分为2~3段；若正文较短、只有一个完整论证单元，可以保留1段。不要为了形式整齐强行分段，不要刻意追求段落长度整齐。段首可使用“进一步看”“从实践层面”“然而”等逻辑词自然衔接。
8. 少用双引号，普通判断句和概念直接陈述，不加引号；只在直接转述他人原话、术语首次界定或特殊含义临时用法时使用双引号。
9. **语言规范**：表达拟定计划、办法、方案时，一律使用“制订”，不使用“制定”；表达“做出 + 名词”结构时，统一使用“做出”，不使用“作出”；描述水平、程度、质量的提高时，使用“提高”，不使用“提升”；谨慎使用连接词，避免滥用“而”“且”“并”“以及”等造成句子拖沓，能用句号断开就断开；使用“应”“可”“需”时必须区分语义，“应”表义务或推荐，“可”表可能性或许可，“需”表必要条件，不可混用或堆砌。

## 六、篇幅控制
1. 用户会为章节或小节指定篇幅目标；字数要严格控制在要求内。
2. 不得为了凑字数编造事实、案例、数据或文献；篇幅不足时只能扩展概念界定、机制分析、边界条件、适用场景、比较维度和用户资料中已有信息。
3. 不在模型正文中自行输出字数统计、偏差说明、自评结果或任何生成过程说明。

## 七、单章质量自检评分
评分机制只用于“当前单章内容质量自检”，不用于判断全书引用完整性，也不要求普通章输出参考文献。

评分维度如下（满分50分）：
| 维度 | 分值 | 扣分标准 |
|------|------|----------|
| 编号连续性与一致性 | 10 | 当前章内跳号、重号、标题层级混乱扣5-10分 |
| 字数偏差（±5%内） | 10 | 当前章/当前写作单元偏差超过5%后，每增加5个百分点扣2分 |
| 资料分类与引用正确性 | 10 | 当前章误用内部资料、虚构来源、无来源却写引用式句子扣3-10分 |
| 参考文献格式规范性 | 10 | 仅在当前章/末章实际存在真实参考文献时检查格式；无真实参考文献不得扣分 |
| 语言客观性与语法正确性 | 10 | 第一人称、主观词、明显语病、非学术表达每处扣1分 |

通过线：80分。若不通过，系统可进行一次确定性格式修复或提示人工审核。评分表只作为单章质量校验，不代表全书引用完整性审查。

## 八、二次优化规则
当用户要求二次优化时，只修改用户明确定位的部分，保持其他内容不变。新增参考文献必须来自真实资料；没有真实资料时删除该引用请求并说明信息缺失。二次优化同样遵守反幻觉、术语统一、缩进和编号规则。
"""


BLOCK_PREFIXES = (
    "#", "##", "###", "####", "- ", "* ", "【", "本章实际字数", "（本节实际", "|"
)
FORBIDDEN_PATTERNS = (
    "我们", "笔者", "值得注意的是", "令人惊讶的是", "显然", "<html", "<script", "<iframe",
    "[待补充]", "TODO", "此处省略", "详见", "根据最新检索结果", "请搜索", "请查询",
    "制定", "作出", "提升"
)
REFERENCE_LINE_RE = re.compile(r"^\s*\[\d+\]\s*.+(?:\[M\]|\[J\]|\[S\]|\[R\]|\[EB/OL\]|\[D\]).+", re.IGNORECASE)


def count_manuscript_words(text: str) -> int:
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text or "")
    english_words = re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", text or "")
    return len(chinese_chars) + len(english_words)


def strip_self_assessment(content: str) -> str:
    return re.split(r"\n\s*【自评(?:打分|结果)】", content or "", maxsplit=1)[0].strip()


def ensure_fullwidth_indent(content: str) -> str:
    """为普通正文自然段添加两个全角空格；保留内部 Markdown 标题和列表等结构行。"""
    lines = []
    for raw in (content or "").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if stripped.startswith(BLOCK_PREFIXES) or re.match(r"^\d+(?:\.\d+){0,3}\s+", stripped):
            lines.append(stripped)
            continue
        if stripped.startswith("　　"):
            lines.append(stripped)
        else:
            lines.append("　　" + stripped.lstrip())
    return "\n".join(lines).strip()


def _score_word_deviation(actual: int, target_words: int) -> Tuple[int, str]:
    if not target_words:
        return 8, "未提供目标字数"
    deviation = abs(actual - target_words) / max(target_words, 1)
    # 质量评分与生成后系统裁判保持一致：±5% 内满分，超过后每 5 个百分点扣 2 分。
    # 字数统计、偏差判断、补写和压缩由代码完成，不要求模型自行数字数。
    if deviation <= 0.05:
        return 10, f"偏差{deviation:.0%}"
    excess_steps = int(((deviation - 0.05) * 100 + 4.999) // 5)
    score = max(0, 10 - excess_steps * 2)
    return score, f"偏差{deviation:.0%}"


def _extract_reference_lines(text: str) -> List[str]:
    marker = re.search(r"(?:本章|全书)?参考文献", text or "")
    if not marker:
        return []
    tail = text[marker.end():]
    lines = []
    for line in tail.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("【自评") or "术语表" in stripped:
            break
        if re.match(r"^\[\d+\]", stripped):
            lines.append(stripped)
    return lines


def _has_chinese_academic_numbering(text: str) -> bool:
    """识别中文专著正文中的章节/层级编号，不强制要求保留“第X章”章标题。"""
    if not text:
        return False
    return bool(
        re.search(r"第\s*(?:[1-9]\d*|[一二三四五六七八九十百千万零〇两]+)\s*章", text)
        or re.search(r"第\s*(?:[1-9]\d*|[一二三四五六七八九十百千万零〇两]+)\s*节", text)
        or re.search(r"(?m)^\s*#{1,6}\s*第\s*(?:[1-9]\d*|[一二三四五六七八九十百千万零〇两]+)\s*节", text)
        or re.search(r"(?m)^\s*#{1,6}\s*[一二三四五六七八九十百千万零〇两]+、\S+", text)
        or re.search(r"(?m)^\s*[一二三四五六七八九十百千万零〇两]+、\S+", text)
        or re.search(r"(?m)^\s*#{1,6}\s*（[一二三四五六七八九十百千万零〇两]+）\S+", text)
        or re.search(r"(?m)^\s*（[一二三四五六七八九十百千万零〇两]+）\S+", text)
    )


def self_assess_chapter(content: str, target_words: int = 0) -> Tuple[Dict[str, int], int, str]:
    text = content or ""
    scores: Dict[str, int] = {}

    has_invalid_number = bool(re.search(r"第\s*0\s*章|第\s*0\s*节|Section\s*1\s*:", text, re.IGNORECASE))
    has_numbering = _has_chinese_academic_numbering(text)
    scores["编号连续性与一致性"] = 10 if has_numbering and not has_invalid_number else 5 if has_numbering else 0

    actual = count_manuscript_words(strip_self_assessment(text))
    scores["字数偏差"], deviation_note = _score_word_deviation(actual, target_words)

    reference_lines = _extract_reference_lines(text)
    has_citation = bool(re.search(r"\[\d+\]|资料来源：内部资料|客户提供|内部资料", text))
    has_missing_info = "【信息缺失】" in text
    has_fake_operation = any(token in text for token in ["请搜索", "请查询", "根据最新检索结果", "详见某某网站"])
    classification_score = 10
    if not has_citation and (reference_lines or "参考资料" in text or "内部资料" in text):
        classification_score -= 3
    if has_fake_operation:
        classification_score -= 5
    if any(token in text for token in ["虚构", "编造"]):
        classification_score -= 3
    if has_missing_info:
        classification_score = max(classification_score, 8)
    scores["资料分类与引用正确性"] = max(0, classification_score)

    if reference_lines:
        valid_refs = sum(1 for line in reference_lines if REFERENCE_LINE_RE.search(line))
        scores["参考文献格式规范性"] = max(0, 10 - (len(reference_lines) - valid_refs))
    else:
        # 普通章不应输出参考文献；无真实参考文献时不因“没有参考文献列表”扣分。
        scores["参考文献格式规范性"] = 10

    paragraphs = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith(BLOCK_PREFIXES) and not re.match(r"^\d+(?:\.\d+){0,3}\s+", ln.strip())]
    indented = [ln for ln in paragraphs if ln.strip().startswith("　　")]
    style_score = 10
    if paragraphs and len(indented) / max(len(paragraphs), 1) < 0.9:
        style_score -= 2
    forbidden_hits = sum(1 for item in FORBIDDEN_PATTERNS if item.lower() in text.lower())
    style_score -= min(10, forbidden_hits)
    scores["语言客观性与语法正确性"] = max(0, style_score)

    total = sum(scores.values())
    percent = round(total / 50 * 100)
    verdict = "通过" if percent >= 80 else f"未达到80/100分，请人工审核（当前{percent}/100，原始{total}/50）"
    return scores, total, verdict


def build_self_assessment_table(scores: Dict[str, int], total: int, verdict: str, target_words: int = 0, actual_words: int = 0) -> str:
    percent = round(total / 50 * 100)
    word_note = ""
    if target_words:
        deviation = abs(actual_words - target_words) / max(target_words, 1)
        word_note = f"（偏差{deviation:.0%}）"
    lines: List[str] = ["【自评结果】", ""]
    lines.append(f"编号连续性与一致性：{scores.get('编号连续性与一致性', 0)}/10")
    lines.append("")
    lines.append(f"字数偏差：{scores.get('字数偏差', 0)}/10{word_note}")
    lines.append("")
    lines.append(f"资料分类与引用正确性：{scores.get('资料分类与引用正确性', 0)}/10")
    lines.append("")
    lines.append(f"参考文献格式规范性：{scores.get('参考文献格式规范性', 0)}/10")
    lines.append("")
    lines.append(f"语言客观性：{scores.get('语言客观性与语法正确性', 0)}/10")
    lines.append(f"总分：{percent}/100（原始{total}/50），判定：{verdict}")
    return "\n".join(lines).strip()


def finalize_academic_chapter(content: str, target_words: int = 0) -> Tuple[str, int, str]:
    body = ensure_fullwidth_indent(strip_self_assessment(content))
    actual_words = count_manuscript_words(body)
    scores, total, verdict = self_assess_chapter(body, target_words=target_words)
    return body.rstrip() + "\n\n" + build_self_assessment_table(scores, total, verdict, target_words=target_words, actual_words=actual_words) + "\n", total, verdict

"""Prompt playbook service for Libriscribe.

This module provides built-in writing playbooks and editable prompt templates used by
Web UI, workflow services, and future API layers.
"""

from __future__ import annotations

import yaml
from pathlib import Path

DEFAULT_OUTLINE_PROMPT_TEMPLATE = """# 中文专著大纲生成提示词（Web 可编辑版）

你是中文专著总策划与大纲架构专家。请先进行全书整体框架思考，再输出可解析的正式目录。

## 项目信息
- 书名：{book_title}
- 学科/类型：{genre}
- 分类：{category}
- 语言：{language}
- 项目描述：{description}
- 目标章数：{target_chapters}
- 总目标字数：约 {target_words} 字
- 每章建议字数：约 {words_per_chapter} 字
- 是否包含序言：{include_preface}
- 现有大纲：{existing_outline}
- 用户补充要求：{instruction}

## 生成流程
1. 先在内部完成“为什么要写、全书价值定位、研究对象、主线逻辑、章节递进关系”的整体框架思考。
2. 再为每一章确定写作职责和写作思路，确保章与章之间不重复、不断裂、概念口径一致。
3. 最后只输出正式大纲，不输出推理过程、解释、免责声明或代码块。

## 输出格式
必须使用中文专著目录格式，示例如下：
第一章 标题（总字数 xxxx字）
第一节 二级标题（约 xxxx字）
一、三级标题（约 xxxx字）
（一）四级标题（约 xxxx字）
写作思路：说明本小目如何展开、从什么背景切入、分析什么机制、与上下文如何衔接。

## 强制要求
1. 必须输出完整全书目录，不能只输出第一章。
2. 每一章都必须有明确写作思路；每个四级标题后必须跟“写作思路：”。
3. 章节逻辑要形成递进：背景与价值定位 → 核心对象与技术/理论基础 → 场景/机制 → 实施路径 → 治理评价 → 持续优化。
4. 不编造具体政策编号、数据、文献、案例名称；没有资料依据时只写一般性研究方向。
5. 只输出目录正文，便于程序解析。
"""

DEFAULT_CHAPTER_PROMPT_TEMPLATE = """# 学术专著小节写作提示词（Web 可编辑版）

你是一个严谨的学术专著撰写助手，请根据项目资料和当前写作单元生成正文。

## 专著信息
- 书名：{book_title}
- 学科/类型：{genre}
- 分类：{category}
- 语言：{language}
- 目标读者：{target_audience}
- 全书说明：{description}

## 当前章节
- 章号：第{chapter_number}章
- 章标题：{chapter_title}
- 章目标/摘要：{chapter_outline}

## 当前写作单元
- 编号与标题：{section_title}
- 层级：{section_level}
- 写作目标：{section_goal}
- 目标字数：约 {target_words} 字

## 本章目录树
{outline_tree}

## 前文摘要
{previous_summaries}

## 已生成小节摘要
{generated_summaries}

## 术语表
{terminology_context}

## 参考资料/RAG 检索结果
{rag_context}

## 强制写作要求
1. 只围绕当前写作单元展开，不要越界写其他小节。
2. 每个自然段开头使用两个全角空格（　　），段落之间空行分隔。
3. 论述要有概念界定、机制分析、适用边界和必要总结，避免空泛口号。
4. 不得编造文献、数据、案例、法规、标准编号、作者、机构和引用序号。
5. 只有参考资料明确给出真实来源时，才允许使用 [1] 式引用；否则不得虚构参考文献。
6. 信息不足时明确写“【信息缺失】需要您提供……”，不要假装已经检索。
7. 不要输出 HTML、XML、JSON、代码、注释、网页错误页或调试信息。
8. 当前只输出本写作单元正文，不输出标题、参考文献、附录或评分表。

## 去 AI 痕迹与出版级表达要求
1. 以长期从事学术写作与出版工作的资深编辑视角组织语言，保持研究者或专业作者的自然表达，不使用机械化、模板化口吻。
2. 弱化“首先、其次、最后”“综上所述”“总之”“值得注意的是”“毫无疑问”“一般来说”等高频套语，改用更具体的语义承接、因果推进和问题递进。
3. 避免刻意的“总—分—总”和并列堆砌结构；可调整语序和段落推进方式，让论证像真实研究思考一样自然展开。
4. 主动句优先，长短句交错，减少连续抽象概念堆叠；必要时用克制的背景补充、限定性措辞或具体化说明提升可读性。
5. 在不削弱学术严谨性的前提下，可以使用“在多数情况下”“某种程度上”“实际上”“或许”等审慎表达，但不得把不确定信息写成确定事实。
6. 少用空泛判断，多使用有指向性的动词和名词；每段最好解决一个明确问题，而不是只做姿态化总结。
"""

DEFAULT_MANUSCRIPT_PREFACE_PROMPT_TEMPLATE = """【系统指令】
你是一名学术专著撰写专家。你的唯一任务是为指定的专著生成“前言”。输出必须是纯文本的前言正文，不包含“前言”二字标题，不包含任何其他内容。

【任务参数】
- 专著名称：{book_title}
- 作者：{author}
- 全书所属学科/领域：{field}
- 前言预期字数：{target_words} 字；绝对允许范围：{min_words}—{max_words} 字

【全书结构概览】（你撰写的所有内容必须紧扣此框架）
{chapters}

{common_context}

【写作要求】
1. 前言应包含：
   - 研究背景与问题意识：阐述本领域现状、核心矛盾，以及撰写本书的缘由。
   - 全书主旨与目标：用凝练语言阐明本书要解决的核心问题、核心主张。
   - 内容导览：基于给定的全书结构，简要说明每一章的研究重点及其逻辑关联。
   - 致谢（若有）：用自然的方式融入，不单独设节，点到为止。
2. 语言风格：学术、平实、客观。禁止使用“在当今时代”“随着……发展”“众所周知”等空泛套话。禁止使用“极大地”“颠覆性地”等夸张副词。保持陈述句为主。
3. 不得超出给定框架虚构章节或内容。

【字数规定 - 绝对红线】
- 前言全文必须严格控制在 {target_words} 字左右，允许偏差上下不超过 8%，即 {min_words}—{max_words} 字。
- 生成完毕后你必须自己统计中文字符数（不含空格和标题）并校验；如果超出范围，必须立刻重写精简或补足，直到达标。
- 自检用的“实际字数”报告只能用于你内部校验，最终输出绝对不能包含任何字数统计。

【输出规则】
- 直接输出前言正文第一段；不得输出“前言”二字，不得输出 Markdown 标题。
- 正文结束后直接结束，不留任何空格、换行以外的符号。
- 绝对禁止输出：字数统计、自评、评分、附录、术语表、任何标记线（如“#####”）。
"""

DEFAULT_MANUSCRIPT_CONCLUSION_PROMPT_TEMPLATE = """【系统指令】
你是一名学术专著撰写专家。你的唯一任务是为指定的专著生成“结语”。输出必须是纯文本的结语正文，不包含“结语”二字标题，不包含任何其他内容。

【任务参数】
- 专著名称：{book_title}
- 作者：{author}
- 全书所属学科/领域：{field}
- 结语预期字数：{target_words} 字；绝对允许范围：{min_words}—{max_words} 字

【全书各章核心结论】（你必须据此总结，不得偏离）
{chapters}

【前言核心问题与主张】（用于形成前后闭环，若平台未提供则忽略此条）
{foreword_core_summary}

{common_context}

【写作要求】
1. 结语必须包含：
   - 全书主要发现与贡献：提炼全书各章共通的核心成果，形成一个整体性的学术判断。
   - 实践启示与理论价值（若适用）：指出本成果对领域实践的指导意义。
   - 研究局限与未来方向：客观、诚实地点出未解决的问题，提出后续可深入的2-3个方向。
2. 必须与前言形成呼应：若前言提出了核心问题或预设，结语须对此作出明确回答。保持术语、论调一致。
3. 语言风格：与前言一致，学术、平实、不夸大。

【字数规定 - 绝对红线】
- 结语全文必须严格控制在 {target_words} 字左右，允许偏差上下不超过 8%，即 {min_words}—{max_words} 字。
- 生成完毕后你必须自己统计中文字符数（不含空格和标题）并校验；如果超出范围，必须立刻重写精简或补足，直到达标。
- 自检用的“实际字数”报告只能用于你内部校验，最终输出绝对不能包含任何字数统计。

【输出规则】
- 直接输出结语正文第一段；不得输出“结语”二字，不得输出 Markdown 标题。
- 正文结束后直接结束，不允许任何附加信息。
- 绝对禁止：字数统计、自评、评分、附录、术语表、任何分隔标记。
"""

DEFAULT_MANUSCRIPT_REFERENCES_PROMPT_TEMPLATE = """你是一名学术参考文献整理与校验专家。
你的唯一任务是为给生成的文章专著整理一批中文参考文献。
你输出的内容必须是纯参考文献列表，不包含任何其他信息。

【任务参数】
- 专著名称：{book_title}
- 所属学科/领域：{field}
- 参考文献总数量：{ref_count} 条（控制在15-35条之间）
- 文献语种分布：{language_distribution}（以中文文献为主；可含少量权威英文文献，但必须以中文为主）
- 出版/发表时间范围：严格限制为 {ref_start_year} 年至 {ref_end_year} 年
- 参考文献格式：{citation_style}

【全书结构概览】
{chapters}

{common_context}

【平台已有引用与资料上下文】
{citation_context}

【文献类型构成要求】
1. 必须以 M 类文献（专著、图书）为主体，占到总条目的 80% 以上。
2. 可以辅以少量期刊论文（[J]）、学位论文（[D]）、会议论文（[C]）等，但期刊论文必须是能够在知网（cnki.net）公开检索到的。
3. 禁止包含报纸文章（[N]）、一般网络文章（[EB/OL]）、标准（[S]）、专利（[P]）等非学术核心文献。

【真实性硬性约束 - 不可违反】
1. 你列出的每一条文献，都必须是真实存在的出版物。严禁编造、杜撰、拼凑任何文献。
2. 对于 M 类文献（专著/图书）：
   - 必须在条目中完整著录：作者、书名、出版地、出版社、出版年份。
   - 出版社和出版年份必须是该专著实际对应的准确信息，不可随意匹配。
   - 如果你对某本书的出版社或出版年份不确定，直接跳过，不列该条目。
3. 对于期刊论文（[J]）：
   - 必须能够在中国知网（cnki.net）通过篇名或作者检索到。
   - 必须在条目中完整著录：作者、篇名、期刊名、年、卷、期、起止页码。
   - 如果某篇论文你无法确认是否被知网收录，直接跳过。
4. 对于其他类型文献（如论文集[C]、学位论文[D]），同样要求真实可查。

【生成策略】
- 你必须在内部进行“可验证性自检”：对每一篇拟输出的文献，确认自己有极高把握它是真实存在的，且出版信息准确。不确定的条目一律舍弃。
- 为保证真实性，宁可少列几篇，也绝不用不确定的条目凑数。
- 优先使用平台已有可核验引用记录、资料库来源和已导入的 OpenAlex/DOI/链接文献；但只有确认满足上述类型、年份、格式和真实性要求时才可列入。
- 如果某个主题下真实存在的文献确实不足以达到请求数量，可以诚实减少输出条目，并在列表末尾用一行“（说明：经校验后确信存在的相关文献共计X条）”，但这一行说明之后不能再添加任何其他文字。

【输出规则】
1. 输出第一行是“参考文献”四个字（作为标题），空一行后逐条列出参考文献。
2. 每条文献单独一行，按作者姓氏拼音排序，中文文献在前，英文文献在后。
3. 正文结束后直接结束，不留任何额外字符、空行或表情符号。
4. 绝对禁止在正文前后或中间输出以下内容：
   - 字数统计、自评、评分
   - 任何过程说明（如“以下是符合要求的文献”）
   - 术语表、附录
   - 分隔标记或装饰线
"""

PROMPT_DISPLAY_NAMES = {
    "chapter_writer": "章节正文写作（当前生效）",
    "outliner": "大纲生成与优化",
    "manuscript_preface": "前言生成（当前生效）",
    "manuscript_conclusion": "结语/总结生成（当前生效）",
    "manuscript_references": "参考文献生成（当前生效）",
    "researcher": "资料研究与文献梳理",
    "fact_checker": "事实核验与反幻觉检查",
    "citation_agent": "引用格式与证据绑定",
    "content_reviewer": "内容审校",
    "critic_agent": "批判性审稿",
    "editor": "正文润色",
    "style_editor": "风格统一与降 AI 痕迹",
    "plagiarism_checker": "查重风险检查",
    "concept_generator": "选题与概念生成",
    "character_generator": "小说角色生成（旧模板）",
    "scene_generator": "小说场景生成（旧模板）",
    "scene_outliner": "小说场景大纲（旧模板）",
    "worldbuilding": "小说世界观生成（旧模板）",
}

PROMPT_USAGE_NOTES = {
    "chapter_writer": "当前章节正文生成会读取这一条。建议重点维护。",
    "outliner": "用于后续大纲生成/优化接入；当前不参与章节正文生成。",
    "manuscript_preface": "写章节页生成前言时实际读取这一条；支持在提示词中使用 {book_title}、{target_words}、{chapters} 等变量。",
    "manuscript_conclusion": "写章节页生成结语/总结时实际读取这一条；支持在提示词中使用 {foreword_core_summary}、{chapters} 等变量。",
    "manuscript_references": "写章节页 AI 生成参考文献时实际读取这一条；支持在提示词中使用 {ref_count}、{citation_context} 等变量。",
    "researcher": "用于后续资料分析、文献梳理接入；当前不参与章节正文生成。",
    "fact_checker": "用于后续事实核验、反幻觉检查接入；当前不参与章节正文生成。",
    "citation_agent": "用于后续引用格式、证据绑定接入；当前不参与章节正文生成。",
    "content_reviewer": "用于后续内容审校接入；当前不参与章节正文生成。",
    "critic_agent": "用于后续批判性审稿接入；当前不参与章节正文生成。",
    "editor": "用于后续正文润色接入；当前不参与章节正文生成。",
    "style_editor": "用于后续统一文风和降低 AI 痕迹接入；当前不参与章节正文生成。",
    "plagiarism_checker": "用于后续查重风险提示接入；当前不参与章节正文生成。",
    "concept_generator": "用于选题/概念生成；当前不参与章节正文生成。",
    "character_generator": "旧小说写作模板，专著正文一般不用。",
    "scene_generator": "旧小说写作模板，专著正文一般不用。",
    "scene_outliner": "旧小说写作模板，专著正文一般不用。",
    "worldbuilding": "旧小说写作模板，专著正文一般不用。",
}


PROMPT_EXAMPLES = {
    "chapter_writer": "范文片段：\n　　智慧工地并非单一技术设备的简单叠加，而是施工现场管理方式在数字化条件下的系统重组。它通过感知设备、数据平台和管理流程之间的协同，把质量、安全、进度、成本等原本分散的管理对象纳入同一运行框架之中，从而提升项目治理的连续性和可追溯性。",
    "outliner": "范文格式：\n第一章 智慧工地的生成逻辑与价值定位\n第一节 建筑业数字化转型的现实背景\n一、工程建造方式演进的外部驱动\n（一）城镇建设需求持续升级\n写作思路：从城市更新、基础设施完善和高品质建造需求提升切入，说明工程建造方式升级的现实背景。",
    "manuscript_preface": "范文片段：\n　　本书围绕智慧工地建设与工程现场数字化管理展开，试图在技术应用与现场治理之间建立更清晰的分析框架。",
    "manuscript_conclusion": "范文片段：\n　　全书的讨论表明，智慧工地的价值并不止于设备更新，而在于工程现场管理逻辑、数据流转方式和责任协同机制的系统重塑。",
    "manuscript_references": "范文格式：\n参考文献\n\n[1] 作者．书名[M]．出版地：出版社，年份．\n[2] 作者．篇名[J]．期刊名，年份，卷(期)：起止页码．",
    "researcher": "范文片段：\n资料显示，当前研究主要集中在施工现场感知、BIM 协同、风险预警和平台化治理四个方向。可优先将这些资料对应到“技术基础、应用场景、监管评价、持续优化”等章节。",
    "fact_checker": "范文片段：\n核验结果：文中“某政策明确要求……”缺少来源支撑，建议改为一般表述，或补充政策原文、发布日期、发布机构后再使用。",
    "citation_agent": "范文片段：\n引用建议：[1] 可绑定到“智慧工地平台建设背景”段落；当前缺少页码和出版社信息，导出参考文献前需要补齐。",
    "content_reviewer": "范文片段：\n审校意见：本章从背景进入价值定位较顺，但第二节与第三节均在重复说明数字技术作用，建议第二节聚焦生成逻辑，第三节聚焦价值转化。",
    "critic_agent": "范文片段：\n批判性意见：当前论证偏重技术正向价值，对数据治理成本、组织协同阻力和现场执行偏差讨论不足，建议增加约束条件分析。",
    "editor": "范文片段：\n润色前：智慧工地很重要，可以提高管理水平。\n润色后：智慧工地的重要性并不只体现在技术更新上，更体现在施工现场管理颗粒度、响应速度和责任链条的同步优化。",
    "style_editor": "范文片段：\n风格调整：减少“首先、其次、最后”的机械连接，弱化模板化总分总结构，改用因果推进、语义承接和研究者自然推敲观点时的表达节奏。",
    "plagiarism_checker": "范文片段：\n风险提示：该段存在连续模板句式，建议调整句法结构，增加具体分析对象，减少空泛判断和重复收束句。",
    "concept_generator": "范文片段：\n选题建议：可将“智慧工地”定位为工程建造方式、现场治理机制和数字技术应用之间的交叉研究对象。",
    "character_generator": "旧小说模板范文：生成人物姓名、动机、关系和成长弧线。专著写作一般不使用。",
    "scene_generator": "旧小说模板范文：生成场景地点、冲突、行动和情绪变化。专著写作一般不使用。",
    "scene_outliner": "旧小说模板范文：生成场景顺序、叙事节奏和情节功能。专著写作一般不使用。",
    "worldbuilding": "旧小说模板范文：生成世界规则、历史背景和社会结构。专著写作一般不使用。",
}

PROMPT_CHINESE_DEFAULT_TEMPLATES = {
    "outliner": DEFAULT_OUTLINE_PROMPT_TEMPLATE,
    "manuscript_preface": DEFAULT_MANUSCRIPT_PREFACE_PROMPT_TEMPLATE,
    "manuscript_conclusion": DEFAULT_MANUSCRIPT_CONCLUSION_PROMPT_TEMPLATE,
    "manuscript_references": DEFAULT_MANUSCRIPT_REFERENCES_PROMPT_TEMPLATE,
}

PROMPT_ANALYSIS_GUIDE = """## AI 提示词分析与优化方向

重点检查这些问题：

1. **目标是否明确**：是否说清楚要写“学术专著正文”、前言、结语或参考文献，还是容易写成报告、论文、新闻稿或口号。
2. **输入变量是否完整**：章节正文必须保留 `{book_title}`、`{chapter_title}`、`{section_title}`、`{target_words}`、`{rag_context}` 等变量；前言/结语/参考文献模板可使用 `{book_title}`、`{author}`、`{field}`、`{target_words}`、`{min_words}`、`{max_words}`、`{chapters}`、`{common_context}`、`{foreword_core_summary}`、`{ref_count}`、`{ref_start_year}`、`{ref_end_year}`、`{citation_style}`、`{language_distribution}`、`{citation_context}`，否则生成时缺上下文。
3. **资料约束是否清楚**：如果文章质量差或胡编引用，要加强“只使用资料库/RAG，不得编造来源”。
4. **结构要求是否具体**：质量差通常是因为只写“严谨专业”，没有要求概念界定、机制分析、边界条件、实践意义。
5. **字数要求是否合理**：目标字数太大而资料不足时，模型容易灌水；建议拆小节或补资料。
6. **禁止项是否过多过硬**：禁止项太多会让模型过度保守，必要时可以放宽“信息缺失”出现频率。
7. **输出格式是否单一**：如果只要正文，就明确不要标题、不要参考文献、不要评分表，避免污染章节内容。

推荐优化方式：
- 想要更像书稿：增加“按专著章节行文，段落连贯，不列过多项目符号，并减少 AI 高频套语和机械化总分总结构”。
- 想要更有深度：增加“必须包含概念界定、原因机制、影响路径、局限与边界”。
- 想减少幻觉：增加“没有资料时不得出现具体年份、百分比、法规编号和文献名”。
- 想减少空话：增加“每段必须回答一个明确问题，避免泛泛评价”。
"""


class PromptService:
    """Service that exposes built-in playbooks and editable global prompt templates."""

    @staticmethod
    def custom_prompt_path(project_dir: str | Path | None) -> Path | None:
        if not project_dir:
            return None
        return Path(project_dir) / "prompts" / "chapter_writer.md"

    @staticmethod
    def global_prompt_key(prompt_name: str) -> str:
        return str(prompt_name or "chapter_writer").replace(".yml", "").strip() or "chapter_writer"

    @staticmethod
    def templates_dir() -> Path:
        return Path(__file__).resolve().parents[3] / "prompts" / "templates"

    @classmethod
    def load_builtin_template(cls, prompt_name: str) -> str:
        """Load the original built-in YAML prompt template by name."""
        prompt_key = cls.global_prompt_key(prompt_name)
        if prompt_key == "chapter_writer":
            path = cls.templates_dir() / "chapter_writer.yml"
            if path.exists():
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                return str(data.get("template") or DEFAULT_CHAPTER_PROMPT_TEMPLATE)
            return DEFAULT_CHAPTER_PROMPT_TEMPLATE

        if prompt_key in PROMPT_CHINESE_DEFAULT_TEMPLATES:
            return PROMPT_CHINESE_DEFAULT_TEMPLATES[prompt_key]

        path = cls.templates_dir() / f"{prompt_key}.yml"
        if not path.exists():
            return ""
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return str(data.get("template") or "")

    @classmethod
    def list_all_global_prompts(cls) -> list[dict]:
        """Return all previous/built-in global prompt templates plus edited global values."""
        from libriscribe.services.global_settings_service import GlobalSettingsService

        settings_prompts = GlobalSettingsService().load().get("prompts", {}) or {}
        prompts: list[dict] = []
        template_dir = cls.templates_dir()
        if template_dir.exists():
            for path in sorted(template_dir.glob("*.yml")):
                try:
                    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                except Exception:
                    data = {}
                key = path.stem
                default_template = PROMPT_CHINESE_DEFAULT_TEMPLATES.get(key) or str(data.get("template") or "")
                current_template = str(settings_prompts.get(key) or default_template)
                prompts.append({
                    "key": key,
                    "name": PROMPT_DISPLAY_NAMES.get(key) or data.get("name") or key,
                    "original_name": data.get("name") or key,
                    "description": PROMPT_USAGE_NOTES.get(key) or data.get("description") or "",
                    "example": PROMPT_EXAMPLES.get(key) or "范文示例：此模板暂无专门范文，可按当前提示词变量自行补充输出样例。",
                    "version": data.get("version") or "",
                    "category": "当前生效" if key in {"chapter_writer", "outliner", "manuscript_preface", "manuscript_conclusion", "manuscript_references"} else "备用模板",
                    "default_template": default_template,
                    "current_template": current_template,
                    "is_customized": key in settings_prompts,
                    "is_active": key in {"chapter_writer", "outliner", "manuscript_preface", "manuscript_conclusion", "manuscript_references"},
                    "path": str(path),
                })

        existing_keys = {item["key"] for item in prompts}
        for key, default_template in PROMPT_CHINESE_DEFAULT_TEMPLATES.items():
            if key in existing_keys:
                continue
            current_template = str(settings_prompts.get(key) or default_template)
            prompts.append({
                "key": key,
                "name": PROMPT_DISPLAY_NAMES.get(key) or key,
                "original_name": key,
                "description": PROMPT_USAGE_NOTES.get(key) or "全局中文内置提示词",
                "example": PROMPT_EXAMPLES.get(key) or "范文示例：此模板暂无专门范文，可按当前提示词变量自行补充输出样例。",
                "version": "built-in-cn",
                "category": "当前生效" if key in {"chapter_writer", "outliner", "manuscript_preface", "manuscript_conclusion", "manuscript_references"} else "内置模板",
                "default_template": default_template,
                "current_template": current_template,
                "is_customized": key in settings_prompts,
                "is_active": key in {"chapter_writer", "outliner", "manuscript_preface", "manuscript_conclusion", "manuscript_references"},
                "path": "内置中文默认模板",
            })
        existing_keys = {item["key"] for item in prompts}
        for key, value in sorted(settings_prompts.items()):
            if key not in existing_keys:
                prompts.append({
                    "key": key,
                    "name": PROMPT_DISPLAY_NAMES.get(key) or key,
                    "original_name": key,
                    "description": PROMPT_USAGE_NOTES.get(key) or "全局自定义提示词",
                    "example": PROMPT_EXAMPLES.get(key) or "范文示例：这是自定义提示词，可在提示词正文中补充你期望的范文格式。",
                    "version": "custom",
                    "category": "当前生效" if key in {"chapter_writer", "outliner", "manuscript_preface", "manuscript_conclusion", "manuscript_references"} else "自定义备用",
                    "default_template": "",
                    "current_template": str(value),
                    "is_customized": True,
                    "is_active": key in {"chapter_writer", "outliner", "manuscript_preface", "manuscript_conclusion", "manuscript_references"},
                    "path": "config/global_settings.json",
                })
        active_order = {
            "chapter_writer": 0,
            "outliner": 1,
            "manuscript_preface": 2,
            "manuscript_conclusion": 3,
            "manuscript_references": 4,
        }
        return sorted(prompts, key=lambda item: (active_order.get(item.get("key", ""), 99), item.get("key", "")))

    @classmethod
    def load_global_prompt(cls, prompt_key: str, default: str = "") -> str:
        """Load an editable global prompt by key, falling back to Chinese built-in defaults."""
        from libriscribe.services.global_settings_service import GlobalSettingsService

        key = cls.global_prompt_key(prompt_key)
        global_prompt = GlobalSettingsService().get_prompt(key, "")
        if global_prompt:
            return global_prompt
        return cls.load_builtin_template(key) or default

    @classmethod
    def load_outline_prompt(cls) -> str:
        """Load the global outline prompt used by AI outline generation."""
        return cls.load_global_prompt("outliner", DEFAULT_OUTLINE_PROMPT_TEMPLATE)

    @classmethod
    def load_chapter_prompt(cls, project_dir: str | Path | None = None) -> str:
        """Load the global chapter-writing prompt.

        project_dir is retained only for backwards compatibility; global settings now take priority and are not project-bound.
        """
        return cls.load_global_prompt("chapter_writer", DEFAULT_CHAPTER_PROMPT_TEMPLATE)

    @classmethod
    def save_chapter_prompt(cls, project_dir: str | Path | None, prompt_text: str) -> Path:
        from libriscribe.services.global_settings_service import GlobalSettingsService

        return GlobalSettingsService().save_prompt("chapter_writer", prompt_text)

    @classmethod
    def save_global_prompt(cls, prompt_key: str, prompt_text: str) -> Path:
        from libriscribe.services.global_settings_service import GlobalSettingsService

        return GlobalSettingsService().save_prompt(cls.global_prompt_key(prompt_key), prompt_text)

    @classmethod
    def reset_chapter_prompt(cls, project_dir: str | Path | None = None) -> Path:
        from libriscribe.services.global_settings_service import GlobalSettingsService

        return GlobalSettingsService().reset_prompt("chapter_writer")

    @classmethod
    def reset_global_prompt(cls, prompt_key: str) -> Path:
        from libriscribe.services.global_settings_service import GlobalSettingsService

        return GlobalSettingsService().reset_prompt(cls.global_prompt_key(prompt_key))

    @staticmethod
    def prompt_analysis_guide() -> str:
        return PROMPT_ANALYSIS_GUIDE

    @staticmethod
    def builtin_playbooks() -> list[dict]:
        """Return the built-in commercial writing playbooks.

        Each playbook describes a repeatable production workflow for a specific
        book/document type. The dictionaries are deliberately plain JSON-like
        structures so they can be rendered directly in the UI or serialized by
        future service layers.
        """
        return [
            {
                "id": "academic_monograph",
                "name": "学术专著",
                "description": "面向严肃学术研究、博士后成果、课题结项与出版社专著的长篇写作流程。",
                "target_users": ["高校教师", "科研人员", "博士/博士后", "学术编辑"],
                "workflow": [
                    "明确研究对象、核心问题与理论框架",
                    "整理文献资料并建立证据链",
                    "生成章节目次与四级大纲",
                    "逐章撰写正文并绑定引用来源",
                    "执行术语、结构、引用与反幻觉审校",
                    "导出 DOCX/PDF/LaTeX 与参考文献",
                ],
                "prompt_focus": [
                    "学术概念界定清晰",
                    "论证链条完整",
                    "事实性陈述必须依托资料证据",
                    "保持专著体例、章节编号与学术语体",
                ],
                "quality_checks": ["文献覆盖率", "引用可追溯性", "术语一致性", "结构完整性", "学术表达规范"],
                "deliverables": ["完整专著稿", "参考文献", "引用核验清单", "出版前审校报告"],
            },
            {
                "id": "textbook",
                "name": "教材",
                "description": "面向课程建设、职业教育、培训课程与知识普及的教学型内容生产流程。",
                "target_users": ["高校教师", "职业院校教师", "培训机构", "课程研发团队"],
                "workflow": [
                    "定义学习对象、课程目标与能力要求",
                    "拆分知识模块、章节目标与教学重点",
                    "生成教材目录、知识点体系与学习路径",
                    "撰写正文、案例、例题、练习与小结",
                    "检查难度梯度、知识连贯性与教学可用性",
                    "导出教材稿、教师用书或课程配套资料",
                ],
                "prompt_focus": [
                    "围绕学习目标组织内容",
                    "语言清晰易懂且符合教学场景",
                    "每章包含导学、正文、案例、练习与总结",
                    "知识点难度循序渐进",
                ],
                "quality_checks": ["教学目标匹配", "知识点覆盖", "难度梯度", "案例适配度", "练习题有效性"],
                "deliverables": ["教材正文", "章节习题", "教学案例", "课程大纲", "教学质量检查报告"],
            },
            {
                "id": "industry_whitepaper",
                "name": "行业白皮书",
                "description": "面向企业研究、市场洞察、产业分析与品牌内容发布的专业白皮书流程。",
                "target_users": ["企业战略部门", "咨询顾问", "行业研究员", "市场与品牌团队"],
                "workflow": [
                    "确定行业范围、目标读者与核心观点",
                    "汇总市场数据、政策资料、案例与竞争格局",
                    "构建趋势判断、问题诊断与机会分析框架",
                    "撰写摘要、洞察章节、案例分析与行动建议",
                    "核验数据来源、图表口径与商业表述风险",
                    "导出白皮书正文、执行摘要与传播素材",
                ],
                "prompt_focus": [
                    "结论先行，突出洞察与趋势判断",
                    "数据、案例和观点来源清晰",
                    "兼顾专业性、可读性和商业传播价值",
                    "避免夸大、绝对化或无依据的市场判断",
                ],
                "quality_checks": ["数据来源可靠性", "观点证据匹配", "行业术语一致", "商业风险表述", "摘要传播性"],
                "deliverables": ["行业白皮书", "执行摘要", "关键洞察清单", "图表说明", "发布前风险检查报告"],
            },
            {
                "id": "policy_research",
                "name": "政策研究",
                "description": "面向政府咨询、智库研究、政策评估与决策建议的研究报告流程。",
                "target_users": ["智库研究员", "政府研究部门", "公共政策顾问", "课题组"],
                "workflow": [
                    "界定政策问题、研究边界与决策场景",
                    "收集政策文本、统计数据、案例和访谈资料",
                    "梳理现状、问题成因、比较经验与约束条件",
                    "形成政策选项、影响评估与实施路径",
                    "审校事实依据、政策口径、风险提示与可执行性",
                    "导出研究报告、决策摘要和政策建议清单",
                ],
                "prompt_focus": [
                    "问题导向和决策导向并重",
                    "政策依据、数据来源和案例证据可追溯",
                    "建议具体、可执行、可评估",
                    "保持客观审慎，避免未经证实的政策判断",
                ],
                "quality_checks": ["政策依据完整性", "问题诊断准确性", "建议可执行性", "风险评估", "决策摘要清晰度"],
                "deliverables": ["政策研究报告", "决策咨询摘要", "政策建议清单", "风险与实施评估", "依据材料索引"],
            },
        ]

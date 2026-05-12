# src/libriscribe/workflow/nodes.py
"""LangGraph 节点实现

实现工作流中的各个处理节点。
"""

import logging
from typing import Dict, Any
from pathlib import Path

from libriscribe.workflow.state import BookWritingState
from libriscribe.knowledge_base import ProjectKnowledgeBase
from libriscribe.utils.llm_client import LLMClient
from libriscribe.utils import prompts_context as prompts
from libriscribe.utils.file_utils import read_markdown_file, write_markdown_file
from libriscribe.utils.academic_prompt import ACADEMIC_MONOGRAPH_SYSTEM_PROMPT, finalize_academic_chapter
from libriscribe.rag.retriever import Retriever
from libriscribe.memory.terminology import TerminologyManager
from libriscribe.memory.summary_manager import SummaryManager
from libriscribe.settings import Settings

logger = logging.getLogger(__name__)


def planner_node(state: BookWritingState) -> Dict[str, Any]:
    """规划节点：初始化项目，准备章节计划"""
    logger.info(f"Planner: Starting project '{state['title']}'")
    return {
        "status": "planning",
        "current_chapter": 1,
        "iteration_count": 0,
        "messages": [f"开始规划项目: {state['title']}"]
    }


def research_node(state: BookWritingState) -> Dict[str, Any]:
    """研究节点：从 RAG 中检索相关资料"""
    logger.info(f"Research: Retrieving context for chapter {state['current_chapter']}")

    rag_context = ""
    try:
        retriever = Retriever()
        query = f"{state.get('chapter_title', '')}: {state.get('chapter_summary', '')}"
        if not query.strip():
            query = state.get('description', '')
        rag_context = retriever.get_context_for_prompt(query)
    except Exception as e:
        logger.warning(f"RAG retrieval failed: {e}")

    return {
        "rag_context": rag_context,
        "status": "writing",
        "messages": [f"第{state['current_chapter']}章: 完成资料检索"]
    }


def writer_node(state: BookWritingState) -> Dict[str, Any]:
    """写作节点：生成章节内容"""
    chapter_num = state['current_chapter']
    logger.info(f"Writer: Generating chapter {chapter_num}")

    try:
        settings = Settings()
        llm_provider = state.get('llm_provider', settings.default_llm)
        llm_client = LLMClient(llm_provider)
        if settings.cost_optimization:
            llm_client.set_model(settings.draft_model)

        # 构建上下文
        context_sections = []
        if state.get('previous_summaries'):
            context_sections.append(state['previous_summaries'])
        if state.get('terminology_context'):
            context_sections.append(state['terminology_context'])
        if state.get('rag_context'):
            context_sections.append(state['rag_context'])
        if state.get('style_guide'):
            context_sections.append(f"## 风格指南\n{state['style_guide']}")

        context = "\n\n".join(context_sections)
        human_feedback = ""
        if state.get('human_feedback'):
            human_feedback = f"\n\n## 人类反馈（请据此修改）\n{state['human_feedback']}"

        prompt = f"""{ACADEMIC_MONOGRAPH_SYSTEM_PROMPT}

## 项目信息
- 标题: {state['title']}
- 类型: {state['genre']}
- 类别: {state['category']}
- 语言: {state['language']}

## 当前章节
- 章节号: 第{chapter_num}章
- 章节标题: {state.get('chapter_title', f'Chapter {chapter_num}')}
- 章节摘要: {state.get('chapter_summary', '')}

## 上下文与参考资料
{context}
{human_feedback}

请生成完整章节内容。必须按强制规范版提示词完成资料分类、正文写作、50分制自评；若低于80分（40/50），自动重写一次，只输出最终通过版本。不得编造数据、案例、文献、法规、标准编号、人名、机构名、时间、地点；不得输出“请搜索”“请查询”“详见某网页”等虚假操作表述；信息不足时必须输出“【信息缺失】需要您提供……”。"""

        content = llm_client.generate_content(prompt, max_tokens=9000, temperature=0.6)
        if not content:
            return {"error": "Failed to generate chapter content", "messages": [f"第{chapter_num}章: 生成失败"]}

        content, _, _ = finalize_academic_chapter(content, target_words=state.get('target_word_count', 0) or 0)
        return {
            "chapter_content": content,
            "status": "reviewing",
            "iteration_count": state.get('iteration_count', 0) + 1,
            "human_feedback": "",
            "messages": [f"第{chapter_num}章: 内容生成完成 (迭代 {state.get('iteration_count', 0) + 1})"]
        }
    except Exception as e:
        logger.error(f"Writer error: {e}")
        return {"error": str(e), "messages": [f"第{chapter_num}章: 写作错误 - {str(e)}"]}


def critic_node(state: BookWritingState) -> Dict[str, Any]:
    """评审节点：检查章节质量"""
    import json, re
    chapter_num = state['current_chapter']
    logger.info(f"Critic: Reviewing chapter {chapter_num}")

    try:
        settings = Settings()
        llm_client = LLMClient(state.get('llm_provider', settings.default_llm))
        content = state.get('chapter_content', '')
        if not content:
            return {"review_result": {"score": 0, "issues": ["No content"]}, "messages": [f"第{chapter_num}章: 无内容"]}

        prompt = f"""评审以下章节，输出 JSON：
{{"score": 0.85, "issues": [], "suggestions": []}}

术语表: {state.get('terminology_context', '无')}

内容: {content[:3000]}"""

        response = llm_client.generate_content(prompt, max_tokens=1000, temperature=0.3)
        review_result = {"score": 0.5, "issues": [], "suggestions": []}
        try:
            if "```json" in response:
                start = response.find("```json") + 7
                end = response.find("```", start)
                review_result = json.loads(response[start:end].strip())
            else:
                review_result = json.loads(response)
        except:
            score_match = re.search(r'"?score"?\s*[:=]\s*(0?\.\d+|1\.0)', response)
            if score_match:
                review_result["score"] = float(score_match.group(1))

        return {"review_result": review_result, "messages": [f"第{chapter_num}章: 评审完成, 评分: {review_result.get('score', 0):.2f}"]}
    except Exception as e:
        logger.error(f"Critic error: {e}")
        return {"review_result": {"score": 0, "issues": [str(e)]}, "messages": [f"第{chapter_num}章: 评审错误"]}


def editor_node(state: BookWritingState) -> Dict[str, Any]:
    """编辑节点：根据评审结果润色章节"""
    chapter_num = state['current_chapter']
    logger.info(f"Editor: Polishing chapter {chapter_num}")
    try:
        settings = Settings()
        llm_client = LLMClient(state.get('llm_provider', settings.default_llm))
        if settings.cost_optimization:
            llm_client.set_model(settings.polish_model)

        content = state.get('chapter_content', '')
        review = state.get('review_result', {})
        issues = review.get('issues', [])
        suggestions = review.get('suggestions', [])
        feedback = "\n".join(f"- {i}" for i in issues + suggestions)

        prompt = f"""{ACADEMIC_MONOGRAPH_SYSTEM_PROMPT}

根据反馈润色章节，必须保持强制规范版专著格式、两个全角空格首行缩进、参考文献/内部资料分类、50分制自评。不得编造数据、案例、文献、法规、标准编号；不得输出“请搜索”“请查询”“详见某网页”等虚假操作表述；信息不足时必须输出“【信息缺失】需要您提供……”。
反馈: {feedback}
术语表: {state.get('terminology_context', '无')}

原文:
{content}

输出润色后的完整内容；若自评低于80分，自动重写一次，只输出最终通过版本。"""

        edited = llm_client.generate_content(prompt, max_tokens=9000, temperature=0.5)
        if not edited:
            return {"messages": [f"第{chapter_num}章: 编辑失败"]}

        edited, _, _ = finalize_academic_chapter(
            edited,
            target_words=state.get('target_word_count', 0) or 0,
        )
        return {"chapter_content": edited, "status": "completed", "messages": [f"第{chapter_num}章: 润色完成"]}
    except Exception as e:
        logger.error(f"Editor error: {e}")
        return {"messages": [f"第{chapter_num}章: 编辑错误"]}


def human_review_node(state: BookWritingState) -> Dict[str, Any]:
    """人工审核节点"""
    return {"status": "reviewing", "needs_human_review": True, "messages": [f"第{state['current_chapter']}章: 等待人工审核"]}


def save_chapter_node(state: BookWritingState) -> Dict[str, Any]:
    """保存节点"""
    chapter_num = state['current_chapter']
    try:
        project_dir = Path(state.get('project_dir', 'projects')) / state['project_name']
        project_dir.mkdir(parents=True, exist_ok=True)
        chapter_path = project_dir / f"chapter_{chapter_num}.md"
        write_markdown_file(str(chapter_path), state.get('chapter_content', ''))
        return {"messages": [f"第{chapter_num}章: 已保存"]}
    except Exception as e:
        return {"error": str(e), "messages": [f"第{chapter_num}章: 保存错误"]}


def next_chapter_node(state: BookWritingState) -> Dict[str, Any]:
    """下一章节点"""
    current = state['current_chapter']
    total = state['total_chapters']
    if current >= total:
        return {"status": "completed", "messages": ["所有章节已完成！"]}
    return {
        "current_chapter": current + 1,
        "iteration_count": 0,
        "chapter_content": "",
        "review_result": {},
        "human_feedback": "",
        "status": "writing",
        "messages": [f"进入第{current + 1}章"]
    }
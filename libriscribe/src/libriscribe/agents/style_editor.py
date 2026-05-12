# src/libriscribe/agents/style_editor.py

import logging
from pathlib import Path

from libriscribe.agents.agent_base import Agent
from libriscribe.utils.llm_client import LLMClient
from libriscribe.utils.file_utils import read_markdown_file, write_markdown_file, read_json_file, extract_json_from_markdown
from libriscribe.utils.academic_prompt import ACADEMIC_MONOGRAPH_SYSTEM_PROMPT, finalize_academic_chapter

from libriscribe.knowledge_base import ProjectKnowledgeBase
from rich.console import Console
console = Console()
logger = logging.getLogger(__name__)
class StyleEditorAgent(Agent):
    """Refines the writing style of a chapter."""

    def __init__(self, llm_client: LLMClient):
        super().__init__("StyleEditorAgent", llm_client)
        self.llm_client = llm_client

    def execute(self, project_knowledge_base: ProjectKnowledgeBase, chapter_number: int) -> None:
        """Refines style based on project settings."""
        proj_dir = project_knowledge_base.project_dir
        if not proj_dir:
            self.logger.error("project_dir is not set. Please save the project first.")
            return
        chapter_path = str(Path(proj_dir) / f"chapter_{chapter_number}.md")
        chapter_content = read_markdown_file(chapter_path)
        if not chapter_content:
            self.logger.error("Chapter file is empty or not found: %s", chapter_path)
            return

        # Get tone and target_audience with default values if not present
        tone = getattr(project_knowledge_base, 'tone', 'Informative')
        target_audience = getattr(project_knowledge_base, 'target_audience', 'General')
        
        console.print("[cyan]Polishing writing style for Chapter %d...[/cyan]" % chapter_number)
        prompt = f"""{ACADEMIC_MONOGRAPH_SYSTEM_PROMPT}

        你是学术专著风格编辑。请在不改变事实依据、论证结构和章节编号的前提下润色以下章节全文。

        Target Tone: {tone}
        Target Audience: {target_audience}
        Language: {project_knowledge_base.language}

        必须保持两个全角空格首行缩进、参考文献/内部资料分类规则、本章参考文献、本章术语表与50分制自评（百分制≥80通过）。若自评低于80分，自动重写一次，只输出最终通过版本。不得编造数据、案例、文献、法规、标准编号、人名、机构名、时间、地点；不得输出"请搜索""请查询""详见某网页"等虚假操作表述；信息不足时必须明确写出"【信息缺失】需要您提供……"。

        Chapter Excerpt:
        ---
        {chapter_content}
        ---
        """
        try:
            response = self.llm_client.generate_content(prompt, max_tokens=3000)
            
            # Extract the revised content from the response
            if "```" in response:
                start = response.find("```") + 3
                end = response.rfind("```")
                
                # Skip the language identifier if present (e.g., ```markdown)
                next_newline = response.find("\n", start)
                if next_newline < end and next_newline != -1:
                    start = next_newline + 1
                
                revised_text = response[start:end].strip()
            else:
                # If no code blocks, try to extract the content after a leading explanation
                lines = response.split("\n")
                content_start = 0
                for i, line in enumerate(lines):
                    if line.startswith("#") or line.startswith("Chapter"):
                        content_start = i
                        break
                
                if content_start > 0:
                    revised_text = "\n".join(lines[content_start:])
                else:
                    revised_text = response
            
            if revised_text:
                revised_text, _, _ = finalize_academic_chapter(
                    revised_text,
                    target_words=getattr(project_knowledge_base.chapters.get(chapter_number), "word_count", 0) if getattr(project_knowledge_base, "chapters", None) else 0,
                )
                write_markdown_file(chapter_path, revised_text)
                console.print("[green]Style improvements applied to Chapter %d![/green]" % chapter_number)
            else:
                self.logger.error("Could not extract revised text for %s.", chapter_path)
                self.logger.error(f"Could not extract from StyleEditor response for {chapter_path}.")

        except Exception as e:
            self.logger.exception(f"Error during style editing for {chapter_path}: {e}")
            self.logger.error("Failed to edit style for chapter %s. See log.", chapter_path)
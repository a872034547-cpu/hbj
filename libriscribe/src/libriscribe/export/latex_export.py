# src/libriscribe/export/latex_export.py
"""LaTeX 导出"""

import logging
import re
import subprocess
from pathlib import Path
from typing import List
from libriscribe.settings import Settings
from libriscribe.utils.chinese_labels import format_chapter_label, strip_leading_chapter_heading

logger = logging.getLogger(__name__)


class LatexExporter:
    def __init__(self):
        settings = Settings()
        self.pandoc_path = settings.pandoc_path

    def export(self, chapters: List[dict], output_path: str, title="", author="", genre="", language="English", compile_pdf=False):
        latex = self._generate_latex(chapters, title, author, genre, language)
        tex_path = output_path if output_path.endswith('.tex') else output_path + '.tex'
        Path(tex_path).parent.mkdir(parents=True, exist_ok=True)
        with open(tex_path, 'w', encoding='utf-8') as f:
            f.write(latex)
        logger.info(f"LaTeX exported to: {tex_path}")
        if compile_pdf:
            self._compile_pdf(tex_path, tex_path.replace('.tex', '.pdf'))

    def _generate_latex(self, chapters, title, author, genre, language):
        lang_opt = "\n\\usepackage[UTF8]{ctex}" if language.lower() in ["chinese", "中文", "简体中文"] else ""
        latex = f"""\\documentclass[12pt,a4paper]{{book}}
\\usepackage[utf8]{{inputenc}}
\\usepackage[T1]{{fontenc}}
\\usepackage{{lmodern}}
\\usepackage{{geometry}}
\\usepackage{{hyperref}}
{lang_opt}
\\geometry{{margin=2.5cm}}
\\title{{{self._esc(title)}}}
\\author{{{self._esc(author)}}}
\\date{{}}
\\begin{{document}}
\\maketitle
\\tableofcontents
\\newpage
"""
        for ch in chapters:
            number = ch.get('number') or ch.get('chapter_number')
            if number:
                if int(number) < 1:
                    raise ValueError(f"Invalid chapter number for LaTeX export: {number}")
                title = ch.get('display_title') or format_chapter_label(number, ch.get('title', ''))
                content = self._strip_leading_chapter_heading(ch.get('content', ''), number, ch.get('title', ''))
            else:
                title = ch.get('display_title') or ch.get('title', '未命名部分')
                content = self._strip_leading_part_heading(ch.get('content', ''), title)
            latex += f"\\chapter*{{{self._esc(title)}}}\n\\addcontentsline{{toc}}{{chapter}}{{{self._esc(title)}}}\n\n"
            latex += self._md2tex(content)
            latex += "\n\n"
        latex += "\\end{document}\n"
        return latex

    def _strip_leading_chapter_heading(self, content, number, title):
        return strip_leading_chapter_heading(content, number, title)

    def _strip_leading_part_heading(self, content, title):
        pattern = rf"^\s*#{{1,6}}\s*{re.escape(str(title).strip())}\s*\n+"
        return re.sub(pattern, "", str(content or ""), count=1)

    def _md2tex(self, content):
        lines = content.split('\n')
        out = []
        in_code = False
        for line in lines:
            if line.strip().startswith('```'):
                out.append('\\end{verbatim}' if in_code else '\\begin{verbatim}')
                in_code = not in_code
                continue
            if in_code:
                out.append(self._esc(line))
                continue
            if line.startswith('### '):
                out.append(f'\\subsubsection{{{self._esc(line[4:])}}}')
            elif line.startswith('## '):
                out.append(f'\\subsection{{{self._esc(line[3:])}}}')
            elif line.startswith('# '):
                out.append(f'\\section{{{self._esc(line[2:])}}}')
            elif not line.strip():
                out.append('')
            else:
                t = re.sub(r'\*\*(.*?)\*\*', r'\\textbf{\1}', line)
                t = re.sub(r'\*(.*?)\*', r'\\textit{\1}', t)
                out.append(self._esc(t))
        return '\n'.join(out)

    def _esc(self, text):
        for c, e in [('\\', '\\textbackslash{}'), ('&', '\\&'), ('%', '\\%'), ('$', '\\$'), ('#', '\\#'), ('_', '\\_'), ('{', '\\{'), ('}', '\\}')]:
            text = text.replace(c, e)
        return text

    def _compile_pdf(self, tex_path, pdf_path):
        try:
            r = subprocess.run([self.pandoc_path, tex_path, '-o', pdf_path, '--pdf-engine=xelatex'], capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                logger.info(f"PDF compiled: {pdf_path}")
            else:
                logger.error(f"PDF compilation failed: {r.stderr}")
        except Exception as e:
            logger.error(f"PDF compilation error: {e}")

    def export_from_project(self, project_dir, output_path, title="", author="", genre="", language="English", compile_pdf=False):
        from libriscribe.utils.file_utils import get_chapter_files, read_markdown_file
        chapter_files = get_chapter_files(project_dir)
        chapters = []
        for i, cf in enumerate(chapter_files, 1):
            content = read_markdown_file(cf)
            m = re.search(r'^#+\s*(.+)$', content, re.MULTILINE)
            chapters.append({"number": i, "title": m.group(1) if m else f"Chapter {i}", "content": content})
        self.export(chapters, output_path, title, author, genre, language, compile_pdf)

import json
import re
from pathlib import Path

base = Path('projects/cs0511')
kb = json.load(open(base / 'knowledge_base.json', encoding='utf-8'))
data = {'title': kb.get('title', '人工智能赋能高职图书馆阅读推广研究'), 'author': '', 'chapters': []}

for md in sorted(base.glob('chapter_*.md'), key=lambda p: int(re.search(r'chapter_(\d+)', p.name).group(1))):
    lines = md.read_text(encoding='utf-8').splitlines()
    ch = None
    sec = None
    sub = None
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith('# '):
            ch = {'heading': s[2:].strip(), 'sections': [], 'references': []}
            data['chapters'].append(ch)
            sec = None
            sub = None
        elif s.startswith('## ') and ch is not None:
            title = s[3:].strip()
            if title == '本章小结' or '参考文献' in title:
                sec = None
                sub = None
                continue
            sec = {'heading': title, 'content': [], 'subsections': []}
            ch['sections'].append(sec)
            sub = None
        elif s.startswith('### ') and sec is not None:
            sub = {'heading': s[4:].strip(), 'content': []}
            sec['subsections'].append(sub)
        elif s.startswith('#### ') and sec is not None:
            sub = {'heading': s[5:].strip(), 'content': []}
            sec['subsections'].append(sub)
        else:
            text = s.lstrip('\u3000 ')
            if ch is None:
                continue
            if text.startswith('- [') or re.match(r'^\[\d+\]', text):
                ch['references'].append(text)
            elif sub is not None:
                sub['content'].append(text)
            elif sec is not None:
                sec['content'].append(text)
            else:
                ch.setdefault('content', []).append(text)

out = base / 'exports' / '人工智能赋能高职图书馆阅读推广研究_structured.json'
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
print(out)
print('chapters', len(data['chapters']))
print('sections', sum(len(c.get('sections', [])) for c in data['chapters']))

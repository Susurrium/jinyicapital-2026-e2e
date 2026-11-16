from pathlib import Path
from urllib.parse import unquote

from markdown_it import MarkdownIt


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "docs" / "比赛规则与流程.md"
content = PATH.read_text(encoding="utf-8")
parser = MarkdownIt("commonmark").enable("table")
environment = {}
tokens = parser.parse(content, environment)

headings = []
links = []
for index, token in enumerate(tokens):
    if token.type == "heading_open":
        headings.append(tokens[index + 1].content)
    for child in token.children or []:
        if child.type == "link_open":
            links.append(child.attrGet("href"))

assert headings[0] == "进益资本杯 2026：端到端赛道规则与流程"
assert len([token for token in tokens if token.type == "heading_open" and token.tag == "h2"]) == 14
assert len([token for token in tokens if token.type == "table_open"]) >= 15
assert all(token.content.endswith("\n") for token in tokens if token.type == "fence")
assert environment.get("references")
assert not environment.get("duplicate_refs")
assert "报名" not in content
assert "奖金" not in content
assert "10 月 29 日 23:59:59" in content
assert "10 月 30 日 23:59:59" in content
assert "13. 尚待确认的规则细节" in headings
assert "条款正文未完整读取" in content
for link in links:
    if link.startswith("E:/"):
        assert Path(unquote(link)).exists(), link
    else:
        assert link.startswith("https://"), link

print(f"已检查 UTF-8 文本、14 个主章节、Markdown 表格与链接：{PATH}")
print(f"字符数：{len(content)}；链接数：{len(links)}")

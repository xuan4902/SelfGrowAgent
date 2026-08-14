"""知识语料加载与分块。

语料位于 data/knowledge/{domain}/*.md；按 `## ` 二级标题分块，
保证每个 chunk 语义完整且长度适中（便于 embedding 与检索）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from selfgrow.paths import KNOWLEDGE_DIR


@dataclass
class Chunk:
    doc_id: str          # 块 id：{file_stem}#{section}
    title: str           # 文档标题（一级标题）
    section: str         # 二级标题
    content: str         # 该节正文

    def to_text(self) -> str:
        return f"{self.title}｜{self.section}\n{self.content}"


def load_document(path: Path) -> tuple[str, str]:
    """返回 (title, text)。"""
    text = path.read_text(encoding="utf-8")
    title = path.stem
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    return title, text


def chunk_text(text: str, min_chars: int = 80, max_chars: int = 900) -> list[tuple[str, str]]:
    """按 ## 标题分块，返回 [(section, content)]；无标题部分归入『概述』。"""
    blocks: list[tuple[str, list[str]]] = []
    current = ("概述", [])
    for line in text.splitlines():
        if line.startswith("## "):
            if current[1]:
                blocks.append(current)
            current = (line[3:].strip(), [])
        elif line.startswith("# "):
            continue
        else:
            current[1].append(line)
    if current[1]:
        blocks.append(current)

    result: list[tuple[str, str]] = []
    for section, lines in blocks:
        content = "\n".join(lines).strip()
        # 极长节按段落再切，极短节合并到概述
        if len(content) > max_chars:
            buf = ""
            for para in content.split("\n\n"):
                if buf and len(buf) + len(para) > max_chars:
                    result.append((section, buf.strip()))
                    buf = ""
                buf += (para + "\n\n")
            if buf.strip():
                result.append((section, buf.strip()))
        elif content and len(content) >= min_chars:
            result.append((section, content))
    return result


def load_corpus(domain: str) -> list[Chunk]:
    """加载某领域全部语料并分块。"""
    dir_path = KNOWLEDGE_DIR / domain
    if not dir_path.exists():
        return []
    chunks: list[Chunk] = []
    for path in sorted(dir_path.glob("*.md")):
        title, text = load_document(path)
        for section, content in chunk_text(text):
            doc_id = f"{path.stem}#{section}"
            chunks.append(Chunk(doc_id=doc_id, title=title, section=section, content=content))
    return chunks

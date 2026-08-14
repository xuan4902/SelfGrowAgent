"""节点共享运行时：领域、LLM、知识库、数据库、能力框架。"""

from __future__ import annotations

from dataclasses import dataclass

from selfgrow.competency.models import CompetencyFramework
from selfgrow.competency.loader import load_framework
from selfgrow.llm.base import get_llm, LLMProvider
from selfgrow.rag.knowledge_base import KnowledgeBase
from selfgrow.storage.db import Database

DEFAULT_DOMAIN = "managing_up"


@dataclass
class Runtime:
    domain: str
    llm: LLMProvider
    kb: KnowledgeBase
    db: Database
    framework: CompetencyFramework


def default_runtime(
    domain: str = DEFAULT_DOMAIN,
    db: Database | None = None,
    kb: KnowledgeBase | None = None,
) -> Runtime:
    """构造默认运行时：LLM 自动选择（Mock/Claude），知识库就地构建，DB 可注入。"""
    framework = load_framework(domain)
    kb = kb or KnowledgeBase(domain=domain)
    if not kb.count():
        kb.build()
    db = db or Database()
    return Runtime(
        domain=domain,
        llm=get_llm(),
        kb=kb,
        db=db,
        framework=framework,
    )

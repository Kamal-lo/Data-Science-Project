"""Sous-package T42 : gabarits et prompts structurés des 6 sections du mémoire technique."""

from rag_module.templates.prompt_builder import PromptBuilder
from rag_module.templates.sections import (
    SECTION_TEMPLATES,
    get_all_section_templates,
    get_section_template,
)

__all__ = [
    "PromptBuilder",
    "SECTION_TEMPLATES",
    "get_all_section_templates",
    "get_section_template",
]

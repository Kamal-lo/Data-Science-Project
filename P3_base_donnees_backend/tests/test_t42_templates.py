"""Tests unitaires et d'intégration pour T42 : Gabarits et prompts des 6 sections."""

from __future__ import annotations

from rag_module.schemas import BuildPromptRequest, LanguageCode, SectionId
from rag_module.templates.prompt_builder import PromptBuilder
from rag_module.templates.sections import get_all_section_templates, get_section_template


def test_all_six_section_templates_exist_and_are_ordered():
    templates = get_all_section_templates()
    assert len(templates) == 6
    assert [t.order for t in templates] == [1, 2, 3, 4, 5, 6]
    for tpl in templates:
        assert tpl.title_fr
        assert tpl.title_ar
        assert len(tpl.required_subsections) >= 3
        assert len(tpl.preferred_doc_types) >= 1
        assert any("[SRC-i]" in rule for rule in tpl.anti_hallucination_rules)
        assert any("DONNÉE MANQUANTE" in rule for rule in tpl.anti_hallucination_rules)


def test_prompt_builder_end_to_end_for_all_6_sections(rag_stack, sample_dce_context):
    pipeline = rag_stack["pipeline"]
    company_id = rag_stack["company_id"]
    builder = PromptBuilder()

    for section_id in SectionId:
        req = BuildPromptRequest(
            company_id=company_id,
            company_name="Atlas Cloud & Systèmes SARL",
            dce_context=sample_dce_context,
            language=LanguageCode.FR,
            top_k=4,
            strict_doc_type_filter=False,
        )
        rendered, retrieval = builder.retrieve_and_build_prompt(
            pipeline=pipeline,
            section_id=section_id,
            request=req,
        )

        tpl = get_section_template(section_id)
        assert rendered.section_id == section_id
        assert rendered.section_order == tpl.order
        assert len(rendered.sources) >= 1
        assert len(retrieval.results) == len(rendered.sources)
        assert "[SRC-1]" in rendered.user_prompt
        assert sample_dce_context.reference_ao in rendered.user_prompt
        assert "DONNÉE MANQUANTE À COMPLÉTER PAR L'ENTREPRISE" in rendered.system_prompt
        for sub in tpl.required_subsections:
            assert sub.code in rendered.user_prompt


def test_prompt_builder_warns_when_no_sources_found(sample_dce_context):
    builder = PromptBuilder()
    rendered = builder.render_section_prompt(
        section_id=SectionId.MOYENS_HUMAINS,
        dce_context=sample_dce_context,
        retrieved_chunks=[],
        language=LanguageCode.BILINGUAL,
    )
    assert rendered.sources == []
    assert len(rendered.warnings) == 1
    assert "Aucune source entreprise" in rendered.warnings[0]
    assert "Français / Arabe" in rendered.system_prompt
    assert "[AUCUNE SOURCE ENTREPRISE DISPONIBLE" in rendered.user_prompt

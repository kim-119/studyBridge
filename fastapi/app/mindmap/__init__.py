"""Semantic Learning Concept Map (AI07).

LLM answer text -> semantic concept graph. Pipeline:
  extractor.extract_candidates  (LLM structured output | deterministic noun-phrase chunking)
  concept_text.normalize_surface (surface form -> canonical concept, e.g. "JDBC가" -> "JDBC")
  concept_text.validate_concept  (deterministic: rejects particles/predicates/adverbs/fillers/artifacts)
  graph_builder.build_semantic_graph (dedupe -> relation -> hierarchy -> budget -> graph validation)
"""
from app.mindmap.graph_builder import build_semantic_graph, validate_graph  # noqa: F401

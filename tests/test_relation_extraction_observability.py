import logging

import networkx as nx

import graph.entity_extractor as entity_extractor_module
from graph.entity_extractor import EntityExtractor
from graph.persistent import (
    GraphArtifactStore,
    InMemoryObjectStore,
    ManifestStore,
    PersistentGraphPipeline,
    deserialize_graph,
)


_TEXT = "Alpha Corporation explicitly collaborates with Beta Institute on a research programme with shared outcomes."
_ENTITIES = [("Alpha Corporation", "ORG"), ("Beta Institute", "ORG")]


class _Provider:
    active_provider = "fake"

    def __init__(self, response):
        self.response = response
        self.calls = 0

    def call_llm(self, system_prompt, prompt):
        del system_prompt, prompt
        self.calls += 1
        return self.response


class _UnavailableProvider:
    def resolve_chain(self):
        return []

    def call_llm(self, system_prompt, prompt):
        del system_prompt, prompt
        raise AssertionError("an unavailable provider must not be called")


class _MalformedLlmClient:
    def extract_relations(self, chunk_text, entities):
        del chunk_text, entities
        return [None, {"head": "Alpha Corporation", "tail": "Beta Institute"}]


class _FailingProvider:
    active_provider = "failing"

    def call_llm(self, system_prompt, prompt):
        del system_prompt, prompt
        raise OSError("simulated transport failure")


class _GraphBuilder:
    def build_graph(self, chunks, embeddings, entities, relations):
        del chunks, embeddings, entities, relations
        return nx.Graph()


class _Detector:
    def detect(self, graph):
        return graph, [], {}, 0.0


def _extractor(monkeypatch, provider=None):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(entity_extractor_module.spacy, "load", lambda _: object())
    return EntityExtractor(provider_router=provider)


def test_unavailable_provider_uses_spacy_only_relation_fallback(monkeypatch):
    extractor = _extractor(monkeypatch, _UnavailableProvider())

    relations = extractor.extract_relations_llm(_TEXT, _ENTITIES)

    assert relations == [{
        "head": "Alpha Corporation",
        "relation": "co-occurs_with",
        "tail": "Beta Institute",
        "source": "rule-based",
    }]
    assert extractor.relation_extraction_mode == "spacy-only"


def test_no_relation_candidates_are_reported_as_unavailable(monkeypatch):
    extractor = _extractor(monkeypatch)

    assert extractor.extract_relations_llm(_TEXT, _ENTITIES[:1]) == []
    assert extractor.relation_extraction_mode == "unavailable"


def test_malformed_injected_llm_client_relations_warn_and_use_fallback(monkeypatch, caplog):
    extractor = _extractor(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="graph.entity_extractor"):
        relations = extractor.extract_relations_llm(_TEXT, _ENTITIES, llm_client=_MalformedLlmClient())

    assert relations == [{
        "head": "Alpha Corporation",
        "relation": "co-occurs_with",
        "tail": "Beta Institute",
        "source": "rule-based",
    }]
    assert extractor.relation_extraction_mode == "spacy-only"
    assert any("Skipping malformed LLM relation" in record.message for record in caplog.records)


def test_provider_transport_error_warns_and_uses_spacy_only_fallback(monkeypatch, caplog):
    extractor = _extractor(monkeypatch, _FailingProvider())

    with caplog.at_level(logging.WARNING, logger="graph.entity_extractor"):
        relations = extractor.extract_relations_llm(_TEXT, _ENTITIES)

    assert relations == [{
        "head": "Alpha Corporation",
        "relation": "co-occurs_with",
        "tail": "Beta Institute",
        "source": "rule-based",
    }]
    assert extractor.relation_extraction_mode == "spacy-only"
    assert any("Relation provider call failed" in record.message for record in caplog.records)


def test_available_provider_marks_llm_enhanced_and_persists_mode(monkeypatch):
    provider = _Provider(
        '{"relations":[{"head":"Alpha Corporation","relation":"collaborates_with","tail":"Beta Institute"}]}'
    )
    extractor = _extractor(monkeypatch, provider)
    chunks = [{"chunk_id": 0, "chunk_uid": "paper:0", "text": _TEXT}]
    extractor.extract_entities = lambda _: ({"paper:0": _ENTITIES}, [
        {"chunk_id": 0, "chunk_uid": "paper:0", "text": "Alpha Corporation", "label": "ORG"},
        {"chunk_id": 0, "chunk_uid": "paper:0", "text": "Beta Institute", "label": "ORG"},
    ])
    objects = InMemoryObjectStore()
    manifests = ManifestStore(objects, collection="papers")
    artifacts = GraphArtifactStore(objects, collection="papers")
    pipeline = PersistentGraphPipeline("papers", manifests=manifests, artifacts=artifacts)

    result = pipeline.build_and_publish(
        chunks,
        [[1.0, 0.0]],
        "paper",
        entity_extractor=extractor,
        graph_builder=_GraphBuilder(),
        detector=_Detector(),
    )
    artifact = deserialize_graph(artifacts.read(result["artifact_key"], result["artifact_digest"]))

    assert result["status"] == "available"
    assert provider.calls == 1
    assert artifact["diagnostics"]["relation_extraction"]["mode"] == "llm-enhanced"
    assert artifact["raw_evidence"][0]["source"] == "fake"
    assert artifact["active_evidence"] == artifact["raw_evidence"]


def test_malformed_provider_relations_warn_and_never_enter_raw_evidence(monkeypatch, caplog):
    provider = _Provider(
        '{"relations":[null,{"head":"Alpha Corporation","tail":"Beta Institute"},'
        '{"head":"Alpha Corporation","relation":"collaborates_with","tail":7}]}'
    )
    extractor = _extractor(monkeypatch, provider)
    chunks = [{"chunk_id": 0, "chunk_uid": "paper:0", "text": _TEXT}]
    extractor.extract_entities = lambda _: ({"paper:0": _ENTITIES}, [
        {"chunk_id": 0, "chunk_uid": "paper:0", "text": "Alpha Corporation", "label": "ORG"},
        {"chunk_id": 0, "chunk_uid": "paper:0", "text": "Beta Institute", "label": "ORG"},
    ])

    with caplog.at_level(logging.WARNING, logger="graph.entity_extractor"):
        from graph.persistent import build_document_graph

        _, details = build_document_graph(
            chunks,
            [[1.0, 0.0]],
            "paper",
            entity_extractor=extractor,
            graph_builder=_GraphBuilder(),
            detector=_Detector(),
        )

    assert extractor.relation_extraction_mode == "spacy-only"
    assert all(relation["source"] == "rule-based" for relation in details["raw_evidence"])
    assert details["active_evidence"] == []
    assert any("Skipping malformed LLM relation" in record.message for record in caplog.records)

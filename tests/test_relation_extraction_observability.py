import logging

import networkx as nx

import graph.entity_extractor as entity_extractor_module
from graph.entity_extractor import EntityExtractor
from graph.persistent import (
    GraphArtifactStore,
    InMemoryObjectStore,
    ManifestStore,
    PersistentGraphPipeline,
    build_document_graph,
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


class _PositionedFallbackExtractor:
    relation_extraction_mode = "spacy-only"

    def __init__(self, mentions):
        self.mentions = mentions

    def extract_entities(self, chunks):
        chunk_uid = chunks[0]["chunk_uid"]
        return {chunk_uid: _ENTITIES}, self.mentions

    def extract_relations_llm(self, chunk_text, entities):
        del chunk_text, entities
        return [{
            "head": "Alpha Corporation",
            "relation": "co-occurs_with",
            "tail": "Beta Institute",
            "source": "rule-based",
        }]


class _Sentence:
    def __init__(self, start_char, end_char):
        self.start_char = start_char
        self.end_char = end_char


class _Entity:
    def __init__(self, text, label, start_char, end_char, sentence):
        self.text = text
        self.label_ = label
        self.start_char = start_char
        self.end_char = end_char
        self.sent = sentence


class _Doc:
    def __init__(self, entities, sentences):
        self.ents = entities
        self.sents = sentences


class _Nlp:
    def __init__(self, doc):
        self.doc = doc

    def __call__(self, text):
        del text
        return self.doc


def _extractor(monkeypatch, provider=None):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(entity_extractor_module.spacy, "load", lambda _: object())
    return EntityExtractor(provider_router=provider)


def test_entity_extraction_preserves_tuple_map_and_records_spacy_positions(monkeypatch):
    sentence = _Sentence(0, 38)
    doc = _Doc([
        _Entity("Alpha Corporation", "ORG", 0, 17, sentence),
        _Entity("Beta Institute", "ORG", 24, 38, sentence),
    ], [sentence])
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(entity_extractor_module.spacy, "load", lambda _: _Nlp(doc))
    extractor = EntityExtractor()

    entity_map, all_entities = extractor.extract_entities([{
        "chunk_id": 0,
        "chunk_uid": "paper:0",
        "text": _TEXT,
    }])

    assert entity_map == {"paper:0": _ENTITIES}
    assert all_entities == [
        {
            "chunk_id": 0,
            "chunk_uid": "paper:0",
            "text": "Alpha Corporation",
            "label": "ORG",
            "start_char": 0,
            "end_char": 17,
            "sentence_start_char": 0,
            "sentence_end_char": 38,
            "sentence_index": 0,
        },
        {
            "chunk_id": 0,
            "chunk_uid": "paper:0",
            "text": "Beta Institute",
            "label": "ORG",
            "start_char": 24,
            "end_char": 38,
            "sentence_start_char": 0,
            "sentence_end_char": 38,
            "sentence_index": 0,
        },
    ]


def test_repeated_entity_mentions_enable_same_sentence_weak_evidence(monkeypatch):
    first_sentence = _Sentence(0, 100)
    second_sentence = _Sentence(200, 300)
    doc = _Doc([
        _Entity("Alpha", "ORG", 0, 5, first_sentence),
        _Entity("Alpha", "ORG", 200, 205, second_sentence),
        _Entity("Beta", "ORG", 210, 214, second_sentence),
    ], [first_sentence, second_sentence])
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(entity_extractor_module.spacy, "load", lambda _: _Nlp(doc))
    extractor = EntityExtractor()
    chunk = {"chunk_id": 0, "chunk_uid": "paper:0", "text": _TEXT}

    entity_map, all_entities = extractor.extract_entities([chunk])

    assert entity_map == {"paper:0": [("Alpha", "ORG"), ("Beta", "ORG")]}
    assert [
        (entity["text"], entity["start_char"], entity["sentence_index"])
        for entity in all_entities
    ] == [
        ("Alpha", 0, 0),
        ("Alpha", 200, 1),
        ("Beta", 210, 1),
    ]

    _, details = build_document_graph(
        [chunk],
        [[1.0, 0.0]],
        "paper",
        entity_extractor=extractor,
        graph_builder=_GraphBuilder(),
        detector=_Detector(),
    )

    assert details["raw_evidence"][0]["evidence_type"] == "same_sentence"


def test_rule_based_raw_evidence_uses_position_tiers():
    chunk = {"chunk_id": 0, "chunk_uid": "paper:0", "text": _TEXT}
    mentions_by_type = [
        ("same_sentence", [
            {
                "chunk_id": 0,
                "chunk_uid": "paper:0",
                "text": "Alpha Corporation",
                "sentence_index": 0,
                "start_char": 0,
                "end_char": 17,
            },
            {
                "chunk_id": 0,
                "chunk_uid": "paper:0",
                "text": "Beta Institute",
                "sentence_index": 0,
                "start_char": 24,
                "end_char": 38,
            },
        ]),
        ("nearby_window", [
            {
                "chunk_id": 0,
                "chunk_uid": "paper:0",
                "text": "Alpha Corporation",
                "sentence_index": 0,
                "start_char": 0,
                "end_char": 17,
            },
            {
                "chunk_id": 0,
                "chunk_uid": "paper:0",
                "text": "Beta Institute",
                "sentence_index": 1,
                "start_char": 48,
                "end_char": 62,
            },
        ]),
        ("same_chunk", [
            {
                "chunk_id": 0,
                "chunk_uid": "paper:0",
                "text": "Alpha Corporation",
                "sentence_index": 0,
                "start_char": 0,
                "end_char": 17,
            },
            {
                "chunk_id": 0,
                "chunk_uid": "paper:0",
                "text": "Beta Institute",
                "sentence_index": 1,
                "start_char": 200,
                "end_char": 214,
            },
        ]),
        ("same_chunk", [
            {
                "chunk_id": 0,
                "chunk_uid": "paper:0",
                "text": "Alpha Corporation",
                "hierarchy": {"sentence_index": 0},
            },
            {
                "chunk_id": 0,
                "chunk_uid": "paper:0",
                "text": "Beta Institute",
                "hierarchy": {"sentence_index": 0},
            },
        ]),
    ]
    expected_weights = {
        "same_sentence": 0.6,
        "nearby_window": 0.4,
        "same_chunk": 0.2,
    }

    for evidence_type, mentions in mentions_by_type:
        _, details = build_document_graph(
            [chunk],
            [[1.0, 0.0]],
            "paper",
            entity_extractor=_PositionedFallbackExtractor(mentions),
            graph_builder=_GraphBuilder(),
            detector=_Detector(),
        )

        assert details["raw_evidence"] == [{
            "head": "Alpha Corporation",
            "relation": "co-occurs_with",
            "tail": "Beta Institute",
            "source": "rule-based",
            "scope": "local",
            "confidence": expected_weights[evidence_type],
            "support_chunk_uids": ["paper:0"],
            "evidence_type": evidence_type,
            "verification_state": "unverified",
            "status": "unverified",
            "resolved_weight": expected_weights[evidence_type],
        }]
        assert details["active_evidence"] == []


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
    assert artifact["raw_evidence"][0]["evidence_type"] == "explicit"
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

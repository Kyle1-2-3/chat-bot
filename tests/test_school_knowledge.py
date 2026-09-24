import pytest

import app as appmod
import school_knowledge as kb


@pytest.fixture
def sample_knowledge(monkeypatch):
    data = {"checked_on": "2026-09-23", "records": [
        {"id": "snow", "title": "Ken Snow", "category": "staff", "keywords": [],
         "facts": ["Ken Snow is Houseparent of Rogers House and teaches Senior Chemistry."],
         "source_url": "https://www.brentwood.ca/staff/"},
        {"id": "rogers", "title": "Adriane Rogers", "category": "staff", "keywords": [],
         "facts": ["Adriane Rogers is Houseparent of Allard House."],
         "source_url": "https://www.brentwood.ca/staff/"},
        {"id": "foote", "title": "Foote Athletic Centre", "category": "facility", "keywords": [],
         "facts": ["Facilities include the Wheaton Gym and squash courts."],
         "source_url": "https://www.brentwood.ca/athletics/facilities/"},
        {"id": "film", "title": "Film Centre Facilities", "category": "facility", "keywords": [],
         "facts": ["The film studio has cameras and a green screen."],
         "source_url": "https://www.brentwood.ca/arts/film/"},
    ]}
    monkeypatch.setattr(kb, "load_knowledge", lambda: data)
    return data


def test_named_staff_and_facility_retrieval_keep_provenance(sample_knowledge):
    staff = kb.search_school_knowledge("Rogers house parent")
    assert any(r["id"] == "snow" for r in staff)
    result = kb.search_school_knowledge("Foote facilities")[0]
    assert result["id"] == "foote"
    assert result["checked_on"] == "2026-09-23"
    assert result["source_url"].endswith("/athletics/facilities/")
    assert all(r["id"] != "film" for r in kb.search_school_knowledge("Foote Centre facilities"))


def test_no_unrelated_fallback_and_bounded_results(sample_knowledge):
    assert kb.search_school_knowledge("zzzzquantumzzz") == []
    assert kb.search_school_knowledge("") == []
    assert len(kb.search_school_knowledge("house", limit=1)) == 1


def test_missing_snapshot_is_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(kb, "KNOWLEDGE_PATH", tmp_path / "missing.json")
    kb.load_knowledge.cache_clear()
    try:
        assert kb.search_school_knowledge("Rogers") == []
    finally:
        kb.load_knowledge.cache_clear()


def test_classifier_query_validation_and_resolved_followup(monkeypatch):
    assert appmod.validate_request({"intent": "SCHOOL_INFO", "school_query": ["Rogers"]})["school_query"] == ""
    query = appmod.validate_request({"intent": "SCHOOL_INFO", "school_query": "Rogers houseparent "})
    seen = []
    monkeypatch.setattr(appmod, "search_school_knowledge", lambda q: seen.append(q) or [])
    assert appmod.build_result_from_classification(query, "What about Rogers?") == {"type": "SCHOOL_INFO", "records": []}
    assert seen == ["Rogers houseparent"]


def test_assigned_teacher_skips_directory_and_answer_model(monkeypatch):
    monkeypatch.setattr(appmod, "classify_query", lambda *a: [{"intent": "PERSONAL_SCHOOL"}])
    def unexpected(*a, **kw):
        raise AssertionError("Personal assignments must not use the directory or answer model")
    monkeypatch.setattr(appmod, "search_school_knowledge", unexpected)
    monkeypatch.setattr(appmod, "generate_answer", unexpected)
    result = appmod.app.test_client().post("/chat", json={"message": "Who is my math teacher?"})
    assert result.status_code == 200
    assert result.get_json()["reply"] == appmod.PERSONAL_SCHOOL_REPLY


def test_mixed_public_and_personal_questions_remain_separate(monkeypatch, sample_knowledge):
    monkeypatch.setattr(appmod, "classify_query", lambda *a: [
        {"intent": "PERSONAL_SCHOOL"}, {"intent": "SCHOOL_INFO", "school_query": "Ken Snow"}])
    captured = []
    monkeypatch.setattr(appmod, "generate_answer", lambda msg, cls, results: captured.extend(results) or "Combined")
    result = appmod.app.test_client().post("/chat", json={"message": "Who is my math teacher and who is Mr Snow?"})
    assert result.status_code == 200
    assert captured[0]["reply"] == appmod.PERSONAL_SCHOOL_REPLY
    assert captured[1]["records"][0]["title"] == "Ken Snow"


def test_snapshot_has_rogers_houseparent_and_official_sources():
    data = kb.load_knowledge()
    assert len(data["records"]) > 100
    assert any("Ken Snow" in " ".join(r["facts"]) and "Rogers" in " ".join(r["facts"])
               for r in kb.search_school_knowledge("Rogers houseparent"))
    assert all(r["source_url"].startswith("https://www.brentwood.ca/") for r in data["records"])
    assert len({r["id"] for r in data["records"]}) == len(data["records"])
    assert all(isinstance(r["facts"], list) and r["facts"]
               and all(isinstance(f, str) for f in r["facts"])
               and isinstance(r["keywords"], list) for r in data["records"])

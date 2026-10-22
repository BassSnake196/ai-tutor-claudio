from evals.curriculum_eval import validate_curriculum
from evals.prompt_registry import fingerprint

def valid_response():
    return {"topic_title":"Ecuaciones", "target_level":"Secundaria", "pedagogical_approach":"ABP", "learning_objectives":["Resolver ecuaciones lineales"], "syllabus_units":[{"unit_number":1,"unit_name":"Resolver ecuaciones","estimated_hours":2,"subtopics":["ecuaciones"],"didactic_explanation":"Explicación clara","practical_activities":["Resolver ejercicios"],"evaluation_questions":[{"question":"¿Cómo resolver?","expected_answer":"Despejar"}],"learning_outcomes":["Resolver ecuaciones"],"guided_activity":"Resolver en parejas","formative_assessment":"Lista de cotejo","evidence_of_learning":["Ejercicios resueltos"],"citations":[]}],"grounding_status":"UNSUPPORTED"}

def test_curriculum_validates_schema_hours_and_alignment():
    result = validate_curriculum({"weeks":1,"hours_per_week":2,"expected_units":1,"source_ids":[]}, valid_response())
    assert result["valid"] is True

def test_curriculum_rejects_hours_and_unauthorized_citation():
    response = valid_response(); response["syllabus_units"][0]["estimated_hours"] = 3
    response["syllabus_units"][0]["citations"] = [{"source_id":"not-allowed","fragment_reference":"x"}]
    result = validate_curriculum({"weeks":1,"hours_per_week":2,"expected_units":1,"source_ids":[]}, response)
    assert result["valid"] is False
    assert result["checks"]["hours"] is False and result["checks"]["citations_authorized"] is False

def test_prompt_registry_is_stable_and_changes_with_config():
    first = fingerprint(prompt="p", model="m", config={"x":1})
    assert first == fingerprint(prompt="p", model="m", config={"x":1})
    assert first["run_hash"] != fingerprint(prompt="p", model="m", config={"x":2})["run_hash"]

def test_alignment_is_structural_and_lexical_signal_is_diagnostic():
    response = valid_response(); response["learning_objectives"] = ["Resolver ecuaciones"]
    result = validate_curriculum({"weeks":1,"hours_per_week":2,"expected_units":1,"source_ids":[]}, response)
    assert result["checks"]["alignment_structural"] is True
    assert result["checks"]["alignment_lexical_signal"] is True

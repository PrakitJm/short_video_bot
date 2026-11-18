"""Data shapes. Scripts stay plain dicts (they round-trip through JSON); this holds their schema."""
from jsonschema import Draft202012Validator

# Also sent to Gemini as response_json_schema, so keep to keywords Gemini supports.
SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "scenes": {
            "type": "array",
            "minItems": 5,
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "narration": {"type": "string"},
                    "visual_query": {"type": "string"},
                    "visual_note": {"type": "string"},
                },
                "required": ["id", "narration", "visual_query", "visual_note"],
            },
        },
    },
    "required": ["topic", "title", "description", "tags", "scenes"],
}

_validator = Draft202012Validator(SCRIPT_SCHEMA)


def validate_script(data) -> list[str]:
    """Return human-readable problems; empty list means valid."""
    errors = [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in _validator.iter_errors(data)]
    if errors:
        return errors
    ids = [s["id"] for s in data["scenes"]]
    if ids != list(range(1, len(ids) + 1)):
        errors.append(f"scenes: id ต้องเรียง 1..n แต่ได้ {ids}")
    if len(data["title"]) > 70:
        errors.append(f"title: ยาว {len(data['title'])} ตัวอักษร เกิน 70")
    for s in data["scenes"]:
        if not s["narration"].strip():
            errors.append(f"scenes/{s['id']}: narration ว่าง")
        if not s["visual_query"].isascii():
            errors.append(f"scenes/{s['id']}: visual_query ต้องเป็นภาษาอังกฤษ")
    return errors

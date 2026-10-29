import json
from pathlib import Path
from typing import Any

from sitegen.aspects import registry
from sitegen.card import Company

OUT = Path(__file__).resolve().parent.parent / "docs" / "company.schema.json"


def build_schema() -> dict[str, Any]:
    schema = Company.model_json_schema()
    defs = schema.setdefault("$defs", {})
    props: dict[str, Any] = {}
    #схемы разделов берём у аспектов
    for aspect in registry.all_aspects():
        sub = aspect.model.model_json_schema(ref_template="#/$defs/{model}")
        defs.update(sub.pop("$defs", {}))
        name = aspect.model.__name__
        defs[name] = sub
        props[aspect.key] = {"$ref": f"#/$defs/{name}", "description": f"{aspect.number}. {aspect.title}"}
    schema["properties"]["sections"] = {"type": "object", "properties": props, "additionalProperties": False}
    return schema


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(build_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("записано", OUT)


if __name__ == "__main__":
    main()

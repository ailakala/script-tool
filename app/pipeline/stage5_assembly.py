import yaml
from dataclasses import dataclass, field
from app.pipeline.stage2_cross_chapter_synthesis import GlobalAnalysis
from app.pipeline.stage3_script_structure import ScriptStructure
from app.pipeline.stage4_scene_generation import GeneratedScene

@dataclass
class AssemblyResult:
    yaml_text: str = ""
    warnings: list = field(default_factory=list)
    is_valid: bool = False


def assemble(meta: dict, config: dict, global_analysis: GlobalAnalysis,
             structure: ScriptStructure, scenes: list) -> AssemblyResult:
    result = AssemblyResult()

    script = {
        "meta": meta,
        "config": config,
        "characters": _build_characters(global_analysis),
        "scenes": _build_scenes(scenes),
        "extensions": _build_extensions(config.get("script_type", "other"), structure),
    }

    result.yaml_text = yaml.dump(script, allow_unicode=True, default_flow_style=False,
                                  sort_keys=False, width=120)
    result.warnings = _validate(script)
    result.is_valid = len([w for w in result.warnings if w.startswith("ERROR")]) == 0
    return result


def _build_characters(ga: GlobalAnalysis) -> list:
    chars = []
    for i, c in enumerate(ga.characters):
        char = {
            "id": f"char_{i+1:03d}",
            "name": c.get("name", ""),
            "aliases": c.get("aliases", []),
            "role": c.get("role", "supporting"),
            "description": c.get("description", ""),
            "traits": c.get("traits", []),
            "relationships": [],
            "first_appearance_scene": "",
            "notes": "",
        }
        chars.append(char)

    name_to_id = {c["name"]: c["id"] for c in chars}
    for rel in ga.relationships:
        from_id = name_to_id.get(rel.get("from", ""))
        to_id = name_to_id.get(rel.get("to", ""))
        if from_id and to_id:
            for c in chars:
                if c["id"] == from_id:
                    c["relationships"].append({
                        "to": to_id,
                        "type": rel.get("type", ""),
                        "description": rel.get("description", ""),
                    })
    return chars


def _build_scenes(generated_scenes: list) -> list:
    scenes = []
    for gs in generated_scenes:
        scene = {
            "id": gs.id,
            "act": gs.act,
            "episode": gs.episode,
            "sequence": gs.sequence,
            "setting": {
                "location": gs.location,
                "time": gs.time,
                "description": gs.setting_description,
            },
            "characters_present": gs.characters_present,
            "content": gs.content,
            "page": None,
            "notes": "",
        }
        scenes.append(scene)
    return scenes


def _build_extensions(script_type: str, structure: ScriptStructure) -> dict:
    extensions = {}
    if script_type == "tv_series" and structure.episode_summaries:
        extensions["tv_series"] = {"episode_summaries": structure.episode_summaries}
    if script_type == "film" and structure.beat_sheet:
        extensions["film"] = {"beat_sheet": structure.beat_sheet}
    extensions["custom"] = {}
    return extensions


def _validate(script: dict) -> list:
    warnings = []
    if not script["meta"].get("title"):
        warnings.append("ERROR: 缺少剧本标题")
    if not script["scenes"]:
        warnings.append("ERROR: 没有场景内容")
    if not script["characters"]:
        warnings.append("WARNING: 人物表为空")

    char_ids = {c["id"] for c in script["characters"]}
    for scene in script["scenes"]:
        for elem in scene.get("content", []):
            if elem.get("type") == "dialogue":
                char_name = elem.get("character", "")
                if char_name and char_name not in char_ids:
                    warnings.append(f"WARNING: {scene['id']} 中台词归属未知角色 '{char_name}'")
    return warnings

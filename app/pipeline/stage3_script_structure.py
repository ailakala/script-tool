import json
from dataclasses import dataclass, field
from app.ai.interface import AIProvider
from app.ai.factory import create_ai_provider
from app.pipeline.stage2_cross_chapter_synthesis import GlobalAnalysis
from app.pipeline.utils import extract_json

@dataclass
class ScenePlan:
    id: str = ""
    act: int = 1
    episode: int = 1
    sequence: int = 1
    location: str = ""
    time: str = ""
    setting_description: str = ""
    characters_present: list = field(default_factory=list)
    summary: str = ""
    source_chapter: int = 0

@dataclass
class ScriptStructure:
    script_type: str = "film"
    scenes: list = field(default_factory=list)
    episode_summaries: list = field(default_factory=list)
    beat_sheet: list = field(default_factory=list)
    raw_response: str = ""

SYSTEM_PROMPT = """你是一位专业的剧本结构设计师。根据人物表、场景目录和情节分析，设计剧本的场景结构。输出 JSON。

输出格式：
{
  "scenes": [
    {"act": 1, "episode": 1, "sequence": 1, "location": "", "time": "", "setting_description": "", "characters_present": ["角色名"], "summary": "该场内容概述", "source_chapter": 1}
  ],
  "episode_summaries": [
    {"episode": 1, "title": "", "summary": "", "scene_indices": [0, 1, 2], "cliffhanger": ""}
  ],
  "beat_sheet": [
    {"beat": "开场画面/催化剂/中点/...", "scene_index": 0, "description": ""}
  ]
}

设计原则：
1. 每场通常 2-5 分钟（剧本 1 页 ≈ 1 分钟），合理分配
2. 关键情节事件必须有对应场景
3. 人物初次出场应安排单独的引入场景
4. 保持场景之间因果关系清晰"""


async def design_structure(global_analysis: GlobalAnalysis, config: dict,
                           provider: AIProvider = None) -> ScriptStructure:
    if provider is None:
        provider = create_ai_provider()

    prompt = f"""基于以下分析结果设计剧本结构：

剧本类型：{config.get('script_type', 'film')}
目标集数：{config.get('target_episodes', 'N/A')}
单集时长：{config.get('target_duration_per_episode', 'N/A')}
风格：{config.get('style', '通用')}

人物表：{json.dumps(global_analysis.characters, ensure_ascii=False)}
人物关系：{json.dumps(global_analysis.relationships, ensure_ascii=False)}
场景目录：{json.dumps(global_analysis.locations, ensure_ascii=False)}
主线：{global_analysis.main_plot}
支线：{json.dumps(global_analysis.subplots, ensure_ascii=False)}

请设计完整的场景列表。"""

    response = await provider.generate(prompt, system=SYSTEM_PROMPT, output_format="json")
    return _parse_structure(response, config.get("script_type", "film"))


def _parse_structure(response: str, script_type: str) -> ScriptStructure:
    result = ScriptStructure(script_type=script_type, raw_response=response)
    data = extract_json(response)
    if data:
        for i, s in enumerate(data.get("scenes", [])):
            result.scenes.append(ScenePlan(
                id=f"scene_{i+1:03d}",
                act=s.get("act", 1),
                episode=s.get("episode", 1),
                sequence=s.get("sequence", i+1),
                location=s.get("location", ""),
                time=s.get("time", ""),
                setting_description=s.get("setting_description", ""),
                characters_present=s.get("characters_present", []),
                summary=s.get("summary", ""),
                source_chapter=s.get("source_chapter", 0),
            ))
        result.episode_summaries = data.get("episode_summaries", [])
        result.beat_sheet = data.get("beat_sheet", [])
    return result

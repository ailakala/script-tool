import json
import asyncio
from dataclasses import dataclass, field
from app.ai.interface import AIProvider
from app.ai.factory import create_ai_provider
from app.pipeline.stage3_script_structure import ScenePlan

@dataclass
class GeneratedScene:
    id: str = ""
    act: int = 1
    episode: int = 1
    sequence: int = 1
    location: str = ""
    time: str = ""
    setting_description: str = ""
    characters_present: list = field(default_factory=list)
    content: list = field(default_factory=list)
    raw_response: str = ""

SYSTEM_PROMPT = """你是一位专业的剧本作家。根据场景计划和人物信息，生成该场景的完整剧本内容。输出 JSON。

输出格式：
{
  "content": [
    {"type": "action", "text": "动作描述"},
    {"type": "dialogue", "character": "角色名", "text": "台词", "direction": "表演指示（可选）"},
    {"type": "transition", "text": "CUT TO:"},
    {"type": "note", "text": "备注"}
  ]
}

规则：
1. action 描述环境、动作、表情等视觉元素，使用现在时
2. dialogue 的 character 必须是人物表中存在的角色名
3. direction 是括号里的表演提示，可选
4. transition 仅用于场景切换，通常放在 content 末尾
5. 每场控制在 5-15 个 content 元素"""


async def generate_scene(plan: ScenePlan, characters: list,
                         original_text: str = "", provider: AIProvider = None) -> GeneratedScene:
    if provider is None:
        provider = create_ai_provider()

    scene_chars = [c for c in characters if c["name"] in plan.characters_present]
    char_desc = "\n".join(
        f"- {c['name']}（{c.get('role','')}）：{c.get('description','')}，性格：{', '.join(c.get('traits',[]))}"
        for c in scene_chars
    )

    prompt = f"""生成以下场景的剧本内容：

场景：{plan.id}
地点：{plan.location}
时间：{plan.time}
环境：{plan.setting_description}
出场人物：{', '.join(plan.characters_present)}
场景概要：{plan.summary}

人物信息：
{char_desc}

原始小说片段（参考）：
{original_text[:2000]}

请生成该场景的完整 content 数组。"""

    response = await provider.generate(prompt, system=SYSTEM_PROMPT, output_format="json")
    return _parse_scene(plan, response)


async def generate_scenes_parallel(plans: list, characters: list,
                                   chapter_texts: dict, provider: AIProvider = None) -> list:
    if provider is None:
        provider = create_ai_provider()
    tasks = [
        generate_scene(p, characters, chapter_texts.get(p.source_chapter, ""), provider)
        for p in plans
    ]
    return await asyncio.gather(*tasks)


def _parse_scene(plan: ScenePlan, response: str) -> GeneratedScene:
    scene = GeneratedScene(
        id=plan.id, act=plan.act, episode=plan.episode,
        sequence=plan.sequence, location=plan.location,
        time=plan.time, setting_description=plan.setting_description,
        characters_present=plan.characters_present,
        raw_response=response,
    )
    try:
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])
        data = json.loads(text)
        scene.content = data.get("content", [])
    except (json.JSONDecodeError, KeyError):
        pass
    return scene

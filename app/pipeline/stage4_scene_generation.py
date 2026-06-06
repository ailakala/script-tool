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
5. 每场控制在 5-15 个 content 元素
6. 台词必须贴合角色的性格、身份和人物关系（参考人物信息中的性格标签和角色描述）
7. 如有原始小说对话参考，应从中把握角色的说话风格和语气特点"""


async def generate_scene(plan: ScenePlan, characters: list,
                         original_text: str = "",
                         dialogue_excerpts: list = None,
                         provider: AIProvider = None) -> GeneratedScene:
    if provider is None:
        provider = create_ai_provider()

    scene_chars = [c for c in characters if c["name"] in plan.characters_present]
    char_desc = "\n".join(
        f"- {c['name']}（{c.get('role','')}）：{c.get('description','')}，性格：{', '.join(c.get('traits',[]))}"
        for c in scene_chars
    )

    # 构建原始对话参考（最多 5 条）
    dialogue_ref = ""
    if dialogue_excerpts:
        excerpts_lines = []
        for ex in dialogue_excerpts[:5]:
            speaker = ex.get("speaker", "?")
            text = ex.get("text", "")
            context = ex.get("context", "")
            line = f"- {speaker}：「{text}」"
            if context:
                line += f"（{context}）"
            excerpts_lines.append(line)
        if excerpts_lines:
            dialogue_ref = (
                "\n原始小说对话参考（参考角色语气和说话风格）：\n"
                + "\n".join(excerpts_lines)
                + "\n"
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
{dialogue_ref}
请生成该场景的完整 content 数组。台词要贴合角色的性格和身份，参考原始小说对话的风格。"""

    response = await provider.generate(prompt, system=SYSTEM_PROMPT, output_format="json")
    return _parse_scene(plan, response)


async def generate_scenes_parallel(plans: list, characters: list,
                                   chapter_texts: dict,
                                   chapter_analyses: list = None,
                                   provider: AIProvider = None) -> list:
    if provider is None:
        provider = create_ai_provider()

    # 构建章节索引 → 对话摘录的映射
    chapter_dialogue_map = {}
    if chapter_analyses:
        for ca in chapter_analyses:
            if ca.dialogue_excerpts:
                chapter_dialogue_map[ca.chapter_index] = ca.dialogue_excerpts

    tasks = [
        generate_scene(
            p, characters,
            chapter_texts.get(p.source_chapter, ""),
            chapter_dialogue_map.get(p.source_chapter, []),
            provider,
        )
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

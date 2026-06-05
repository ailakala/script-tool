import json
import asyncio
from dataclasses import dataclass, field
from app.ai.interface import AIProvider
from app.ai.factory import create_ai_provider
from app.pipeline.stage0_preprocess import Chapter

@dataclass
class ChapterAnalysis:
    chapter_index: int
    chapter_title: str
    new_characters: list = field(default_factory=list)
    locations: list = field(default_factory=list)
    plot_events: list = field(default_factory=list)
    dialogue_excerpts: list = field(default_factory=list)
    raw_response: str = ""

SYSTEM_PROMPT = """你是一位专业的剧本分析师。分析给定的小说章节，输出 JSON。只输出 JSON，不要其他文字。

输出格式：
{
  "new_characters": [
    {"name": "角色名", "aliases": ["别名"], "description": "简要描述", "traits": ["性格标签"], "role_hint": "protagonist/antagonist/supporting/cameo"}
  ],
  "locations": [
    {"name": "地点名", "description": "简要描述", "time_hint": "时间提示"}
  ],
  "plot_events": [
    {"summary": "事件摘要", "importance": "major/minor", "characters_involved": ["角色名"]}
  ],
  "dialogue_excerpts": [
    {"speaker": "说话者", "text": "台词片段", "context": "上下文"}
  ]
}"""


async def analyze_chapter(chapter: Chapter, provider: AIProvider = None) -> ChapterAnalysis:
    if provider is None:
        provider = create_ai_provider()

    prompt = f"""分析以下小说章节：

章节标题：{chapter.title}
章节内容：
{chapter.content[:6000]}

请输出该章节的人物、地点、情节事件和对话片段。"""

    response = await provider.generate(prompt, system=SYSTEM_PROMPT, output_format="json")
    return _parse_response(chapter.index, chapter.title, response)


async def analyze_chapters_parallel(chapters: list, provider: AIProvider = None) -> list:
    if provider is None:
        provider = create_ai_provider()
    tasks = [analyze_chapter(c, provider) for c in chapters]
    return await asyncio.gather(*tasks)


def _parse_response(index: int, title: str, response: str) -> ChapterAnalysis:
    analysis = ChapterAnalysis(chapter_index=index, chapter_title=title, raw_response=response)
    try:
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])
        data = json.loads(text)
        analysis.new_characters = data.get("new_characters", [])
        analysis.locations = data.get("locations", [])
        analysis.plot_events = data.get("plot_events", [])
        analysis.dialogue_excerpts = data.get("dialogue_excerpts", [])
    except (json.JSONDecodeError, KeyError):
        pass
    return analysis

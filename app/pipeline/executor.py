import json
import hashlib
from enum import Enum
from dataclasses import dataclass, field
from app.ai.interface import AIProvider
from app.ai.factory import create_ai_provider
from app.pipeline.stage0_preprocess import preprocess_text
from app.pipeline.stage1_chapter_analysis import analyze_chapters_parallel
from app.pipeline.stage2_cross_chapter_synthesis import synthesize
from app.pipeline.stage3_script_structure import design_structure
from app.pipeline.stage4_scene_generation import generate_scenes_parallel
from app.pipeline.stage5_assembly import assemble

class StageStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"

@dataclass
class PipelineState:
    project_id: str = ""
    current_stage: int = 0
    stage_status: dict = field(default_factory=lambda: {i: StageStatus.PENDING.value for i in range(6)})
    stage_results: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    progress_callback: object = None

    def set_stage(self, stage: int, status: StageStatus):
        self.stage_status[stage] = status.value
        self.current_stage = stage


async def run_pipeline(project_id: str, text: str, meta: dict, config: dict,
                       provider: AIProvider = None,
                       progress_callback=None) -> PipelineState:
    if provider is None:
        provider = create_ai_provider()

    state = PipelineState(project_id=project_id, progress_callback=progress_callback)
    chapter_texts = {}

    try:
        # Stage 0
        state.set_stage(0, StageStatus.RUNNING)
        await _notify(state, "正在解析文本...")
        preprocess = preprocess_text(text)
        if not preprocess.is_valid():
            raise ValueError(f"文本章节不足（需要至少3章，检测到{len(preprocess.chapters)}章）")
        state.stage_results["preprocess"] = preprocess
        state.stage_results["meta"] = meta
        state.stage_results["config"] = config
        for ch in preprocess.chapters:
            chapter_texts[ch.index] = ch.content
        state.set_stage(0, StageStatus.DONE)

        # Stage 1
        state.set_stage(1, StageStatus.RUNNING)
        await _notify(state, f"正在分析 {len(preprocess.chapters)} 个章节...")
        chapter_analyses = await analyze_chapters_parallel(preprocess.chapters, provider)
        state.stage_results["chapter_analyses"] = chapter_analyses
        state.set_stage(1, StageStatus.DONE)

        # Stage 2
        state.set_stage(2, StageStatus.RUNNING)
        await _notify(state, "正在综合人物和情节...")
        global_analysis = await synthesize(chapter_analyses, provider)
        state.stage_results["global_analysis"] = global_analysis
        state.set_stage(2, StageStatus.DONE)

        # Stage 3
        state.set_stage(3, StageStatus.RUNNING)
        await _notify(state, "正在设计剧本结构...")
        structure = await design_structure(global_analysis, config, provider)
        state.stage_results["structure"] = structure
        state.set_stage(3, StageStatus.DONE)

        # Stage 4
        state.set_stage(4, StageStatus.RUNNING)
        await _notify(state, f"正在生成 {len(structure.scenes)} 场内容...")
        scenes = await generate_scenes_parallel(
            structure.scenes, global_analysis.characters, chapter_texts, provider
        )
        state.stage_results["scenes"] = scenes
        state.set_stage(4, StageStatus.DONE)

        # Stage 5
        state.set_stage(5, StageStatus.RUNNING)
        await _notify(state, "正在组装和校验 YAML...")
        result = assemble(meta, config, global_analysis, structure, scenes)
        state.stage_results["assembly"] = result
        if not result.is_valid:
            state.errors.extend(result.warnings)
        state.set_stage(5, StageStatus.DONE)

    except Exception as e:
        state.set_stage(state.current_stage, StageStatus.ERROR)
        state.errors.append(str(e))

    return state


def compute_input_hash(**kwargs) -> str:
    raw = json.dumps(kwargs, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def _notify(state: PipelineState, message: str):
    if state.progress_callback:
        await state.progress_callback({
            "project_id": state.project_id,
            "current_stage": state.current_stage,
            "stage_status": state.stage_status,
            "message": message,
        })

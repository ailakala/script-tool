import json
import hashlib
from dataclasses import asdict
from enum import Enum
from dataclasses import dataclass, field
from typing import Callable, Optional
from app.ai.interface import AIProvider
from app.ai.factory import create_ai_provider
from app.pipeline.stage0_preprocess import preprocess_text, PreprocessResult
from app.pipeline.stage1_chapter_analysis import analyze_chapters_parallel, ChapterAnalysis
from app.pipeline.stage2_cross_chapter_synthesis import synthesize, GlobalAnalysis
from app.pipeline.stage3_script_structure import design_structure, ScriptStructure
from app.pipeline.stage4_scene_generation import generate_scenes_parallel, GeneratedScene
from app.pipeline.stage5_assembly import assemble, AssemblyResult

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
                       progress_callback=None,
                       cache_get: Optional[Callable] = None,
                       cache_put: Optional[Callable] = None) -> PipelineState:
    if provider is None:
        provider = create_ai_provider()

    state = PipelineState(project_id=project_id, progress_callback=progress_callback)
    chapter_texts = {}

    try:
        # Stage 0 — 纯工程，不做缓存
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

        # Stage 1 — 分章节分析（按文本内容缓存）
        state.set_stage(1, StageStatus.RUNNING)
        await _notify(state, f"正在分析 {len(preprocess.chapters)} 个章节...")
        s1_hash = compute_input_hash(stage=1, text=text)
        chapter_analyses = await _cache_or_run(
            cache_get, cache_put, project_id, 1, s1_hash,
            lambda: analyze_chapters_parallel(preprocess.chapters, provider)
        )
        state.stage_results["chapter_analyses"] = chapter_analyses
        state.set_stage(1, StageStatus.DONE)

        # Stage 2 — 跨章节综合（按章节分析结果缓存）
        state.set_stage(2, StageStatus.RUNNING)
        await _notify(state, "正在综合人物和情节...")
        s2_hash = compute_input_hash(stage=2, analyses=_dataclass_list_hash(chapter_analyses))
        global_analysis = await _cache_or_run(
            cache_get, cache_put, project_id, 2, s2_hash,
            lambda: synthesize(chapter_analyses, provider)
        )
        state.stage_results["global_analysis"] = global_analysis
        state.set_stage(2, StageStatus.DONE)

        # Stage 3 — 剧本结构设计（按综合结果 + config 缓存）
        state.set_stage(3, StageStatus.RUNNING)
        await _notify(state, "正在设计剧本结构...")
        s3_hash = compute_input_hash(stage=3, analysis_hash=s2_hash, config=json.dumps(config, sort_keys=True))
        structure = await _cache_or_run(
            cache_get, cache_put, project_id, 3, s3_hash,
            lambda: design_structure(global_analysis, config, provider)
        )
        state.stage_results["structure"] = structure
        state.set_stage(3, StageStatus.DONE)

        # Stage 4 — 逐场内容生成（按 structure + characters 缓存）
        state.set_stage(4, StageStatus.RUNNING)
        await _notify(state, f"正在生成 {len(structure.scenes)} 场内容...")
        s4_hash = compute_input_hash(stage=4, structure_hash=s3_hash,
                                     char_hash=_dict_list_hash(global_analysis.characters))
        scenes = await _cache_or_run(
            cache_get, cache_put, project_id, 4, s4_hash,
            lambda: generate_scenes_parallel(
                structure.scenes, global_analysis.characters, chapter_texts, provider
            )
        )
        state.stage_results["scenes"] = scenes
        state.set_stage(4, StageStatus.DONE)

        # Stage 5 — 组装校验（按前序结果哈希缓存）
        state.set_stage(5, StageStatus.RUNNING)
        await _notify(state, "正在组装和校验 YAML...")
        s5_hash = compute_input_hash(stage=5, meta=json.dumps(meta, sort_keys=True),
                                     s4_hash=s4_hash)
        result = await _cache_or_run(
            cache_get, cache_put, project_id, 5, s5_hash,
            lambda: _sync_assemble(meta, config, global_analysis, structure, scenes, state)
        )
        state.stage_results["assembly"] = result
        if not result.is_valid:
            state.errors.extend(result.warnings)
        state.set_stage(5, StageStatus.DONE)

    except Exception as e:
        state.set_stage(state.current_stage, StageStatus.ERROR)
        state.errors.append(str(e))

    return state


async def _sync_assemble(meta, config, global_analysis, structure, scenes, state):
    """Async wrapper for sync assemble to store validation errors."""
    result = assemble(meta, config, global_analysis, structure, scenes)
    if not result.is_valid:
        for w in result.warnings:
            if w.startswith("ERROR"):
                state.errors.append(w)
    return result


async def _cache_or_run(cache_get, cache_put, project_id: str, stage: int,
                        input_hash: str, fn):
    """如果缓存命中则直接返回，否则执行 fn 并写入缓存。"""
    if cache_get:
        cached = await cache_get(project_id, stage, input_hash)
        if cached is not None:
            return cached
    result = await fn()
    if cache_put:
        await cache_put(project_id, stage, input_hash, result)
    return result


def _dataclass_list_hash(items) -> str:
    """为 dataclass 列表生成稳定的哈希字符串。"""
    data = json.dumps([asdict(item) for item in items], sort_keys=True, default=str)
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def _dict_list_hash(items: list) -> str:
    """为 dict 列表生成稳定的哈希字符串。"""
    data = json.dumps(items, sort_keys=True, default=str)
    return hashlib.sha256(data.encode()).hexdigest()[:16]


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

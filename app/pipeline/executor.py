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
    percent: int = 0

    def set_stage(self, stage: int, status: StageStatus):
        self.stage_status[stage] = status.value
        self.current_stage = stage


# ── Independent stage functions ──────────────────────────────────────

async def run_stage_0(project_id: str, text: str,
                      notify=None,
                      cache_get: Optional[Callable] = None,
                      cache_put: Optional[Callable] = None) -> PreprocessResult:
    s0_hash = compute_input_hash(stage=0, text=text)
    if cache_get:
        cached = await cache_get(project_id, 0, s0_hash)
        if cached is not None:
            return cached

    if notify:
        await notify("正在解析文本...")
    result = preprocess_text(text)
    if not result.is_valid():
        raise ValueError(f"文本章节不足（需要至少3章，检测到{len(result.chapters)}章）")

    if cache_put:
        await cache_put(project_id, 0, s0_hash, result)
    return result


async def run_stage_1(project_id: str, text: str, chapters: list,
                      provider: AIProvider = None,
                      notify=None,
                      on_chapter_done=None,
                      cache_get: Optional[Callable] = None,
                      cache_put: Optional[Callable] = None) -> list:
    if provider is None:
        provider = create_ai_provider()

    s1_hash = compute_input_hash(stage=1, text=text)

    async def _run():
        if notify:
            await notify(f"正在分析 {len(chapters)} 个章节...")
        return await analyze_chapters_parallel(chapters, provider, on_chapter_done)

    return await _cache_or_run(cache_get, cache_put, project_id, 1, s1_hash, _run)


async def run_stage_2(project_id: str, chapter_analyses: list,
                      provider: AIProvider = None,
                      notify=None,
                      cache_get: Optional[Callable] = None,
                      cache_put: Optional[Callable] = None) -> GlobalAnalysis:
    if provider is None:
        provider = create_ai_provider()

    s2_hash = compute_input_hash(stage=2, analyses=_dataclass_list_hash(chapter_analyses))

    async def _run():
        if notify:
            await notify("正在综合人物和情节...")
        return await synthesize(chapter_analyses, provider)

    return await _cache_or_run(cache_get, cache_put, project_id, 2, s2_hash, _run)


async def run_stage_3(project_id: str, global_analysis: GlobalAnalysis,
                      config: dict,
                      provider: AIProvider = None,
                      notify=None,
                      cache_get: Optional[Callable] = None,
                      cache_put: Optional[Callable] = None) -> ScriptStructure:
    if provider is None:
        provider = create_ai_provider()

    s3_hash = compute_input_hash(stage=3,
                                 analysis_hash=_dataclass_list_hash([global_analysis]),
                                 config=json.dumps(config, sort_keys=True))

    async def _run():
        if notify:
            await notify("正在设计剧本结构...")
        return await design_structure(global_analysis, config, provider)

    return await _cache_or_run(cache_get, cache_put, project_id, 3, s3_hash, _run)


async def run_stage_4(project_id: str, structure: ScriptStructure,
                      characters: list, chapter_texts: dict,
                      chapter_analyses: list = None,
                      provider: AIProvider = None,
                      notify=None,
                      on_scene_done=None,
                      cache_get: Optional[Callable] = None,
                      cache_put: Optional[Callable] = None) -> list:
    if provider is None:
        provider = create_ai_provider()

    s4_hash = compute_input_hash(stage=4,
                                 structure_hash=_dataclass_list_hash(structure.scenes),
                                 char_hash=_dict_list_hash(characters),
                                 chapter_analyses_hash=_dataclass_list_hash(chapter_analyses) if chapter_analyses else "")

    async def _run():
        if notify:
            await notify(f"正在生成 {len(structure.scenes)} 场内容...")
        result = await generate_scenes_parallel(
            structure.scenes, characters, chapter_texts, chapter_analyses, provider, on_scene_done
        )
        empty = [s for s in result if not s.content]
        if empty and result:
            names = ", ".join(s.id for s in empty)
            # 查看第一个空场景的原始响应帮助诊断
            raw_preview = ""
            for s in empty:
                if s.raw_response:
                    raw_preview = s.raw_response[:300]
                    break
            hint = f"\n原始响应预览：{raw_preview}" if raw_preview else ""
            raise ValueError(
                f"{len(empty)}/{len(result)} 个场景内容为空（{names}）。"
                f"已自动重试 2 次仍失败，可能是 AI 返回了不完整的 JSON。"
                f"建议：换用其他 AI 模型或减少场景复杂度后重试。{hint}"
            )
        return result

    return await _cache_or_run(cache_get, cache_put, project_id, 4, s4_hash, _run)


async def run_stage_5(project_id: str, meta: dict, config: dict,
                      global_analysis: GlobalAnalysis,
                      structure: ScriptStructure, scenes: list,
                      notify=None,
                      cache_get: Optional[Callable] = None,
                      cache_put: Optional[Callable] = None) -> AssemblyResult:
    s5_hash = compute_input_hash(stage=5,
                                 meta=json.dumps(meta, sort_keys=True),
                                 structure_hash=_dataclass_list_hash(structure.scenes),
                                 scenes_hash=_dataclass_list_hash(scenes))

    async def _run():
        if notify:
            await notify("正在组装剧本并校验...")
        return assemble(meta, config, global_analysis, structure, scenes)

    result = await _cache_or_run(cache_get, cache_put, project_id, 5, s5_hash, _run)
    return result


# ── All-in-one pipeline wrapper ──────────────────────────────────────

async def run_pipeline(project_id: str, text: str, meta: dict, config: dict,
                       provider: AIProvider = None,
                       progress_callback=None,
                       cache_get: Optional[Callable] = None,
                       cache_put: Optional[Callable] = None) -> PipelineState:
    if provider is None:
        provider = create_ai_provider()

    state = PipelineState(project_id=project_id, progress_callback=progress_callback)

    # 各阶段权重（总和 100%）
    STAGE_WEIGHTS = [5, 30, 10, 10, 40, 5]

    async def notify(msg):
        await _notify(state, msg)

    try:
        # Stage 0: 预处理
        state.set_stage(0, StageStatus.RUNNING)
        state.percent = 0
        preprocess = await run_stage_0(project_id, text, notify, cache_get, cache_put)
        chapter_texts = {ch.index: ch.content for ch in preprocess.chapters}
        state.stage_results["preprocess"] = preprocess
        state.stage_results["meta"] = meta
        state.stage_results["config"] = config
        state.set_stage(0, StageStatus.DONE)
        state.percent = STAGE_WEIGHTS[0]  # 5%
        await notify("文本预处理完成")

        # Stage 1: 分章节分析（N 个章节并行，逐章更新进度）
        state.set_stage(1, StageStatus.RUNNING)
        n_chapters = len(preprocess.chapters)
        s1_done = 0
        s1_base = STAGE_WEIGHTS[0]  # 5%

        async def on_chapter_done():
            nonlocal s1_done
            s1_done += 1
            pct_in_stage = int(s1_done / n_chapters * STAGE_WEIGHTS[1])
            state.percent = min(s1_base + pct_in_stage, 99)
            await _notify(state, f"章节分析 {s1_done}/{n_chapters}")

        chapter_analyses = await run_stage_1(
            project_id, text, preprocess.chapters, provider, notify,
            on_chapter_done, cache_get, cache_put)
        state.stage_results["chapter_analyses"] = chapter_analyses
        state.set_stage(1, StageStatus.DONE)
        state.percent = s1_base + STAGE_WEIGHTS[1]  # 35%
        await notify(f"{n_chapters} 个章节分析完成")

        # Stage 2: 跨章节综合
        state.set_stage(2, StageStatus.RUNNING)
        global_analysis = await run_stage_2(
            project_id, chapter_analyses, provider, notify, cache_get, cache_put)
        state.stage_results["global_analysis"] = global_analysis
        state.set_stage(2, StageStatus.DONE)
        state.percent = s1_base + STAGE_WEIGHTS[1] + STAGE_WEIGHTS[2]  # 45%
        await notify("人物和情节综合完成")

        # Stage 3: 剧本结构设计
        state.set_stage(3, StageStatus.RUNNING)
        config["num_chapters"] = len(preprocess.chapters)
        structure = await run_stage_3(
            project_id, global_analysis, config, provider, notify, cache_get, cache_put)
        state.stage_results["structure"] = structure
        state.set_stage(3, StageStatus.DONE)
        state.percent = sum(STAGE_WEIGHTS[:4])  # 55%
        await notify("剧本结构设计完成")

        # Stage 4: 逐场内容生成（M 个场景并行，逐场更新进度）
        state.set_stage(4, StageStatus.RUNNING)
        n_scenes = len(structure.scenes)
        s4_done = 0
        s4_base = sum(STAGE_WEIGHTS[:4])  # 55%

        async def on_scene_done():
            nonlocal s4_done
            s4_done += 1
            pct_in_stage = int(s4_done / n_scenes * STAGE_WEIGHTS[4])
            state.percent = min(s4_base + pct_in_stage, 99)
            await _notify(state, f"场景生成 {s4_done}/{n_scenes}")

        scenes = await run_stage_4(
            project_id, structure, global_analysis.characters, chapter_texts,
            chapter_analyses,
            provider, notify, on_scene_done, cache_get, cache_put)
        state.stage_results["scenes"] = scenes
        state.set_stage(4, StageStatus.DONE)
        state.percent = s4_base + STAGE_WEIGHTS[4]  # 95%

        empty_scenes = [s for s in scenes if not s.content]
        if empty_scenes and n_scenes > 0:
            names = ", ".join(s.id for s in empty_scenes)
            raw_preview = ""
            for s in empty_scenes:
                if s.raw_response:
                    raw_preview = s.raw_response[:300]
                    break
            hint = f"\n原始响应预览：{raw_preview}" if raw_preview else ""
            raise ValueError(
                f"{len(empty_scenes)}/{n_scenes} 个场景内容为空（{names}）。"
                f"已自动重试 2 次仍失败，可能是 AI 返回了不完整的 JSON。"
                f"建议：换用其他 AI 模型或减少场景复杂度后重试。{hint}"
            )
        await notify(f"{n_scenes} 场内容生成完成")

        # Stage 5: 组装 & 校验
        state.set_stage(5, StageStatus.RUNNING)
        result = await run_stage_5(
            project_id, meta, config, global_analysis, structure, scenes,
            notify, cache_get, cache_put)
        state.stage_results["assembly"] = result
        if not result.is_valid:
            for w in result.warnings:
                if w.startswith("ERROR"):
                    state.errors.append(w)
        state.set_stage(5, StageStatus.DONE)
        state.percent = 100
        await notify("剧本生成完成")

    except Exception as e:
        state.set_stage(state.current_stage, StageStatus.ERROR)
        state.errors.append(str(e))

    return state


# ── Helpers ──────────────────────────────────────────────────────────

async def _cache_or_run(cache_get, cache_put, project_id: str, stage: int,
                        input_hash: str, fn):
    if cache_get:
        cached = await cache_get(project_id, stage, input_hash)
        if cached is not None:
            return cached
    result = await fn()
    if cache_put:
        await cache_put(project_id, stage, input_hash, result)
    return result


def _dataclass_list_hash(items) -> str:
    data = json.dumps([asdict(item) for item in items], sort_keys=True, default=str)
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def _dict_list_hash(items: list) -> str:
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
            "percent": state.percent,
        })

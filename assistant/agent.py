"""电影剧本智能助手 —— VeADK Agent（本地持久化 + 多能力工具/技能）。

本模块只暴露 `root_agent`（一个纯 VeADK Agent），不引入 server / agentkit，
以便 veADK Frontend 与 ADK server 都能直接加载。上下文自动压缩、本地会话存储、
以及服务暴露在 `main.py` 中通过 ADK `App` + `AgentkitAgentServerApp` 装配。

能力对应关系（详见 README）：
- 网页搜索 / 读取           -> 内置工具 web_search / web_fetch / link_reader
- Seedream 生成图片         -> 内置工具 image_generate（doubao-seedream）
- Seedance 生成视频         -> 内置工具 video_generate（doubao-seedance）
- 代码生成与执行(sandbox)   -> 内置工具 run_code / coding（AgentKit sandbox tool_id）
- word/pdf/ppt/html 生成读取 -> create_document / read_document：在同一个 AgentKit
  sandbox 内用镜像内置库（python-docx / python-pptx / pypdf / weasyprint）真实生成并读回。
  （账号沙箱为纯 CodeEnv、无 skill 中心运行器，故不走 execute_skills，改用沙箱兜底方案。）
- 阶段性要点/素材整理         -> 本地 sqlite（save_local_knowledge / search_local_knowledge）
"""

from __future__ import annotations

import functools
import inspect
import json
import os
import re
import uuid

from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import ToolContext
from google.genai import types

from veadk import Agent
from veadk.utils.logger import get_logger

from .continuation_store import continuation_store
from .local_knowledge_store import local_knowledge_store

logger = get_logger(__name__)

_DEFAULT_MAX_OUTPUT_TOKENS = int(
    os.getenv("VEADK_MAX_OUTPUT_TOKENS", "3000")
)
_CONTINUATION_MAX_OUTPUT_TOKENS = int(
    os.getenv("VEADK_CONTINUATION_MAX_OUTPUT_TOKENS", "2200")
)
_AUTO_CONTINUE_MAX_STEPS = int(
    os.getenv("VEADK_AUTO_CONTINUE_MAX_STEPS", "4")
)
_AUTO_CONTINUE_TAIL_CHARS = int(
    os.getenv("VEADK_AUTO_CONTINUE_TAIL_CHARS", "3000")
)
_CONTINUE_RE = re.compile(r"(继续|接着|续写|下一部分|下一段|后续|继续第?\d+部分)")
_CONTROL_FRAGMENT_RE = re.compile(r"^</?[A-Za-z0-9_:-]+(?:\s[^>]*)?>$")
_FORBIDDEN_RETRIEVAL_TOOL_NAMES = {"load_knowledgebase", "vesearch"}

# --- 图片/视频生成：主模型 + “模型相关错误”自动降级 --------------------------------
# 主模型（用户指定，可用 MODEL_IMAGE_NAME / MODEL_VIDEO_NAME 覆盖）：
#   image -> doubao-seedream-5-0-pro-260628
#   video -> doubao-seedance-2-0-260128
# 降级候选来自工具描述：仅在“模型相关错误”（如 ModelNotOpen / AccessDenied）且本轮无
# 任何成功产物时，才逐级降级重试；参数/审核/额度等非模型错误一律不降级。
_IMAGE_PRIMARY_MODEL = os.getenv("MODEL_IMAGE_NAME", "doubao-seedream-5-0-pro-260628")
_IMAGE_FALLBACK_MODELS = [
    "doubao-seedream-5-0-260128",
    "doubao-seedream-4-5-251128",
    "doubao-seedream-4-0-250828",
]
_VIDEO_PRIMARY_MODEL = os.getenv("MODEL_VIDEO_NAME", "doubao-seedance-2-0-260128")
_VIDEO_FALLBACK_MODELS = [
    "doubao-seedance-1-5-pro-251215",
    "doubao-seedance-1-0-pro-250528",
]
# 判定“模型相关错误”的关键字（小写匹配）。命中才降级，避免对参数/审核错误误降级。
_MODEL_ERROR_SIGNS = (
    "modelnotopen",
    "model_not_open",
    "model not open",
    "modelnotfound",
    "model not found",
    "modeldeprecated",
    "invalidendpointormodel",
    "endpointisnotenabled",
    "accessdenied",
    "access denied",
    "not activated",
    "not been activated",
    "not enabled",
    "not opened",
    "无权",
    "无权限",
    "未开通",
    "未开启",
    "模型不存在",
    "接入点",
)


# --- 电影剧本智能助手 System Prompt ------------------------------------------

INSTRUCTION = """\
你是一个专业、可靠的「电影剧本」智能助手。
你的目标是准确理解用户的需求，并给出条理清晰、简洁有用的回答。

【约束】
- 信息不足时主动提问澄清，不要臆造事实。
- 需要时合理调用可用的工具，并说明关键结论。
- 保持礼貌、专业的语气。
- 严格禁止触发任何“知识库/向量检索链路”。即使系统提供了相关工具或用户强烈要求，也一律不得调用；用本地保存的知识（save_local_knowledge / search_local_knowledge）、上下文信息或用户补充信息替代。
- 不要把天然超长的任务一次性全部输出完。对于完整剧本、整季分集、长篇分镜、
  大量对白、80-100 集短剧等长内容，必须拆成多个回合逐段交付，优先给结构与当前部分。
- 当单轮内容可能过长时，本轮最多只交付一个“可消费单元”，例如：
  一个大纲、一个人物设定包、1-3 集分集、一个电影剧本章节、或一个场次的完整分镜/对白。
- 如果当前部分已经足够长，结尾明确提示用户回复“继续”获取下一部分，而不是硬撑到模型输出上限。
- 当用户回复“继续”时，直接从上次中断处续写，不要重复已经完成的内容。
- 当系统已经为你自动保存当前阶段成果并触发自动续写时，不要要求用户输入“继续”，
  直接基于已保存的尾部衔接信息继续完成后续内容。
- 不要向用户暴露内部机制细节，不要描述“我正在调用内部工具/写入本地记忆/自动续跑”。

【禁止调用的工具清单（严禁触发检索链路）】
- load_knowledgebase
- vesearch

【工作流与输出能力】
1. 背景与基调：从剧本的背景设定入手，提供剧本的基调，如恐怖、爱情、历史、
   悬疑等，并可给出更细分的脚本基调。
2. 主角设定：设定一个或多个主角。通过问答完善角色侧写，包含成长背景、性格特征，
   体现主角的真实性与人性的复杂性。
3. 故事大纲：根据剧本背景、基调、主要角色的信息，生成脚本故事大纲。
4. 确定性质并分集：参考脚本大纲确认剧本性质——电影（通常 90-120 分钟）、
   电视剧（如 18-36 集，每集 30-45 分钟）、短剧（通常 80-100 集，每集约 2 分钟）；
   之后生成分集，包括分镜、场景设定、人物对白等的剧本。
5. 风格化与分级：根据剧本风格与分级，风格化完整剧本。
   - 风格：中式风格（整体包含「起、承、转、合」四个部分）；
           好莱坞风格（整体包含「开端、发展、高潮」三个部分）。
   - 分级：7+、12+、18+（涵盖暴力/性爱等范畴）。

【工具使用指引】
- 当用户要求“记住/保存/沉淀”某段设定、人物小传、世界观约束、对白风格规则时，
  调用 save_local_knowledge 保存到本地 sqlite。
- 当需要回查之前保存的设定/规则/素材时，调用 search_local_knowledge 做检索。
- 需要外部资料时，用 web_search 搜索、web_fetch/link_reader 读取网页内容，
  并在回答中说明关键来源与结论。
- 需要生成分镜概念图、海报、场景参考图时，用 image_generate（Seedream）。
- 需要生成预告/分镜动态演示时，用 video_generate（Seedance）。
- 需要产出 Word / PDF / PPT / HTML 等剧本文档时，调用 create_document：
  传入 doc_format（docx/pdf/pptx/html）、filename、content（正文，"# "/"## " 作标题、
  "- " 作要点；pptx 中每个 "# " 起一页；html 也可直接传完整 HTML 字符串）、可选 title。
- 需要读取/校验此前生成的 Word / PDF / PPT / HTML 文件内容时，调用 read_document，
  传入 path（可用 create_document 返回的路径或纯文件名）。
- 需要运行或验证代码（如脚本统计、数据处理、格式转换）时，用 run_code 直接
  在 AgentKit 沙箱执行；较复杂的编码任务可用 coding 发起沙箱编码工作流。
- 调用工具后，务必用简洁的自然语言向用户说明关键结论，不要只贴原始输出。
"""


# --- 工具装配 ----------------------------------------------------------------
# 防御式加载：任一工具导入失败只跳过该工具并告警，不阻断 Agent 构建 / 容器启动。


def _stringify_tool_errors(result: dict) -> str:
    """把工具返回结果里的各种错误字段拼成一段可分类的文本。"""
    fragments: list[str] = []
    for key in ("error_list", "error_detail_list", "error_details", "error"):
        value = result.get(key)
        if not value:
            continue
        try:
            fragments.append(json.dumps(value, ensure_ascii=False, default=str))
        except Exception:  # noqa: BLE001
            fragments.append(str(value))
    return " ".join(fragments)


def _result_failed(result) -> bool:
    """image_generate/video_generate 以返回值（而非异常）暴露错误。"""
    return isinstance(result, dict) and result.get("status") in ("error", "failed")


def _is_model_related_error(result) -> bool:
    """只有“模型相关错误”（如 ModelNotOpen / AccessDenied）才允许触发降级。

    参数错误、内容审核、额度超限等一律返回 False，避免误降级掩盖真实问题。
    """
    if not _result_failed(result):
        return False
    if result.get("success_list"):  # 本轮已有成功产物，说明不是“模型整体不可用”
        return False
    text = _stringify_tool_errors(result).lower()
    return any(sign in text for sign in _MODEL_ERROR_SIGNS)


def _build_model_chain(caller_model: str | None, primary: str, fallbacks: list[str]) -> list[str]:
    """构造尝试顺序：调用方指定模型（若有）优先，其后接主模型与降级候选，去重保序。"""
    chain: list[str] = []
    if caller_model:
        chain.append(caller_model)
    else:
        chain.append(primary)
    for model in fallbacks:
        if model not in chain:
            chain.append(model)
    return chain


def _wrap_with_model_fallback(raw_tool, *, primary_model, fallback_models, kind):
    """包装 image/video 内置工具：钉主模型 + 仅在模型相关错误时逐级自动降级重试。

    - 保留原工具的签名/名称/文档，让 LLM 看到的调用 schema 不变。
    - 若调用方未显式传 model_name，则默认使用主模型；无论是否显式指定，遇到
      “模型相关错误”都会沿降级链继续重试，直到成功或候选用尽。
    """

    @functools.wraps(raw_tool)
    async def _wrapped(*args, **kwargs):
        chain = _build_model_chain(
            kwargs.get("model_name"), primary_model, fallback_models
        )
        last_result = None
        for idx, model in enumerate(chain):
            kwargs["model_name"] = model
            result = await raw_tool(*args, **kwargs)
            last_result = result

            if not _result_failed(result):
                if idx > 0 and isinstance(result, dict):
                    result.setdefault("model_downgrade_note", "")
                    result["model_used"] = model
                    result["model_downgrade_note"] = (
                        f"检测到 {kind} 主模型不可用（模型相关错误），已自动降级到 {model} 并成功生成。"
                        "请在回复中简要提醒用户此次发生了模型降级。"
                    )
                    logger.warning(
                        "%s downgraded to '%s' and succeeded (attempt %s).",
                        kind, model, idx + 1,
                    )
                return result

            # 失败：仅当是“模型相关错误”且仍有候选时才继续降级。
            if idx < len(chain) - 1 and _is_model_related_error(result):
                logger.warning(
                    "%s model '%s' hit a model-related error; downgrading to '%s'. errors=%s",
                    kind, model, chain[idx + 1], _stringify_tool_errors(result),
                )
                continue

            # 非模型错误，或已到最后一个候选：原样返回，交给上层/用户判断。
            if isinstance(result, dict) and idx > 0:
                result["model_used"] = model
            return result

        return last_result

    # 让 ADK 依旧按原始签名生成 function-calling schema（跟随 __wrapped__）。
    try:
        _wrapped.__signature__ = inspect.signature(raw_tool)
    except (TypeError, ValueError):
        pass
    return _wrapped


def _build_tools() -> list:
    tools: list = []

    from veadk.tools import get_builtin_tool

    # 需要“主模型 + 模型相关错误自动降级”的生成类工具。
    _fallback_config = {
        "image_generate": {
            "primary": _IMAGE_PRIMARY_MODEL,
            "fallbacks": _IMAGE_FALLBACK_MODELS,
            "kind": "图片生成",
        },
        "video_generate": {
            "primary": _VIDEO_PRIMARY_MODEL,
            "fallbacks": _VIDEO_FALLBACK_MODELS,
            "kind": "视频生成",
        },
    }

    # (name, 用途) —— 全部走内置工具；run_code/coding 在 AgentKit sandbox 执行。
    builtin_specs = [
        ("web_search", "网页搜索"),
        ("web_fetch", "网页读取"),
        ("link_reader", "网页链接读取"),
        ("image_generate", "Seedream 生成图片"),
        ("video_generate", "Seedance 生成视频"),
        ("run_code", "AgentKit sandbox 代码执行"),
        ("coding", "AgentKit sandbox 编码工作流"),
    ]
    for name, usage in builtin_specs:
        try:
            tool = get_builtin_tool(name)
            cfg = _fallback_config.get(name)
            if cfg is not None:
                tool = _wrap_with_model_fallback(
                    tool,
                    primary_model=cfg["primary"],
                    fallback_models=cfg["fallbacks"],
                    kind=cfg["kind"],
                )
                logger.info(
                    "Loaded builtin tool '%s' (%s) with primary model '%s' + fallback %s.",
                    name, usage, cfg["primary"], cfg["fallbacks"],
                )
            else:
                logger.info(f"Loaded builtin tool '{name}' ({usage}).")
            tools.append(tool)
        except Exception as e:  # noqa: BLE001 - 单个工具缺失不应导致整体失败
            logger.warning(f"Skip builtin tool '{name}' ({usage}): {e}")

    # word/pdf/ppt/html 的“生成与读取”走沙箱兜底方案（create_document / read_document）。
    # 说明：账号 AgentKit sandbox 为纯 CodeEnv、无 skill 中心运行器，execute_skills 无法
    # 加载 docx/pdf-processing-pro 技能包；改为在同一沙箱内用镜像内置库真实生成并读回。
    try:
        from .document_tools import create_document, read_document

        tools.append(create_document)
        tools.append(read_document)
        logger.info(
            "Loaded document tools 'create_document'/'read_document' "
            "(sandbox docx/pdf/pptx/html 生成与读取)."
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Skip document tools (create_document/read_document): {e}")

    return tools


def save_local_knowledge(
    title: str,
    content: str,
    tool_context: ToolContext | None = None,
) -> dict:
    """Save user-provided story knowledge to local sqlite.

    Args:
        title: A short title for this knowledge entry.
        content: The full content to save.
    Returns:
        A dict with ok/id/store fields.
    """
    if tool_context is None:
        return {"ok": False, "message": "tool_context missing"}

    session = tool_context.session
    saved_id = local_knowledge_store.save(
        app_name=session.app_name,
        user_id=tool_context.user_id,
        session_id=session.id,
        title=title,
        content=content,
    )
    if saved_id is None:
        return {"ok": False, "message": "empty title/content"}

    return {
        "ok": True,
        "id": saved_id,
        "store": "sqlite",
    }


def search_local_knowledge(
    query: str,
    limit: int = 5,
    tool_context: ToolContext | None = None,
) -> dict:
    """Search saved local knowledge entries by keyword.

    Args:
        query: Keyword to search in title/content.
        limit: Max results to return (1-20).
    Returns:
        A dict with ok/store/query/results fields.
    """
    if tool_context is None:
        return {"ok": False, "message": "tool_context missing"}

    session = tool_context.session
    results = local_knowledge_store.search(
        app_name=session.app_name,
        user_id=tool_context.user_id,
        session_id=session.id,
        query=query,
        limit=limit,
    )
    return {
        "ok": True,
        "store": "sqlite",
        "query": query,
        "results": results,
    }


def _extract_user_text_from_context(callback_context) -> str:
    user_content = getattr(callback_context, "user_content", None)
    if not user_content or not getattr(user_content, "parts", None):
        return ""

    text_parts: list[str] = []
    for part in user_content.parts:
        text = getattr(part, "text", None)
        if text:
            text_parts.append(text)
    return "\n".join(text_parts).strip()


def _is_continue_request(text: str) -> bool:
    return bool(text and _CONTINUE_RE.search(text))


def _append_text_part(content: types.Content | None, text: str) -> types.Content:
    if content and content.parts:
        parts = list(content.parts)
        parts.append(types.Part.from_text(text=text))
        return types.Content(role=content.role or "model", parts=parts)
    return types.Content(role="model", parts=[types.Part.from_text(text=text)])


def _append_function_call_part(
    content: types.Content | None,
    *,
    name: str,
    args: dict,
    call_id: str,
) -> types.Content:
    parts = list(content.parts) if content and content.parts else []
    parts.append(
        types.Part(
            function_call=types.FunctionCall(
                id=call_id,
                name=name,
                args=args,
            )
        )
    )
    role = content.role if content and content.role else "model"
    return types.Content(role=role, parts=parts)


def _is_control_fragment(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    return bool(_CONTROL_FRAGMENT_RE.fullmatch(stripped))


def _extract_model_text(content: types.Content | None) -> str:
    if not content or not content.parts:
        return ""

    texts: list[str] = []
    for part in content.parts:
        text = getattr(part, "text", None)
        if (
            text
            and not getattr(part, "thought", False)
            and not _is_control_fragment(text)
        ):
            texts.append(text)
    return "\n".join(texts).strip()


def _strip_forbidden_tool_calls(
    content: types.Content | None,
) -> tuple[types.Content | None, list[str]]:
    if not content or not content.parts:
        return content, []

    blocked: list[str] = []
    kept_parts: list[types.Part] = []
    for part in content.parts:
        function_call = getattr(part, "function_call", None)
        function_name = getattr(function_call, "name", None) if function_call else None
        if function_name in _FORBIDDEN_RETRIEVAL_TOOL_NAMES:
            blocked.append(str(function_name))
            continue
        kept_parts.append(part)

    if not blocked:
        return content, []

    role = content.role if content.role else "model"
    return types.Content(role=role, parts=kept_parts), blocked


def _merge_visible_text(existing: str, incoming: str) -> str:
    if not incoming:
        return existing
    if not existing:
        return incoming
    if incoming.startswith(existing):
        return incoming
    if existing.endswith(incoming):
        return existing
    max_overlap = min(len(existing), len(incoming))
    for overlap in range(max_overlap, 0, -1):
        if existing.endswith(incoming[:overlap]):
            return f"{existing}{incoming[overlap:]}"
    return f"{existing}{incoming}"


def _ensure_request_state(callback_context) -> str:
    current_invocation_id = callback_context.invocation_id
    active_invocation_id = callback_context.state.get("temp:active_invocation_id")
    if active_invocation_id == current_invocation_id:
        request_id = callback_context.state.get("temp:active_request_id")
        if request_id:
            return request_id

    request_id = f"{current_invocation_id}-{uuid.uuid4().hex[:8]}"
    callback_context.state["temp:active_invocation_id"] = current_invocation_id
    callback_context.state["temp:active_request_id"] = request_id
    callback_context.state["temp:auto_continue_count"] = 0
    callback_context.state["temp:auto_continue_active"] = False
    callback_context.state["temp:auto_continue_tail"] = ""
    callback_context.state["temp:active_chunk_index"] = 0
    callback_context.state["temp:current_output_buffer"] = ""
    callback_context.state["temp:last_output_truncated"] = False
    callback_context.state["temp:last_output_can_continue"] = False
    callback_context.state["temp:last_checkpoint_signature"] = ""
    return request_id


def _save_output_checkpoint(
    callback_context,
    *,
    content_text: str,
    truncated: bool,
    finish_reason: str = "",
) -> None:
    if not content_text.strip():
        return

    request_id = _ensure_request_state(callback_context)
    checkpoint_signature = "|".join(
        [
            str(callback_context.invocation_id),
            request_id,
            "1" if truncated else "0",
            finish_reason,
            content_text,
        ]
    )
    if checkpoint_signature == str(
        callback_context.state.get("temp:last_checkpoint_signature", "")
    ):
        logger.info(
            "Skip duplicate checkpoint: invocation_id=%s request_id=%s",
            callback_context.invocation_id,
            request_id,
        )
        return

    next_chunk_index = int(callback_context.state.get("temp:active_chunk_index", 0)) + 1
    callback_context.state["temp:active_chunk_index"] = next_chunk_index

    continuation_store.save_chunk(
        app_name=callback_context.session.app_name,
        user_id=callback_context.user_id,
        session_id=callback_context.session.id,
        request_id=request_id,
        chunk_index=next_chunk_index,
        content=content_text,
        truncated=truncated,
        finish_reason=finish_reason,
    )
    callback_context.state["temp:last_checkpoint_signature"] = checkpoint_signature
    logger.info(
        "Saved checkpoint: invocation_id=%s request_id=%s chunk_index=%s truncated=%s finish_reason=%s chars=%s",
        callback_context.invocation_id,
        request_id,
        next_chunk_index,
        truncated,
        finish_reason,
        len(content_text),
    )


def _build_truncation_notice() -> str:
    return (
        "\n\n---\n"
        "## 【输出已截断】\n\n"
        "本轮内容已按**单次输出预算**主动截断，以避免 Agent 因触发模型输出上限而中止。\n\n"
        "- 直接回复：`继续`\n"
        "- 更精确地继续：`继续第 2 部分` / `继续后 3 集` / `继续下一幕`\n\n"
        "> 说明：这不是报错，而是为了保证 long run 可以稳定续写。\n"
    )


def _before_model_budget_guard(callback_context, llm_request: LlmRequest):
    """为每次模型调用注入单轮输出预算与分段生成约束。"""
    request_id = _ensure_request_state(callback_context)
    user_text = _extract_user_text_from_context(callback_context)
    is_continue = _is_continue_request(user_text)
    is_auto_continue = bool(callback_context.state.get("temp:auto_continue_active"))
    output_budget = (
        _CONTINUATION_MAX_OUTPUT_TOKENS
        if (is_continue or is_auto_continue)
        else _DEFAULT_MAX_OUTPUT_TOKENS
    )

    if llm_request.config.max_output_tokens is None:
        llm_request.config.max_output_tokens = output_budget
    else:
        llm_request.config.max_output_tokens = min(
            llm_request.config.max_output_tokens, output_budget
        )

    budget_instruction = [
        f"本轮输出预算上限为 {llm_request.config.max_output_tokens} tokens。",
        "如果任务天然很长，只交付当前阶段或当前片段，不要尝试一次性输出完整长篇结果。",
        "当本轮内容接近上限时，主动收束，并明确提示用户回复“继续”获取下一部分。",
    ]
    if is_continue:
        budget_instruction.append(
            "本轮是续写场景：从上一轮停止的位置继续，不要复述已完成的内容。"
        )
    if is_auto_continue:
        memory_tail = callback_context.state.get("temp:auto_continue_tail", "")
        continue_count = int(callback_context.state.get("temp:auto_continue_count", 0))
        budget_instruction.extend(
            [
                f"当前处于系统自动续写模式，第 {continue_count} 次自动续写。",
                "你已经将前面生成的有效内容写入本地长记忆；不要重复输出已经完成的内容。",
                "请从最近停止的位置继续生成，直接延续上一段，不要重新起标题，不要从头总结。",
            ]
        )
        if memory_tail:
            budget_instruction.append(
                "以下是最近已保存内容的尾部片段，只用于衔接上下文，不要原样重复：\n"
                f"{memory_tail}"
            )

    callback_context.state["temp:active_request_id"] = request_id
    llm_request.append_instructions(budget_instruction)
    return None


def _after_model_truncation_guard(callback_context, llm_response: LlmResponse):
    """把 MAX_TOKENS 从失败态改造成“可继续”的成功响应，避免 long run 直接中断。"""
    finish_reason = getattr(llm_response, "finish_reason", None)
    finish_reason_value = (
        finish_reason.value if hasattr(finish_reason, "value") else finish_reason
    )
    content_text = _extract_model_text(llm_response.content)
    existing_buffer = str(callback_context.state.get("temp:current_output_buffer", ""))
    merged_buffer = _merge_visible_text(existing_buffer, content_text)
    callback_context.state["temp:current_output_buffer"] = merged_buffer
    is_truncated = (
        llm_response.error_code == "MAX_TOKENS"
        or finish_reason_value == "MAX_TOKENS"
    )

    logger.info(
        "after_model: invocation_id=%s partial=%s truncated=%s finish_reason=%s text_chars=%s buffer_chars=%s auto_continue_count=%s",
        callback_context.invocation_id,
        llm_response.partial,
        is_truncated,
        finish_reason_value,
        len(content_text),
        len(merged_buffer),
        callback_context.state.get("temp:auto_continue_count", 0),
    )

    if llm_response.partial:
        return None

    cleaned_content, blocked_tools = _strip_forbidden_tool_calls(llm_response.content)
    if blocked_tools:
        callback_context.state["temp:last_output_truncated"] = False
        callback_context.state["temp:last_output_can_continue"] = False
        callback_context.state["temp:auto_continue_active"] = False
        callback_context.state["temp:current_output_buffer"] = ""

        blocked_message = (
            "已严格禁止触发任何检索链路，因此不会调用以下工具："
            f"{', '.join(blocked_tools)}。"
            "请提供你希望我参考的具体信息，或让我使用本地已保存知识（search_local_knowledge）进行回查。"
        )
        patched_content = _append_text_part(cleaned_content, blocked_message)
        return llm_response.model_copy(
            update={
                "content": patched_content,
                "error_code": None,
                "error_message": None,
                "custom_metadata": {
                    **(llm_response.custom_metadata or {}),
                    "forbidden_retrieval_tool_call_blocked": True,
                    "blocked_tools": blocked_tools,
                },
            }
        )

    if not is_truncated:
        _save_output_checkpoint(
            callback_context,
            content_text=merged_buffer,
            truncated=False,
            finish_reason=str(finish_reason_value or ""),
        )
        callback_context.state["temp:last_output_truncated"] = False
        callback_context.state["temp:last_output_can_continue"] = False
        callback_context.state["temp:auto_continue_active"] = False
        callback_context.state["temp:current_output_buffer"] = ""
        callback_context.state["temp:auto_continue_tail"] = continuation_store.tail_chars(
            app_name=callback_context.session.app_name,
            user_id=callback_context.user_id,
            session_id=callback_context.session.id,
            request_id=callback_context.state.get("temp:active_request_id", ""),
            max_chars=_AUTO_CONTINUE_TAIL_CHARS,
        )
        return None

    _save_output_checkpoint(
        callback_context,
        content_text=merged_buffer,
        truncated=True,
        finish_reason=str(finish_reason_value or "MAX_TOKENS"),
    )
    callback_context.state["temp:current_output_buffer"] = ""
    callback_context.state["temp:last_output_truncated"] = True
    callback_context.state["temp:last_output_can_continue"] = True
    auto_continue_count = int(callback_context.state.get("temp:auto_continue_count", 0)) + 1
    callback_context.state["temp:auto_continue_count"] = auto_continue_count

    request_id = callback_context.state.get("temp:active_request_id", "")
    callback_context.state["temp:auto_continue_tail"] = continuation_store.tail_chars(
        app_name=callback_context.session.app_name,
        user_id=callback_context.user_id,
        session_id=callback_context.session.id,
        request_id=request_id,
        max_chars=_AUTO_CONTINUE_TAIL_CHARS,
    )

    if auto_continue_count > _AUTO_CONTINUE_MAX_STEPS:
        callback_context.state["temp:auto_continue_active"] = False
        patched_content = _append_text_part(
            llm_response.content,
            _build_truncation_notice(),
        )
        return llm_response.model_copy(
            update={
                "content": patched_content,
                "error_code": None,
                "error_message": None,
                "custom_metadata": {
                    **(llm_response.custom_metadata or {}),
                    "truncated_by_budget_guard": True,
                    "truncation_reason": "MAX_TOKENS",
                    "auto_continue_attempted": auto_continue_count,
                    "auto_continue_limit_reached": True,
                },
            }
        )

    callback_context.state["temp:auto_continue_active"] = True

    patched_content = _append_function_call_part(
        llm_response.content,
        name="auto_continue_generation",
        args={
            "request_id": request_id,
            "continue_count": auto_continue_count,
            "tail_chars": _AUTO_CONTINUE_TAIL_CHARS,
        },
        call_id=f"auto-continue-{auto_continue_count}",
    )
    return llm_response.model_copy(
        update={
            "content": patched_content,
            "error_code": None,
            "error_message": None,
            "custom_metadata": {
                **(llm_response.custom_metadata or {}),
                "truncated_by_budget_guard": True,
                "truncation_reason": "MAX_TOKENS",
                "auto_continue_triggered": True,
                "auto_continue_attempted": auto_continue_count,
            },
        }
    )


def _on_model_error_budget_guard(callback_context, llm_request: LlmRequest, error: Exception):
    """兜底处理真正抛出的 MAX_TOKENS 异常，避免整轮失败。"""
    error_text = f"{type(error).__name__}: {error}"
    if "MAX_TOKENS" not in error_text:
        return None

    callback_context.state["temp:last_output_truncated"] = True
    callback_context.state["temp:last_output_can_continue"] = True
    callback_context.state["temp:auto_continue_active"] = False

    fallback_text = (
        "## 【输出已截断】\n\n"
        "当前任务在这一轮触发了模型单次输出上限。"
        "我已停止继续扩写，以避免整个任务中断。\n\n"
        "- 直接回复：`继续`\n"
        "- 或指定粒度：`继续下一幕` / `继续后 2 集` / `继续第 2 部分`\n\n"
        "这不是报错，而是为了让长任务可以稳定续写。"
    )
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=fallback_text)],
        ),
        custom_metadata={
            "truncated_by_budget_guard": True,
            "truncation_reason": "MAX_TOKENS_EXCEPTION",
        },
    )


def auto_continue_generation(
    request_id: str,
    continue_count: int,
    tail_chars: int = _AUTO_CONTINUE_TAIL_CHARS,
    tool_context: ToolContext | None = None,
) -> dict:
    """Save and expose local-memory checkpoint metadata for automatic continuation."""
    if tool_context is None:
        return {"ok": False, "message": "tool_context missing"}

    session = tool_context.session
    memory_tail = continuation_store.tail_chars(
        app_name=session.app_name,
        user_id=tool_context.user_id,
        session_id=session.id,
        request_id=request_id,
        max_chars=tail_chars,
    )
    chunk_count = continuation_store.count_chunks(
        app_name=session.app_name,
        user_id=tool_context.user_id,
        session_id=session.id,
        request_id=request_id,
    )
    if chunk_count == 0:
        buffered_output = str(tool_context.state.get("temp:current_output_buffer", ""))
        if buffered_output.strip():
            next_chunk_index = int(tool_context.state.get("temp:active_chunk_index", 0)) + 1
            continuation_store.save_chunk(
                app_name=session.app_name,
                user_id=tool_context.user_id,
                session_id=session.id,
                request_id=request_id,
                chunk_index=next_chunk_index,
                content=buffered_output,
                truncated=True,
                finish_reason="MAX_TOKENS_BUFFERED",
            )
            tool_context.state["temp:active_chunk_index"] = next_chunk_index
            tool_context.state["temp:last_checkpoint_signature"] = "|".join(
                [
                    str(tool_context.invocation_id),
                    request_id,
                    "1",
                    "MAX_TOKENS_BUFFERED",
                    buffered_output,
                ]
            )
            logger.info(
                "Buffered fallback checkpoint: invocation_id=%s request_id=%s chunk_index=%s chars=%s",
                tool_context.invocation_id,
                request_id,
                next_chunk_index,
                len(buffered_output),
            )
            chunk_count = 1
            memory_tail = continuation_store.tail_chars(
                app_name=session.app_name,
                user_id=tool_context.user_id,
                session_id=session.id,
                request_id=request_id,
                max_chars=tail_chars,
            )

    logger.info(
        "auto_continue tool: invocation_id=%s request_id=%s continue_count=%s chunk_count=%s tail_chars=%s",
        tool_context.invocation_id,
        request_id,
        continue_count,
        chunk_count,
        len(memory_tail),
    )

    tool_context.state["temp:auto_continue_active"] = True
    tool_context.state["temp:auto_continue_count"] = continue_count
    tool_context.state["temp:auto_continue_tail"] = memory_tail
    tool_context.state["temp:active_request_id"] = request_id

    return {
        "ok": True,
        "request_id": request_id,
        "continue_count": continue_count,
        "chunk_count": chunk_count,
        "checkpoint_store": "sqlite",
        "memory_tail": memory_tail,
        "instruction": (
            "已从本地长记忆加载最近输出尾部。"
            "请从上一段停止的位置继续，不要重复已经完成的内容。"
        ),
    }


# `root_agent` 是 veADK Frontend 与 ADK server 查找的名字；Agent name 必须是合法标识符。
root_agent = Agent(
    name="movie_script_agent",
    description="专业电影剧本智能助手：从基调、角色、大纲到分集分镜与风格化分级的一站式创作。",
    instruction=INSTRUCTION,
    tools=[
        *_build_tools(),
        save_local_knowledge,
        search_local_knowledge,
        auto_continue_generation,
    ],
    generate_content_config=types.GenerateContentConfig(
        max_output_tokens=_DEFAULT_MAX_OUTPUT_TOKENS,
    ),
    before_model_callback=_before_model_budget_guard,
    after_model_callback=_after_model_truncation_guard,
    on_model_error_callback=_on_model_error_budget_guard,
)

"""简历导入接口：预览不写库，确认才创建或补充个人档案。"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import ensure_request_id
from app.core.database import Database, get_database, get_session
from app.core.errors import AppError, ErrorCode
from app.core.responses import ApiError, ApiErrorResponse, ApiResponse, ResponseMeta, success

from . import import_service
from .import_service import ImportApplyRead, ImportConfirmRequest, ImportPreviewRead, ResumeUpload

router = APIRouter(prefix="/profile", tags=["profile"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
DatabaseDep = Annotated[Database, Depends(get_database)]
logger = logging.getLogger(__name__)


class ImportPreviewRequest(ResumeUpload):
    """明确同意外部发送后才开始解析与推理。"""

    confirm_external: bool = Field(description="确认发送从文件提取的简历文字到已配置的大模型服务。")


@router.post(
    "/import-preview",
    summary="预览 AI 简历导入候选",
    description=(
        "接收不超过 3 MB 的 PDF/HTML，仅本地提取文字；需 confirm_external 才发送文字到已配置的大模型服务。"
        "返回带原文摘录的候选（基本信息、技能、工作经历、项目经历、教育经历），不写入数据库。"
        "根协议错误返回 422；集合条目分别做严格结构与原文校验，失败项不会进入候选，"
        "并通过 completeness/rejected_items 返回。"
        "项目名称与摘录有效时，其余缺少证据的字段会被清空并通过 warnings 提示，保留项目骨架；"
        "模型以 title 等等价字段表示项目名称或把技术栈写成字符串时，先归一化再按同样规则校验，并在 warnings 中说明。"
        "仅对短暂连接、429 与 5xx 失败自动重试一次；格式、超时和证据失败不重试。大模型服务未配置返回 409。"
    ),
    response_model=ApiResponse[ImportPreviewRead],
)
async def preview_import(session: SessionDep, payload: ImportPreviewRequest) -> ApiResponse[ImportPreviewRead]:
    """返回待人工核对的档案候选，不保存原文件或模型输出。"""
    result = await import_service.preview(session, payload, confirm_external=payload.confirm_external)
    return success(result)


def _stream_event(event: str, data: object) -> str:
    """把固定阶段或统一响应封装为一条 SSE 消息。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post(
    "/import-preview-stream",
    summary="流式预览 AI 简历导入候选",
    description=(
        "输入和确认要求与 /import-preview 相同。text/event-stream 依次返回 progress 阶段码，"
        "最后返回 result（统一成功响应）或 error（统一错误响应，含 request_id）。"
        "流开始后的业务失败以 error 事件表达；请求体无效仍按普通 422 响应。预览不写库。"
    ),
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "阶段事件与最终结果。"}},
)
async def preview_import_stream(database: DatabaseDep, payload: ImportPreviewRequest) -> StreamingResponse:
    """同一次 HTTP 请求中报告真实处理阶段，最终返回候选或安全错误。"""
    request_id = ensure_request_id()

    async def stream() -> AsyncIterator[str]:
        """消费后台预览任务的阶段消息；断开连接时取消等待。"""
        queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()

        async def report(stage: str) -> None:
            """仅把固定阶段码放入流，不传业务数据。"""
            await queue.put(("progress", {"stage": stage}))

        async def run_preview() -> None:
            """在独立会话内完成只读预览，并把最终响应放入队列。"""
            try:
                async with database.session() as session:
                    result = await import_service.preview(
                        session, payload, confirm_external=payload.confirm_external, on_progress=report
                    )
                envelope = ApiResponse[ImportPreviewRead](data=result, meta=ResponseMeta(request_id=request_id))
                await queue.put(("result", envelope.model_dump(mode="json")))
            except AppError as error:
                envelope = ApiErrorResponse(
                    error=ApiError(code=str(error.code), message=error.message, details=error.details),
                    meta=ResponseMeta(request_id=request_id),
                )
                await queue.put(("error", {**envelope.model_dump(mode="json"), "http_status": error.status_code}))
            except Exception as error:
                logger.error(
                    "流式导入预览发生未预期错误",
                    extra={"event": "profile_import_stream_error", "exception_type": type(error).__name__},
                )
                envelope = ApiErrorResponse(
                    error=ApiError(code=str(ErrorCode.INTERNAL_ERROR), message="服务器内部错误，请稍后重试。"),
                    meta=ResponseMeta(request_id=request_id),
                )
                await queue.put(("error", {**envelope.model_dump(mode="json"), "http_status": 500}))

        task = asyncio.create_task(run_preview())
        try:
            yield _stream_event("progress", {"stage": "received"})
            while True:
                try:
                    event, data = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield _stream_event(event, data)
                if event in {"result", "error"}:
                    break
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Request-ID": request_id},
    )


@router.post(
    "/import-confirm",
    summary="确认导入个人档案",
    description=(
        "重传原文件并核对哈希与摘录；仅 confirmed=true 且选中项有效时写入。"
        "候选可由用户在预览界面修正：字段值仍在原文摘录内的条目挂简历证据，"
        "被改到摘录之外的条目改挂『本人陈述』证据，两类都标记未验证。"
        "无档案时创建，有档案时只补充未重复的技能、工作经历、项目经历和教育经历，不覆盖根信息。"
        "无确认/文件无效/摘录无法定位到原文返回 422，文件变化返回 409。"
    ),
    response_model=ApiResponse[ImportApplyRead],
    status_code=status.HTTP_201_CREATED,
)
async def confirm_import(session: SessionDep, payload: ImportConfirmRequest) -> ApiResponse[ImportApplyRead]:
    """将用户已核对的导入条目在一次事务中写入档案。"""
    result = await import_service.apply(session, payload)
    return success(result)

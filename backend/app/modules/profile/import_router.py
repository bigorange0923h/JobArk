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

    confirm_external: bool = Field(description="确认发送从文件提取的简历文字到已配置的 AI 网关。")


@router.post(
    "/import-preview",
    summary="预览 AI 简历导入候选",
    description=(
        "接收不超过 3 MB 的 PDF/HTML，仅本地提取文字；需 confirm_external 才发送文字到已配置 AI 网关。"
        "返回带原文摘录的候选，不写入数据库。格式/摘录无效返回 422，网关未配置返回 409。"
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
        "无档案时创建，有档案时只补充未重复的技能、工作和教育经历，不覆盖根信息；"
        "候选与来源证据标记未验证。无确认/文件无效返回 422，文件变化返回 409。"
    ),
    response_model=ApiResponse[ImportApplyRead],
    status_code=status.HTTP_201_CREATED,
)
async def confirm_import(session: SessionDep, payload: ImportConfirmRequest) -> ApiResponse[ImportApplyRead]:
    """将用户已核对的导入条目在一次事务中写入档案。"""
    result = await import_service.apply(session, payload)
    return success(result)

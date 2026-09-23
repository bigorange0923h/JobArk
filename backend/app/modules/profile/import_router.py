"""简历导入接口：预览不写库，确认才创建或补充个人档案。"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.responses import ApiResponse, success

from . import import_service
from .import_service import ImportApplyRead, ImportConfirmRequest, ImportPreviewRead, ResumeUpload

router = APIRouter(prefix="/profile", tags=["profile"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


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

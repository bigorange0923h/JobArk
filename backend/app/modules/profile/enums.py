"""Profile 领域的枚举取值。

这些取值同时是数据库 CHECK 约束的取值集合（见 `models.py` 中 `native_enum=False` 的说明）：
新增取值必须同时修改本文件与迁移，否则写入会在数据库层被拒绝——这是有意的，
它保证"数据真实性"约束不依赖应用层是否记得校验。
"""

from enum import StrEnum


class ClaimStatus(StrEnum):
    """主张的验证状态。

    用于落实"不确定信息必须明确标记，不能伪装为已验证事实"：数据库层强制
    `VERIFIED` 必须挂有来源证据，因此无法仅靠改一个字符串把无凭据的陈述标成已核验。
    """

    VERIFIED = "VERIFIED"
    """有可核验的客观凭据支撑（证据记录或外部可验证链接）。"""

    UNVERIFIED = "UNVERIFIED"
    """仅本人陈述，尚无凭据。"""

    UNCERTAIN = "UNCERTAIN"
    """信息本身不确定，需要后续确认。"""


class EvidenceSourceType(StrEnum):
    """证据来源类别，对应 `docs/data-model.md` 3.2 的初始取值。"""

    MANUAL_DECLARATION = "MANUAL_DECLARATION"
    """用户手工陈述，无外部凭据。"""

    RESUME_DOCUMENT = "RESUME_DOCUMENT"
    """来自历史简历文档。"""

    WORK_PROOF = "WORK_PROOF"
    """工作产出或任职证明。"""

    PROJECT_LINK = "PROJECT_LINK"
    """项目链接（仓库、上线地址等）。"""

    CERTIFICATE = "CERTIFICATE"
    """证书或资质。"""

    OTHER = "OTHER"
    """其他来源，需在 content 中说明。"""


class VerificationStatus(StrEnum):
    """证据自身的可核验程度。"""

    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    UNCERTAIN = "UNCERTAIN"


class SkillProficiency(StrEnum):
    """技能熟练度分级。

    注意:
        这是用于排序与展示的主观分级，不构成事实主张，因此不参与 `claim_status` 的判定。
    """

    BASIC = "BASIC"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"
    EXPERT = "EXPERT"


class RemotePreference(StrEnum):
    """远程工作偏好；属于可变规则，不是履历事实。"""

    ANY = "ANY"
    ONSITE = "ONSITE"
    HYBRID = "HYBRID"
    REMOTE = "REMOTE"

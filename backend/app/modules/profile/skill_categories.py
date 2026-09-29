"""技能导入时的保守分类建议；分类不是简历原文事实。"""

SKILL_CATEGORIES: tuple[str, ...] = (
    "编程语言", "前端开发", "后端开发", "AI 应用", "数据库", "中间件", "开发工具", "其他",
)

# 仅精确匹配语义稳定的常见名称；Redis 等跨类技能以及未知名称保持未分类。
_KNOWN_SKILLS: dict[str, str] = {
    "python": "编程语言",
    "java": "编程语言",
    "javascript": "编程语言",
    "typescript": "编程语言",
    "go": "编程语言",
    "golang": "编程语言",
    "rust": "编程语言",
    "kotlin": "编程语言",
    "vue": "前端开发",
    "vue.js": "前端开发",
    "vue3": "前端开发",
    "react": "前端开发",
    "angular": "前端开发",
    "spring boot": "后端开发",
    "spring cloud": "后端开发",
    "django": "后端开发",
    "fastapi": "后端开发",
    "flask": "后端开发",
    "langchain": "AI 应用",
    "langgraph": "AI 应用",
    "pytorch": "AI 应用",
    "tensorflow": "AI 应用",
    "postgresql": "数据库",
    "mysql": "数据库",
    "oracle": "数据库",
    "mongodb": "数据库",
    "sqlite": "数据库",
    "kafka": "中间件",
    "rabbitmq": "中间件",
    "rocketmq": "中间件",
    "git": "开发工具",
    "docker": "开发工具",
    "kubernetes": "开发工具",
    "jenkins": "开发工具",
    "maven": "开发工具",
    "gradle": "开发工具",
}


def suggest_skill_category(name: str) -> str | None:
    """按完整技能名给出建议；模糊或跨类名称返回空，让用户决定。"""
    return _KNOWN_SKILLS.get(" ".join(name.casefold().split()))

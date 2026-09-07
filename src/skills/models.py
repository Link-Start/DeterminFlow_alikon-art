"""
Skill 数据模型
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    if isinstance(value, str):
        return [item for item in value.replace(",", " ").split() if item]
    return []


class SkillCategory(str, Enum):
    """Skill 分类"""
    UNCATEGORIZED = "uncategorized"  # 未分类（仅本地使用）
    GENERAL = "general"           # 通用技能
    CODING = "coding"             # 编码相关
    RESEARCH = "research"         # 研究分析
    COMMUNICATION = "communication"  # 沟通协作
    MEMORY = "memory"             # 记忆管理
    WORKFLOW = "workflow"         # 工作流程
    DOMAIN = "domain"             # 领域知识


@dataclass
class Skill:
    """
    Skill 定义模型

    Attributes:
        id: 唯一标识符（通常为文件名，如 "python_best_practices"）
        name: 显示名称
        description: 简短描述
        content: 完整内容（markdown 格式）
        category: 分类
        agent_types: 适用的 agent 类型列表，空列表表示适用所有类型
        priority: 优先级（数字越大越优先，影响注入顺序）
        tags: 标签列表
        enabled: 是否启用
        version: 版本号
        author: 作者
        created_at: 创建时间
        updated_at: 更新时间
        metadata: 额外元数据
    """
    id: str
    name: str
    description: str
    content: str
    category: SkillCategory | str = SkillCategory.UNCATEGORIZED
    agent_types: list[str] = field(default_factory=list)  # 空列表 = 适用所有
    workflow_only: bool = False
    priority: int = 50  # 0-100，默认 50
    tags: list[str] = field(default_factory=list)
    enabled: bool = True
    version: str = ""
    author: str = ""
    language: str = ""
    scope: str = "all"
    license: str = ""
    compatibility: str = ""
    requires_core: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    required_plugins: list[str] = field(default_factory=list)
    required_apps: list[str] = field(default_factory=list)
    manifest_metadata: dict[str, Any] = field(default_factory=dict)
    frontmatter_extra: dict[str, Any] = field(default_factory=dict)
    validation_warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def matches_agent_type(self, agent_type: str) -> bool:
        """判断此 skill 是否适用于指定的 agent 类型"""
        if not self.agent_types:  # 空列表表示适用所有
            return True
        return agent_type in self.agent_types

    def to_dict(self) -> dict:
        """序列化为字典"""
        category = (
            self.category.value
            if isinstance(self.category, SkillCategory)
            else str(self.category)
        )
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "content": self.content,
            "category": category,
            "agent_types": self.agent_types,
            "workflow_only": self.workflow_only,
            "priority": self.priority,
            "tags": self.tags,
            "enabled": self.enabled,
            "version": self.version,
            "author": self.author,
            "language": self.language,
            "scope": self.scope,
            "license": self.license,
            "compatibility": self.compatibility,
            "requires_core": self.requires_core,
            "allowed_tools": self.allowed_tools,
            "required_tools": self.required_tools,
            "required_plugins": self.required_plugins,
            "required_apps": self.required_apps,
            "manifest_metadata": self.manifest_metadata,
            "frontmatter_extra": self.frontmatter_extra,
            "validation_warnings": self.validation_warnings,
            "provenance": self.metadata.get("provenance"),
            "local_modified": self.metadata.get("local_modified", False),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Skill":
        """从字典反序列化"""
        category = data.get("category", SkillCategory.UNCATEGORIZED.value)
        if isinstance(category, str):
            try:
                category = SkillCategory(category)
            except ValueError:
                category = category.strip() or SkillCategory.UNCATEGORIZED

        scope = str(data.get("scope") or "").strip().lower()
        if scope not in {"all", "workflow"}:
            scope = "workflow" if data.get("workflow_only", False) else "all"

        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            content=data.get("content", ""),
            category=category,
            agent_types=_list_value(data.get("agent_types", [])),
            workflow_only=data.get("workflow_only", scope == "workflow"),
            priority=data.get("priority", 50),
            tags=_list_value(data.get("tags", [])),
            enabled=data.get("enabled", True),
            version=data.get("version", ""),
            author=data.get("author", ""),
            language=data.get("language", ""),
            scope=scope,
            license=data.get("license", ""),
            compatibility=data.get("compatibility", ""),
            requires_core=data.get("requires_core", ""),
            allowed_tools=_list_value(data.get("allowed_tools", [])),
            required_tools=_list_value(data.get("required_tools", [])),
            required_plugins=_list_value(data.get("required_plugins", [])),
            required_apps=_list_value(data.get("required_apps", [])),
            manifest_metadata=dict(data.get("manifest_metadata", {})),
            frontmatter_extra=dict(data.get("frontmatter_extra", {})),
            validation_warnings=list(data.get("validation_warnings", [])),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
            metadata=data.get("metadata", {}),
        )

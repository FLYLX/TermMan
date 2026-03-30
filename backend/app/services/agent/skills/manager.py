import logging
import re
import shutil
from pathlib import Path
from typing import Any

from .definition import SkillDefinition, TriggerConfig, ActionConfig, SafetyConfig
from .loader import SkillLoader

logger = logging.getLogger(__name__)


class SkillManager:

    def __init__(self, loader: SkillLoader | None = None):
        self._loader = loader or __import__("app.services.agent.skills", fromlist=["skill_loader"]).skill_loader
        self.skills_dir = self._loader.skills_dir

    def _get_skill_dir_name(self, skill_id: str) -> str:
        skill = self._loader.get(skill_id)
        return skill.skill_dir if skill and skill.skill_dir else skill_id

    def _find_skill_file(self, skill_dir: Path) -> Path | None:
        for f in skill_dir.iterdir():
            if f.is_file() and f.suffix.lower() == ".md":
                return f
        return None

    def create_skill(
        self,
        skill_id: str,
        name: str,
        description: str = "",
        category: str = "general",
        trigger: dict[str, Any] | None = None,
        action: dict[str, Any] | None = None,
        safety: dict[str, Any] | None = None,
        content: str = "",
    ) -> SkillDefinition:
        skill_dir = self.skills_dir / skill_id
        if skill_dir.exists():
            raise ValueError(f"Skill '{skill_id}' already exists")

        skill_dir.mkdir(parents=True, exist_ok=True)

        frontmatter = self._build_frontmatter(
            skill_id=skill_id,
            name=name,
            description=description,
            category=category,
            trigger=trigger,
            action=action,
            safety=safety,
        )

        skill_content = f"---\n{frontmatter}\n---\n\n{content}"
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(skill_content, encoding="utf-8")

        (skill_dir / "scripts").mkdir(exist_ok=True)
        (skill_dir / "templates").mkdir(exist_ok=True)
        (skill_dir / "Resources").mkdir(exist_ok=True)
        (skill_dir / "examples").mkdir(exist_ok=True)

        self._loader.reload()

        skill = self._loader.get(skill_id)
        if not skill:
            raise RuntimeError(f"Failed to load created skill '{skill_id}'")

        logger.info(f"[SkillManager] Created skill '{skill_id}'")
        return skill

    def update_skill(
        self,
        skill_id: str,
        name: str | None = None,
        description: str | None = None,
        category: str | None = None,
        trigger: dict[str, Any] | None = None,
        action: dict[str, Any] | None = None,
        safety: dict[str, Any] | None = None,
        content: str | None = None,
    ) -> SkillDefinition:
        skill = self._loader.get(skill_id)
        if not skill:
            raise ValueError(f"Skill '{skill_id}' not found")

        skill_dir_name = self._get_skill_dir_name(skill_id)
        skill_dir = self.skills_dir / skill_dir_name
        skill_file = self._find_skill_file(skill_dir)
        
        if not skill_file:
            raise ValueError(f"No skill file found in '{skill_id}'")

        current_content = skill_file.read_text(encoding="utf-8")
        current_metadata = self._loader._parse_frontmatter(current_content)

        new_metadata = {
            "skill_id": skill_id,
            "name": name if name is not None else skill.name,
            "description": description if description is not None else skill.description,
            "category": category if category is not None else skill.category,
        }

        if trigger is not None:
            new_metadata["trigger"] = trigger
        elif skill.trigger:
            new_metadata["trigger"] = skill.trigger.to_dict()

        if action is not None:
            new_metadata["action"] = action
        elif skill.action:
            new_metadata["action"] = skill.action.to_dict()

        if safety is not None:
            new_metadata["safety"] = safety
        elif skill.safety:
            new_metadata["safety"] = skill.safety.to_dict()

        frontmatter = self._dict_to_yaml(new_metadata)
        body = content if content is not None else self._extract_body(current_content)
        new_skill_content = f"---\n{frontmatter}\n---\n\n{body}"

        skill_file.write_text(new_skill_content, encoding="utf-8")

        self._loader.reload()

        updated_skill = self._loader.get(skill_id)
        if not updated_skill:
            raise RuntimeError(f"Failed to load updated skill '{skill_id}'")

        logger.info(f"[SkillManager] Updated skill '{skill_id}'")
        return updated_skill

    def delete_skill(self, skill_id: str) -> bool:
        skill = self._loader.get(skill_id)
        if not skill:
            raise ValueError(f"Skill '{skill_id}' not found")

        skill_dir_name = self._get_skill_dir_name(skill_id)
        skill_dir = self.skills_dir / skill_dir_name
        if not skill_dir.exists():
            return False

        shutil.rmtree(skill_dir)
        self._loader.reload()

        logger.info(f"[SkillManager] Deleted skill '{skill_id}'")
        return True

    def get_skill_file(self, skill_id: str, file_path: str) -> str | bytes | None:
        skill = self._loader.get(skill_id)
        if not skill:
            return None

        skill_dir_name = self._get_skill_dir_name(skill_id)
        skill_dir = self.skills_dir / skill_dir_name
        target_file = skill_dir / file_path

        if not target_file.exists() or not target_file.is_file():
            return None

        if file_path.startswith("Resources/"):
            return target_file.read_bytes()
        return target_file.read_text(encoding="utf-8")

    def update_skill_file(self, skill_id: str, file_path: str, content: str | bytes) -> bool:
        skill = self._loader.get(skill_id)
        if not skill:
            raise ValueError(f"Skill '{skill_id}' not found")

        skill_dir_name = self._get_skill_dir_name(skill_id)
        skill_dir = self.skills_dir / skill_dir_name
        target_file = skill_dir / file_path

        target_file.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(content, bytes):
            target_file.write_bytes(content)
        else:
            target_file.write_text(content, encoding="utf-8")

        self._loader.reload()
        logger.info(f"[SkillManager] Updated file '{file_path}' in skill '{skill_id}'")
        return True

    def create_skill_file(self, skill_id: str, file_path: str, content: str | bytes = "") -> bool:
        skill = self._loader.get(skill_id)
        if not skill:
            raise ValueError(f"Skill '{skill_id}' not found")

        skill_dir_name = self._get_skill_dir_name(skill_id)
        skill_dir = self.skills_dir / skill_dir_name
        target_file = skill_dir / file_path

        if target_file.exists():
            raise ValueError(f"File '{file_path}' already exists in skill '{skill_id}'")

        target_file.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(content, bytes):
            target_file.write_bytes(content)
        else:
            target_file.write_text(content, encoding="utf-8")

        self._loader.reload()
        logger.info(f"[SkillManager] Created file '{file_path}' in skill '{skill_id}'")
        return True

    def delete_skill_file(self, skill_id: str, file_path: str) -> bool:
        skill = self._loader.get(skill_id)
        if not skill:
            raise ValueError(f"Skill '{skill_id}' not found")

        skill_dir_name = self._get_skill_dir_name(skill_id)
        skill_dir = self.skills_dir / skill_dir_name
        target_file = skill_dir / file_path

        if not target_file.exists():
            return False

        if target_file.suffix.lower() == ".md" and target_file.parent == skill_dir:
            raise ValueError(f"Cannot delete skill definition file")

        target_file.unlink()
        self._loader.reload()

        logger.info(f"[SkillManager] Deleted file '{file_path}' from skill '{skill_id}'")
        return True

    def list_skill_files(self, skill_id: str) -> list[dict[str, Any]]:
        skill = self._loader.get(skill_id)
        if not skill:
            return []

        skill_dir_name = self._get_skill_dir_name(skill_id)
        skill_dir = self.skills_dir / skill_dir_name
        files = []

        for path in skill_dir.rglob("*"):
            if path.is_file():
                rel_path = path.relative_to(skill_dir)
                files.append({
                    "path": str(rel_path),
                    "name": path.name,
                    "size": path.stat().st_size,
                    "is_binary": path.suffix.lower() in [".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip"],
                })

        return files

    def _build_frontmatter(
        self,
        skill_id: str,
        name: str,
        description: str,
        category: str,
        trigger: dict[str, Any] | None,
        action: dict[str, Any] | None,
        safety: dict[str, Any] | None,
    ) -> str:
        metadata = {
            "skill_id": skill_id,
            "name": name,
            "description": description,
            "category": category,
        }

        if trigger:
            metadata["trigger"] = trigger
        if action:
            metadata["action"] = action
        if safety:
            metadata["safety"] = safety

        return self._dict_to_yaml(metadata)

    def _dict_to_yaml(self, data: dict[str, Any], indent: int = 0) -> str:
        lines = []
        prefix = "  " * indent

        for key, value in data.items():
            if isinstance(value, dict):
                lines.append(f"{prefix}{key}:")
                lines.append(self._dict_to_yaml(value, indent + 1))
            elif isinstance(value, list):
                lines.append(f"{prefix}{key}:")
                for item in value:
                    lines.append(f"{prefix}  - {item}")
            elif isinstance(value, str):
                if "\n" in value or ":" in value or '"' in value:
                    lines.append(f'{prefix}{key}: "{value}"')
                else:
                    lines.append(f"{prefix}{key}: {value}")
            elif isinstance(value, bool):
                lines.append(f"{prefix}{key}: {str(value).lower()}")
            else:
                lines.append(f"{prefix}{key}: {value}")

        return "\n".join(lines)

    def _extract_body(self, content: str) -> str:
        match = re.match(r"^---\s*\n.*?\n---\s*\n", content, re.DOTALL)
        if match:
            return content[match.end():]
        return content


skill_manager = SkillManager()

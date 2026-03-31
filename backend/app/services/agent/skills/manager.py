import logging
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from .definition import SkillDefinition
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

        metadata = {"skill_id": skill_id, "name": name, "description": description, "category": category}
        if trigger:
            metadata["trigger"] = trigger
        if action:
            metadata["action"] = action
        if safety:
            metadata["safety"] = safety

        skill_content = f"---\n{yaml.dump(metadata, allow_unicode=True, default_flow_style=False)}---\n\n{content}"
        (skill_dir / "SKILL.md").write_text(skill_content, encoding="utf-8")

        for subdir in ["scripts", "templates", "Resources", "examples"]:
            (skill_dir / subdir).mkdir(exist_ok=True)

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

        skill_dir = self.skills_dir / self._get_skill_dir_name(skill_id)
        skill_file = self._find_skill_file(skill_dir)
        if not skill_file:
            raise ValueError(f"No skill file found in '{skill_id}'")

        current_content = skill_file.read_text(encoding="utf-8")
        
        metadata = {
            "skill_id": skill_id,
            "name": name if name is not None else skill.name,
            "description": description if description is not None else skill.description,
            "category": category if category is not None else skill.category,
        }
        
        if trigger is not None:
            metadata["trigger"] = trigger
        elif skill.trigger:
            metadata["trigger"] = skill.trigger.to_dict()
        if action is not None:
            metadata["action"] = action
        elif skill.action:
            metadata["action"] = skill.action.to_dict()
        if safety is not None:
            metadata["safety"] = safety
        elif skill.safety:
            metadata["safety"] = skill.safety.to_dict()

        body = content if content is not None else self._extract_body(current_content)
        new_content = f"---\n{yaml.dump(metadata, allow_unicode=True, default_flow_style=False)}---\n\n{body}"
        skill_file.write_text(new_content, encoding="utf-8")

        self._loader.reload()
        updated = self._loader.get(skill_id)
        if not updated:
            raise RuntimeError(f"Failed to load updated skill '{skill_id}'")

        logger.info(f"[SkillManager] Updated skill '{skill_id}'")
        return updated

    def delete_skill(self, skill_id: str) -> bool:
        skill = self._loader.get(skill_id)
        if not skill:
            raise ValueError(f"Skill '{skill_id}' not found")

        skill_dir = self.skills_dir / self._get_skill_dir_name(skill_id)
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

        target = self.skills_dir / self._get_skill_dir_name(skill_id) / file_path
        if not target.exists() or not target.is_file():
            return None

        return target.read_bytes() if file_path.startswith("Resources/") else target.read_text(encoding="utf-8")

    def update_skill_file(self, skill_id: str, file_path: str, content: str | bytes) -> bool:
        skill = self._loader.get(skill_id)
        if not skill:
            raise ValueError(f"Skill '{skill_id}' not found")

        target = self.skills_dir / self._get_skill_dir_name(skill_id) / file_path
        target.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")

        self._loader.reload()
        logger.info(f"[SkillManager] Updated file '{file_path}' in skill '{skill_id}'")
        return True

    def create_skill_file(self, skill_id: str, file_path: str, content: str | bytes = "") -> bool:
        skill = self._loader.get(skill_id)
        if not skill:
            raise ValueError(f"Skill '{skill_id}' not found")

        target = self.skills_dir / self._get_skill_dir_name(skill_id) / file_path
        if target.exists():
            raise ValueError(f"File '{file_path}' already exists in skill '{skill_id}'")

        target.parent.mkdir(parents=True, exist_ok=True)
        
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")

        self._loader.reload()
        logger.info(f"[SkillManager] Created file '{file_path}' in skill '{skill_id}'")
        return True

    def delete_skill_file(self, skill_id: str, file_path: str) -> bool:
        skill = self._loader.get(skill_id)
        if not skill:
            raise ValueError(f"Skill '{skill_id}' not found")

        target = self.skills_dir / self._get_skill_dir_name(skill_id) / file_path
        if not target.exists():
            return False

        if target.suffix.lower() == ".md" and target.parent == self.skills_dir / self._get_skill_dir_name(skill_id):
            raise ValueError("Cannot delete skill definition file")

        target.unlink()
        self._loader.reload()
        logger.info(f"[SkillManager] Deleted file '{file_path}' from skill '{skill_id}'")
        return True

    def list_skill_files(self, skill_id: str) -> list[dict[str, Any]]:
        skill = self._loader.get(skill_id)
        if not skill:
            return []

        skill_dir = self.skills_dir / self._get_skill_dir_name(skill_id)
        files = []
        binary_exts = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip"}

        for path in skill_dir.rglob("*"):
            if path.is_file():
                rel_path = path.relative_to(skill_dir)
                files.append({
                    "path": str(rel_path),
                    "name": path.name,
                    "size": path.stat().st_size,
                    "is_binary": path.suffix.lower() in binary_exts,
                })

        return files

    def _extract_body(self, content: str) -> str:
        match = re.match(r"^---\s*\n.*?\n---\s*\n", content, re.DOTALL)
        return content[match.end():] if match else content


skill_manager = SkillManager()

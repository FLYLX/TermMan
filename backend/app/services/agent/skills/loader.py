import logging
import re
from pathlib import Path
from typing import Any

import yaml

from .definition import ActionConfig, SafetyConfig, SkillDefinition, TriggerConfig

logger = logging.getLogger(__name__)


class SkillLoader:
    SKILL_FILES = ["SKILL.md", "SYSTEM_PROMPT.md"]

    def __init__(self, skills_dir: Path | None = None):
        if skills_dir is None:
            skills_dir = Path(__file__).parent.parent.parent.parent.parent / "skills"
        self.skills_dir = Path(skills_dir)
        self._skills: dict[str, SkillDefinition] = {}
        self._load_all()

    def _load_all(self):
        if not self.skills_dir.exists():
            self.skills_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"[SkillLoader] Created skills directory: {self.skills_dir}")
        else:
            for skill_path in self.skills_dir.iterdir():
                if skill_path.is_dir():
                    skill = self._load_skill(skill_path)
                    if skill:
                        self._skills[skill.skill_id] = skill

        self._load_builtin_plugin_skills()

        logger.info(f"[SkillLoader] Loaded {len(self._skills)} skills")

    def _load_builtin_plugin_skills(self) -> None:
        try:
            from app.plugins.robot.prompts import build_robot_messaging_skill_definition
        except Exception as exc:
            logger.debug("[SkillLoader] Robot plugin skill unavailable: %s", exc)
            return

        skill = build_robot_messaging_skill_definition()
        if skill is None or skill.skill_id in self._skills:
            return
        self._skills[skill.skill_id] = skill

    def _load_skill(self, skill_path: Path) -> SkillDefinition | None:
        skill_file = None
        for filename in self.SKILL_FILES:
            candidate = skill_path / filename
            if candidate.exists():
                skill_file = candidate
                break

        if not skill_file:
            logger.warning(f"[SkillLoader] No skill file found in {skill_path}")
            return None

        try:
            content = skill_file.read_text(encoding="utf-8")
            metadata = self._parse_frontmatter(content)

            skill = SkillDefinition(
                skill_id=str(metadata.get("skill_id", skill_path.name)),
                name=str(metadata.get("name", skill_path.name)),
                description=str(metadata.get("description", "")),
                category=str(metadata.get("category", "general")),
                content=content,
                skill_dir=str(skill_path.name),
            )

            if "trigger" in metadata:
                skill.trigger = TriggerConfig.from_dict(metadata["trigger"])
            if "action" in metadata:
                skill.action = ActionConfig.from_dict(metadata["action"])
            if "safety" in metadata:
                skill.safety = SafetyConfig.from_dict(metadata["safety"])
            if "mcp_servers" in metadata and isinstance(metadata["mcp_servers"], list):
                skill.mcp_servers = [str(m) for m in metadata["mcp_servers"]]

            self._load_skill_resources(skill, skill_path)
            return skill

        except Exception as e:
            logger.error(f"[SkillLoader] Failed to load skill from {skill_path}: {e}")
            return None

    def _load_skill_resources(self, skill: SkillDefinition, skill_path: Path):
        dirs = {
            "scripts": skill.scripts,
            "templates": skill.templates,
        }

        for dir_name, target_dict in dirs.items():
            dir_path = skill_path / dir_name
            if dir_path.exists():
                for file in dir_path.glob("*"):
                    if file.is_file():
                        target_dict[file.name] = file.read_text(encoding="utf-8")

        resources_dir = skill_path / "Resources"
        if resources_dir.exists():
            for file in resources_dir.glob("*"):
                if file.is_file():
                    skill.resources[file.name] = file.read_bytes()

        examples_dir = skill_path / "examples"
        if examples_dir.exists():
            import json
            for file in examples_dir.glob("*.json"):
                try:
                    with open(file, encoding="utf-8") as f:
                        skill.examples.append(json.load(f))
                except Exception as e:
                    logger.warning(f"[SkillLoader] Failed to load example {file}: {e}")

    def _parse_frontmatter(self, content: str) -> dict[str, Any]:
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if not match:
            return {}
        try:
            return yaml.safe_load(match.group(1)) or {}
        except Exception as e:
            logger.warning(f"[SkillLoader] Failed to parse frontmatter: {e}")
            return {}

    def get(self, skill_id: str) -> SkillDefinition | None:
        return self._skills.get(skill_id)

    def get_all(self) -> list[SkillDefinition]:
        return list(self._skills.values())

    def reload(self):
        self._skills.clear()
        self._load_all()


skill_loader = SkillLoader()

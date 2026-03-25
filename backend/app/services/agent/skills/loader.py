import logging
import re
from pathlib import Path
from typing import Any

from .definition import SkillDefinition, TriggerConfig, ActionConfig, SafetyConfig

logger = logging.getLogger(__name__)


class SkillLoader:
    SKILL_FILE = "SKILL.md"

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
            return

        for skill_path in self.skills_dir.iterdir():
            if skill_path.is_dir():
                skill = self._load_skill(skill_path)
                if skill:
                    self._skills[skill.skill_id] = skill

        logger.info(f"[SkillLoader] Loaded {len(self._skills)} skills")

    def _load_skill(self, skill_path: Path) -> SkillDefinition | None:
        skill_file = skill_path / self.SKILL_FILE
        if not skill_file.exists():
            logger.warning(f"[SkillLoader] SKILL.md not found in {skill_path}")
            return None

        try:
            content = skill_file.read_text(encoding="utf-8")
            metadata = self._parse_frontmatter(content)

            skill_id = str(metadata.get("skill_id", skill_path.name))
            name = metadata.get("name", skill_id)
            description = metadata.get("description", "")
            category = metadata.get("category", "general")
            
            skill = SkillDefinition(
                skill_id=skill_id,
                name=str(name) if name is not None else skill_id,
                description=str(description) if description is not None else "",
                category=str(category) if category is not None else "general",
                content=content,
            )

            if "trigger" in metadata:
                skill.trigger = TriggerConfig.from_dict(metadata["trigger"])

            if "action" in metadata:
                skill.action = ActionConfig.from_dict(metadata["action"])

            if "safety" in metadata:
                skill.safety = SafetyConfig.from_dict(metadata["safety"])

            scripts_dir = skill_path / "scripts"
            if scripts_dir.exists():
                for script_file in scripts_dir.glob("*"):
                    if script_file.is_file():
                        skill.scripts[script_file.name] = script_file.read_text(encoding="utf-8")

            templates_dir = skill_path / "templates"
            if templates_dir.exists():
                for template_file in templates_dir.glob("*"):
                    if template_file.is_file():
                        skill.templates[template_file.name] = template_file.read_text(encoding="utf-8")

            resources_dir = skill_path / "Resources"
            if resources_dir.exists():
                for resource_file in resources_dir.glob("*"):
                    if resource_file.is_file():
                        skill.resources[resource_file.name] = resource_file.read_bytes()

            examples_dir = skill_path / "examples"
            if examples_dir.exists():
                import json
                for example_file in examples_dir.glob("*.json"):
                    try:
                        with open(example_file, encoding="utf-8") as f:
                            skill.examples.append(json.load(f))
                    except Exception as e:
                        logger.warning(f"[SkillLoader] Failed to load example {example_file}: {e}")

            return skill

        except Exception as e:
            logger.error(f"[SkillLoader] Failed to load skill from {skill_path}: {e}")
            return None

    def _parse_frontmatter(self, content: str) -> dict[str, Any]:
        metadata: dict[str, Any] = {}

        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if not frontmatter_match:
            return metadata

        frontmatter = frontmatter_match.group(1)
        import yaml
        try:
            metadata = yaml.safe_load(frontmatter) or {}
        except Exception as e:
            logger.warning(f"[SkillLoader] Failed to parse frontmatter: {e}")

        return metadata

    def get(self, skill_id: str) -> SkillDefinition | None:
        return self._skills.get(skill_id)

    def get_all(self) -> list[SkillDefinition]:
        return list(self._skills.values())

    def reload(self):
        self._skills.clear()
        self._load_all()


skill_loader = SkillLoader()

import logging
import zipfile
import tempfile
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Body, UploadFile, File
from pydantic import BaseModel

from app.api.deps import CurrentUser
from app.services.agent.skills import skill_loader, skill_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/skills", tags=["skills"])


class SkillListItem(BaseModel):
    skill_id: str
    name: str
    description: str
    category: str


class SkillsListResponse(BaseModel):
    data: list[SkillListItem]
    count: int


class SkillDetail(BaseModel):
    skill_id: str
    name: str
    description: str
    category: str
    trigger: dict[str, Any]
    action: dict[str, Any]
    safety: dict[str, Any]
    content: str
    scripts: list[str]
    templates: list[str]
    resources: list[str]
    examples: list[dict[str, Any]]


class SkillCreateBody(BaseModel):
    skill_id: str
    name: str
    description: str = ""
    category: str = "general"


class SkillUpdateBody(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    trigger: dict[str, Any] | None = None
    action: dict[str, Any] | None = None
    safety: dict[str, Any] | None = None


@router.get("/", response_model=SkillsListResponse)
def list_skills(
    current_user: CurrentUser,
    category: str | None = None,
):
    skills = skill_loader.get_all()

    if category:
        skills = [s for s in skills if s.category == category]

    return SkillsListResponse(
        data=[
            SkillListItem(
                skill_id=s.skill_id,
                name=s.name,
                description=s.description,
                category=s.category,
            )
            for s in skills
        ],
        count=len(skills),
    )


@router.get("/{skill_id}", response_model=SkillDetail)
def get_skill(
    skill_id: str,
    current_user: CurrentUser,
):
    skill = skill_loader.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    return SkillDetail(
        skill_id=skill.skill_id,
        name=skill.name,
        description=skill.description,
        category=skill.category,
        trigger=skill.trigger.to_dict(),
        action=skill.action.to_dict(),
        safety=skill.safety.to_dict(),
        content=skill.content,
        scripts=list(skill.scripts.keys()),
        templates=list(skill.templates.keys()),
        resources=list(skill.resources.keys()),
        examples=skill.examples,
    )


@router.post("/", response_model=SkillListItem)
def create_skill(
    current_user: CurrentUser,
    body: SkillCreateBody,
):
    if skill_loader.get(body.skill_id):
        raise HTTPException(status_code=400, detail=f"Skill '{body.skill_id}' already exists")

    try:
        skill = skill_manager.create_skill(
            skill_id=body.skill_id,
            name=body.name,
            description=body.description,
            category=body.category,
        )
        return SkillListItem(
            skill_id=skill.skill_id,
            name=skill.name,
            description=skill.description,
            category=skill.category,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{skill_id}", response_model=SkillListItem)
def update_skill(
    skill_id: str,
    current_user: CurrentUser,
    body: SkillUpdateBody,
):
    skill = skill_loader.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    try:
        updated = skill_manager.update_skill(
            skill_id=skill_id,
            name=body.name,
            description=body.description,
            category=body.category,
            trigger=body.trigger,
            action=body.action,
            safety=body.safety,
        )
        return SkillListItem(
            skill_id=updated.skill_id,
            name=updated.name,
            description=updated.description,
            category=updated.category,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{skill_id}")
def delete_skill(
    skill_id: str,
    current_user: CurrentUser,
):
    skill = skill_loader.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    try:
        skill_manager.delete_skill(skill_id)
        return {"message": "Skill deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{skill_id}/files")
def list_skill_files(
    skill_id: str,
    current_user: CurrentUser,
):
    files = skill_manager.list_skill_files(skill_id)
    return {"files": files}


@router.get("/{skill_id}/files/{file_path:path}")
def get_skill_file(
    skill_id: str,
    file_path: str,
    current_user: CurrentUser,
):
    content = skill_manager.get_skill_file(skill_id, file_path)
    if content is None:
        raise HTTPException(status_code=404, detail="File not found")

    if isinstance(content, bytes):
        from fastapi.responses import Response
        return Response(content=content, media_type="application/octet-stream")

    return {"content": content}


@router.put("/{skill_id}/files/{file_path:path}")
def update_skill_file(
    skill_id: str,
    file_path: str,
    current_user: CurrentUser,
    content: str = Body(..., embed=True),
):
    skill = skill_loader.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    try:
        skill_manager.update_skill_file(skill_id, file_path, content)
        return {"message": "File updated successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{skill_id}/files/{file_path:path}")
def create_skill_file(
    skill_id: str,
    file_path: str,
    current_user: CurrentUser,
    content: str = Body(default="", embed=True),
):
    skill = skill_loader.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    try:
        skill_manager.create_skill_file(skill_id, file_path, content)
        return {"message": "File created successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{skill_id}/files/{file_path:path}")
def delete_skill_file(
    skill_id: str,
    file_path: str,
    current_user: CurrentUser,
):
    skill = skill_loader.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    try:
        skill_manager.delete_skill_file(skill_id, file_path)
        return {"message": "File deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/upload-zip")
async def upload_skill_zip(
    current_user: CurrentUser,
    file: UploadFile = File(...),
):
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are supported")

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            zip_path = temp_path / file.filename

            content = await file.read()
            zip_path.write_bytes(content)

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(temp_path)

            extracted_dirs = [d for d in temp_path.iterdir() if d.is_dir()]
            if not extracted_dirs:
                raise HTTPException(status_code=400, detail="No skill directory found in zip")

            skill_dir = extracted_dirs[0]
            skill_file = skill_dir / "SKILL.md"

            if not skill_file.exists():
                raise HTTPException(status_code=400, detail="SKILL.md not found in zip")

            skill_meta = skill_loader._parse_frontmatter(skill_file.read_text(encoding="utf-8"))
            skill_id = skill_meta.get("skill_id", skill_dir.name)

            if skill_loader.get(skill_id):
                raise HTTPException(status_code=400, detail=f"Skill '{skill_id}' already exists")

            dest_dir = skill_manager.skills_dir / skill_id
            if dest_dir.exists():
                raise HTTPException(status_code=400, detail=f"Skill directory '{skill_id}' already exists")

            shutil.copytree(skill_dir, dest_dir)
            skill_loader.reload()

            return {
                "message": "Skill uploaded successfully",
                "skill_id": skill_id,
            }

    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid zip file")
    except Exception as e:
        logger.error(f"[Skills] Failed to upload skill zip: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reload")
def reload_skills(
    current_user: CurrentUser,
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Only superusers can reload skills")

    skill_loader.reload()
    return {"message": f"Reloaded {len(skill_loader.get_all())} skills"}

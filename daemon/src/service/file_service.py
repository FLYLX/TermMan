import hashlib
import mimetypes
import shutil
import uuid
from pathlib import Path
from typing import Any, Optional

import chardet
from fastapi import UploadFile

from .item_path_service import ItemPathError, item_path_service


class FileServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class FileService:
    DEFAULT_PREVIEW_BYTES = 256 * 1024

    def get_default_directory(
        self,
        *,
        user_uuid: str,
        item_uuid: str,
        working_directory: Optional[str] = None,
    ) -> dict[str, Any]:
        try:
            target = item_path_service.resolve_workdir(
                user_uuid=user_uuid,
                item_uuid=item_uuid,
                working_directory=working_directory,
                create=True,
            )
            files_root = item_path_service.get_files_root()
            current_path = item_path_service.to_relative_path(files_root, target)
        except ItemPathError as exc:
            raise FileServiceError(str(exc), status_code=403) from exc

        return {
            "success": True,
            "item_uuid": item_uuid,
            "path": "/" if not current_path else current_path,
        }

    def list_directory(
        self,
        *,
        user_uuid: str,
        item_uuid: str,
        path: str = "/",
        working_directory: Optional[str] = None,
    ) -> dict[str, Any]:
        root, target = self._resolve_existing_target(
            user_uuid=user_uuid,
            item_uuid=item_uuid,
            path=path,
            working_directory=working_directory,
            expected_type="directory",
        )

        entries: list[dict[str, Any]] = []
        for child in sorted(target.iterdir(), key=lambda value: (not value.is_dir(), value.name.lower())):
            try:
                stat = child.lstat()
            except OSError:
                continue

            try:
                child_path = item_path_service.to_relative_path(root, child)
            except ItemPathError:
                continue

            is_symlink = child.is_symlink()
            entry_type = "directory" if child.is_dir() else "file"
            has_children = False

            if entry_type == "directory":
                has_children = self._has_children(child, root)
            entries.append(
                {
                    "name": child.name,
                    "path": child_path,
                    "type": entry_type,
                    "size": None if entry_type == "directory" else stat.st_size,
                    "modified_at": stat.st_mtime,
                    "has_children": has_children,
                    "is_symlink": is_symlink,
                }
            )

        current_path = item_path_service.to_relative_path(root, target)
        return {
            "success": True,
            "item_uuid": item_uuid,
            "current_path": "/" if not current_path else current_path,
            "entries": entries,
        }

    def read_text_content(
        self,
        *,
        user_uuid: str,
        item_uuid: str,
        path: str,
        working_directory: Optional[str] = None,
        preview_bytes: int = DEFAULT_PREVIEW_BYTES,
    ) -> dict[str, Any]:
        if preview_bytes < 1:
            raise FileServiceError("preview_bytes must be positive")

        root, target = self._resolve_existing_target(
            user_uuid=user_uuid,
            item_uuid=item_uuid,
            path=path,
            working_directory=working_directory,
            expected_type="file",
        )

        file_size = target.stat().st_size
        with target.open("rb") as file:
            sample = file.read(preview_bytes + 1)

        truncated = len(sample) > preview_bytes or file_size > preview_bytes
        payload = sample[:preview_bytes]

        if b"\x00" in payload:
            raise FileServiceError("Binary file preview is not supported", status_code=415)

        detected = chardet.detect(payload) if payload else {}
        encoding = detected.get("encoding") or "utf-8"
        try:
            content = payload.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            encoding = "utf-8"
            content = payload.decode(encoding, errors="replace")

        relative_path = item_path_service.to_relative_path(root, target)
        return {
            "success": True,
            "item_uuid": item_uuid,
            "path": relative_path,
            "size": file_size,
            "encoding": encoding,
            "truncated": truncated,
            "content": content,
        }

    def write_text_content(
        self,
        *,
        user_uuid: str,
        item_uuid: str,
        path: str,
        content: str,
        working_directory: Optional[str] = None,
        encoding: str = "utf-8",
    ) -> dict[str, Any]:
        root, target = self._resolve_target(
            user_uuid=user_uuid,
            item_uuid=item_uuid,
            path=path,
            working_directory=working_directory,
        )

        if target == root or target.name in {"", ".", ".."}:
            raise FileServiceError("Invalid file path")

        if target.exists() and target.is_dir():
            raise FileServiceError("Path is a directory", status_code=409)

        if not target.parent.exists() or not target.parent.is_dir():
            raise FileServiceError("Target parent directory does not exist", status_code=404)

        normalized_encoding = (encoding or "utf-8").strip() or "utf-8"
        try:
            payload = content.encode(normalized_encoding)
        except LookupError as exc:
            raise FileServiceError("Unsupported text encoding") from exc
        except UnicodeEncodeError as exc:
            raise FileServiceError("Content cannot be encoded with the selected encoding") from exc

        temp_path = target.parent / f".{target.name}.write-{uuid.uuid4().hex}.part"
        try:
            with temp_path.open("wb") as temp_file:
                temp_file.write(payload)
            temp_path.replace(target)
        except OSError as exc:
            raise FileServiceError("Failed to write file", status_code=500) from exc
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

        relative_path = item_path_service.to_relative_path(root, target)
        return {
            "success": True,
            "item_uuid": item_uuid,
            "path": relative_path,
            "size": len(payload),
            "encoding": normalized_encoding,
        }

    async def save_upload(
        self,
        *,
        user_uuid: str,
        item_uuid: str,
        path: str,
        upload_file: UploadFile,
        working_directory: Optional[str] = None,
        allow_overwrite: bool = False,
    ) -> dict[str, Any]:
        if not upload_file.filename:
            raise FileServiceError("Missing upload filename")

        root, target = self._resolve_target(
            user_uuid=user_uuid,
            item_uuid=item_uuid,
            path=path,
            working_directory=working_directory,
        )

        if target.name in {"", ".", ".."}:
            raise FileServiceError("Invalid upload path")

        if target.exists() and target.is_dir():
            raise FileServiceError("Target path is a directory", status_code=409)

        if target.exists() and not allow_overwrite:
            raise FileServiceError("Target file already exists", status_code=409)

        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target.parent / f".{target.name}.upload-{uuid.uuid4().hex}.part"
        sha256 = hashlib.sha256()
        size = 0

        try:
            with temp_path.open("wb") as temp_file:
                while True:
                    chunk = await upload_file.read(1024 * 1024)
                    if not chunk:
                        break
                    temp_file.write(chunk)
                    sha256.update(chunk)
                    size += len(chunk)

            temp_path.replace(target)
        finally:
            await upload_file.close()
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

        relative_path = item_path_service.to_relative_path(root, target)
        return {
            "success": True,
            "item_uuid": item_uuid,
            "path": relative_path,
            "size": size,
            "sha256": sha256.hexdigest(),
        }

    def create_directory(
        self,
        *,
        user_uuid: str,
        item_uuid: str,
        path: str,
        working_directory: Optional[str] = None,
    ) -> dict[str, Any]:
        root, target = self._resolve_target(
            user_uuid=user_uuid,
            item_uuid=item_uuid,
            path=path,
            working_directory=working_directory,
        )

        if target == root:
            raise FileServiceError("Cannot create root directory")

        if target.exists():
            if target.is_dir():
                raise FileServiceError("Directory already exists", status_code=409)
            raise FileServiceError("Target path already exists", status_code=409)

        try:
            target.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise FileServiceError("Target path already exists", status_code=409) from exc
        except OSError as exc:
            raise FileServiceError("Failed to create directory", status_code=500) from exc

        relative_path = item_path_service.to_relative_path(root, target)
        return {
            "success": True,
            "item_uuid": item_uuid,
            "path": relative_path,
            "type": "directory",
        }

    def rename_path(
        self,
        *,
        user_uuid: str,
        item_uuid: str,
        path: str,
        target_path: str,
        working_directory: Optional[str] = None,
    ) -> dict[str, Any]:
        root, source = self._resolve_existing_target(
            user_uuid=user_uuid,
            item_uuid=item_uuid,
            path=path,
            working_directory=working_directory,
            expected_type="any",
        )

        if source == root:
            raise FileServiceError("Cannot rename root directory")

        normalized_target = item_path_service.normalize_daemon_path(target_path)
        if not normalized_target:
            raise FileServiceError("Target path is required")

        target = (root / normalized_target).resolve(strict=False)
        try:
            item_path_service._ensure_within_root(root, target)
        except ItemPathError as exc:
            raise FileServiceError(str(exc), status_code=403) from exc

        if target.exists():
            raise FileServiceError("Target path already exists", status_code=409)

        if not target.parent.exists() or not target.parent.is_dir():
            raise FileServiceError("Target parent directory does not exist", status_code=404)

        if source.is_dir():
            try:
                target.relative_to(source)
            except ValueError:
                pass
            else:
                raise FileServiceError("Cannot move a directory into its own subdirectory")

        try:
            source.rename(target)
        except OSError as exc:
            raise FileServiceError("Failed to rename path", status_code=500) from exc

        source_relative = item_path_service.to_relative_path(root, source)
        target_relative = item_path_service.to_relative_path(root, target)
        return {
            "success": True,
            "item_uuid": item_uuid,
            "path": source_relative,
            "target_path": target_relative,
            "type": "directory" if target.is_dir() else "file",
        }

    def delete_path(
        self,
        *,
        user_uuid: str,
        item_uuid: str,
        path: str,
        working_directory: Optional[str] = None,
    ) -> dict[str, Any]:
        root, target = self._resolve_existing_target(
            user_uuid=user_uuid,
            item_uuid=item_uuid,
            path=path,
            working_directory=working_directory,
            expected_type="any",
        )

        if target == root:
            raise FileServiceError("Cannot delete root directory")

        relative_path = item_path_service.to_relative_path(root, target)
        entry_type = "directory" if target.is_dir() else "file"

        try:
            if target.is_symlink():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        except OSError as exc:
            raise FileServiceError("Failed to delete path", status_code=500) from exc

        return {
            "success": True,
            "item_uuid": item_uuid,
            "path": relative_path,
            "type": entry_type,
        }

    def get_download_metadata(
        self,
        *,
        user_uuid: str,
        item_uuid: str,
        path: str,
        working_directory: Optional[str] = None,
    ) -> dict[str, Any]:
        root, target = self._resolve_existing_target(
            user_uuid=user_uuid,
            item_uuid=item_uuid,
            path=path,
            working_directory=working_directory,
            expected_type="file",
        )

        relative_path = item_path_service.to_relative_path(root, target)
        content_type, _ = mimetypes.guess_type(str(target))
        return {
            "path": target,
            "relative_path": relative_path,
            "filename": target.name,
            "content_type": content_type or "application/octet-stream",
        }

    def _resolve_existing_target(
        self,
        *,
        user_uuid: str,
        item_uuid: str,
        path: str,
        working_directory: Optional[str],
        expected_type: str,
    ) -> tuple[Path, Path]:
        root, target = self._resolve_target(
            user_uuid=user_uuid,
            item_uuid=item_uuid,
            path=path,
            working_directory=working_directory,
        )

        if not target.exists():
            raise FileServiceError("Path not found", status_code=404)

        if expected_type == "directory" and not target.is_dir():
            raise FileServiceError("Path is not a directory")

        if expected_type == "file" and not target.is_file():
            raise FileServiceError("Path is not a file")

        return root, target

    def _resolve_target(
        self,
        *,
        user_uuid: str,
        item_uuid: str,
        path: str,
        working_directory: Optional[str],
    ) -> tuple[Path, Path]:
        try:
            root, target = item_path_service.resolve_daemon_path(path=path)
        except ItemPathError as exc:
            raise FileServiceError(str(exc), status_code=403) from exc

        return root, target

    @staticmethod
    def _has_children(directory: Path, root: Path) -> bool:
        try:
            for child in directory.iterdir():
                try:
                    item_path_service.to_relative_path(root, child)
                    return True
                except ItemPathError:
                    continue
        except OSError:
            return False
        return False


file_service = FileService()

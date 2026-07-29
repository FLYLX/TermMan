from pathlib import Path
from typing import Optional

from core import config


class ItemPathError(ValueError):
    pass


class ItemPathService:
    def __init__(self, workdir_base: str):
        self.workdir_base = Path(workdir_base).resolve(strict=False)
        self.files_root = Path("/").resolve(strict=False)
        self.workdir_base.mkdir(parents=True, exist_ok=True)

    def get_item_root(self, user_uuid: str, item_uuid: str) -> Path:
        root = (self.workdir_base / user_uuid / item_uuid).resolve(strict=False)
        self._ensure_within_root(self.workdir_base, root)
        root.mkdir(parents=True, exist_ok=True)
        return root

    def resolve_workdir(
        self,
        user_uuid: str,
        item_uuid: str,
        working_directory: Optional[str] = None,
        create: bool = True,
    ) -> Path:
        item_root = self.get_item_root(user_uuid, item_uuid)
        target = item_root

        if working_directory:
            raw_workdir = working_directory.replace("\\", "/").strip()
            candidate = Path(raw_workdir)
            if candidate.is_absolute():
                absolute_candidate = candidate.resolve(strict=False)
                if (
                    absolute_candidate == item_root
                    or item_root in absolute_candidate.parents
                ):
                    target = absolute_candidate
                else:
                    # Legacy absolute workdirs are remapped under the item root
                    # instead of being used as-is, so existing items keep working
                    # without reopening access outside the item sandbox.
                    logical_path = self.normalize_logical_path(raw_workdir)
                    # A path that actually points into ANOTHER item root (e.g.
                    # the terminal's cwd started by a different user) must not
                    # be appended verbatim — that nests workdirs. Rebase the
                    # sub-path after <user>/<item> onto this item root instead.
                    logical_path = self._rebase_foreign_workdir(logical_path, item_uuid)
                    target = item_root if not logical_path else (item_root / logical_path).resolve(strict=False)
            else:
                target = (item_root / raw_workdir).resolve(strict=False)

            self._ensure_within_root(item_root, target)

        if create:
            target.mkdir(parents=True, exist_ok=True)

        return target

    def resolve_item_path(
        self,
        user_uuid: str,
        item_uuid: str,
        path: str = "/",
        working_directory: Optional[str] = None,
        create_root: bool = True,
    ) -> tuple[Path, Path]:
        root = self.resolve_workdir(
            user_uuid=user_uuid,
            item_uuid=item_uuid,
            working_directory=working_directory,
            create=create_root,
        )
        normalized_path = self.normalize_logical_path(path)
        target = root if not normalized_path else (root / normalized_path).resolve(strict=False)
        self._ensure_within_root(root, target)
        return root, target

    def get_files_root(self) -> Path:
        return self.files_root

    def resolve_daemon_path(self, path: str = "/") -> tuple[Path, Path]:
        root = self.get_files_root()
        normalized_path = self.normalize_daemon_path(path)
        target = root if not normalized_path else (root / normalized_path).resolve(strict=False)
        self._ensure_within_root(root, target)
        return root, target

    def to_relative_path(self, root: Path, target: Path) -> str:
        root_resolved = root.resolve(strict=False)
        target_resolved = target.resolve(strict=False)
        self._ensure_within_root(root_resolved, target_resolved)
        relative_path = target_resolved.relative_to(root_resolved).as_posix()
        return "" if relative_path == "." else relative_path

    @staticmethod
    def normalize_logical_path(path: Optional[str]) -> str:
        if not path:
            return ""

        normalized = path.replace("\\", "/").strip()
        if normalized in {"", ".", "/"}:
            return ""

        normalized = normalized.lstrip("/")
        return normalized

    def _rebase_foreign_workdir(self, logical_path: str, item_uuid: str) -> str:
        """Strip a foreign item-root prefix (<workdir_base>/<user>/<item>/...)
        from a normalized logical path, returning only the sub-path after the
        item segment. Returns the input unchanged when it does not point into
        another root of the same item."""
        base_parts = [p for p in self.workdir_base.parts if p not in {"/", "\\"}]
        parts = logical_path.split("/")
        if len(parts) < len(base_parts) + 2:
            return logical_path
        if parts[: len(base_parts)] != base_parts:
            return logical_path
        remainder = parts[len(base_parts):]
        if remainder[1] != item_uuid:
            return logical_path
        return "/".join(remainder[2:])

    @staticmethod
    def normalize_daemon_path(path: Optional[str]) -> str:
        return ItemPathService.normalize_logical_path(path)

    @staticmethod
    def _ensure_within_root(root: Path, target: Path):
        root_resolved = root.resolve(strict=False)
        target_resolved = target.resolve(strict=False)
        if target_resolved != root_resolved and root_resolved not in target_resolved.parents:
            raise ItemPathError("Path escapes item root")


item_path_service = ItemPathService(config.get("WORKDIR"))

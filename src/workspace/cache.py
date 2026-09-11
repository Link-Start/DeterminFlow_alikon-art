"""Disposable materialization, usable only after an authorized provider read."""
import hashlib
import os
import re
import tempfile
from pathlib import Path
from src.workspace.contracts import WorkspaceError
from src.workspace.validation import valid_scope


class WorkspaceCache:
    def __init__(self, root: Path):
        self.root = root

    def materialize(self, scope: str, result: dict) -> Path:
        metadata, content = result["file"], result["content"]
        if not valid_scope(scope) or not isinstance(content, bytes):
            raise WorkspaceError("工作区缓存输入无效")
        digest = hashlib.sha256(content).hexdigest()
        if digest != metadata.get("sha256"):
            raise WorkspaceError("文件校验失败")
        key = hashlib.sha256((scope + "\0" + metadata["path"] + "\0" + metadata["version"] + "\0" + digest).encode()).hexdigest()
        if self.root.is_symlink():
            raise WorkspaceError("工作区缓存目录无效")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = self.root / key
        if target.is_symlink():
            raise WorkspaceError("工作区缓存路径无效")
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
            return target
        fd, temporary = tempfile.mkstemp(dir=self.root, prefix=".workspace-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return target

    def clear(self) -> None:
        if not self.root.exists():
            return
        if self.root.is_symlink():
            raise WorkspaceError("工作区缓存目录无效")
        for path in self.root.iterdir():
            if re.fullmatch(r"[a-f0-9]{64}", path.name) and (path.is_file() or path.is_symlink()):
                path.unlink(missing_ok=True)
        try:
            self.root.rmdir()
        except OSError:
            pass  # Another materialization or an unrelated file still exists.

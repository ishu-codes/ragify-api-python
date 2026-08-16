from pathlib import Path


def ensure_dir(path: str) -> None:
    p = Path(path)
    target_dir = p.parent if p.suffix else p
    target_dir.mkdir(parents=True, exist_ok=True)


def remove_dir(path: str) -> None:
    p = Path(path)
    if not p.exists():
        return
    for child in p.iterdir():
        if child.is_file():
            child.unlink()
    p.rmdir()

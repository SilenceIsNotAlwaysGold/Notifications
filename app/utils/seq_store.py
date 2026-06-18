from pathlib import Path


class SeqStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def read(self) -> int:
        if not self.path.exists():
            return 0
        content = self.path.read_text(encoding="utf-8").strip()
        if not content:
            return 0
        try:
            return int(content)
        except ValueError:
            return 0

    def write(self, seq: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        tmp_path.write_text(str(seq), encoding="utf-8")
        tmp_path.replace(self.path)

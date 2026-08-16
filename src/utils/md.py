from pathlib import Path

from markitdown import MarkItDown

from src.utils.files import save_to_file


def convert_to_md(path: str = "avengers-endgame-script.pdf"):
    md = MarkItDown(enable_plugins=False)
    result = md.convert(path)
    output_path = str(Path(path).with_suffix(".md"))
    save_to_file(output_path, result.text_content)
    return output_path

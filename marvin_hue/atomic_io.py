"""Escrita atômica de arquivos JSON (temp no mesmo diretório + ``os.replace``).

Um crash ou disco cheio no meio da escrita nunca deixa o arquivo pela metade:
ou o conteúdo novo substitui o antigo inteiro, ou o antigo fica intacto.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_json_atomic(path: str | Path, data: Any, *, trailing_newline: bool = False) -> None:
    """Grava ``data`` como JSON em ``path`` de forma atômica.

    Raises:
        OSError: a escrita ou a troca falhou (o arquivo original fica intacto).
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".tmp-{target.name}-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            if trailing_newline:
                fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, str(target))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise

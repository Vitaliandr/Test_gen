#не даёт закоммитить ключи
import argparse
import os
import re
import subprocess
import sys

# ключи openrouter, anthropic, openai
PATTERNS = [
    re.compile(r"sk-or-v1-[0-9a-f]{32,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}"),
]
#этот файл в git вообще нельзя
FORBIDDEN = {".env"}
# venv, базу и кеши не смотрим
SKIP_DIRS = {".git", ".venv", "venv", "data", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", check=True).stdout


def _staged(name: str) -> str:
    # байты, а не text=True: на jpg текстовый режим падает внутри subprocess, а не тут
    raw = subprocess.run(["git", "show", f":{name}"], capture_output=True, check=True).stdout
    return raw.decode("utf-8")


def project_files() -> tuple[list[str], bool]:
    try:
        #без --others новые файлы не видно, а они тоже уйдут в репо
        return _git("ls-files", "--cached", "--others", "--exclude-standard").splitlines(), True
    except (OSError, subprocess.CalledProcessError):
        # git нет, например скачали архивом
        names = []
        for root, dirs, files in os.walk("."):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            names += [os.path.relpath(os.path.join(root, f)).replace(os.sep, "/") for f in files]
        return sorted(names), False


def mask(secret: str) -> str:
    return secret[:8] + "..." if len(secret) > 8 else "..."


def scan_text(name: str, text: str) -> list[str]:
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        for pattern in PATTERNS:
            for m in pattern.finditer(line):
                found.append(f"{name}:{n}: похоже на ключ {mask(m.group(0))}")
    return found


def scan(staged: bool) -> list[str]:
    if staged:
        names, in_git = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines(), True
    else:
        names, in_git = project_files()
    #без git .env просто лежит рядом, его тоже сканим
    found = [f"{n}: этот файл нельзя хранить в git" for n in names if in_git and n.rsplit("/", 1)[-1] in FORBIDDEN]
    for name in names:
        try:
            # для коммита берём из индекса
            text = _staged(name) if staged else open(name, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError, subprocess.CalledProcessError):
            continue
        found += scan_text(name, text)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ищет ключи в файлах проекта")
    parser.add_argument("--staged", action="store_true", help="проверить только то, что добавлено в коммит")
    args = parser.parse_args(argv)
    found = scan(args.staged)
    for line in found:
        print(line)
    if found:
        print("коммит остановлен: уберите ключ из файла, ключ должен лежать в .env или в хранилище")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

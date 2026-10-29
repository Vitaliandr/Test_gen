import json
import shutil
import sys
from pathlib import Path

from sitegen.card import Company as Card
from sitegen.core import builder, consistency

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
#по три варианта на компанию: тема, схема, шрифт, каждый в свою папку site-<тема>
STYLES = {
    "zitara": [("classic", "ocean", "sans"), ("editorial", "graphite", "serif"), ("dark", "violet", "sans")],
    "lavirt": [("classic", "forest", "sans"), ("editorial", "ocean", "serif"), ("dark", "graphite", "sans")],
}


def build(name: str) -> None:
    folder = EXAMPLES / name
    data = json.loads((folder / "company.json").read_text(encoding="utf-8"))
    card = Card.model_validate(data)
    issues = consistency.check_company(card)
    if issues:
        sys.exit(f"{name}: {issues}")

    # фото лежат рядом как p1.jpg, p2.jpg..., кого нет, тому силуэт
    team = [folder / "photos" / f"p{i}.jpg" for i in range(1, len(card.people) + 1)]
    pics = [p.read_bytes() if p.is_file() else None for p in team]
    for theme, scheme, font in STYLES[name]:
        files = builder.render_site(data, data, card.language, scheme, font, theme, pics)
        pages = {n: b.decode("utf-8") for n, b in files.items() if n.endswith(".html")}
        report = consistency.check_site(data, data, pages, files, card.language)
        if not report["ok"]:
            sys.exit(f"{name}, {theme}: сайт не прошёл проверки: {report['checks']}")

        site = folder / f"site-{theme}"
        shutil.rmtree(site, ignore_errors=True)
        for rel, content in files.items():
            target = site / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        print(f"{name}, {theme}: готово, {len(files)} файлов")


def main() -> None:
    for name in STYLES:
        build(name)


if __name__ == "__main__":
    main()

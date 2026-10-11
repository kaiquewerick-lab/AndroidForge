
#!/usr/bin/env python3
"""
AndroidForge - Project Detector
Detecta projetos Flutter, Android/Gradle e aplicações Web.
"""

import argparse
import json
import os
import sys
from pathlib import Path


IGNORED_DIRS = {
    ".git",
    ".gradle",
    ".idea",
    "node_modules",
    "build",
    "dist",
    ".dart_tool",
    ".androidforge",
}

GRADLE_MARKERS = (
    "settings.gradle",
    "settings.gradle.kts",
    "build.gradle",
    "build.gradle.kts",
)

WEB_MARKERS = (
    "index.html",
    "main.html",
    "app.html",
    "SaturnDesktopBETA.html",
)


def has_any(root: Path, names) -> bool:
    return any((root / name).is_file() for name in names)


def find_project_root(start: Path) -> Path:
    """Procura a raiz do projeto sem entrar em pastas de dependências."""
    start = start.resolve()

    if start.is_file():
        start = start.parent

    candidates = [start]

    try:
        for child in start.iterdir():
            if child.is_dir() and child.name not in IGNORED_DIRS:
                candidates.append(child)
    except OSError:
        pass

    # Prioriza projetos Android/Flutter reconhecíveis.
    for candidate in candidates:
        if (
            (candidate / "pubspec.yaml").is_file()
            or has_any(candidate, GRADLE_MARKERS)
        ):
            return candidate

    # Procura arquivos HTML comuns na raiz ou em public/.
    for candidate in candidates:
        if has_any(candidate, WEB_MARKERS):
            return candidate

        public_dir = candidate / "public"
        if public_dir.is_dir() and has_any(public_dir, WEB_MARKERS):
            return candidate

    return start


def detect_project(root: Path) -> dict:
    """Identifica o tipo de projeto e os arquivos encontrados."""
    root = root.resolve()

    result = {
        "project_type": "unknown",
        "sub_type": "unknown",
        "project_root": str(root),
        "needs_gradle": False,
        "needs_flutter": False,
        "needs_web_wrapper": False,
        "entry_point": None,
        "has_package_json": (root / "package.json").is_file(),
        "has_server_mjs": (root / "server.mjs").is_file(),
        "has_server_js": (root / "server.js").is_file(),
        "gradle_files": [],
        "notes": [],
    }

    # Flutter deve ser detectado antes de Gradle.
    if (root / "pubspec.yaml").is_file():
        result.update({
            "project_type": "flutter",
            "sub_type": "flutter",
            "needs_gradle": True,
            "needs_flutter": True,
        })
        result["notes"].append("Projeto Flutter detectado.")
        return result

    gradle_files = [
        name for name in GRADLE_MARKERS
        if (root / name).is_file()
    ]

    if gradle_files:
        result.update({
            "project_type": "gradle",
            "sub_type": "android",
            "needs_gradle": True,
            "gradle_files": gradle_files,
        })
        result["notes"].append("Projeto Gradle detectado.")
        return result

    # Procura uma página HTML na raiz ou em public/.
    for name in WEB_MARKERS:
        if (root / name).is_file():
            result["entry_point"] = name
            break

    if result["entry_point"] is None:
        public_dir = root / "public"
        if public_dir.is_dir():
            for name in WEB_MARKERS:
                if (public_dir / name).is_file():
                    result["entry_point"] = str(
                        Path("public") / name
                    )
                    break

    # Aceita outros arquivos HTML se não houver um nome conhecido.
    if result["entry_point"] is None:
        try:
            html_files = sorted(
                path for path in root.glob("*.html")
                if path.is_file()
            )
            if html_files:
                result["entry_point"] = html_files[0].name
        except OSError:
            pass

    if result["entry_point"]:
        result.update({
            "project_type": "web",
            "sub_type": "static-web",
            "needs_gradle": False,
            "needs_flutter": False,
            "needs_web_wrapper": True,
        })
        result["notes"].append(
            "Projeto web detectado. É necessário gerar um projeto "
            "Android com WebView antes de executar a compilação Gradle."
        )

        if result["has_server_mjs"] or result["has_server_js"]:
            result["notes"].append(
                "Foi encontrado um servidor Node.js. O código do servidor "
                "não é executado automaticamente dentro de um WebView Android."
            )

        if result["has_package_json"]:
            result["notes"].append(
                "Foi encontrado package.json. Verifique se o projeto "
                "precisa de uma etapa de build antes de empacotar os arquivos."
            )

        return result

    result["notes"].append(
        "Nenhum projeto Flutter, Gradle ou HTML reconhecido foi encontrado."
    )
    return result


def write_github_output(result: dict) -> None:
    """Publica saídas para etapas posteriores do GitHub Actions."""
    output_path = os.environ.get("GITHUB_OUTPUT")

    if not output_path:
        return

    with open(output_path, "a", encoding="utf-8") as output:
        for key in (
            "project_type",
            "sub_type",
            "needs_gradle",
            "needs_flutter",
            "needs_web_wrapper",
            "entry_point",
            "project_root",
        ):
            value = result.get(key)
            if value is None:
                value = ""
            elif isinstance(value, bool):
                value = str(value).lower()

            output.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detecta projetos compatíveis com AndroidForge."
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Pasta do projeto extraído (padrão: diretório atual).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Arquivo opcional para salvar o relatório JSON.",
    )
    args = parser.parse_args()

    start = Path(args.root)

    if not start.exists():
        print(
            f"Erro: a pasta informada não existe: {start}",
            file=sys.stderr,
        )
        return 2

    root = find_project_root(start)
    result = detect_project(root)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    write_github_output(result)

    if args.output:
        output_file = Path(args.output)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    if result["project_type"] == "unknown":
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

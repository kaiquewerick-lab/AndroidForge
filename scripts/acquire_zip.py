
#!/usr/bin/env python3
"""AndroidForge: seleciona o ZIP correto para compilar."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.request
import urllib.error
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = REPO_ROOT / "input"


def list_input_zips():
    if not INPUT_DIR.is_dir():
        return []
    return sorted(
        (p for p in INPUT_DIR.iterdir()
         if p.is_file() and p.suffix.lower() == ".zip"),
        key=lambda p: p.name.lower()
    )


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url, destination):
    request = urllib.request.Request(
        url, headers={"User-Agent": "AndroidForge-Action"}
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        with destination.open("wb") as output:
            shutil.copyfileobj(response, output)


def release_asset(repo, tag, token):
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AndroidForge-Action",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            release = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"Erro ao consultar release {tag}: HTTP {error.code}"
        ) from error

    assets = [
        asset for asset in release.get("assets", [])
        if asset.get("name", "").lower().endswith(".zip")
    ]

    if len(assets) != 1:
        names = [asset.get("name", "") for asset in assets]
        raise RuntimeError(
            f"A release '{tag}' precisa ter exatamente um ZIP. "
            f"ZIPs encontrados: {names}"
        )

    asset = assets[0]
    return asset["name"], asset["browser_download_url"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        default="input-directory",
        choices=["input-directory", "download-url", "release-asset"],
    )
    parser.add_argument("--url", default="")
    parser.add_argument("--tag", default="")
    parser.add_argument("--path", default="")
    parser.add_argument("--dest-dir", default="")
    args = parser.parse_args()

    dest_dir = (
        Path(args.dest_dir).resolve()
        if args.dest_dir
        else REPO_ROOT / ".androidforge" / "downloads"
    )
    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.source == "input-directory":
            if args.path:
                source = Path(args.path)
                if not source.is_absolute():
                    source = REPO_ROOT / source
                source = source.resolve()

                if not source.is_file() or source.suffix.lower() != ".zip":
                    raise RuntimeError(
                        f"O caminho informado não é um ZIP válido: {source}"
                    )
            else:
                zips = list_input_zips()

                if not zips:
                    raise RuntimeError("Nenhum ZIP encontrado na pasta input/.")

                if len(zips) > 1:
                    names = "\n".join(f" - {p.name}" for p in zips)
                    raise RuntimeError(
                        "Há vários ZIPs em input/. Para evitar compilar o "
                        "aplicativo errado, informe --path com o ZIP desejado:\n"
                        f"{names}"
                    )

                source = zips[0]

            target = dest_dir / source.name
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
            zip_path = target

        elif args.source == "download-url":
            if not args.url:
                raise RuntimeError(
                    "--url é obrigatório quando source=download-url."
                )
            name = args.url.split("?")[0].rstrip("/").split("/")[-1]
            if not name.lower().endswith(".zip"):
                name = "source.zip"
            zip_path = dest_dir / name
            download(args.url, zip_path)

        else:
            if not args.tag:
                raise RuntimeError(
                    "--tag é obrigatório quando source=release-asset."
                )
            repo = os.environ.get("GITHUB_REPOSITORY", "")
            if not repo:
                raise RuntimeError("GITHUB_REPOSITORY não está definido.")

            name, url = release_asset(
                repo, args.tag, os.environ.get("GITHUB_TOKEN")
            )
            zip_path = dest_dir / name
            download(url, zip_path)

        if not zip_path.is_file() or zip_path.stat().st_size == 0:
            raise RuntimeError("O ZIP baixado está vazio ou não existe.")

        result = {
            "source": args.source,
            "zip_path": str(zip_path),
            "zip_name": zip_path.name,
            "size_bytes": zip_path.stat().st_size,
            "sha256": sha256_file(zip_path),
        }

        print(json.dumps(result, indent=2, ensure_ascii=False))

        output_path = os.environ.get("GITHUB_OUTPUT")
        if output_path:
            with open(output_path, "a", encoding="utf-8") as output:
                output.write(f"zip_path={zip_path}\n")
                output.write(f"zip_name={zip_path.name}\n")
                output.write(f"zip_sha256={result['sha256']}\n")

        return 0

    except Exception as error:
        print(f"ERRO: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

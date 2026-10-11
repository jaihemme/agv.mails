#!/usr/bin/env python3

import os
import sys
import json
import hashlib
import subprocess
import tempfile
from pathlib import Path
from openai import OpenAI


CACHE_DIR = Path(".transcription_cache")
HISTORY_FILE = CACHE_DIR / "history.json"
MODEL = "gpt-4o-mini-transcribe"
HISTORY_SIZE = 5


BASE_PROMPT = """
CONTEXTE

Cette discussion a commencé lors de la donnation de la maison Suzanne en 2024 à ses enfants.
David Bernat, déjà sollicité par Suzanne Marfurt pour la gestion de ses impôts, s'est occupé
des démarches administratives liées à cette donation : registre de la propriété, cadastre, etc.
Après le décès de Suzanne, se sont ajoutés les démarches pour le testament, l'héritage.
Georges et Sabine ont décidé de vendre leur maison par l'agence Engel & Völkers.
Ils ont donné une procuration à Noémie Bernat pour tout ce qui concerne la vente et l'héritage.

Participants :
- Georges Marfurt : propriétaire de la maison à Puerto de la Cruz, Tenerife
- Sabine Spielmann : isoeur de George et copropriétaire de la maison
- David Bernat : économiste à Tenerife, chargé de démarches administratives
- Noémie Bernat : comptable et secrétaire dans l'agence de son frère David

Autre personnes évoquées:
- Suzanne Marfurt : mère de Georges et Sabine, décédée le 24.7.2026.
- Astrid Marfurt : fille de Suzanne, soeur de Georges et Sabine, décédée
- Samuel Marfurt : fils de Astrid, petit-fils de Suzanne, donc héritier
- Paolo Comba : interlocuteur de l'agence immobilière Engel & Völkers.

Noms et termes susceptibles d'être mentionnés :
- Engel & Völkers
- Puerto de la Cruz
- Tenerife
- Registro de la Propiedad
- Catastro
- testament
- procuration
- usufruit
- nu-propriété

L'audio est en français et et vient principalement de David Bernat qui a un fort accent espagnol.

Transcrire fidèlement ce qui est réellement dit.
Utiliser le contexte uniquement pour identifier correctement
les personnes, noms propres, lieux et termes techniques.
Ne pas inventer de phrases à partir du contexte.
"""


def file_sha256(path: Path) -> str:
    sha256 = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            sha256.update(block)

    return sha256.hexdigest()


def convert_opus_to_ogg(source: Path, destination: Path):
    """Convertit un fichier .opus en conteneur .ogg sans réencodage."""

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel", "error",
                "-i", str(source),
                "-c:a", "copy",
                str(destination),
            ],
            check=True,
        )

    except FileNotFoundError:
        print(
            "Erreur : ffmpeg n'est pas installé ou n'est pas dans le PATH.",
            file=sys.stderr,
        )
        sys.exit(1)

    except subprocess.CalledProcessError:
        print(
            f"Erreur : impossible de convertir {source}",
            file=sys.stderr,
        )
        sys.exit(1)


def load_history() -> list[str]:
    """Charge les dernières transcriptions."""

    if not HISTORY_FILE.is_file():
        return []

    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)

        return data[-HISTORY_SIZE:]

    except (json.JSONDecodeError, OSError):
        return []


def save_history(history: list[str]):
    """Enregistre les dernières transcriptions."""

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    history = history[-HISTORY_SIZE:]

    with HISTORY_FILE.open("w", encoding="utf-8") as f:
        json.dump(
            history,
            f,
            ensure_ascii=False,
            indent=2,
        )


def add_to_history(text: str):
    history = load_history()

    history.append(text)

    save_history(history)


def build_prompt() -> str:
    """Construit le prompt avec les 5 conversations précédentes."""

    history = load_history()

    if not history:
        return BASE_PROMPT

    parts = [
        BASE_PROMPT,
        "\nHISTORIQUE DES CONVERSATIONS PRÉCÉDENTES\n",
    ]

    for number, text in enumerate(history, start=1):
        parts.append(
            f"\n--- Conversation précédente {number} ---\n{text}\n"
        )

    parts.append("""
FIN DE L'HISTORIQUE

L'historique précédent sert uniquement de contexte.
Il ne fait pas partie de l'audio à transcrire.
""")

    return "".join(parts)


def cache_filename(
    original_audio_path: Path,
    prompt: str,
) -> Path:

    audio_hash = file_sha256(original_audio_path)

    key = f"{audio_hash}:{MODEL}:{prompt}"
    cache_hash = hashlib.sha256(
        key.encode("utf-8")
    ).hexdigest()

    return CACHE_DIR / f"{cache_hash}.json"


def read_cache(cache_path: Path):

    if not cache_path.is_file():
        return None

    try:
        with cache_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        return data["text"]

    except (json.JSONDecodeError, KeyError, OSError):
        return None


def write_cache(
    cache_path: Path,
    original_audio_path: Path,
    prompt: str,
    text: str,
):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    data = {
        "audio": str(original_audio_path),
        "audio_sha256": file_sha256(original_audio_path),
        "model": MODEL,
        "prompt": prompt,
        "text": text,
    }

    with cache_path.open("w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )


def transcribe(
    audio_path: Path,
    original_audio_path: Path,
    prompt: str,
) -> str:

    cache_path = cache_filename(
        original_audio_path,
        prompt,
    )

    cached_text = read_cache(cache_path)

    if cached_text is not None:
        print(
            f"Cache : {original_audio_path}",
            file=sys.stderr,
        )
        return cached_text

    print(
        f"Transcription OpenAI : {original_audio_path}",
        file=sys.stderr,
    )

    client = OpenAI()

    with audio_path.open("rb") as audio:
        result = client.audio.transcriptions.create(
            model=MODEL,
            file=audio,
            language="fr",
            prompt=prompt,
        )

    text = result.text

    write_cache(
        cache_path,
        original_audio_path,
        prompt,
        text,
    )

    return text


def main():

    if len(sys.argv) != 2:
        print(
            f"Usage : {sys.argv[0]} fichier.ogg|fichier.opus",
            file=sys.stderr,
        )
        sys.exit(1)

    original_path = Path(sys.argv[1])

    if not original_path.is_file():
        print(
            f"Erreur : fichier introuvable : {original_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        print(
            "Erreur : OPENAI_API_KEY n'est pas définie ou est vide.",
            file=sys.stderr,
        )
        sys.exit(1)

    suffix = original_path.suffix.lower()

    if suffix not in (".ogg", ".opus"):
        print(
            "Erreur : seuls les fichiers .ogg et .opus sont acceptés.",
            file=sys.stderr,
        )
        sys.exit(1)

    prompt = build_prompt()

    # Fichier OGG : transcription directe
    if suffix == ".ogg":

        text = transcribe(
            original_path,
            original_path,
            prompt,
        )

    # Fichier OPUS : conversion temporaire en OGG
    else:

        with tempfile.TemporaryDirectory() as tmpdir:

            ogg_path = (
                Path(tmpdir) /
                f"{original_path.stem}.ogg"
            )

            print(
                f"Conversion OPUS -> OGG : {original_path}",
                file=sys.stderr,
            )

            convert_opus_to_ogg(
                original_path,
                ogg_path,
            )

            text = transcribe(
                ogg_path,
                original_path,
                prompt,
            )

    print(text)

    # La transcription actuelle devient une conversation
    # précédente pour le prochain fichier.
    add_to_history(text)


if __name__ == "__main__":
    main()
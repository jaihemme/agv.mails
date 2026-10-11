# Transcription de WhatsApp (`parse_whatsapp.py`)

Ce script permet de parser des exports de conversations WhatsApp (`_chat.txt`), de filtrer les messages et de transcrire les fichiers audio `.opus` en texte en utilisant OpenAI Whisper.

## Fonctionnalités actuelles

### 1. Parsing & Filtrage
- **Extraction :** Analyse le fichier `_chat.txt` pour extraire les timestamps, les expéditeurs et le contenu des messages.
- **Normalisation des dates :** Gère plusieurs formats de date courants dans les exports WhatsApp.
- **Filtres :** Permet de filtrer les messages par :
    - Plage de dates (`--start-date`, `--end-date`).
    - Nom du contact (`--contact`).

### 2. Transcription Audio (Whisper)
- **Détection :** Identifie les pièces jointes `.opus` dans les messages.
- **Transcription :** Utilise le modèle OpenAI Whisper pour convertir l'audio en texte (langue forcée : français).
- **Optimisation :**
    - Support de différents modèles (`tiny`, `base`, `small`, `medium`, `large`).
    - Système de cache interne pour éviter de re-transcrire le même fichier dans une session.
    - **Traitement Incrémental :** Le script peut détecter le dernier message traité dans les rapports Markdown existants et ne transcrire que les nouveaux messages.

### 3. Sorties (Outputs)
- **JSON :** Sauvegarde l'intégralité de la conversation filtrée et transcrite dans un fichier `.json`.
- **Markdown :** Génère un rapport `.md` avec :
    - Mise en forme des messages.
    - Liens cliquables vers les pièces jointes (audio, images).
    - Intégration des PDF via des balises `<embed>` pour un affichage direct.

## Utilisation

```bash
python parse_whatsapp.py --input <dossier_export> [options]
```

**Options principales :**
- `--start-date DD.MM.YYYY` : Filtrer à partir de cette date.
- `--end-date DD.MM.YYYY` : Filtrer jusqu'à cette date.
- `--contact "Nom"` : Filtrer par contact.
- `--model <size>` : Choisir la taille du modèle Whisper (default: `base`).
- `--force` : Forcer la re-transcription de tous les messages, ignorant l'état incrémental.

## Dépendances
- `openai-whisper` (optionnel pour la transcription)
- `tqdm` (pour la barre de progression)

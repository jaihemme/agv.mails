#!/usr/bin/env bash
#
# Script: git_commit_tag_push.sh
# Description: Réalise un git commit avec message des changements,
#              crée un tag au format 'v<aaaammjj>-<seq>', et pousse vers le remote.
#

set -e

COMMIT_MSG=""
AUTO_ADD=true
DRY_RUN=false
DO_PUSH=true
REMOTE="origin"

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  -m, --message <msg>   Message de commit décrivant les changements.
  -a, --all             Ajouter automatiquement tous les fichiers modifiés et nouveaux (git add -A) [Défaut: oui].
  --no-add              Ne pas exécuter git add -A (utiliser uniquement les fichiers déjà indexés / staged).
  --no-push             Créer le commit et le tag localement sans exécuter de git push.
  -d, --dry-run         Simuler les actions sans modifier le dépôt ni laisser de modifications indexées.
  -r, --remote <name>   Nom du remote Git (Défaut: origin).
  -h, --help            Afficher cette aide.

Exemples:
  $(basename "$0") -m "feat: ajout du parser et documentation"
  $(basename "$0") --dry-run
EOF
  exit 0
}

# Traitement des arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    -m|--message)
      COMMIT_MSG="$2"
      shift 2
      ;;
    -a|--all)
      AUTO_ADD=true
      shift
      ;;
    --no-add)
      AUTO_ADD=false
      shift
      ;;
    --no-push)
      DO_PUSH=false
      shift
      ;;
    -d|--dry-run)
      DRY_RUN=true
      shift
      ;;
    -r|--remote)
      REMOTE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo "Option inconnue: $1" >&2
      usage
      ;;
  esac
done

# 1. Vérification de l'environnement Git
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Erreur : ce répertoire n'est pas un dépôt Git valide." >&2
  exit 1
fi

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ -z "$CURRENT_BRANCH" ]; then
  CURRENT_BRANCH="main"
fi

# Mémoriser l'état initial des fichiers staged avant auto-add si dry-run
PREV_STAGED=$(git diff --cached --name-only)

# 2. Stage des fichiers si demandé
if [ "$AUTO_ADD" = true ]; then
  git add -A
fi

CHANGES_STAGED=$(git diff --cached --name-only)

if [ -z "$CHANGES_STAGED" ]; then
  echo "Information : Aucun changement à commiter."
  git status -s
  exit 0
fi

# 3. Message de commit
if [ -z "$COMMIT_MSG" ]; then
  CHANGED_FILES_COUNT=$(echo "$CHANGES_STAGED" | wc -l | tr -d ' ')
  SUMMARY=$(git diff --cached --stat | tail -n 1 | sed 's/^[ ]*//')
  COMMIT_MSG="Mise à jour: $CHANGED_FILES_COUNT fichier(s) modifié(s) ($SUMMARY)"
fi

# 4. Calcul du tag 'v<aaaammjj>-<seq>'
TODAY=$(date +%Y%m%d)

# Recherche de la séquence maximale existante pour aujourd'hui
MAX_SEQ=0
for tag in $(git tag -l "v${TODAY}-*"); do
  seq="${tag#v${TODAY}-}"
  if [[ "$seq" =~ ^[0-9]+$ ]] && [ "$seq" -gt "$MAX_SEQ" ]; then
    MAX_SEQ=$seq
  fi
done

NEXT_SEQ=$((MAX_SEQ + 1))
NEW_TAG="v${TODAY}-${NEXT_SEQ}"

echo "============================================================"
echo "  GIT COMMIT, TAG & PUSH"
echo "============================================================"
echo "Branche       : $CURRENT_BRANCH"
echo "Remote        : $REMOTE"
echo "Tag calculé   : $NEW_TAG (Date: $TODAY, Séquence: $NEXT_SEQ)"
echo "Message       : $COMMIT_MSG"
echo "Changements   :"
echo "$CHANGES_STAGED" | sed 's/^/  - /'
echo "============================================================"

# Mode simulation
if [ "$DRY_RUN" = true ]; then
  # Nettoyer l'indexation si elle a été faite par le dry-run
  if [ "$AUTO_ADD" = true ] && [ -z "$PREV_STAGED" ]; then
    git reset >/dev/null 2>&1 || true
  fi
  echo ""
  echo "[DRY RUN] Simulation uniquement. Commandes qui seraient exécutées :"
  echo "  1. git commit -m \"$COMMIT_MSG\""
  echo "  2. git tag -a \"$NEW_TAG\" -m \"Release $NEW_TAG: $COMMIT_MSG\""
  if [ "$DO_PUSH" = true ]; then
    echo "  3. git push $REMOTE $CURRENT_BRANCH"
    echo "  4. git push $REMOTE $NEW_TAG"
  fi
  echo "============================================================"
  exit 0
fi

# 5. Exécution du commit
echo ""
echo "-> Exécution du commit..."
git commit -m "$COMMIT_MSG"

# 6. Création du tag
echo "-> Création du tag annoté '$NEW_TAG'..."
git tag -a "$NEW_TAG" -m "Release $NEW_TAG: $COMMIT_MSG"

# 7. Push vers le remote
if [ "$DO_PUSH" = true ]; then
  echo "-> Push de la branche '$CURRENT_BRANCH' vers '$REMOTE'..."
  git push "$REMOTE" "$CURRENT_BRANCH"
  echo "-> Push du tag '$NEW_TAG' vers '$REMOTE'..."
  git push "$REMOTE" "$NEW_TAG"
  echo ""
  echo "✅ Opération terminée : commit, tag $NEW_TAG et push effectués avec succès."
else
  echo ""
  echo "✅ Opération terminée : commit et tag $NEW_TAG créés localement (--no-push)."
fi

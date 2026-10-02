---
name: git-commit-tag-push
description: >-
  Effectue un git commit avec le commentaire des derniers changements, génère automatiquement un tag de version au format 'v<aaaammjj>-<seq>' (où date est aaaammjj et seq est un numéro de séquence débutant à 1 et incrémenté de +1) puis effectue un git push de la branche et du tag vers le dépôt distant. Utilisez ce skill dès que l'utilisateur demande de commiter, taguer et pusher les modifications du projet.
metadata:
  icon: git
---

# Git Commit, Tag & Push Automatisé

Ce skill permet d'automatiser le cycle complet de livraison Git :
1. **Commit** : indexation et commit avec un message descriptif des derniers changements.
2. **Tag horodaté et séquencé** : création d'un tag au format `v<aaaammjj>-<seq>` (ex: `v20261002-1`, `v20261002-2` pour les commits successifs du même jour).
3. **Push** : publication de la branche active et du tag associé sur le dépôt distant.

---

## 🛠️ Utilisation via le Script Intégré

Le script exécutable [`scripts/git_commit_tag_push.sh`](file:///Users/yogi/Docker/agv.mails/.agents/skills/git-commit-tag-push/scripts/git_commit_tag_push.sh) gère l'ensemble de la procédure de manière unifiée et sécurisée.

### Commande recommandée

```bash
# Avec message de commit explicite
bash .agents/skills/git-commit-tag-push/scripts/git_commit_tag_push.sh -m "votre message de commit"

# Ou avec détection automatique du message basé sur le résumé des modifications
bash .agents/skills/git-commit-tag-push/scripts/git_commit_tag_push.sh
```

### Options du script

- `-m, --message "<msg>"` : Message du commit. S'il n'est pas fourni, le script génère automatiquement un résumé des fichiers modifiés.
- `-a, --all` : Ajoute automatiquement tous les changements (`git add -A`, activé par défaut).
- `--no-add` : N'ajoute pas les fichiers automatiquement ; utilise uniquement les fichiers déjà indexés (`staged`).
- `-d, --dry-run` : Affiche les actions et le tag calculé sans rien modifier.
- `--no-push` : Effectue le commit et le tag en local sans pousser sur le remote.
- `-r, --remote "<nom>"` : Nom du remote cible (par défaut `origin`).

---

## 📋 Procédure Manuelle Étape par Étape

Si le script n'est pas utilisé directement, suivez rigoureusement la procédure suivante :

### 1. Préparer et indexer les modifications

Vérifiez l'état du dépôt et indexez les fichiers modifiés :

```bash
git status -s
git add -A
```

Rédigez un message de commit clair décrivant les derniers changements apportés.

```bash
git commit -m "Description concise des changements"
```

### 2. Calculer le Tag `v<aaaammjj>-<seq>`

1. Obtenez la date du jour au format `aaaammjj` :
   ```bash
   DATE=$(date +%Y%m%d)
   ```
2. Interrogez les tags existants pour cette date :
   ```bash
   git tag -l "v${DATE}-*"
   ```
3. Déterminez la séquence `seq` :
   - Si aucun tag ne correspond à `v${DATE}-*`, `seq` vaut `1`.
   - Si des tags existent déjà (ex: `v20261002-1`, `v20261002-2`), extrayez le numéro de séquence le plus élevé et incrémentez-le de `+1` (ex: `seq = 3`).
   - Le tag résultant est `v${DATE}-${seq}` (ex: `v20261002-1`).

4. Créez le tag annoté :
   ```bash
   git tag -a "v${DATE}-${SEQ}" -m "Release v${DATE}-${SEQ}"
   ```

### 3. Pousser vers le remote

Identifiez la branche courante (ex: `main`) et poussez à la fois le commit et le nouveau tag :

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git push origin "$BRANCH"
git push origin "v${DATE}-${SEQ}"
```

---

## ✅ Validation et Vérification

Après exécution, vérifiez le bon déroulement avec :

```bash
# Vérifier le dernier commit
git log -1 --oneline

# Vérifier le dernier tag créé
git describe --tags --abbrev=0

# Vérifier que l'arbre de travail est propre
git status
```

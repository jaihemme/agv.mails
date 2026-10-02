# agv.mails — Analyseur & Agrégateur de Conversations E-mail

Ce projet fournit un outil en ligne de commande en Python permettant de parser des fichiers e-mails au format standard `.eml`, de nettoyer leur contenu, de les regrouper automatiquement par fil de discussion (conversation) et de consolider l'ensemble dans un fichier JSON structuré (ex. [`ppe.json`](file:///Users/yogi/Docker/agv.mails/ppe.json)).

---

## 📁 Structure du Projet

```text
/Users/yogi/Docker/agv.mails/
├── PPE/                                # Dossier contenant les e-mails sources (.eml)
│   ├── RE_ 4287 Rte de Nierlet...eml
│   └── Rappel _ PPE Nierlet...eml
├── update_conversations.py             # Script principal de parsing et regroupement
├── ppe.json                            # Résultat structuré des conversations au format JSON
├── update_conversations.log            # Fichier de logs d'exécution
└── README.md                           # Documentation du projet
```

---

## ⚙️ Fonctionnalités de `update_conversations.py`

Le script [`update_conversations.py`](file:///Users/yogi/Docker/agv.mails/update_conversations.py) assure les tâches suivantes :

1. **Parcours des fichiers :** Accepte un fichier `.eml` individuel ou explore récursivement un dossier complet.
2. **Extraction des en-têtes RFC 822 :**
   - Identifiants uniques (`Message-ID`, `In-Reply-To`).
   - Horodatage converti au format ISO 8601 (`YYYY-MM-DDTHH:MM:SS`).
   - Identité et adresse de l'expéditeur (`From`).
   - Listes structurées de destinataires (`To`, `Cc`, `Bcc`) avec nom et adresse e-mail.
3. **Nettoyage du corps du message (`contenu_nettoye`) :**
   - Détection et suppression des signatures courantes (`-- `, `Sent from my...`, `Envoyé de mon...`).
   - Suppression des citations d'anciens messages (`>`, `Le ... a écrit`, `On ... wrote`).
4. **Détection des transferts & pièces jointes :**
   - Extraction des métadonnées des messages transférés (`FWD:`, `TR:`).
   - Recensement des pièces jointes (nom, type MIME, taille en octets).
5. **Algorithme de regroupement en conversations :**
   - **Déduplication :** Ignore les messages déjà importés selon leur `message_id`.
   - **Liaison parent-enfant :** Rapproche le message d'une conversation existante via l'identifiant `In-Reply-To`.
   - **Liaison par sujet :** En l'absence de `In-Reply-To`, normalise le sujet (suppression des préfixes `Re:`, `Fwd:`, `TR:`, balises de version) et cherche une conversation au sujet identique.
   - **Création :** Si aucune correspondance n'est trouvée, crée un nouveau fil de discussion.
   - **Ordonnancement :** Trie chronologiquement les messages d'un fil et ajuste `date_debut` et `date_fin`.
6. **Mise à jour incrémentale :** Charge le fichier JSON existant, y injecte les nouveaux messages sans écraser l'historique, et met à jour les métadonnées globales.

---

## 🚀 Utilisation

### Prérequis

- Python 3.10+ (utilise les modules de la bibliothèque standard : `email`, `json`, `logging`, `argparse`, `re`, `datetime`, `os`).

### Ligne de commande

```bash
python3 update_conversations.py --input <FICHIER_OU_DOSSIER_EML> --json_file <FICHIER_JSON> [OPTIONS]
```

### Options disponibles

| Argument | Type | Description |
| :--- | :---: | :--- |
| `--input` | *Requis* | Chemin vers un fichier `.eml` ou un répertoire contenant des fichiers `.eml` (ex: `PPE`). |
| `--json_file` | *Requis* | Chemin vers le fichier JSON existant à mettre à jour ou à créer (ex: `ppe.json`). |
| `--output` | *Optionnel* | Chemin alternatif du fichier JSON de sortie (par défaut : identique à `--json_file`). |
| `--dry-run` | *Optionnel* | Mode simulation : traite et affiche le résumé sans enregistrer de modifications. |
| `--log-level` | *Optionnel* | Niveau de verbosité des logs : `debug`, `info` (défaut), `warning`, `error`. |
| `--log-file` | *Optionnel* | Fichier de destination des logs (défaut : `update_conversations.log`). |

### Exemples

**Traitement du dossier `PPE` vers `ppe.json` :**
```bash
python3 update_conversations.py --input PPE --json_file ppe.json
```

**Test en mode simulation (dry-run) avec logs détaillés :**
```bash
python3 update_conversations.py --input PPE --json_file ppe.json --dry-run --log-level debug
```

**Exemple de sortie console :**
```text
============================================================
SUMMARY
============================================================
Files processed: 2
New messages added: 2
Messages skipped (duplicates): 0
Errors: 0
Total conversations: 2
Total messages: 2

JSON saved to: ppe.json
============================================================
```

---

## 📄 Structure du Résultat : `ppe.json`

Le fichier [`ppe.json`](file:///Users/yogi/Docker/agv.mails/ppe.json) contient la structure consolidée des échanges.

### Schéma global

```json
{
  "meta": {
    "date_derniere_mise_a_jour": "2026-10-02T14:29:28.326384",
    "nombre_conversations": 2,
    "nombre_messages": 2
  },
  "conversations": [
    {
      "sujet": "4287 Rte de Nierlet 8 - Neyruz_Garage Grille pare-pluie",
      "sujet_normalise": "4287 Rte de Nierlet 8 - Neyruz_Garage Grille pare-pluie",
      "date_debut": "2026-07-20T08:06:36",
      "date_fin": "2026-07-20T08:06:36",
      "nombre_messages": 1,
      "messages": [ /* Liste des messages de la conversation */ ]
    }
  ]
}
```

### Description des champs

#### 1. Objet racine `meta`
- `date_derniere_mise_a_jour` *(string ISO)* : Date et heure de la dernière exécution ayant modifié le JSON.
- `nombre_conversations` *(int)* : Total des conversations référencées.
- `nombre_messages` *(int)* : Total cumulé de l'ensemble des messages indexés.

#### 2. Objet `conversations[]`
- `sujet` *(string)* : Objet du message tel qu'initialement renseigné.
- `sujet_normalise` *(string)* : Objet nettoyé des préfixes de réponse/transfert pour le regroupement.
- `date_debut` *(string ISO)* : Date du message le plus ancien du fil.
- `date_fin` *(string ISO)* : Date du message le plus récent du fil.
- `nombre_messages` *(int)* : Quantité de messages rattachés à cette conversation.
- `messages[]` *(array)* : Liste ordonnée chronologiquement des messages composant le fil.

#### 3. Détail d'un élément `messages[]`

| Champ | Type | Description |
| :--- | :--- | :--- |
| `fichier_source` | `string` | Chemin absolu vers le fichier `.eml` d'origine. |
| `timestamp` | `string` | Date et heure d'envoi normalisée en ISO 8601. |
| `message_id` | `string` | Identifiant universel du message RFC 822 (sans chevrons `<>`). |
| `in_reply_to` | `string` | Identifiant du message parent auquel ce courriel répond. |
| `expediteur_nom` | `string` | Nom d'affichage de l'émetteur. |
| `expediteur_email` | `string` | Adresse e-mail de l'expéditeur. |
| `destinataires` | `object` | Contient les listes `to`, `cc`, et `bcc`, chacune composée d'objets `{"nom": "...", "email": "..."}`. |
| `sujet` | `string` | Objet normalisé du message. |
| `contenu_nettoye` | `string` | Corps textuel brut après suppression des signatures et historiques cités. |
| `pieces_jointes` | `array` | Liste d'objets pour chaque pièce jointe : `{"nom": "...", "type": "...", "taille": <octets>}`. |
| `forwarded_message` | `object \| null` | Contient `{"auteur": "...", "date": "...", "sujet": "..."}` si le message transfère un autre échange, sinon `null`. |

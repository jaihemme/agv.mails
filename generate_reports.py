import argparse
import json
import os
import re
import hashlib
from datetime import datetime
from pathlib import Path

def slugify(text):
    """Convert subject to a filesystem-safe filename."""
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    return re.sub(r'\s+', '_', text).strip('_')

def compute_conversation_hash(conversation):
    """Compute a hash based on message IDs and timestamps to detect changes."""
    hash_input = ""
    for msg in conversation.get('messages', []):
        hash_input += f"{msg.get('message_id', '')}|{msg.get('timestamp', '')}"
    return hashlib.sha256(hash_input.encode('utf-8')).hexdigest()

def get_attachment_filename(attachment_obj):
    """
    Convert attachment object to filename as per README: {date_creation}_{nom_original}
    Note: date_creation in JSON is often in RFC 2822 format (e.g., 'Fri, 13 Dec 2024...').
    We need to normalize it to YYYYMMDDHHMMSS.
    """
    date_str = attachment_obj.get('creation-date', '')
    nom = attachment_obj.get('nom', 'unknown')

    if not date_str:
        return nom

    try:
        # Try to parse RFC 2822 date
        dt = datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S GMT')
        formatted_date = dt.strftime('%Y%m%d%H%M%S')
    except ValueError:
        # Fallback if date format differs
        formatted_date = "00000000000000"

    return f"{formatted_date}_{nom}"

def generate_llm_summary(conversation_data):
    """
    Placeholder for LLM narrative summary.
    In a real implementation, this would call an API (e.g., Anthropic, OpenAI).
    """
    messages = conversation_data.get('messages', [])
    full_text = "\n\n".join([f"From: {m.get('expediteur_email')}\n{m.get('contenu_nettoye', '')}" for m in messages])

    # This is a placeholder. Replace with actual LLM API call.
    return f"***[RÉSUMÉ GÉNÉRÉ PAR LLM]***\n\nCette conversation contient {len(messages)} messages concernant '{conversation_data.get('sujet_normalise')}'.\n\n(Le contenu narratif serait ici après appel API avec le texte suivant : {full_text[:200]}...)"

def needs_update(conversation, rapports_dir):
    """Check if report needs to be created or updated."""
    slug = slugify(conversation['sujet_normalise'])
    report_path = Path(rapports_dir) / f"{slug}.md"

    if not report_path.exists():
        return True

    current_hash = compute_conversation_hash(conversation)

    with open(report_path, 'r', encoding='utf-8') as f:
        content = f.read()
        # Look for hidden hash in HTML comment
        match = re.search(r'<!-- hash: ([a-f0-9]+) -->', content)
        if match:
            stored_hash = match.group(1)
            return current_hash != stored_hash

    return True

def generate_report(conversation, rapports_dir, attachment_dir):
    """Generate the Markdown report for a single conversation."""
    slug = slugify(conversation['sujet_normalise'])
    report_path = Path(rapports_dir) / f"{slug}.md"

    # Header
    lines = []
    lines.append(f"# {conversation['sujet_normalise']}")
    lines.append(f"**Période:** {conversation['date_debut']} - {conversation['date_fin']}")
    lines.append("")

    # Chapter 1: Messages
    msgs = conversation.get('messages', [])
    lines.append(f"## Messages ({len(msgs)})")

    # Table Header
    lines.append("| Date d'envoi | Sujet et Participants |")
    lines.append("| :--- | :--- |")

    for m in msgs:
        ts = m.get('timestamp', 'N/A')
        sujet = m.get('sujet', 'Sans sujet')
        source = m.get('fichier_source', '')

        # Expéditeur
        exp_nom = m.get('expediteur_nom', '')
        exp_email = m.get('expediteur_email', 'Inconnu')
        exp_full = f"{exp_nom} <{exp_email}>" if exp_nom else exp_email

        # Destinataires (to et cc uniquement)
        dests = m.get('destinataires', {})
        recipients_list = []
        for key in ['to', 'cc']:
            for r in dests.get(key, []):
                name = r.get('nom', '')
                email = r.get('email', '')
                recipients_list.append(f"{name} <{email}>" if name else email)
        dest_str = ", ".join(filter(None, recipients_list))

        source_link = f"[{sujet}]({source})" if source else sujet

        # Construction de la cellule Sujet (Sujet lien <br> Expéditeur -> Destinataires)
        participants = f"{exp_full} → {dest_str}" if dest_str else exp_full
        subject_cell = f"{source_link}<br>{participants}"

        lines.append(f"| {ts} | {subject_cell} |")

    lines.append("")

    # Chapter 2: Résumé
    lines.append("## Résumé")
    summary = generate_llm_summary(conversation)
    lines.append(summary)
    lines.append("")

    # Chapter 3: Pièces jointes
    all_attachments = []
    for m in msgs:
        all_attachments.extend(m.get('pieces_jointes', []))

    if all_attachments:
        lines.append("## Pièces jointes")
        for att in all_attachments:
            filename = get_attachment_filename(att)
            att_path = Path(attachment_dir) / filename
            if att_path.exists():
                lines.append(f"- [{att.get('nom')}]({att_path})")
            else:
                lines.append(f"- {att.get('nom')} *(Fichier non trouvé : {filename})*")
        lines.append("")

    # Footer with hash for incremental updates
    conv_hash = compute_conversation_hash(conversation)
    lines.append(f"<!-- hash: {conv_hash} -->")

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))

    return report_path

def main():
    parser = argparse.ArgumentParser(description="Generate conversation reports from email JSON.")
    parser.add_argument("--input", help="Input JSON file (e.g. ppe.json)")
    parser.add_argument("--rapports-dir", default="ppe-rapports", help="Directory for output reports")
    parser.add_argument("--attachment-dir", default="ppe-att", help="Directory for attachment files")

    args = parser.parse_args()

    input_file = args.input
    if not input_file:
        input_file = input("Please enter the path to the JSON file to process: ").strip()

    if not input_file or not os.path.exists(input_file):
        print(f"Error: Input file {input_file} not found.")
        return

    # Ensure directories exist
    os.makedirs(args.rapports_dir, exist_ok=True)

    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    conversations = data.get('conversations', [])
    print(f"Processing {len(conversations)} conversations...")

    updated_count = 0
    for conv in conversations:
        if needs_update(conv, args.rapports_dir):
            report_path = generate_report(conv, args.rapports_dir, args.attachment_dir)
            print(f"Updated: {report_path.name}")
            updated_count += 1

    print(f"\nDone. {updated_count} reports were created or updated.")

if __name__ == "__main__":
    main()

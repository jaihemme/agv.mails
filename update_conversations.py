"""
Parsing functions for email .eml files.
Extracts metadata, recipients, body, attachments, and forwarded messages.
"""

import argparse
import email
import email.policy
from email.iterators import _structure
import json
import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any


class LogWriter:
    # pour avoir une fonction 'write' qui déroute les données de _structure
    def __init__(self, logger, level=logging.DEBUG):
        self.logger = logger
        self.level = level
        self._buffer = ''

    def write(self, msg):
        self._buffer += msg
        if '\n' in self._buffer:
            for line in self._buffer.splitlines():
                if line: self.logger.log(self.level, line)
            self._buffer = ''

    def flush(self):
        if self._buffer:
            self.logger.log(self.level, self._buffer)
            self._buffer = ''


def setup_logging(log_file: str, level: str = "info") -> None:
    """
    Configure logging to file with specified level.
    
    Args:
        log_file: Path to the log file.
        level: Logging level - 'debug' for developer, 'info' for user.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        filename=log_file,
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        force=True
    )


def normalize_subject(subject: str) -> str:
    """
    Normalize email subject by removing common prefixes and extra spaces.
    
    Args:
        subject: The raw email subject string.
        
    Returns:
        Normalized subject string.
    """
    if not subject:
        return ""
    
    # Remove common prefixes (case-insensitive)
    prefixes = [
        r'^\s*Re:\s*',
        r'^\s*Fwd:\s*',
        r'^\s*TR:\s*',
        r'^\s*FWD:\s*',
        r'^\s*FW:\s*',
        r'^\s*RE:\s*',
        r'^\s*\[.*?\]\s*',  # Version numbers in brackets
    ]
    
    for prefix in prefixes:
        subject = re.sub(prefix, '', subject, flags=re.IGNORECASE)
    
    # Remove leading/trailing whitespace and multiple spaces
    subject = re.sub(r'\s+', ' ', subject).strip()
    
    logging.debug(f"Normalized subject: '{subject}'")
    return subject


def _parse_address(address_str: str) -> Tuple[str, str]:
    """
    Parse an email address string into (name, email) tuple.
    Handles various formats: 'Name <email@dom.com>', 'email@dom.com', 'Name <email@dom.com> (Comment)'
    
    Args:
        address_str: Raw address string.
        
    Returns:
        Tuple of (name, email). Name is empty string if not present.
    """
    if not address_str:
        return "", ""
    
    # Remove any trailing comments
    address_str = re.sub(r'\(.*\)$', '', address_str).strip()
    
    # Check for format: Name <email>
    match = re.match(r'^(.*?)\s*<(.+?)>$', address_str)
    if match:
        name = match.group(1).strip()
        email_addr = match.group(2).strip()
        return name, email_addr
    
    # Check for just email
    if re.match(r'^[\w.+-]+@[\w.-]+\.\w+$', address_str):
        return "", address_str
    
    # Try to extract email from string
    email_match = re.search(r'([\w.+-]+@[\w.-]+\.\w+)', address_str)
    if email_match:
        email_addr = email_match.group(1)
        name = address_str.replace(email_addr, '').strip()
        return name, email_addr
    
    return address_str, ""


def _parse_recipients(header_value: str) -> List[Dict[str, str]]:
    """
    Parse recipient header into list of {name, email} dicts.
    
    Args:
        header_value: Raw header value (e.g., '"Name" <a@b.com>, c@d.com')
        
    Returns:
        List of dicts with 'nom' and 'email' keys.
    """
    if not header_value:
        return []
    
    recipients = []
    # Split by comma, but respect quoted strings
    for addr in email.utils.getaddresses([header_value]):
        # getaddresses returns list of (name, email) tuples
        if addr[1]:  # If email exists
            recipients.append({
                "nom": addr[0] or "",
                "email": addr[1]
            })
    
    return recipients


def _extract_forwarded_message(email_msg) -> Optional[Dict[str, Any]]:
    """
    Extract forwarded message information if this is a forwarded email.
    
    Args:
        email_msg: Parsed email.message object.
        
    Returns:
        Dict with forwarded message info or None.
    """
    subject = email_msg.get('Subject', '') or ''
    
    # Check if subject indicates forwarding
    is_forwarded = any(
        prefix in subject.upper() 
        for prefix in ['FWD:', 'FWD', 'TR:', 'TR', 'FORWARDED:', 'FORWARDED']
    )
    
    if not is_forwarded:
        return None
    
    forwarded = None
    
    # Try to find forwarded content in body
    if email_msg.is_multipart():
        for part in email_msg.walk():
            content_type = part.get_content_type()
            if content_type == 'message/rfc822':
                # This is an embedded message
                try:
                    payload = part.get_payload()
                    if isinstance(payload, list) and len(payload) > 0:
                        embedded_msg = payload[0]
                    elif isinstance(payload, email.message.Message):
                        embedded_msg = payload
                    else:
                        raw_payload = part.get_payload(decode=True)
                        embedded_msg = email.message_from_bytes(raw_payload) if raw_payload else part

                    forwarded = {
                        "auteur": embedded_msg.get('From', ''),
                        "date": embedded_msg.get('Date', ''),
                        "sujet": embedded_msg.get('Subject', '')
                    }
                    logging.debug(f"Found embedded forwarded message: {forwarded}")
                    break
                except Exception as e:
                    logging.debug(f"Could not parse embedded message: {e}")
                    continue
            
            # Check for forwarded text in plain text parts
            if content_type == 'text/plain':
                body = part.get_payload(decode=True)
                if isinstance(body, bytes):
                    body = body.decode('utf-8', errors='replace')
                if isinstance(body, str):
                    forwarded = _extract_forwarded_from_text(body)
                    if forwarded:
                        break
    else:
        # Single part message
        body = email_msg.get_payload(decode=True)
        if isinstance(body, bytes):
            body = body.decode('utf-8', errors='replace')
        if isinstance(body, str):
            forwarded = _extract_forwarded_from_text(body)
    
    return forwarded


def _extract_forwarded_from_text(body: str) -> Optional[Dict[str, str]]:
    """
    Extract forwarded message info from text body.
    Looks for patterns like '-----Forwarded Message-----' or similar.
    
    Args:
        body: Email body text.
        
    Returns:
        Dict with author, date, subject or None.
    """
    # Common forwarded message separators
    separators = [
        r'-----Original Message-----',
        r'-----Forwarded Message-----',
        r'-------- Forwarded message --------',
        r'---\s*Forwarded\s+Message\s*---',
        r'De\s*:',
        r'From\s*:',
    ]
    
    for sep in separators:
        match = re.search(sep, body, re.IGNORECASE)
        if match:
            # Extract the forwarded part
            forwarded_text = body[match.start():]
            
            # Try to extract From, Date, Subject
            author = None
            date = None
            subject = None
            
            # Parse from forwarded text
            for line in forwarded_text.split('\n'):
                line = line.strip()
                from_match = re.match(r'(?:De|From)\s*:\s*(.+)', line, re.IGNORECASE)
                if from_match:
                    author = from_match.group(1).strip()
                date_match = re.match(r'Date\s*:\s*(.+)', line, re.IGNORECASE)
                if date_match:
                    date = date_match.group(1).strip()
                subject_match = re.match(r'Subject\s*:\s*(.+)', line, re.IGNORECASE)
                if subject_match:
                    subject = subject_match.group(1).strip()
            
            if author or date or subject:
                return {
                    "auteur": author or "",
                    "date": date or "",
                    "sujet": subject or ""
                }
    
    return None


def _clean_body(body: str) -> str:
    """
    Clean email body by removing signatures, quoted text, and cited history.
    
    Args:
        body: Raw email body text.
        
    Returns:
        Cleaned body text.
    """
    if not body:
        return ""
    
    lines = body.split('\n')
    cleaned_lines = []
    in_signature = False

    # Common signature separators
    sig_separators = [
        '--',
        '-- ',
        '---',
        '_____',
        'Sent from my',
        'Envoyé de mon',
    ]
    
    # Common quoted line prefixes
    quote_prefixes = ['> ', '>> ', '>>> ']
    
    for line in lines:
        stripped = line.strip()
        
        # Check for signature start
        if line.startswith('-- ') or any(stripped.startswith(sep) or stripped == sep for sep in sig_separators):
            in_signature = True
            continue
        
        if in_signature:
            continue
        
        # Check for quoted text
        if any(stripped.startswith(prefix) for prefix in quote_prefixes):
            continue
        
        # Check for "Le ... a écrit" patterns (French quoted text indicator)
        if re.search(r'Le\s+.*?\s+a\s+écrit', stripped, re.IGNORECASE):
            continue
        if re.search(r'On\s+.*?\s+wrote', stripped, re.IGNORECASE):
            continue
        if re.match(r'On\s+\w+\s+\d+\s+\w+\s+\d+\s+a\s+écrit', stripped, re.IGNORECASE):
            continue
        if re.match(r'On\s+\w+\s+\d+\s+at\s+\d+:\d+', stripped, re.IGNORECASE):
            continue
        
        # Skip empty lines at the end if we're in signature mode
        if not stripped and in_signature:
            continue
        
        cleaned_lines.append(line)
    
    # Join and clean up multiple newlines
    cleaned = '\n'.join(cleaned_lines)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = cleaned.strip()

    logging.debug(f"Cleaned body: {cleaned}")
    
    return cleaned


def _get_attachments(email_msg, attachment_dir=None) -> List[Dict[str, str]]:
    """
    Extract attachment information from email.
    If attachment_dir is provided, saves the attachment files to disk.

    Args:
        email_msg: Parsed email.message object.
        attachment_dir: Optional directory to save attachments.

    Returns:
        List of attachment dicts with name, content_type, size.
    """
    attachments = []

    if attachment_dir:
        os.makedirs(attachment_dir, exist_ok=True)

    if email_msg.is_multipart():
        for part in email_msg.walk():
            content_disposition = part.get('Content-Disposition', '')
            content_type = part.get('Content-Type', '')

            # Skip multipart containers and text parts
            if part.is_multipart():
                continue
            if content_type.startswith('text/'):
                continue
            
            # Check if it's an attachment
            if 'attachment' in content_disposition:

                # Utilisation d'un objet temporaire EmailMessage pour parser proprement les paramètres
                temp_msg = email.message.EmailMessage()
                temp_msg['Content-Disposition'] = content_disposition

                # Extraction des éléments
                filename = temp_msg.get_filename() or None
                params = temp_msg['Content-Disposition'].params
                size = params.get('size')
                creation_date_raw = params.get('creation-date')

                # Traitement de la date de création
                if creation_date_raw:
                    dt = email.utils.parsedate_to_datetime(creation_date_raw)
                else:
                    # Repli si la date de création n'est pas spécifiée dans l'en-tête
                    dt = datetime.now()
                date_prefix = dt.strftime('%Y%m%d%H%M%S')

                logging.debug(f"Attachment {filename} - Content-Disposition: {content_disposition}, {size} bytes, "
                              f"{creation_date_raw}")

                if not attachment_dir:
                    logging.error(f"Attachment-dir n'est pas spécifié, donc pas de sauvegarde de la pièce jointe")
                    continue

                # création du nouveau nom de fichier
                if not filename:
                    # Try to extract from content-type
                    match = re.search(r'name="?([^";]+)"?', content_type)
                    if match:
                        filename = match.group(1)
                
                if filename:
                    new_filename = f"{date_prefix}_{filename}"
                    # Use get_payload(decode=True) for binary data
                    payload = part.get_payload(decode=True)
                    if not payload:
                        continue
                    if not size:  # si 'size' n'est pas spécifié, on prend la taille du payload
                        size = len(payload)
                    if int(size) != len(payload):  # si 'size' est spécifié, on compare avec la taille réelle (juste info)
                        logging.error(f"Size in header ({size}) differs from payload size ({len(payload)})")

                    save_path = os.path.join(attachment_dir, new_filename)
                    try:
                        with open(save_path, 'wb') as f:
                            f.write(payload)
                        logging.info(f"Saved attachment to {save_path}")
                    except Exception as e:
                        logging.error(f"Failed to save attachment {new_filename} to {save_path}: {e}")

                    attachments.append({
                        "nom": new_filename,
                        "type": content_type.split(';')[0].strip(),
                        "taille": size,
                        "creation-date": creation_date_raw
                    })

    return attachments


def parse_email_file(filepath: str, attachment_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Parse an .eml email file and extract all relevant information.

    Args:
        filepath: Path to the .eml file.
        attachment_dir: Optional directory to save attachments.

    Returns:
        Dict with parsed email data following the specified structure,
        or None if parsing fails (with error logged).
    
    The returned dict has structure:
    {
      "fichier_source": "...",
      "timestamp": "...",
      "message_id": "...",
      "in_reply_to": "...",
      "expediteur_nom": "...",
      "expediteur_email": "...",
      "destinataires": {"to": [], "cc": [], "bcc": []},
      "sujet": "...",
      "contenu_nettoye": "...",
      "pieces_jointes": [],
      "forwarded_message": {...} or null
    }
    """
    try:
        logging.info(f"Parsing file: {filepath}")
        
        # Read the file
        with open(filepath, 'rb') as f:
            msg_bytes = f.read()
        
        # Parse the email
        msg = email.message_from_bytes(msg_bytes, policy=email.policy.default)

        # analyse de la structure mime
        logging.debug(f"Analyse de la structure des mime types:")
        _structure(msg, fp=LogWriter(logging.getLogger()), level=1)

        # Extract basic headers
        message_id = msg.get('Message-ID', '') or ''
        in_reply_to = msg.get('In-Reply-To', '') or ''
        raw_subject = msg.get('Subject', '') or ''
        raw_date = msg.get('Date', '') or ''
        raw_from = msg.get('From', '') or ''
        raw_to = msg.get('To', '') or ''
        raw_cc = msg.get('Cc', '') or ''
        raw_bcc = msg.get('Bcc', '') or ''
        
        logging.debug(f"Extracted headers from {filepath}")
        logging.debug(f"  Message-ID: {message_id}")
        logging.debug(f"  In-Reply-To: {in_reply_to}")
        logging.debug(f"  Subject: {raw_subject}")
        logging.debug(f"  From: {raw_from}")
        
        # Parse sender
        from_parsed = email.utils.parseaddr(raw_from)
        expediteur_nom = from_parsed[0] or ""
        expediteur_email = from_parsed[1] or ""
        
        # Parse recipients
        to_recipients = _parse_recipients(raw_to)
        cc_recipients = _parse_recipients(raw_cc)
        bcc_recipients = _parse_recipients(raw_bcc)
        
        logging.debug(f"  To: {len(to_recipients)} recipients")
        logging.debug(f"  Cc: {len(cc_recipients)} recipients")
        logging.debug(f"  Bcc: {len(bcc_recipients)} recipients")
        
        # Normalize subject
        sujet = normalize_subject(raw_subject)
        
        # Parse date to timestamp
        timestamp = ""
        if raw_date:
            try:
                # Parse email date string
                date_tuple = email.utils.parsedate_tz(raw_date)
                if date_tuple:
                    # Convert to ISO format
                    dt = datetime.fromtimestamp(email.utils.mktime_tz(date_tuple))
                    timestamp = dt.isoformat()
            except Exception as e:
                logging.debug(f"Could not parse date '{raw_date}': {e}")
                timestamp = raw_date
        
        # Extract body
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == 'text/plain':
                    payload = part.get_content()
                    if isinstance(payload, bytes):
                        logging.error(f"NE DEVRAIT PAS ARRIVER: in get_content en bytes")
                    elif isinstance(payload, str):
                        body += payload
                    body += '\n'
        else:
            payload = msg.get_payload(decode=True)
            if isinstance(payload, bytes):
                body = payload.decode(msg.get_content_charset() or 'latin-1', errors='replace')
            elif isinstance(payload, str):
                body = payload
        
        # Clean body
        contenu_nettoye = _clean_body(body)
        
        # Get attachments
        pieces_jointes = _get_attachments(msg, attachment_dir=attachment_dir)
        
        # Check for forwarded message
        forwarded_message = _extract_forwarded_message(msg)
        
        # Build result
        result = {
            "fichier_source": os.path.abspath(filepath),
            "timestamp": timestamp,
            "message_id": message_id.strip('<>') if message_id else "",
            "in_reply_to": in_reply_to.strip('<>') if in_reply_to else "",
            "expediteur_nom": expediteur_nom,
            "expediteur_email": expediteur_email,
            "destinataires": {
                "to": to_recipients,
                "cc": cc_recipients,
                "bcc": bcc_recipients
            },
            "sujet": sujet,
            "contenu_nettoye": contenu_nettoye,
            "pieces_jointes": pieces_jointes,
            "forwarded_message": forwarded_message
        }
        
        logging.info(f"Successfully parsed: {filepath}")
        return result
        
    except FileNotFoundError:
        error_msg = f"File not found: {filepath}"
        logging.error(error_msg)
        return None
    except PermissionError:
        error_msg = f"Permission denied: {filepath}"
        logging.error(error_msg)
        return None
    except email.errors.MessageError as e:
        error_msg = f"Invalid email format in {filepath}: {e}"
        logging.error(error_msg)
        return None
    except UnicodeDecodeError as e:
        error_msg = f"Encoding error in {filepath}: {e}"
        logging.error(error_msg)
        return None
    except Exception as e:
        error_msg = f"Unexpected error parsing {filepath}: {e}"
        logging.error(error_msg)
        return None


def load_json(filepath: str) -> Dict[str, Any]:
    """
    Load existing JSON file or create empty structure.
    
    Args:
        filepath: Path to the JSON file.
        
    Returns:
        Dict with structure: {"meta": {...}, "conversations": []}
    """
    default_structure = {
        "meta": {
            "date_derniere_mise_a_jour": "",
            "nombre_conversations": 0,
            "nombre_messages": 0
        },
        "conversations": []
    }
    
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Ensure structure is valid
                if "conversations" not in data:
                    data["conversations"] = []
                if "meta" not in data:
                    data["meta"] = default_structure["meta"]
                logging.info(f"Loaded existing JSON: {filepath}")
                return data
        else:
            logging.info(f"Creating new JSON structure for: {filepath}")
            return default_structure.copy()
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in {filepath}: {e}")
        return default_structure.copy()
    except Exception as e:
        logging.error(f"Error loading {filepath}: {e}")
        return default_structure.copy()


def merge_message_into_conversations(json_data: Dict[str, Any], new_message: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Merge a parsed message into the conversations structure.
    
    Args:
        json_data: Existing JSON data with conversations.
        new_message: New message dict from parse_email_file.
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    if not new_message or not new_message.get("message_id"):
        return False, "Message has no valid message_id"
    
    message_id = new_message["message_id"]
    in_reply_to = new_message.get("in_reply_to", "")
    sujet = new_message.get("sujet", "")
    timestamp = new_message.get("timestamp", "")
    
    # Check if message already exists
    for conv in json_data["conversations"]:
        for msg in conv.get("messages", []):
            if msg.get("message_id") == message_id:
                return False, f"Message {message_id} already exists, skipped"
    
    # Try to find parent conversation via in_reply_to
    target_conv = None
    if in_reply_to:
        for conv in json_data["conversations"]:
            for msg in conv.get("messages", []):
                if msg.get("message_id") == in_reply_to:
                    target_conv = conv
                    break
            if target_conv:
                break
    
    # If not found by in_reply_to, try by normalized subject
    if not target_conv and sujet:
        normalized_subj = normalize_subject(sujet)
        for conv in json_data["conversations"]:
            conv_subj = normalize_subject(conv.get("sujet", ""))
            if conv_subj and conv_subj == normalized_subj:
                target_conv = conv
                break
    
    # If still not found, create new conversation
    if not target_conv:
        target_conv: Dict[str, Any] = {
            "sujet": sujet,
            "sujet_normalise": normalize_subject(sujet),
            "date_debut": timestamp,
            "date_fin": timestamp,
            "nombre_messages": 0,
            "messages": []
        }
        json_data["conversations"].append(target_conv)
        json_data["meta"]["nombre_conversations"] += 1
        logging.info(f"Created new conversation: {sujet}")
    
    # Add message to conversation
    target_conv["messages"].append(new_message)
    target_conv["nombre_messages"] += 1
    
    # Update conversation timestamps
    if timestamp:
        if not target_conv.get("date_debut") or timestamp < target_conv["date_debut"]:
            target_conv["date_debut"] = timestamp
        if not target_conv.get("date_fin") or timestamp > target_conv["date_fin"]:
            target_conv["date_fin"] = timestamp
    
    # Sort messages by timestamp
    target_conv["messages"].sort(
        key=lambda m: m.get("timestamp", ""),
        reverse=False
    )
    
    # Update global meta
    json_data["meta"]["nombre_messages"] += 1
    json_data["meta"]["date_derniere_mise_a_jour"] = datetime.now().isoformat()
    
    logging.info(f"Added message {message_id} to conversation: {target_conv.get('sujet', 'Unknown')}")
    return True, f"Message {message_id} added successfully"


def save_json(filepath: str, data: Dict[str, Any]) -> bool:
    """
    Save data to JSON file.
    
    Args:
        filepath: Path to save the JSON file.
        data: Data to save.
        
    Returns:
        True if successful, False otherwise.
    """
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logging.info(f"Saved JSON to: {filepath}")
        return True
    except Exception as e:
        logging.error(f"Error saving JSON to {filepath}: {e}")
        return False


def main():
    """
    Main entry point with argparse.
    Processes .eml files, parses them, and merges into conversations JSON.
    """
    parser = argparse.ArgumentParser(
        description='Parse .eml files and update conversations JSON'
    )
    parser.add_argument(
        '--input',
        type=str,
        required=True,
        help='Input file or directory containing .eml files'
    )
    parser.add_argument(
        '--json_file',
        type=str,
        required=True,
        help='Path to the JSON file to load/update'
    )
    parser.add_argument(
        '--output',
        type=str,
        help='Output JSON file path (default: same as --json_file)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Process without saving changes'
    )
    parser.add_argument(
        '--log-level',
        type=str,
        default='info',
        choices=['debug', 'info', 'warning', 'error'],
        help='Logging level (default: info)'
    )
    parser.add_argument(
        '--log-file',
        type=str,
        default='update_conversations.log',
        help='Path to the log file (default: update_conversations.log)'
    )
    parser.add_argument(
        '--attachment-dir',
        type=str,
        required=True,
        help='Directory to save email attachments'
    )

    args = parser.parse_args()
    
    # Setup logging
    setup_logging(args.log_file, args.log_level)
    logging.info(f"Starting processing with args: {args}")
    
    # Determine output path
    output_path = args.output if args.output else args.json_file
    
    # Load existing JSON
    json_data = load_json(args.json_file)
    #initial_message_count = json_data["meta"]["nombre_messages"]
    #initial_conv_count = json_data["meta"]["nombre_conversations"]
    
    # Collect input files
    input_files = []
    if os.path.isfile(args.input):
        if args.input.endswith('.eml'):
            input_files.append(args.input)
        else:
            logging.warning(f"Input file {args.input} is not a .eml file, skipping")
    elif os.path.isdir(args.input):
        for root, _, files in os.walk(args.input):
            for file in files:
                if file.endswith('.eml'):
                    input_files.append(os.path.join(str(root), str(file)))
    else:
        logging.error(f"Input path does not exist: {args.input}")
        print(f"Error: Input path does not exist: {args.input}")
        return
    
    logging.info(f"Found {len(input_files)} .eml files to process")
    
    # Process files
    new_messages = 0
    skipped_messages = 0
    errors = 0
    
    for filepath in sorted(input_files):
        try:
            # Parse email
            message = parse_email_file(filepath, attachment_dir=args.attachment_dir)
            if message is None:
                errors += 1
                continue
            
            # Merge into conversations
            success, msg = merge_message_into_conversations(json_data, message)
            if success:
                new_messages += 1
                logging.info(f"Processed: {filepath} -> {msg}")
            else:
                skipped_messages += 1
                logging.info(f"Skipped: {filepath} -> {msg}")
                
        except Exception as e:
            errors += 1
            logging.error(f"Error processing {filepath}: {e}")
    
    # Display summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Files processed: {len(input_files)}")
    print(f"New messages added: {new_messages}")
    print(f"Messages skipped (duplicates): {skipped_messages}")
    print(f"Errors: {errors}")
    print(f"Total conversations: {json_data['meta']['nombre_conversations']}")
    print(f"Total messages: {json_data['meta']['nombre_messages']}")
    
    if not args.dry_run:
        if save_json(output_path, json_data):
            print(f"\nJSON saved to: {output_path}")
        else:
            print(f"\nERROR: Failed to save JSON to: {output_path}")
    else:
        print("\n[DRY RUN] No changes were saved")
    
    print("="*60)


if __name__ == "__main__":
    main()

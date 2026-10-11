import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from tqdm import tqdm
from urllib.parse import quote


# Try to import whisper; if it fails, the script will still run but skip transcription
try:
    import whisper
    WHISPER_AVAILABLE = False
except ImportError:
    WHISPER_AVAILABLE = False

def parse_whatsapp_chat(file_path):
    """
    Parses a WhatsApp export .txt file.
    """
    messages = []
    # Regex to detect the start of a message (Date/Time pattern)
    msg_start_pattern = re.compile(r'^[\s‎]*\[?(\d{1,4}[./-]\d{1,2}[./-]\d{2,4}\s\d{1,2}:\d{2}(?::\d{2})?),?\s?\]?[\s-]*([^:]+):')

    current_msg = None

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            match = msg_start_pattern.match(line)
            if match:
                if current_msg:
                    messages.append(current_msg)

                timestamp_str = match.group(1)
                sender = match.group(2).strip()
                content = line[match.end():].strip()

                current_msg = {
                    "timestamp": timestamp_str,
                    "sender": sender,
                    "message": content
                }
            else:
                if current_msg:
                    current_msg["message"] += "\n" + line

        if current_msg:
            messages.append(current_msg)

    return messages

def normalize_date(date_str):
    """Attempts to parse common WhatsApp date formats into a datetime object."""
    formats = [
        '%d.%m.%y %H:%M:%S',
        '%d.%m.%Y %H:%M:%S',
        '%d/%m/%y, %H:%M:%S',
        '%d/%m/%Y, %H:%M:%S',
        '%d/%m/%y, %H:%M',
        '%d/%m/%Y, %H:%M',
    ]
    clean_date = date_str.strip('[]')
    for fmt in formats:
        try:
            return datetime.strptime(clean_date, fmt)
        except ValueError:
            continue
    return None

def filter_messages(messages, start_date=None, end_date=None, contact=None):
    """Filters messages based on date range and contact name."""
    filtered = []
    for msg in messages:
        if contact and contact.lower() not in msg['sender'].lower():
            continue
        if start_date or end_date:
            msg_date = normalize_date(msg['timestamp'])
            if msg_date:
                if start_date and msg_date < start_date:
                    continue
                if end_date and msg_date > end_date:
                    continue
        filtered.append(msg)
    return filtered

def transcribe_audio(audio_path, model, cache):
    """Transcribes an opus file using OpenAI Whisper."""
    if not WHISPER_AVAILABLE:
        return "[Whisper non installé]"

    filename = Path(audio_path).name
    if filename in cache:
        return cache[filename]

    try:
        result = model.transcribe(str(audio_path), language='fr')
        text = result['text'].strip()
        cache[filename] = text
        return text
    except Exception as e:
        return f"[Erreur de transcription: {e}]"

def save_as_json(messages, output_path):
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(messages, f, indent=2, ensure_ascii=False)

def save_as_markdown(messages, output_path):
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("# WhatsApp Chat Export\n\n")
        for msg in messages:
            f.write(f"### {msg['timestamp']} - {msg['sender']} ###\n")
            f.write(f"\n\n{msg['message']}\n")
            f.write("\n\n---\n")

def get_last_processed_timestamp(directory):
    """Finds the most recent _chat_*.md file and extracts the last message timestamp."""
    dir_path = Path(directory)
    md_files = sorted(dir_path.glob("_chat_*.md"), reverse=True)
    if not md_files:
        return None

    last_file = md_files[0]
    try:
        with open(last_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            # Find the last line that looks like a message header: **DATE - Name**
            for line in reversed(lines):
                match = re.search(r'^\*\*(.*?) - ', line)
                if match:
                    return match.group(1)
    except Exception as e:
        print(f"Error reading last report: {e}")

    return None

def main():
    parser = argparse.ArgumentParser(description="Parse and filter WhatsApp export chats with audio transcription.")
    parser.add_argument("--input", required=True, help="Path to the WhatsApp export directory")
    parser.add_argument("--start-date", help="Start date filter (DD.MM.YYYY)")
    parser.add_argument("--end-date", help="End date filter (DD.MM.YYYY)")
    parser.add_argument("--contact", help="Filter by contact name")
    parser.add_argument("--model", default="base", choices=["tiny", "base", "small", "medium", "large"], help="Whisper model size (default: base)")
    parser.add_argument("--force", action="store_true", help="Force full processing, ignoring incremental state")

    args = parser.parse_args()
    input_dir = Path(args.input)
    chat_file = input_dir / "_chat.txt"

    if not chat_file.exists():
        print(f"Error: _chat.txt not found in {args.input}")
        return

    start_dt = datetime.strptime(args.start_date, '%d.%m.%Y') if args.start_date else None
    end_dt = datetime.strptime(args.end_date, '%d.%m.%Y').replace(hour=23, minute=59, second=59) if args.end_date else None

    print(f"Parsing {chat_file}...")
    all_messages = parse_whatsapp_chat(str(chat_file))

    # Incremental Processing
    last_ts_str = None
    if not args.force:
        last_ts_str = get_last_processed_timestamp(args.input)
        if last_ts_str:
            print(f"Incremental mode: processing messages after {last_ts_str}")

    # Filtering
    filtered = filter_messages(all_messages, start_dt, end_dt, args.contact)

    # Identify which messages actually need transcription (those after last_ts)
    messages_to_transcribe = []
    final_messages = []

    last_dt = normalize_date(last_ts_str) if last_ts_str else None

    for msg in filtered:
        msg_dt = normalize_date(msg['timestamp'])
        # Transcription is needed if force is on, no previous report, or message is newer than last report
        needs_transcription = args.force or not last_dt or (msg_dt and msg_dt > last_dt)

        if needs_transcription:
            messages_to_transcribe.append(msg)

        final_messages.append(msg)

    # Transcription process
    if WHISPER_AVAILABLE and messages_to_transcribe:
        print(f"Loading Whisper model '{args.model}'... (this may take a moment)")
        model = whisper.load_model(args.model)
        cache = {}

        # Using tqdm for progress bar
        for msg in tqdm(messages_to_transcribe, desc="Transcribing audio", unit="msg"):
            audio_match = re.search(r'< pièce jointe : ([^>]+?\.opus) >', msg['message'])
            if audio_match:
                audio_filename = audio_match.group(1).strip()
                audio_path = input_dir / audio_filename

                if audio_path.exists():
                    transcription = transcribe_audio(audio_path, model, cache)
                    msg['message'] = f"{msg['message']}\n\n**Transcription:**\n{transcription}"
                else:
                    msg['message'] = f"{msg['message']}\n\n[Fichier audio non trouvé: {audio_filename}]"
    elif not WHISPER_AVAILABLE and messages_to_transcribe:
        print("Warning: openai-whisper not available. Skipping audio transcription.")

    # Generate Output Files
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_json = input_dir / f"_chat_{timestamp_str}.json"
    output_md = input_dir / f"_chat_{timestamp_str}.md"

    save_as_json(final_messages, str(output_json))

    # Custom Markdown saving to include links to files in the same folder
    with open(output_md, 'w', encoding='utf-8') as f:
        f.write(f"# WhatsApp Chat Export - {timestamp_str}\n\n")
        for msg in final_messages:
            f.write(f"### {msg['timestamp']} - {msg['sender']} ###\n")

            # Replace attachment mentions with actual links
            content = msg['message']
            audio_matches = re.findall(r'< pièce jointe : ([^>]+?\.opus) >', content)
            for audio_file in audio_matches:
                url = quote(audio_file)
                content = content.replace(f"< pièce jointe : {audio_file} >", f"\n[{audio_file}]({url})")

            image_matches = re.findall(r'< pièce jointe : ([^>]+?\.jpg) >', content)
            for image_file in image_matches:
                url = quote(image_file)
                content = content.replace(f"< pièce jointe : {image_file} >",
                                          f"\n**{image_file}:**\n![{image_file}]({url})")

            pdf_matches = re.findall(r'< pièce jointe : ([^>]+?\.pdf) >', content)
            for pdf_file in pdf_matches:
                url = quote(pdf_file)
                # content = content.replace(f"< pièce jointe : {pdf_file} >", f"\n**{pdf_file}:**\n![{pdf_file}]({url})")
                # <embed src="00000034-Testament%20Mami.pdf" width="50%" height="400px">
                content = content.replace(f"< pièce jointe : {pdf_file} >",
                                          f'\n<embed src={url} width="50%" height="400px">')

            f.write(f"\n{content}\n")
            f.write("\n---\n")

    print(f"\nDone. Processed {len(all_messages)} messages, {len(final_messages)} kept.")
    print(f"Reports saved to:\n- {output_json}\n- {output_md}")

if __name__ == "__main__":
    main()

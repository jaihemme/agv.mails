# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

### Development & Execution
- **Process emails:** `python3 update_conversations.py --input <dir_or_file> --json_file <json_file>`
- **Dry run:** `python3 update_conversations.py --input PPE --json_file ppe.json --dry-run`
- **Verbose logs:** `python3 update_conversations.py --input PPE --json_file ppe.json --log-level debug`

### Testing
- **Run all tests:** `pytest`
- **Run a specific test file:** `pytest test_update_conversations.py`

## Architecture & Structure

### Overview
The project is an email analyzer and aggregator that transforms `.eml` files into a structured JSON representation of conversations.

### Key Components
- `update_conversations.py`: The core engine.
    - **Parsing:** Extracts RFC 822 headers, cleans bodies (removes signatures and quotes), and identifies attachments/forwarded messages.
    - **Aggregation:** Groups messages into conversations using a two-step priority:
        1. `In-Reply-To` / `Message-ID` linkage.
        2. Normalized subject matching (strips `Re:`, `Fwd:`, `TR:`, etc.).
    - **Persistence:** Incremental updates to a JSON file (`meta` for globals, `conversations` for threaded messages).
- `PPE/`: Source directory for `.eml` files.
- `ppe.json`: The consolidated output file containing the conversation history.

### Data Flow
`.eml` files → `parse_email_file()` → `merge_message_into_conversations()` → `save_json()`
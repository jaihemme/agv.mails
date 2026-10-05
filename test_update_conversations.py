"""
Tests unitaires et d'intégration pour update_conversations.py.
Exécutable avec pytest.
"""

import email
import email.errors
import email.policy
import json
import logging
import os
import re
from unittest.mock import MagicMock, patch

import pytest

from update_conversations import (
    LogWriter,
    _clean_body,
    _extract_forwarded_from_text,
    _extract_forwarded_message,
    _get_attachments,
    _parse_address,
    _parse_recipients,
    load_json,
    main,
    merge_message_into_conversations,
    normalize_subject,
    parse_email_file,
    save_json,
    setup_logging,
)


# ============================================================================
# 1. Tests LogWriter et setup_logging
# ============================================================================

class TestLogging:
    def test_log_writer_buffering_and_flush(self):
        mock_logger = MagicMock()
        writer = LogWriter(mock_logger, level=logging.INFO)

        # Write without newline: should buffer, no log call yet
        writer.write("Première partie ")
        mock_logger.log.assert_not_called()

        # Write with newline: should flush buffered lines
        writer.write("suite.\nDeuxième ligne\n")
        assert mock_logger.log.call_count == 2
        mock_logger.log.assert_any_call(logging.INFO, "Première partie suite.")
        mock_logger.log.assert_any_call(logging.INFO, "Deuxième ligne")

        # Buffer remaining without trailing newline, then flush
        writer.write("Fin de message sans newline")
        writer.flush()
        mock_logger.log.assert_called_with(logging.INFO, "Fin de message sans newline")

    def test_setup_logging(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        setup_logging(log_file, "debug")
        logging.debug("Message de debug test")
        assert os.path.exists(log_file)
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "Message de debug test" in content


# ============================================================================
# 2. Tests de normalisation de sujet (normalize_subject)
# ============================================================================

class TestNormalizeSubject:
    @pytest.mark.parametrize(
        "raw_subject, expected",
        [
            ("Re: Test message", "Test message"),
            ("RE: Test message", "Test message"),
            ("re: Test message", "Test message"),
            ("Fwd: Notification importante", "Notification importante"),
            ("FWD: Notification importante", "Notification importante"),
            ("TR: Transfert dossier", "Transfert dossier"),
            ("FW: Transfert dossier", "Transfert dossier"),
            ("[V2.0] Sujet avec version", "Sujet avec version"),
            ("[PROJET-123] Sujet avec crochet", "Sujet avec crochet"),
            ("Re: Fwd: TR: Multiples préfixes", "Multiples préfixes"),
            ("   Sujet avec   espaces   multiples   ", "Sujet avec espaces multiples"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_normalize_subject(self, raw_subject, expected):
        assert normalize_subject(raw_subject) == expected


# ============================================================================
# 3. Tests de parsing d'adresses et de destinataires
# ============================================================================

class TestAddressParsing:
    @pytest.mark.parametrize(
        "address_str, expected_name, expected_email",
        [
            ("John Doe <john.doe@example.com>", "John Doe", "john.doe@example.com"),
            ("<alice@example.com>", "", "alice@example.com"),
            ("bob@example.com", "", "bob@example.com"),
            ("Charlie <charlie@example.com> (Personnel)", "Charlie", "charlie@example.com"),
            ("Paul Dupont paul.dupont@example.com", "Paul Dupont", "paul.dupont@example.com"),
            ("Texte sans aucun email", "Texte sans aucun email", ""),
            ("", "", ""),
            (None, "", ""),
        ],
    )
    def test_parse_address(self, address_str, expected_name, expected_email):
        name, addr = _parse_address(address_str or '')
        assert name == expected_name
        assert addr == expected_email

    def test_parse_recipients_multiple(self):
        header = '"Alice Wonder" <alice@example.com>, bob@example.com, "Charlie" <charlie@domain.org>'
        recipients = _parse_recipients(header)
        assert len(recipients) == 3
        assert recipients[0] == {"nom": "Alice Wonder", "email": "alice@example.com"}
        assert recipients[1] == {"nom": "", "email": "bob@example.com"}
        assert recipients[2] == {"nom": "Charlie", "email": "charlie@domain.org"}

    def test_parse_recipients_empty(self):
        assert _parse_recipients("") == []
        assert _parse_recipients(None) == []


# ============================================================================
# 4. Tests de nettoyage de corps d'e-mail (_clean_body)
# ============================================================================

class TestCleanBody:
    def test_remove_signature_standard(self):
        raw = "Bonjour,\nVoici le rapport.\n-- \nJean Dupont\nDirecteur"
        cleaned = _clean_body(raw)
        assert "Voici le rapport." in cleaned
        assert "Jean Dupont" not in cleaned

    def test_remove_signature_mobile(self):
        raw = "Message rapide.\nSent from my iPhone\nAutre info"
        cleaned = _clean_body(raw)
        assert cleaned == "Message rapide."

        raw_fr = "Message rapide.\nEnvoyé de mon iPad"
        assert _clean_body(raw_fr) == "Message rapide."

    def test_remove_quoted_lines(self):
        raw = "Ma réponse ici.\n> Message précédent cité\n>> Autre citation\nSuite de ma réponse."
        cleaned = _clean_body(raw)
        assert "Ma réponse ici." in cleaned
        assert "Suite de ma réponse." in cleaned
        assert "Message précédent cité" not in cleaned

    def test_remove_french_reply_header(self):
        raw = "Ok pour moi.\nLe 12 mai 2026 à 10:00, Paul a écrit :\nContenu ancien"
        cleaned = _clean_body(raw)
        assert "Ok pour moi." in cleaned
        assert "Le 12 mai 2026" not in cleaned

    def test_remove_english_reply_header(self):
        raw = "My reply.\nOn Monday 12 Oct 2026 John wrote:\nOld quote"
        cleaned = _clean_body(raw)
        assert "My reply." in cleaned
        assert "John wrote" not in cleaned

    def test_empty_body(self):
        assert _clean_body("") == ""
        assert _clean_body(None) == ""


# ============================================================================
# 5. Tests d'extraction de messages transférés et pièces jointes
# ============================================================================

class TestForwardedAndAttachments:
    def test_extract_forwarded_from_text(self):
        text = (
            "Voici le message transféré:\n"
            "-----Original Message-----\n"
            "From: alice@test.com\n"
            "Date: 2026-05-10 14:00\n"
            "Subject: Dossier important\n"
            "Bonjour tout le monde."
        )
        fwd = _extract_forwarded_from_text(text)
        assert fwd is not None
        assert fwd["auteur"] == "alice@test.com"
        assert fwd["date"] == "2026-05-10 14:00"
        assert fwd["sujet"] == "Dossier important"

    def test_extract_forwarded_from_french_text(self):
        text = (
            "-------- Message transféré --------\n"
            "De: contact@agence.ch\n"
            "Date: 2026-06-01\n"
            "Subject: Rapport PPE\n"
        )
        fwd = _extract_forwarded_from_text(text)
        assert fwd is not None
        assert fwd["auteur"] == "contact@agence.ch"

    def test_extract_forwarded_message_embedded_rfc822(self):
        raw_email = (
            b"From: proxy@test.com\r\n"
            b"To: me@test.com\r\n"
            b"Subject: FWD: Message transfere\r\n"
            b"MIME-Version: 1.0\r\n"
            b'Content-Type: multipart/mixed; boundary="BOUND"\r\n\r\n'
            b"--BOUND\r\n"
            b"Content-Type: message/rfc822\r\n\r\n"
            b"From: original@test.com\r\n"
            b"Date: 2026-04-01 08:00\r\n"
            b"Subject: Original Subject\r\n\r\n"
            b"Original body\r\n"
            b"--BOUND--\r\n"
        )
        msg = email.message_from_bytes(raw_email, policy=email.policy.default)
        fwd = _extract_forwarded_message(msg)
        assert fwd is not None
        assert fwd["auteur"] == "original@test.com"
        assert fwd["sujet"] == "Original Subject"

    def test_extract_forwarded_message_not_forwarded(self):
        raw_email = (
            b"From: me@test.com\r\n"
            b"Subject: Normal subject\r\n\r\n"
            b"Normal body"
        )
        msg = email.message_from_bytes(raw_email, policy=email.policy.default)
        assert _extract_forwarded_message(msg) is None

    def test_extract_attachments_from_mime(self, tmp_path):
        # Setup paths
        attachment_dir = str(tmp_path / "attachments")
        eml_dir = tmp_path / "emails"
        eml_dir.mkdir()

        raw_email = (
            b"From: sender@example.com\r\n"
            b"To: recipient@example.com\r\n"
            b"Subject: Test Attachment\r\n"
            b"MIME-Version: 1.0\r\n"
            b'Content-Type: multipart/mixed; boundary="BOUNDARY"\r\n\r\n'
            b"--BOUNDARY\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
            b"Voir la piece jointe.\r\n"
            b"--BOUNDARY\r\n"
            b'Content-Type: application/pdf; name="facture.pdf"\r\n'
            b'Content-Disposition: attachment; filename="facture.pdf"\r\n\r\n'
            b"%PDF-1.4 dummy content\r\n"
            b"--BOUNDARY--\r\n"
        )
        msg = email.message_from_bytes(raw_email, policy=email.policy.default)
        attachments = _get_attachments(msg, attachment_dir)
        assert len(attachments) == 1
        assert re.match(r"^\d{14}_facture\.pdf$", attachments[0]["nom"])
        assert attachments[0]["type"] == "application/pdf"
        assert attachments[0]["taille"] == 22

    def test_extract_attachments_fallback_name(self, tmp_path):
        # Setup paths
        attachment_dir = str(tmp_path / "attachments")
        eml_dir = tmp_path / "emails"
        eml_dir.mkdir()

        raw_email = (
            b"From: sender@example.com\r\n"
            b"Subject: Test\r\n"
            b"MIME-Version: 1.0\r\n"
            b'Content-Type: multipart/mixed; boundary="BOUNDARY"\r\n\r\n'
            b"--BOUNDARY\r\n"
            b'Content-Type: image/png; name="photo.png"\r\n'
            b'Content-Disposition: attachment\r\n\r\n'
            b"fakeimagebytes\r\n"
            b"--BOUNDARY--\r\n"
        )
        msg = email.message_from_bytes(raw_email, policy=email.policy.default)
        attachments = _get_attachments(msg, attachment_dir)
        assert len(attachments) == 1
        assert re.match(r"^\d{14}_photo\.png$", attachments[0]["nom"])


# ============================================================================
# 6. Tests de parse_email_file
# ============================================================================

class TestParseEmailFile:
    def test_parse_valid_synthetic_email(self, tmp_path):
        eml_file = tmp_path / "sample.eml"
        eml_content = (
            "Message-ID: <msg123@domain.com>\n"
            "Date: Wed, 20 Jul 2026 10:00:00 +0200\n"
            "From: Alice Dupont <alice@domain.com>\n"
            "To: Bob Martin <bob@domain.com>\n"
            "Cc: Charlie <charlie@domain.com>\n"
            "Subject: Re: Sujet Important\n"
            "In-Reply-To: <parent_msg@domain.com>\n"
            "Content-Type: text/plain; charset=utf-8\n"
            "\n"
            "Bonjour Bob,\n"
            "Ceci est le contenu.\n"
            "-- \n"
            "Signature Alice"
        )
        eml_file.write_text(eml_content, encoding="utf-8")

        result = parse_email_file(str(eml_file))
        assert result is not None
        assert result["message_id"] == "msg123@domain.com"
        assert result["in_reply_to"] == "parent_msg@domain.com"
        assert result["expediteur_nom"] == "Alice Dupont"
        assert result["expediteur_email"] == "alice@domain.com"
        assert result["sujet"] == "Sujet Important"
        assert "Ceci est le contenu." in result["contenu_nettoye"]
        assert "Signature Alice" not in result["contenu_nettoye"]
        assert len(result["destinataires"]["to"]) == 1
        assert len(result["destinataires"]["cc"]) == 1

    def test_parse_single_part_latin1_email(self, tmp_path):
        eml_file = tmp_path / "single_latin1.eml"
        raw_bytes = (
            b"Message-ID: <latin1@test.com>\r\n"
            b"Subject: Sujet simple\r\n"
            b"Content-Type: text/plain; charset=iso-8859-1\r\n\r\n"
            b"Caf\xe9 et th\xe9"
        )
        eml_file.write_bytes(raw_bytes)
        result = parse_email_file(str(eml_file))
        assert result is not None
        assert "Café et thé" in result["contenu_nettoye"]

    def test_parse_file_not_found(self):
        result = parse_email_file("/path/that/does/not/exist.eml")
        assert result is None

    def test_parse_file_exceptions(self, tmp_path):
        eml_file = tmp_path / "perm_error.eml"
        eml_file.write_text("Dummy", encoding="utf-8")

        with patch("builtins.open", side_effect=PermissionError("Denied")):
            assert parse_email_file(str(eml_file)) is None

        with patch("email.message_from_bytes", side_effect=email.errors.MessageError("Format")):
            assert parse_email_file(str(eml_file)) is None

        with patch("email.message_from_bytes", side_effect=UnicodeDecodeError("utf-8", b"", 0, 1, "err")):
            assert parse_email_file(str(eml_file)) is None

        with patch("email.message_from_bytes", side_effect=RuntimeError("Unexpected")):
            assert parse_email_file(str(eml_file)) is None

    def test_parse_real_ppe_files_if_present(self):
        ppe_dir = "/Users/yogi/Docker/agv.mails/PPE"
        if os.path.isdir(ppe_dir):
            files = [f for f in os.listdir(ppe_dir) if f.endswith(".eml")]
            for f in files:
                filepath = os.path.join(ppe_dir, f)
                parsed = parse_email_file(filepath)
                assert parsed is not None
                assert "message_id" in parsed
                assert "timestamp" in parsed


# ============================================================================
# 7. Tests load_json et save_json
# ============================================================================

class TestJsonIO:
    def test_load_json_non_existent(self, tmp_path):
        non_existent = str(tmp_path / "missing.json")
        data = load_json(non_existent)
        assert data["meta"]["nombre_conversations"] == 0
        assert data["meta"]["nombre_messages"] == 0
        assert data["conversations"] == []

    def test_load_json_malformed(self, tmp_path):
        corrupt = tmp_path / "corrupt.json"
        corrupt.write_text("{ invalid json ...", encoding="utf-8")
        data = load_json(str(corrupt))
        assert data["conversations"] == []

    def test_load_json_missing_keys(self, tmp_path):
        partial = tmp_path / "partial.json"
        partial.write_text('{"other": 123}', encoding="utf-8")
        data = load_json(str(partial))
        assert "conversations" in data
        assert "meta" in data

    def test_save_and_reload_json(self, tmp_path):
        target = str(tmp_path / "saved.json")
        sample_data = {
            "meta": {"date_derniere_mise_a_jour": "2026-10-02T12:00:00", "nombre_conversations": 1, "nombre_messages": 1},
            "conversations": [{"sujet": "Test", "nombre_messages": 1, "messages": []}],
        }
        success = save_json(target, sample_data)
        assert success is True

        reloaded = load_json(target)
        assert reloaded["meta"]["nombre_conversations"] == 1
        assert reloaded["conversations"][0]["sujet"] == "Test"

    def test_save_json_failure(self):
        with patch("builtins.open", side_effect=OSError("Write failed")):
            assert save_json("/invalid/path.json", {}) is False


# ============================================================================
# 8. Tests de fusion dans les conversations (merge_message_into_conversations)
# ============================================================================

class TestMergeConversations:
    def test_reject_invalid_message(self):
        data = load_json("/non/existent/path")
        success, msg = merge_message_into_conversations(data, {})
        assert success is False
        assert "no valid message_id" in msg

        success, msg = merge_message_into_conversations(data, {"message_id": ""})
        assert success is False

    def test_create_new_conversation(self):
        data = load_json("/non/existent/path")
        msg = {
            "message_id": "msg-001",
            "in_reply_to": "",
            "sujet": "Projet A",
            "timestamp": "2026-06-01T10:00:00",
            "expediteur_nom": "Alice",
            "expediteur_email": "alice@a.ch",
        }
        success, status_msg = merge_message_into_conversations(data, msg)
        assert success is True
        assert data["meta"]["nombre_conversations"] == 1
        assert data["meta"]["nombre_messages"] == 1
        assert data["conversations"][0]["sujet"] == "Projet A"
        assert data["conversations"][0]["date_debut"] == "2026-06-01T10:00:00"

    def test_skip_duplicate_message(self):
        data = load_json("/non/existent/path")
        msg = {
            "message_id": "msg-001",
            "sujet": "Projet A",
            "timestamp": "2026-06-01T10:00:00",
        }
        merge_message_into_conversations(data, msg)

        # Essayer d'ajouter le même message_id
        success, status_msg = merge_message_into_conversations(data, msg)
        assert success is False
        assert "already exists" in status_msg
        assert data["meta"]["nombre_messages"] == 1

    def test_merge_by_in_reply_to(self):
        data = load_json("/non/existent/path")
        msg_parent = {
            "message_id": "parent-100",
            "in_reply_to": "",
            "sujet": "Discussion Budget",
            "timestamp": "2026-06-01T09:00:00",
        }
        merge_message_into_conversations(data, msg_parent)

        # Message enfant avec sujet modifié mais In-Reply-To correspondant
        msg_child = {
            "message_id": "child-101",
            "in_reply_to": "parent-100",
            "sujet": "Budget Révisé",
            "timestamp": "2026-06-01T11:00:00",
        }
        success, status_msg = merge_message_into_conversations(data, msg_child)
        assert success is True
        assert data["meta"]["nombre_conversations"] == 1
        assert data["meta"]["nombre_messages"] == 2
        conv = data["conversations"][0]
        assert conv["nombre_messages"] == 2
        assert conv["date_debut"] == "2026-06-01T09:00:00"
        assert conv["date_fin"] == "2026-06-01T11:00:00"
        assert conv["messages"][0]["message_id"] == "parent-100"
        assert conv["messages"][1]["message_id"] == "child-101"

    def test_merge_by_normalized_subject(self):
        data = load_json("/non/existent/path")
        msg1 = {
            "message_id": "m1",
            "in_reply_to": "",
            "sujet": "Installation panneau",
            "timestamp": "2026-07-01T08:00:00",
        }
        merge_message_into_conversations(data, msg1)

        # Second message sans in_reply_to mais même sujet normalisé avec Re:
        msg2 = {
            "message_id": "m2",
            "in_reply_to": "",
            "sujet": "Re: Installation panneau",
            "timestamp": "2026-07-01T10:00:00",
        }
        success, _ = merge_message_into_conversations(data, msg2)
        assert success is True
        assert data["meta"]["nombre_conversations"] == 1
        assert data["meta"]["nombre_messages"] == 2

    def test_messages_chronological_sort(self):
        data = load_json("/non/existent/path")
        # Ingestion dans le désordre chronologique
        msg_later = {
            "message_id": "msg-late",
            "sujet": "Chantier",
            "timestamp": "2026-08-02T15:00:00",
        }
        msg_earlier = {
            "message_id": "msg-early",
            "sujet": "Chantier",
            "timestamp": "2026-08-01T09:00:00",
        }
        merge_message_into_conversations(data, msg_later)
        merge_message_into_conversations(data, msg_earlier)

        conv = data["conversations"][0]
        assert conv["messages"][0]["message_id"] == "msg-early"
        assert conv["messages"][1]["message_id"] == "msg-late"
        assert conv["date_debut"] == "2026-08-01T09:00:00"
        assert conv["date_fin"] == "2026-08-02T15:00:00"


# ============================================================================
# 9. Tests d'intégration CLI (main)
# ============================================================================

class TestMainCLI:
    def test_main_with_directory_and_dry_run(self, tmp_path, capsys):
        # Créer un faux email
        eml_path = tmp_path / "email1.eml"
        eml_path.write_text(
            "Message-ID: <cli-test-1@test.com>\n"
            "Date: Mon, 01 Sep 2026 10:00:00 +0200\n"
            "Subject: Sujet Test CLI\n"
            "From: sender@test.com\n"
            "To: recipient@test.com\n\n"
            "Message body",
            encoding="utf-8",
        )
        json_output = tmp_path / "result.json"
        log_file = tmp_path / "cli.log"

        test_args = [
            "update_conversations.py",
            "--input", str(tmp_path),
            "--json_file", str(json_output),
            "--dry-run",
            "--log-file", str(log_file),
            "--log-level", "debug",
        ]

        with patch("sys.argv", test_args):
            main()

        captured = capsys.readouterr().out
        assert "SUMMARY" in captured
        assert "Files processed: 1" in captured
        assert "[DRY RUN] No changes were saved" in captured
        assert not json_output.exists()

    def test_main_execution_and_save(self, tmp_path, capsys):
        eml_path = tmp_path / "email2.eml"
        eml_path.write_text(
            "Message-ID: <cli-test-2@test.com>\n"
            "Date: Mon, 01 Sep 2026 12:00:00 +0200\n"
            "Subject: Sujet Test Réel\n"
            "From: sender@test.com\n"
            "To: recipient@test.com\n\n"
            "Message body 2",
            encoding="utf-8",
        )
        json_output = tmp_path / "result_saved.json"
        log_file = tmp_path / "cli.log"

        test_args = [
            "update_conversations.py",
            "--input", str(eml_path),
            "--json_file", str(json_output),
            "--log-file", str(log_file),
        ]

        with patch("sys.argv", test_args):
            main()

        assert json_output.exists()
        saved = json.loads(json_output.read_text(encoding="utf-8"))
        assert saved["meta"]["nombre_conversations"] == 1
        assert saved["meta"]["nombre_messages"] == 1
        assert saved["conversations"][0]["messages"][0]["message_id"] == "cli-test-2@test.com"

    def test_main_with_invalid_input(self, tmp_path, capsys):
        # Non-existent input path
        test_args = [
            "update_conversations.py",
            "--input", str(tmp_path / "does_not_exist"),
            "--json_file", str(tmp_path / "out.json"),
        ]
        with patch("sys.argv", test_args):
            main()
        captured = capsys.readouterr().out
        assert "Error: Input path does not exist" in captured

        # Non-eml input file
        txt_path = tmp_path / "test.txt"
        txt_path.write_text("not an eml", encoding="utf-8")
        test_args = [
            "update_conversations.py",
            "--input", str(txt_path),
            "--json_file", str(tmp_path / "out.json"),
        ]
        with patch("sys.argv", test_args):
            main()
        captured = capsys.readouterr().out
        assert "Files processed: 0" in captured

    def test_main_save_error(self, tmp_path, capsys):
        eml_path = tmp_path / "test.eml"
        eml_path.write_text("Message-ID: <id@test.com>\nSubject: T\n\nBody", encoding="utf-8")
        test_args = [
            "update_conversations.py",
            "--input", str(eml_path),
            "--json_file", str(tmp_path / "out.json"),
        ]
        with patch("sys.argv", test_args), patch("update_conversations.save_json", return_value=False):
            main()
        captured = capsys.readouterr().out
        assert "ERROR: Failed to save JSON" in captured

# ============================================================================
# 10. Tests de sauvegarde des pièces jointes (Attachment Saving)
# ============================================================================

class TestAttachmentSaving:
    def test_save_attachments_success(self, tmp_path):
        # Setup paths
        attachment_dir = str(tmp_path / "attachments")
        eml_dir = tmp_path / "emails"
        eml_dir.mkdir()

        # Create a mock email with an attachment and a creation-date
        # Content-Disposition: attachment; filename="test.pdf"; creation-date="Tue, 19 Aug 2025 06:39:49 GMT"
        raw_email = (
            b"From: sender@example.com\r\n"
            b"Subject: Test Save\r\n"
            b"MIME-Version: 1.0\r\n"
            b'Content-Type: multipart/mixed; boundary="BOUNDARY"\r\n\r\n'
            b"--BOUNDARY\r\n"
            b"Content-Type: text/plain\r\n\r\n"
            b"Body\r\n"
            b"--BOUNDARY\r\n"
            b'Content-Type: application/pdf\r\n'
            b'Content-Disposition: attachment; filename="test.pdf"; creation-date="Tue, 19 Aug 2025 06:39:49 GMT"\r\n\r\n'
            b"PDF CONTENT"
            b"\r\n--BOUNDARY--\r\n"
        )
        eml_file = eml_dir / "test.eml"
        eml_file.write_bytes(raw_email)

        # Execute
        result = parse_email_file(str(eml_file), attachment_dir=attachment_dir)

        # Verify
        assert result is not None
        # Date Tue, 19 Aug 2025 06:39:49 GMT -> 20250819063949
        expected_filename = "20250819063949_test.pdf"
        saved_file = tmp_path / "attachments" / expected_filename
        assert saved_file.exists()
        assert saved_file.read_bytes() == b"PDF CONTENT"

    def test_save_attachments_fallback_date(self, tmp_path):
        # Setup paths
        attachment_dir = str(tmp_path / "attachments")
        eml_dir = tmp_path / "emails"
        eml_dir.mkdir()

        # Mock email without creation-date
        raw_email = (
            b"From: sender@example.com\r\n"
            b"Subject: Test Fallback\r\n"
            b"MIME-Version: 1.0\r\n"
            b"MIME-Version: 1.0\r\n"
            b'Content-Type: multipart/mixed; boundary="BOUNDARY"\r\n\r\n'
            b"--BOUNDARY\r\n"
            b"Content-Type: text/plain\r\n\r\n"
            b"Body\r\n"
            b"--BOUNDARY\r\n"
            b'Content-Type: application/pdf\r\n'
            b'Content-Disposition: attachment; filename="fallback.pdf"\r\n\r\n'
            b"PDF CONTENT"
            b"\r\n--BOUNDARY--\r\n"
        )
        eml_file = eml_dir / "test.eml"
        eml_file.write_bytes(raw_email)

        # Execute
        result = parse_email_file(str(eml_file), attachment_dir=attachment_dir)

        # Verify
        assert result is not None
        # File should be saved with current date. We check if any file exists in the dir.
        saved_files = list((tmp_path / "attachments").iterdir())
        assert len(saved_files) == 1
        filename = saved_files[0].name
        assert filename.endswith("_fallback.pdf")
        # Check that date part is 14 digits (YYYYMMDDHHMMSS)
        date_part = filename.split('_')[0]
        assert len(date_part) == 14
        assert saved_files[0].read_bytes() == b"PDF CONTENT"

    def test_no_save_when_dir_none(self, tmp_path):
        # Setup paths
        eml_dir = tmp_path / "emails"
        eml_dir.mkdir()

        raw_email = (
            b"From: sender@example.com\r\n"
            b"Subject: Test No Save\r\n"
            b"MIME-Version: 1.0\r\n"
            b'Content-Type: multipart/mixed; boundary="BOUNDARY"\r\n\r\n'
            b"--BOUNDARY\r\n"
            b"Content-Type: text/plain\r\n\r\n"
            b"Body\r\n"
            b"--BOUNDARY\r\n"
            b'Content-Type: application/pdf\r\n'
            b'Content-Disposition: attachment; filename="nosave.pdf"\r\n\r\n'
            b"PDF CONTENT"
            b"--BOUNDARY--\r\n"
        )
        eml_file = eml_dir / "test.eml"
        eml_file.write_bytes(raw_email)

        # Execute with attachment_dir=None
        result = parse_email_file(str(eml_file), attachment_dir=None)

        # Verify
        assert result is not None
        # No attachments folder should have been created
        assert not (tmp_path / "attachments").exists()

    def test_main_execution_and_save(self, tmp_path, capsys):
        eml_path = tmp_path / "email2.eml"
        eml_path.write_text(
            "Message-ID: <cli-test-2@test.com>\n"
            "Date: Mon, 01 Sep 2026 12:00:00 +0200\n"
            "Subject: Sujet Test Réel\n"
            "From: sender@test.com\n"
            "To: recipient@test.com\n\n"
            "Message body 2",
            encoding="utf-8",
        )
        json_output = tmp_path / "result_saved.json"
        log_file = tmp_path / "cli.log"

        test_args = [
            "update_conversations.py",
            "--input", str(eml_path),
            "--json_file", str(json_output),
            "--log-file", str(log_file),
        ]

        with patch("sys.argv", test_args):
            main()

        assert json_output.exists()
        saved = json.loads(json_output.read_text(encoding="utf-8"))
        assert saved["meta"]["nombre_conversations"] == 1
        assert saved["meta"]["nombre_messages"] == 1
        assert saved["conversations"][0]["messages"][0]["message_id"] == "cli-test-2@test.com"

    def test_main_with_invalid_input(self, tmp_path, capsys):
        # Non-existent input path
        test_args = [
            "update_conversations.py",
            "--input", str(tmp_path / "does_not_exist"),
            "--json_file", str(tmp_path / "out.json"),
        ]
        with patch("sys.argv", test_args):
            main()
        captured = capsys.readouterr().out
        assert "Error: Input path does not exist" in captured

        # Non-eml input file
        txt_path = tmp_path / "test.txt"
        txt_path.write_text("not an eml", encoding="utf-8")
        test_args = [
            "update_conversations.py",
            "--input", str(txt_path),
            "--json_file", str(tmp_path / "out.json"),
        ]
        with patch("sys.argv", test_args):
            main()
        captured = capsys.readouterr().out
        assert "Files processed: 0" in captured

    def test_main_save_error(self, tmp_path, capsys):
        eml_path = tmp_path / "test.eml"
        eml_path.write_text("Message-ID: <id@test.com>\nSubject: T\n\nBody", encoding="utf-8")
        test_args = [
            "update_conversations.py",
            "--input", str(eml_path),
            "--json_file", str(tmp_path / "out.json"),
        ]
        with patch("sys.argv", test_args), patch("update_conversations.save_json", return_value=False):
            main()
        captured = capsys.readouterr().out
        assert "ERROR: Failed to save JSON" in captured

import base64
import contextlib
import io
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from xml.etree.ElementTree import fromstring

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "hal"))
sys.path.insert(0, str(ROOT.parent / "message_md"))

import config
import attachment
import markdown
import message
import person


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.folder = Path(self.temp_dir.name)
        self.cfg = config._Config()
        self.cfg.config_folder = str(self.folder)
        self.cfg.output_folder = str(self.folder / "output")
        self.cfg.me.slug = "me"
        self.cfg.service = markdown.YAML_SERVICE_SMS
        markdown.errored_people.clear()

    def load_people(self, people):
        (self.folder / "people.json").write_text(
            json.dumps(people), encoding="utf-8"
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.cfg.load_people(), len(people))

    def test_legacy_name_accessors_share_identity_fields(self):
        contact = person.Person()
        self.assertEqual(contact.first_name, "")
        contact.first_name = "Pat"
        contact.last_name = "Example"
        self.assertEqual(contact.identity.first_name, "Pat")
        self.assertEqual(contact.identity.last_name, "Example")
        contact.identity.first_name = "Updated"
        self.assertEqual(contact.first_name, "Updated")

    def test_names_survive_config_round_trip(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                self.cfg.people = []
                first_key = "first-name" if legacy else "first_name"
                last_key = "last-name" if legacy else "last_name"
                self.load_people([{
                    "slug": "me", first_key: "Me", last_key: "Example",
                    "mobile": "+1 202 555 0101",
                }])
                self.assertEqual(self.cfg.me.contact.mobile, "2025550101")
                self.assertEqual(self.cfg.people[0].identity.full_name, "Me Example")
                self.assertTrue(self.cfg.save_people())
                saved = json.loads((self.folder / "people.json").read_text())
                self.assertEqual(saved[0]["first_name"], "Me")
                self.assertEqual(saved[0]["last_name"], "Example")
                self.cfg.people = []
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(self.cfg.load_people(), 1)
                self.assertEqual(self.cfg.people[0].first_name, "Me")

    def test_full_name_fallback_creates_dated_file(self):
        with self.assertLogs(level="WARNING") as logs:
            self.load_people([{
                "slug": "pat", "first_name": "", "last_name": "",
                "profile_full_name": "Pat Example",
            }])
        self.assertIn("no configured first_name", logs.output[0])
        msg = message.Message()
        msg.from_slug = "pat"
        msg.to_slugs = ["me"]
        msg.body = "Hello"
        msg.timestamp = 1704110400
        self.assertTrue(msg.set_date_time())
        message.add_messages([msg], self.cfg)
        output = Path(self.cfg.output_folder) / "People" / "pat"
        markdown.create_markdown_files(self.cfg.people[0], str(output), self.cfg)
        text = (output / f"{msg.date_str}.md").read_text(encoding="utf-8")
        self.assertIn("Pat ", text)
        self.assertIn("> Hello", text)
        self.assertIn("service: sms", text)
        self.assertTrue(self.cfg.save_people())
        saved = json.loads((self.folder / "people.json").read_text())
        self.assertEqual(saved[0]["first_name"], "Pat")

    def test_missing_name_logs_error_without_debug(self):
        self.load_people([{"slug": "pat", "first_name": None}])
        msg = message.Message()
        msg.from_slug = "pat"
        msg.body = "Hello"
        self.cfg.time_name_separate = True
        with self.assertLogs(level="ERROR") as logs:
            self.assertEqual(
                markdown.format_markdown(msg, self.cfg, self.cfg.people[0]), ""
            )
        self.assertIn("Set first_name or profile_full_name", logs.output[0])

    def test_sms_and_media_only_mms_write_dated_files(self):
        self.load_people([
            {"slug": "me", "first_name": "Me", "last_name": "",
             "mobile": "2025550101"},
            {"slug": "pat", "first_name": "", "last_name": "",
             "profile_full_name": "Pat Example", "mobile": "2025550102"},
        ])
        (self.folder / "groups.json").write_text(
            json.dumps({"groups": [{
                "id": "synthetic-group", "slug": "friends",
                "description": "Synthetic group", "people": ["me", "pat"],
            }]}), encoding="utf-8"
        )
        settings = json.loads(
            (ROOT.parent / "message_md" / "config" / "settings.json").read_text()
        )
        settings["messages-file"] = "messages.xml"
        (self.folder / "settings.json").write_text(
            json.dumps(settings), encoding="utf-8"
        )
        source = self.folder / "source"
        source.mkdir()
        image = b"synthetic image bytes"
        encoded = base64.b64encode(image).decode("ascii")
        xml = f"""<smses>
<sms address="2025550102" date="1704110400000" type="1" body="Incoming SMS"/>
<sms address="2025550102" date="1704110460000" type="2" body="Outgoing SMS"/>
<mms address="2025550102" date="1704196800000" m_id="photo">
  <addrs>
    <addr address="2025550102" type="137"/>
    <addr address="2025550101" type="151"/>
  </addrs>
  <parts><part ct="image/jpeg" cl="photo.jpg" data="{encoded}"/></parts>
</mms>
</smses>"""
        (source / "messages.xml").write_text(xml, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(ROOT / "sms_backup_md.py"),
             "-c", str(self.folder), "-s", str(source), "-f", "messages.xml",
             "-o", self.cfg.output_folder, "-m", "me", "-b", "1970-01-01", "-d"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = Path(self.cfg.output_folder) / "People" / "pat"
        notes = sorted(output.glob("*.md"))
        self.assertEqual(len(notes), 2, result.stdout + result.stderr)
        text = "\n".join(note.read_text(encoding="utf-8") for note in notes)
        self.assertIn("> Incoming SMS", text)
        self.assertIn("> Outgoing SMS", text)
        self.assertIn("![[photo.jpg|450]]", text)
        self.assertEqual((output / "media" / "photo.jpg").read_bytes(), image)
        self.assertFalse((source / "attachments").exists())
        self.assertTrue((source / "messages.xml").exists())

    def test_duplicate_mms_preserves_group_and_media_in_either_order(self):
        self.load_people([
            {"slug": "me", "first_name": "Me", "mobile": "2025550101"},
            {"slug": "pat", "first_name": "Pat", "mobile": "2025550102"},
            {"slug": "sam", "first_name": "Sam", "mobile": "2025550103"},
        ])
        (self.folder / "groups.json").write_text(
            json.dumps({"groups": [{
                "id": "synthetic-group", "slug": "friends",
                "description": "Synthetic group", "people": ["me", "pat", "sam"],
            }]}), encoding="utf-8"
        )
        settings = json.loads(
            (ROOT.parent / "message_md" / "config" / "settings.json").read_text()
        )
        settings["messages-file"] = "messages.xml"
        (self.folder / "settings.json").write_text(
            json.dumps(settings), encoding="utf-8"
        )
        source = self.folder / "source"
        source.mkdir()
        video = b"synthetic video bytes"
        encoded = base64.b64encode(video).decode("ascii")
        group_copy = f"""<mms address="group@rcs.google.com"
    date="1791736856000" m_id="shared-video">
  <addrs>
    <addr address="+12025550102" type="137"/>
    <addr address="+12025550103" type="151"/>
  </addrs>
  <parts>
    <part ct="text/plain" text="Group video"/>
    <part ct="video/mp4" cl="null" name="video.mp4" data="{encoded}"/>
  </parts>
</mms>"""
        direct_copy = f"""<mms address="+12025550102"
    date="1791736856929" m_id="shared-video">
  <addrs><addr address="+12025550102" type="137"/></addrs>
  <parts><part ct="video/mp4" cl="video.mp4" data="{encoded}"/></parts>
</mms>"""
        media_only_group = group_copy.replace(
            '    <part ct="text/plain" text="Group video"/>\n', ""
        )
        for order, records in enumerate((
            [group_copy, direct_copy], [direct_copy, group_copy], [group_copy],
            [media_only_group, direct_copy], [direct_copy, media_only_group],
            [media_only_group],
        )):
            with self.subTest(order=order):
                (source / "messages.xml").write_text(
                    "<smses>" + "".join(records) + "</smses>", encoding="utf-8"
                )
                output = self.folder / f"output-{order}"
                result = subprocess.run(
                    [sys.executable, str(ROOT / "sms_backup_md.py"),
                     "-c", str(self.folder), "-s", str(source),
                     "-f", "messages.xml", "-o", str(output),
                     "-m", "me", "-b", "1970-01-01", "-d"],
                    cwd=ROOT, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                note = output / "People" / "groups" / "friends" / "2026-10-11.md"
                self.assertTrue(note.exists(), result.stdout + result.stderr)
                text = note.read_text(encoding="utf-8")
                self.assertEqual(text.count("[[video.mp4]]"), 1, text)
                self.assertIn("![[video.mp4]]", text)
                if group_copy in records:
                    self.assertIn("> Group video", text)
                self.assertIn("Pat ", text)
                self.assertFalse(list((output / "People" / "pat").glob("*.md")))
                media = list(output.rglob("video.mp4"))
                self.assertTrue(media)
                for path in media:
                    self.assertEqual(path.read_bytes(), video)

    def test_media_and_following_comment_have_plain_blank_separator(self):
        self.load_people([
            {"slug": "me", "first_name": "Me", "mobile": "2025550101"},
            {"slug": "pat", "first_name": "Pat", "mobile": "2025550102"},
        ])
        self.cfg.file_per_day = True
        self.cfg.folder_per_person = True
        self.cfg.file_per_person = True
        self.cfg.people_subfolder = "People"
        self.cfg.image_embed = True
        self.cfg.image_width = 450
        for combined in (False, True):
            with self.subTest(combined=combined):
                video = attachment.Attachment()
                video.id = "video.mp4"
                video.type = "video/mp4"
                media = message.Message()
                media.from_slug = "pat"
                media.to_slugs = ["me"]
                media.timestamp = 1791736856
                media.set_date_time()
                media.add_attachment(video)
                comment = message.Message()
                comment.from_slug = "pat"
                comment.to_slugs = ["me"]
                comment.timestamp = media.timestamp + 60
                comment.set_date_time()
                comment.body = "Bring pajamas tomorrow."
                followup = message.Message()
                followup.from_slug = "pat"
                followup.to_slugs = ["me"]
                followup.timestamp = comment.timestamp + 60
                followup.set_date_time()
                followup.body = "Thanks!"
                if combined:
                    media.body = comment.body
                    messages = [media, followup]
                else:
                    messages = [media, comment, followup]
                self.cfg.people[1].messages = []
                message.add_messages(messages, self.cfg)
                output = self.folder / f"render-{combined}"
                output.mkdir()
                markdown.create_markdown_files(self.cfg.people[1], str(output), self.cfg)
                text = (output / f"{media.date_str}.md").read_text(encoding="utf-8")
                self.assertIn(
                    "![[video.mp4]]\n\n> Bring pajamas tomorrow.\n> \n> Thanks!",
                    text,
                )

    def test_own_numbers_write_sms_and_mms_to_personal_notes(self):
        self.load_people([
            {"slug": "me", "first_name": "Me", "mobile": "2025550101"},
        ])
        self.cfg.daily_notes_subfolder = "Personal Notes"
        self.cfg.mime_types = {"text/plain": "txt", "image/jpeg": "jpg"}
        with patch("message_md.setup", return_value=False):
            with contextlib.redirect_stdout(io.StringIO()):
                parser = runpy.run_path(str(ROOT / "sms_backup_md.py"))

        primary = self.cfg.me.contact.mobile
        work = "2025550199"
        lookup = self.cfg.get_person_by_number
        def resolve_number(number):
            return self.cfg.me if number == work else lookup(number)

        image = b"personal note image"
        encoded = base64.b64encode(image).decode("ascii")
        messages = []
        with patch.object(self.cfg, "get_person_by_number", side_effect=resolve_number):
            with patch.object(self.cfg, "get_group_slug_by_phone_numbers") as group_lookup:
                for sender, recipient in (
                    (work, primary), (primary, work),
                    ("+12025550101", primary), (work, None), (None, work),
                    ("insert-address-token", work),
                ):
                    with self.subTest(sender=sender, recipient=recipient):
                        addrs = ""
                        if sender:
                            addrs += f'<addr address="{sender}" type="137"/>'
                        if recipient:
                            addrs += f'<addr address="{recipient}" type="151"/>'
                        if sender and recipient:
                            addrs += '<addr address="+12025550101" type="151"/>'
                        mms = fromstring(f"""<mms date="1704110400000">
  <addrs>{addrs}</addrs>
  <parts>
    <part ct="text/plain" text="Remember this"/>
    <part ct="image/jpeg" cl="note.jpg" data="{encoded}"/>
  </parts>
</mms>""")
                        msg = message.Message()
                        parser["parse_common"](mms, msg)
                        self.assertTrue(parser["parse_mms"](mms, msg, self.cfg))
                        self.assertEqual(msg.from_slug, "me")
                        self.assertEqual(msg.to_slugs, ["me"])
                        self.assertEqual(msg.group_slug, "")
                        self.assertTrue(msg.is_note_to_self())
                        messages.append(msg)
                for direction in ("1", "2"):
                    sms = fromstring(
                        f'<sms address="{work}" date="1704110400000" '
                        f'type="{direction}" body="SMS note"/>'
                    )
                    msg = message.Message()
                    parser["parse_common"](sms, msg)
                    self.assertTrue(parser["parse_sms"](sms, msg, self.cfg))
                    self.assertTrue(msg.is_note_to_self())
                    messages.append(msg)
                group_lookup.assert_not_called()

        message.add_messages(messages, self.cfg)
        markdown.create_markdown_files(
            self.cfg.people[0],
            str(Path(self.cfg.output_folder) / "People" / "me"), self.cfg,
        )
        output = Path(self.cfg.output_folder) / "Personal Notes"
        text = (output / f"{messages[0].date_str}.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("Remember this"), 6)
        self.assertEqual(text.count("SMS note"), 2)
        self.assertIn("![[note.jpg|450]]", text)
        self.assertEqual((output / "media" / "note.jpg").read_bytes(), image)
        self.assertFalse((Path(self.cfg.output_folder) / "People").exists())

    def test_mms_counts_people_instead_of_phone_number_variants(self):
        self.load_people([
            {"slug": "me", "first_name": "Me", "mobile": "2025550101"},
            {"slug": "pat", "first_name": "Pat", "mobile": "2025550102"},
        ])
        self.cfg.mime_types = {"text/plain": "txt"}
        with patch("message_md.setup", return_value=False):
            with contextlib.redirect_stdout(io.StringIO()):
                parser = runpy.run_path(str(ROOT / "sms_backup_md.py"))
        mms = fromstring("""<mms>
  <addrs>
    <addr address="2025550102" type="137"/>
    <addr address="+12025550102" type="151"/>
    <addr address="+12025550101" type="151"/>
  </addrs>
  <parts><part ct="text/plain" text="Not a group or a personal note"/></parts>
</mms>""")
        msg = message.Message()
        with patch.object(self.cfg, "get_group_slug_by_phone_numbers") as lookup:
            self.assertTrue(parser["parse_mms"](mms, msg, self.cfg))
            lookup.assert_not_called()
        self.assertEqual(msg.from_slug, "pat")
        self.assertEqual(msg.group_slug, "")
        self.assertFalse(msg.is_note_to_self())

    def test_rerunning_conversion_leaves_existing_dated_note_unchanged(self):
        self.load_people([
            {"slug": "me", "first_name": "Me", "mobile": "2025550101"},
            {"slug": "pat", "first_name": "Pat", "mobile": "2025550102"},
        ])
        messages = []
        for sender, recipient, body in (
            ("pat", "me", "Happy Thanksgiving"),
            ("me", "pat", "Thanks!"),
        ):
            msg = message.Message()
            msg.from_slug = sender
            msg.to_slugs = [recipient]
            msg.body = body
            msg.timestamp = 1791842523 + len(messages) * 360
            msg.set_date_time()
            messages.append(msg)
        message.add_messages(messages, self.cfg)
        output = self.folder / "render"
        output.mkdir()
        contact = self.cfg.people[1]
        markdown.create_markdown_files(contact, str(output), self.cfg)
        note = output / f"{messages[0].date_str}.md"
        original = note.read_bytes()
        for age in (0, 60):
            with self.subTest(age=age):
                with patch("markdown.os.path.getctime", return_value=1000-age):
                    markdown.create_markdown_files(contact, str(output), self.cfg)
                self.assertEqual(note.read_bytes(), original)

    def test_missing_or_invalid_mms_data_does_not_create_or_truncate_media(self):
        self.cfg.mime_types = {"video/mp4": "mp4"}
        self.cfg.people_subfolder = "People"
        self.cfg.media_subfolder = "media"
        self.load_people([
            {"slug": "me", "first_name": "Me", "mobile": "2025550101"},
            {"slug": "pat", "first_name": "Pat", "mobile": "2025550102"},
        ])
        with patch("message_md.setup", return_value=False):
            with contextlib.redirect_stdout(io.StringIO()):
                parser = runpy.run_path(str(ROOT / "sms_backup_md.py"))

        for data in (None, "", " \n ", "null", "invalid-base64", "!!!!"):
            for existing in (False, True):
                with self.subTest(data=data, existing=existing):
                    media = Path(self.cfg.output_folder) / "People" / "pat" / "media"
                    filename = media / "video.mp4"
                    if existing:
                        media.mkdir(parents=True, exist_ok=True)
                        filename.write_bytes(b"existing valid video")
                    elif filename.exists():
                        filename.unlink()
                    mms = fromstring("""<mms m_id="missing-video">
  <addrs>
    <addr address="2025550102" type="137"/>
    <addr address="2025550101" type="151"/>
  </addrs>
  <parts><part ct="video/mp4" cl="null" name="video.mp4"/></parts>
</mms>""")
                    if data is not None:
                        mms.find("parts/part").set("data", data)
                    msg = message.Message()
                    level = "ERROR" if data in ("invalid-base64", "!!!!") else "WARNING"
                    with self.assertLogs(level=level) as logs:
                        self.assertTrue(parser["parse_mms"](mms, msg, self.cfg))
                    self.assertIn("video.mp4", "\n".join(logs.output))
                    self.assertEqual([a.id for a in msg.attachments], ["video.mp4"])
                    if existing:
                        self.assertEqual(filename.read_bytes(), b"existing valid video")
                    else:
                        self.assertFalse(filename.exists())

        mms.find("parts/part").set(
            "data", "\n" + base64.b64encode(b"valid video").decode("ascii") + "\n"
        )
        with self.assertNoLogs(level="WARNING"):
            self.assertTrue(parser["parse_mms"](mms, message.Message(), self.cfg))
        self.assertEqual(filename.read_bytes(), b"valid video")


if __name__ == "__main__":
    unittest.main()

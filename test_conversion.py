import base64
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "hal"))
sys.path.insert(0, str(ROOT.parent / "message_md"))

import config
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


if __name__ == "__main__":
    unittest.main()

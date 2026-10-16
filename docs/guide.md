# sms_backup_md

You can learn more about the amazing SMS Backup and Restore tool by SyncTech Pty Ltd on their Web site at https://www.synctech.com.au/sms-backup-restore and the [Fields in XML Backup Files](https://www.synctech.com.au/sms-backup-restore/fields-in-xml-backup-files/) page for details on the XML fields if you're interested.

## getting SMS backup files somewhere

I love Syncthing which I run on Android and my home "servers" and laptop. You can use that to get the backup files somewhere that this code can read them.

Once I've processed a backup file, I go into my Android phone and delete all the messages so I have a clean device and so the next backup file doesn't contain the messages already processed.

That said, if you do end up keeping the messages on your phone and in turn they show up in subsequent SMS backup files, this tool will not overwrite existing Markdown files. On the downside, it will also not add any additional messages from a specific day.
This also applies to immediate reruns: newly created conversation notes are
not appended to a second time. Remove an affected generated note before
rerunning if it already contains duplicates.

## Dated files and media

Messages are written to `People\<person-slug>\YYYY-MM-DD.md` (group conversations
go under `People\groups\<group-slug>`). Senders need a `first_name` in
`people.json`; the shared library also accepts legacy `first-name` and uses the
first word of `profile_full_name` when the first name is empty. Check the logged
errors if a sender has neither name. Saving configuration preserves the names
in HAL's identity fields.

Messages between phone numbers that resolve to your own person slug are saved
as notes to self, not group conversations. This includes messages between your
work and personal phones. Notes go to the configured `daily-notes-subfolder`
(for example, `Personal Notes`), with attachments in its `media` subfolder.
Group detection counts distinct people rather than phone-number strings, so
multiple numbers or number formats for one person do not create a group.

MMS attachments are decoded from the XML directly into
`People\<sender-slug>\media`. They do not need a source `attachments` folder.
The dated message files contain wikilinks to those media filenames. Existing
media files alone do not indicate that the sender's messages could be rendered.
Videos use embedded wikilinks (`![[video.mp4]]`), with a plain blank line before
a following quoted comment.

Some backups contain both an RCS/group MMS record and a sender-only copy with
the same message ID. These copies are combined into one message, preserving
the group conversation, text, and attachments regardless of record order.
Attachment filenames use `cl`, falling back to `name` when `cl` is missing or
`null`.

When an attachment has a filename but no embedded data, the converter logs a
warning and keeps its Markdown reference without creating an empty media file.
The media must be recovered from another backup or the original device if it
is not already available. Invalid base64 data is logged as an error and decoded
before opening the destination, so it cannot truncate an existing media file.

If an earlier conversion placed a duplicate in a person's dated note instead
of the group's note, remove the affected generated dated notes from both
conversations before rerunning the conversion. Existing notes are not
overwritten or repaired automatically.
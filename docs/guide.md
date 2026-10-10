# sms_backup_md

You can learn more about the amazing SMS Backup and Restore tool by SyncTech Pty Ltd on their Web site at https://www.synctech.com.au/sms-backup-restore and the [Fields in XML Backup Files](https://www.synctech.com.au/sms-backup-restore/fields-in-xml-backup-files/) page for details on the XML fields if you're interested.

## getting SMS backup files somewhere

I love Syncthing which I run on Android and my home "servers" and laptop. You can use that to get the backup files somewhere that this code can read them.

Once I've processed a backup file, I go into my Android phone and delete all the messages so I have a clean device and so the next backup file doesn't contain the messages already processed.

That said, if you do end up keeping the messages on your phone and in turn they show up in subsequent SMS backup files, this tool will not overwrite existing Markdown files. On the downside, it will also not add any additional messages from a specific day.

## Dated files and media

Messages are written to `People\<person-slug>\YYYY-MM-DD.md` (group conversations
go under `People\groups\<group-slug>`). Senders need a `first_name` in
`people.json`; the shared library also accepts legacy `first-name` and uses the
first word of `profile_full_name` when the first name is empty. Check the logged
errors if a sender has neither name. Saving configuration preserves the names
in HAL's identity fields.

MMS attachments are decoded from the XML directly into
`People\<sender-slug>\media`. They do not need a source `attachments` folder.
The dated message files contain wikilinks to those media filenames. Existing
media files alone do not indicate that the sender's messages could be rendered.
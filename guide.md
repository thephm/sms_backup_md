# sms_backup_md

You can learn more about the amazing SMS Backup and Restore tool by SyncTech Pty Ltd on their Web site at https://www.synctech.com.au/sms-backup-restore and the [Fields in XML Backup Files](https://www.synctech.com.au/sms-backup-restore/fields-in-xml-backup-files/) page for details on the XML fields if you're interested.

## getting SMS backup files somewhere

I love Syncthing which I run on Android and my home "servers" and laptop. You can use that to get the backup files somewhere that this code can read them.

Once I've processed a backup file, I go into my Android phone and delete all the messages so I have a clean device and so the next backup file doesn't contain the messages already processed.

That said, if you do end up keeping the messages on your phone and in turn they show up in subsequent SMS backup files, this tool will not overwrite existing Markdown files. On the downside, it will also not add any additional messages from a specific day. 
# sms_backup_md

This tool takes the XML output file from the Android [SMS Backup and Restore](https://play.google.com/store/apps/details?id=com.riteshsahu.SMSBackupRestore) Tool and generates a set of Markdown files and corresponding attachment files on your filesystem.

See the `docs\guide.md` for more information.

## message_md dependency

The code in this repo relies heavily on my `message_md` classes which contain generic Message, Person, Group and other classes and the methods to convert messages to Markdown files. Be sure to read the docs for that repo first. I abstracted them from the older sister (first child) tool `signal_md`.

 ## License

 Apache License 2.0

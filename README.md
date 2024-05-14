# sms_backup_md

This tool takes the XML output file from the Android [SMS Backup and Restore](https://play.google.com/store/apps/details?id=com.riteshsahu.SMSBackupRestore) Tool and generates a set of Markdown files and corresponding attachment files on your filesystem.

See the `docs\guide.md` for more information.

## message_md dependency

The code in this repo relies heavily on my [message_md](https://github.com/thephm/message_md/) classes which contain generic `Message`, `Person`, `Group` and other classes and the methods to convert messages to Markdown files. Be sure to read the docs for that repo first. I abstracted them from the older sister (first child) tool `signal_md`.

Make sure to install `libxml` e.g. `sudo apt-get install python-lxml`

If that gave an issue, I also had to `pip install --upgrade lxml`s

## How to use it

If your name is `bob` and you want to convert all messages since `1990-01-01`

```shell
python3 sms_backup_md.py -m bob  -c ../../dev-output/config -f ../../sms/sms-20240505003555.xml -o ../../dev-output -d -b 1990-01-01
```

## License

 Apache License 2.0

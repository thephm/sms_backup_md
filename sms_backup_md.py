import os
from lxml.etree import XMLParser, parse
import xml.etree.ElementTree as ET
import base64

import pathlib
from pathlib import Path
from os.path import exists

import sys
sys.path.insert(1, '../message_md/')
import message_md
import config
import markdown
import attachment
import message

MIN_PHONE_NUMBER_LEN = 7

#-----------------------------------------------------------------------------
# 
# Parser for SMS Backup and Restore XSL file output
# 
# References:
# 
# 1. Google Play app
# https://play.google.com/store/apps/details?id=com.riteshsahu.SMSBackupRestore
#
# 2. Their site: https://www.synctech.com.au/sms-backup-restore/
# 
# 3. Fields in the XML file
# https://www.synctech.com.au/sms-backup-restore/fields-in-xml-backup-files/
# 
# In group messages phone numbers are joined like this with ~
# e.g. address="+12895551212~+14165551313~+12895551414"
#
# Those addresses are also in the `<addr></addr>' attributes of the message
#
#-----------------------------------------------------------------------------

# message types
SMS = "sms"
MMS = "mms"

# SMS fields
SMS_TYPE = "type"
SMS_DATE = "date"
SMS_BODY = "body"
SMS_ADDRESS = "address"
SMS_IMDN_MESSAGE_ID = "imdn_message_id"

# the `type` field values
SMS_RECEIVED = "1"
SMS_SENT = "2"

# MMS fields
MMS_CT_T = "ct_t"
MMS_CT = "ct"
MMS_M_ID = "m_id"
MMS_PARTS = "parts"
MMS_PART = "part"
MMS_CL = "cl"
MMS_DATA = "data"
MMS_TEXT = "text"
MMS_ADDRS = "addrs"
MMS_ADDR = "addr"

# the `type` <addrs> attributes
MMS_ADDRESS = "address"
MMS_TYPE = "type"
MMS_FROM = "137"   # e.g. <addr address="+12895551212" type="137" charset="106" />
MMS_TO = "151"     # e.g. <addr address="+12895551313" type="151" charset="106" />
MMS_INSERT_ADDRESS_TOKEN = "insert-address-token" # possible bug in their XML output

# MIME Types
TXT = "txt"
SMIL = "smil"

#-----------------------------------------------------------------------------
# 
# Parse the fields that are common between SMS and MMS messages
#
# Parameters:
#
#    - sms_mms - the actual message XML
#    - message - the target Message object (which will contain Attachment)
#
#-----------------------------------------------------------------------------
def parse_common(sms_mms, message):
    message.phone_number = sms_mms.get(SMS_ADDRESS)
    try:
        message.timestamp = int(sms_mms.get(SMS_DATE))/1000
        message.set_date_time()
    except:
        pass

#-----------------------------------------------------------------------------
# 
# Check that the message hasn't already been found.
#
# Parameters:
#
#    - target_id - the message ID (SMS_IMDN_MESSAGE_ID or MMS_M_ID) 
#    - messages  - collection of [Messages]
#
# Notes:
#
#    - For some reason with SMS Backup & Restore Android tool, there are 
#      sometimes the same message as an SMS and and MMS in the export
#
#-----------------------------------------------------------------------------
def message_exists(target_id, messages):

    for message in messages:
        if target_id and message.id == target_id:
            return True
    return False

#-----------------------------------------------------------------------------
# 
# Parse the MMS specific fields into a Message object. Could be images or text.
#
# Parameters:
#
#    - mms - the actual message XML
#    - message - the target Message object (which will contain Attachment)
#    - config - the configuration
#
# Notes:
# 
#    - body of the message is base64 encoded binary content in `part`
#    - addr
#        address - The phone number of the sender/recipient.
#        type - The type of address, 129 = BCC, 130 = CC, 151 = To, 137 = From
#    - seems to be an Android issue where 'insert-address-token' gets put into
#      an address field so this function assumes the address was "me" which 
#      could be wrong but needed a person/name
# 
#-----------------------------------------------------------------------------
def parse_mms(mms, message, the_config):

    result = False
    
    message.id = mms.get(MMS_M_ID)
    filename = ""

    phone_numbers = []  # phone numbers for each person the message was sent to

    # get the attachments OR text message between groups of people
    for child in mms.find(MMS_PARTS):
        try:
            content_type = child.get(MMS_CT)
            attachment_type = the_config.mime_types[content_type]
            if attachment_type != TXT and attachment_type != SMIL:
                the_attachment = attachment.Attachment()
                the_attachment.type = attachment_type
                the_attachment.id = child.get(MMS_CL)
                
                # added "if" https://github.com/thephm/sms_backup_md/issues/4
                if not (the_attachment.id == "null"):
                    filename = os.path.join(the_config.attachments_subfolder, the_attachment.id) 
                    filename = os.path.join(the_config.source_folder, filename)
                    mediaFile = open(filename, 'wb')
                    decoded = base64.b64decode(child.get(MMS_DATA))
                    mediaFile.write(decoded)
                    mediaFile.close()
                    message.add_attachment(the_attachment)
            elif attachment_type == TXT:
                message.body = child.get(MMS_TEXT)
        except Exception as e:
            print(e)
            pass

    # get the addresses
    for addr in mms.find(MMS_ADDRS):
        person_slug = ""
        phone_number = addr.get(MMS_ADDRESS)
        if not phone_number == MMS_INSERT_ADDRESS_TOKEN:
            try:
                person = the_config.get_person_by_number(phone_number)

                if phone_number not in phone_numbers:
                    phone_numbers.append(phone_number)
                    person_slug = person.slug
            except:
                pass
        else:
            person_slug = the_config.me.slug
            phone_numbers.append(the_config.me.mobile)

        address_type = addr.get(MMS_TYPE)

        if person_slug:
            
            if address_type == MMS_FROM:
                message.from_slug = person_slug
                result = True

            elif address_type == MMS_TO:
                message.to_slugs.append(person_slug) 
                result = True

    if len(phone_numbers) > 2:
        message.group_slug = the_config.get_group_slug_by_phone_numbers(phone_numbers)
        
    return result

# parse the SMS specific fields
def parse_sms(sms, message, the_config):
    
    result = False
    message.body = sms.get(SMS_BODY)
    message.id = sms.get(SMS_IMDN_MESSAGE_ID)

    phone_number = message.phone_number
                
    if phone_number and len(phone_number) >= MIN_PHONE_NUMBER_LEN:
        person = the_config.get_person_by_number(phone_number)

        if person:
            if sms.get(SMS_TYPE) == SMS_RECEIVED:
                message.from_slug = person.slug
                message.to_slugs.append(the_config.me.slug)
                result = True

            elif sms.get(SMS_TYPE) == SMS_SENT:
                message.from_slug = the_config.me.slug
                message.to_slugs.append(person.slug)
                result = True

        elif the_config.debug:
            print("No one with phone number '" + phone_number + "' found.")

    return result

def load_messages(filename, messages, reactions, the_config):

    p = XMLParser(huge_tree=True)
    result = False

    if not os.path.exists(filename):
        if the_config.debug:
            print(the_config.get_str(the_config.STR_COULD_NOT_LOAD_MESSAGES_FILE) + ": " + filename)
        return False
    else:
        tree = parse(filename, parser=p)
        root = tree.getroot()

        for child in root.iter():
            the_message = message.Message()

            parse_common(child, the_message)
            if child.tag == SMS:
                result = parse_sms(child, the_message, the_config)
            elif child.tag == MMS:
                result = parse_mms(child, the_message, the_config)

            if result:
                # to fix https://github.com/thephm/sms_backup_md/issues/2
                if not message_exists(the_message.id, messages):
                    if len(the_message.body) or len(the_message.attachments):
                        messages.append(the_message)

    return True

# main

the_messages = []
the_reactions = [] # required by `message_md` but not used for SMS messages

the_config = config.Config()

if message_md.setup(the_config, markdown.YAML_SERVICE_SMS):

    # create the working folder `attachments` under the source message folder
    # so media files can be created there from the MMS messages
    folder = os.path.join(the_config.source_folder, the_config.attachments_subfolder) 
    if not os.path.exists(folder):
        Path(folder).mkdir(parents=True, exist_ok=True)

    # needs to be after setup so the command line parameters override the
    # values defined in the settings file
    message_md.get_markdown(the_config, load_messages, the_messages, the_reactions)
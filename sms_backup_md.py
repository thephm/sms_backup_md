"""Parser for SMS Backup and Restore XML file output.

References:
1. Google Play app:
    https://play.google.com/store/apps/details?id=com.riteshsahu.SMSBackupRestore
2. Their site:
    https://www.synctech.com.au/sms-backup-restore/
3. Fields in the XML file:
    https://www.synctech.com.au/sms-backup-restore/fields-in-xml-backup-files/

In group messages phone numbers are joined with "~", e.g.
address="+12895551212~+14165551313~+12895551414"

Those addresses are also in the <addr></addr> attributes of the message.
"""

import os
from lxml.etree import XMLParser, parse
import xml.etree.ElementTree as ET
import base64

import pathlib
from pathlib import Path
from os.path import exists

import logging

import sys
sys.path.insert(1, '../hal/')
import person
sys.path.insert(1, '../message_md/')
import message_md
import config
import markdown
import attachment
import message

MIN_PHONE_NUMBER_LEN = 7

"""Message types."""
SMS = "sms"
MMS = "mms"

"""SMS fields."""
SMS_TYPE = "type"
SMS_DATE = "date"
SMS_BODY = "body"
SMS_ADDRESS = "address"
SMS_IMDN_MESSAGE_ID = "imdn_message_id"

"""The `type` field values."""
SMS_RECEIVED = "1"
SMS_SENT = "2"

"""MMS fields."""
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

"""The `type` <addrs> attributes."""
MMS_ADDRESS = "address"
MMS_TYPE = "type"
MMS_CC = "130"  
"""Example: <addr address="+12895551212" type="137" charset="106" />."""
MMS_FROM = "137"
"""Example: <addr address="+12895551313" type="151" charset="106" />."""
MMS_TO = "151"
"""Possible bug in SMS Backup & Restore XML output."""
MMS_INSERT_ADDRESS_TOKEN = "insert-address-token"

"""MIME types."""
TXT = "txt"
SMIL = "smil"

def parse_common(sms_mms, message):
    """
    Parse the fields that are common between SMS and MMS messages.

    Parameters:
    sms_mms (dict): the actual message in XML format
    message (Message): the target Message object (which will contain 
        Attachment)

    Returns:
    None
    """
    message.phone_number = sms_mms.get(SMS_ADDRESS)
    try:
        message.timestamp = int(sms_mms.get(SMS_DATE))/1000
        message.set_date_time()
    except:
        pass

def get_existing_message(target_id, messages):
    """
    Check that the message hasn't already been found.

    Parameters:
    target_id (str): the message ID (SMS_IMDN_MESSAGE_ID or MMS_M_ID)
    messages (list[Message]): collection of Messages

    Returns:
    Message: The existing Message if found, False otherwise.

    Notes:
    For some reason with SMS Backup & Restore Android tool, there are 
    sometimes the same message as an SMS and and MMS in the export so 
    needed a way to check if the message already exists in the
    collection of messages.
    """
    for message in messages:
        if target_id and message.id == target_id:
            return message
    return False

def parse_mms(mms, message, the_config):
    """
    Parse the MMS specific fields into a Message object: images or text.

    Parameters:
    mms (dict): the actual MMS message
    message (Message): the target Message object which will contain 
        Attachment
    the_config (Config): the configuration object

    Returns:
    bool: True if the message was parsed successfully, False otherwise.

    Notes:
    - body of the message is base64 encoded binary content in `part`
    - addr
        address - The phone number of the sender/recipient.
        type - The type of address, 129 = BCC, 130 = CC, 151 = To, 137 = From
    - seems to be an Android issue where 'insert-address-token' gets put into
      an address field so this function assumes the address was "me" which 
      could be wrong but needed a person/name
    """

    result = False
    
    message.id = mms.get(MMS_M_ID)
    filename = ""

    """Phone numbers for each person the message was sent to."""
    phone_numbers = []

    """Get the addresses."""
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
            if phone_number not in phone_numbers:
                phone_numbers.append(the_config.me.contact.mobile)

        address_type = addr.get(MMS_TYPE)

        if person_slug:
            
            if address_type == MMS_FROM or address_type == MMS_CC:
                message.from_slug = person_slug
                result = True

            elif address_type == MMS_TO:
                message.to_slugs.append(person_slug) 
                result = True

    """Ensure my number is included."""
    if the_config.me.contact.mobile not in phone_numbers:
        phone_numbers.append(the_config.me.contact.mobile)

    if len(phone_numbers) > 2:
        message.group_slug = the_config.get_group_slug_by_phone_numbers(phone_numbers)
        result = True
    elif len(phone_numbers) == 1:
        """Issue #7: MMS images can be separated when my number is missing."""
        if address_type == MMS_FROM or address_type == MMS_CC:
            message.to_slugs.append(the_config.me.slug) 
            result = True

        elif address_type == MMS_TO:
            message.from_slug = the_config.me.slug
            result = True

    if not message.from_slug:
        """Fallback: set to my slug."""
        message.from_slug = the_config.me.slug

    """Get the attachments or group text message content."""
    for child in mms.find(MMS_PARTS):
        try:
            content_type = child.get(MMS_CT)
            attachment_type = the_config.mime_types[content_type]

            if attachment_type != TXT and attachment_type != SMIL:  
                the_attachment = attachment.Attachment()
                the_attachment.type = content_type
                the_attachment.id = child.get(MMS_CL)

                if the_attachment.id and the_attachment.id != "null":
                    filename = the_config.create_media_folder(the_attachment.id, message.from_slug)
                    try:
                        with open(filename, 'wb') as mediaFile:
                            decoded = base64.b64decode(child.get(MMS_DATA))
                            mediaFile.write(decoded)
                    except Exception as e:
                        logging.error(f"Failed to write attachment {filename}: {e}")

                    message.add_attachment(the_attachment)
            elif attachment_type == TXT:
                message.body = child.get(MMS_TEXT)
        except Exception as e:
            logging.error(f"{the_config.get_str(the_config.STR_COULD_NOT_PROCESS_MMS_PART)}: {e}")
            pass

    return result

def parse_sms(sms, message, the_config):
    """
    Parse the SMS specific fields.

    Parameters:
    sms (dict): the actual SMS message
    message (Message): the target Message object
    the_config (Config): the configuration object

    Returns:
    bool: True if the message was parsed successfully, False otherwise.
    """
    
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
            logging.error(f"{the_config.get_str(the_config.STR_NO_PERSON_WITH_PHONE_NUMBER)}: {phone_number}")

    return result

def load_messages(filename, messages, reactions, the_config):
    """
    Load messages from the SMS Backup & Restore XML file.
    
    Parameters:
    filename (str): the path to the XML file    
    messages (list[Message]): collection of Message objects
    reactions (list[Reaction]): collection of Reaction objects (not used)
    the_config (Config): the configuration object
    
    Returns:
    bool: True if the messages were loaded successfully, False otherwise.
    """

    p = XMLParser(huge_tree=True)
    result = False

    if not os.path.exists(filename):
        if the_config.debug:
            logging.error(f"{the_config.get_str(the_config.STR_COULD_NOT_FIND_MESSAGES_FILE)}: {filename}")
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
                """Fixes duplicate handling for issues #2 and #13."""
                existing_message = get_existing_message(the_message.id, messages)
                if existing_message:
                    messages.remove(existing_message)
                    
                """Include messages with text body or MMS media attachments."""
                if len(the_message.body) or len(the_message.attachments) > 0:
                    messages.append(the_message)

    return True

"""Main execution."""

the_messages = []
"""Required by message_md but not used for SMS messages."""
the_reactions = []

the_config = config.Config()

"""Set up logging."""
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)

if message_md.setup(the_config, markdown.YAML_SERVICE_SMS):
    """Create attachments folder under source so MMS media can be written."""
    folder = os.path.join(the_config.source_folder, the_config.attachments_subfolder)
    try:
        if not os.path.exists(folder):
            Path(folder).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logging.error(f"{the_config.get_str(the_config.STR_COULD_NOT_CREATE_ATTACHMENTS_SUBFOLDER)}: {folder}. Error: {str(e)}")

    """Run after setup so CLI parameters override settings-file values."""
    message_md.get_markdown(the_config, load_messages, the_messages, the_reactions)
else:
    print(f"{the_config.get_str(the_config.STR_COULD_NOT_SETUP)}")
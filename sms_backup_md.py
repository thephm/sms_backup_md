import os
from lxml.etree import XMLParser, parse
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

# the `type` field values
SMS_RECEIVED = "1"
SMS_SENT = "2"

# MMS fields
MMS_CT_T = "ct_t"
MMS_CT = "ct"
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
IMAGE_JPEG = "image/jpeg"
JPG = "jpg"
JPEG = "jpeg"

IMAGE_PNG = "image/png"
PNG = "png"

IMAGE_BMP = "image/x-ms-bmp"
BMP = "bmp"

TEXT_PLAIN = "text/plain"
TXT = "txt"

APPLICATION_PDF = "application/pdf"
PDF = "pdf"

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
def parseCommon(sms_mms, message):
    message.phoneNumber = sms_mms.get(SMS_ADDRESS)
    try:
        message.timeStamp = int(sms_mms.get(SMS_DATE))/1000
        message.setDateTime()
    except:
        pass

#-----------------------------------------------------------------------------
# 
# Parse the MMS specific fields. Could be images or text.
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
def parseMMS(mms, message, theConfig):

    result = False

    phoneNumbers = []  # phone numbers for each person the message was sent to

    # get the attachments OR text message between groups of people
    for child in mms.find(MMS_PARTS):
        try:
            attachmentType = theConfig.MIMETypes[child.get(MMS_CT)]
            attachmentType
            if attachmentType in [JPG, JPEG, PNG, BMP, PDF]:
                theAttachment = attachment.Attachment()
                theAttachment.type = IMAGE_JPEG # @todo do this for each type!
                theAttachment.id = child.get(MMS_CL)
                fileName = os.path.join(theConfig.attachmentsSubFolder, theAttachment.id) 
                fileName = os.path.join(theConfig.sourceFolder, fileName) 
                mediaFile = open(fileName, 'wb')
                decoded = base64.b64decode(child.get(MMS_DATA))
                mediaFile.write(decoded)
                mediaFile.close()
                message.addAttachment(theAttachment)
            if attachmentType == TXT:
                message.body = child.get(MMS_TEXT)
        except Exception as e:
            print(e)
            pass

    # get the addresses
    for addr in mms.find(MMS_ADDRS):
        personSlug = ""
        phoneNumber = addr.get(MMS_ADDRESS)
        if not phoneNumber == MMS_INSERT_ADDRESS_TOKEN:
            try:
                person = theConfig.getPersonByNumber(phoneNumber)
                
                if phoneNumber not in phoneNumbers:
                    phoneNumbers.append(phoneNumber)

                if person:
                    personSlug = person.slug
            except:
                pass
        else:
            personSlug = theConfig.me.slug
            phoneNumbers.append(theConfig.me.mobile)

        addressType = addr.get(MMS_TYPE)
        if personSlug:
            if addressType == MMS_FROM:
                message.fromSlug = personSlug
                result = True
            elif addressType == MMS_TO:
                message.toSlugs.append(personSlug) 
                result = True

    if len(phoneNumbers) > 2:
        message.groupSlug = theConfig.getGroupSlugByPhoneNumbers(phoneNumbers)

    return result

# parse the SMS specific fields
def parseSMS(sms, message, theConfig):
    
    result = False
    message.body = sms.get(SMS_BODY)

    phoneNumber = message.phoneNumber

    if phoneNumber and len(phoneNumber) >= MIN_PHONE_NUMBER_LEN:
        person = theConfig.getPersonByNumber(phoneNumber)

        if person:
            if sms.get(SMS_TYPE) == SMS_RECEIVED:
                message.fromSlug = person.slug
                message.toSlugs.append(theConfig.me.slug)
                result = True

            elif sms.get(SMS_TYPE) == SMS_SENT:
                message.fromSlug = theConfig.me.slug
                message.toSlugs.append(person.slug)
                result = True

    return result

def loadMessages(fileName, messages, reactions, theConfig):

    p = XMLParser(huge_tree=True)
    result = False

    if not os.path.exists(fileName):
        if theConfig.debug:
            print(theConfig.getStr(theConfig.STR_COULD_NOT_LOAD_MESSAGES_FILE) + ": " + fileName)
        return False
    else:
        tree = parse(fileName, parser=p)
        root = tree.getroot()

        for child in root.iter():
            theMessage = message.Message()

            parseCommon(child, theMessage)
            if child.tag == SMS:
                result = parseSMS(child, theMessage, theConfig)
            elif child.tag == MMS:
                result = parseMMS(child, theMessage, theConfig)
            else:
                continue

            if result:
                if len(theMessage.body) or len(theMessage.attachments):
                    messages.append(theMessage)
                elif theConfig.debug:
                   print(theConfig.getStr(theConfig.STR_NO_MESSAGE_BODY_OR_ATTACHMENT) + ": " + theMessage.phoneNumber)

    return True

# main

theMessages = []
theReactions = [] # required by `message_md` but not used for SMS messages

theConfig = config.Config()

if message_md.setup(theConfig, markdown.YAML_SERVICE_SMS):

    # create the working folder `attachments` under the source message folder
    # so media files can be created there from the MMS messages
    folder = os.path.join(theConfig.sourceFolder, theConfig.attachmentsSubFolder) 
    if not os.path.exists(folder):
        Path(folder).mkdir(parents=True, exist_ok=True)

    # needs to be after setup so the command line parameters override the
    # values defined in the settings file
    message_md.getMarkdown(theConfig, loadMessages, theMessages, theReactions)
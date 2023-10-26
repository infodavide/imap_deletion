#!/usr/bin/python
# -*- coding: utf-*-

import argparse
import atexit
import os
import signal
import time
import email
import imaplib
import logging
import os
import pathlib
import xml.etree.ElementTree as etree
from logging.handlers import RotatingFileHandler
from imaplib import IMAP4, IMAP4_SSL

__author__ = 'David Rolland, contact@infodavid.org'
__copyright__ = 'Copyright © 2023 David Rolland'
__license__ = 'MIT'

IMAP4_PORT: int = 143


class ObjectView(object):
    def __init__(self, d):
        self.__dict__ = d

    """ Returns the string representation of the view """
    def __str__(self) -> str:
        return str(self.__dict__)


class Settings(object):
    """
    Settings used by the IMAP deletion.
    """
    imap_server: str = None  # Full name or IP address of your IMAP server
    imap_use_ssl: bool = False  # Set True to use SSL
    imap_port: int = IMAP4_PORT  # Port of your IMAP server
    imap_user: str = None  # User used to connect to your IMAP server
    imap_password: str = None  # Password (base64 encoded) of the user used to connect to your IMAP server
    imap_folder: str = None  # The IMAP folder where to delete the messages
    imap_trash: str = None  # The IMAP trash folder
    path: str = None  # Path for the files used by the application
    log_path: str  # Path to the logs file, not used in this version
    log_level: str  # Level of logs, not used in this version

    def parse(self, path: str) -> None:
        """
        Parse the XML configuration.
        """
        with open(path) as f:
            tree = etree.parse(f)
        root_node: etree.Element = tree.getroot()
        log_node: etree.Element = root_node.find('log')
        if log_node is not None:
            v = log_node.get('path')
            if v is not None:
                self.log_path = str(v)
            v = log_node.get('level')
            if v is not None:
                self.log_level = str(v)
        accounts = {}
        for node in tree.findall('accounts/account'):
            v1 = node.get('user')
            v2 = node.get('password')
            v3 = node.get('id')
            if v1 is not None and v2 is not None and v3 is not None:
                accounts[v3] = [v1, v2]
        imap_node: etree.Element = root_node.find('imap')
        if imap_node is not None:
            self.imap_server = imap_node.get('server')
            v = imap_node.get('port')
            if v is not None:
                self.imap_port = int(v)
            else:
                self.imap_port = 143
            v = imap_node.get('folder')
            if v is not None:
                self.imap_folder = str(v)
            else:
                self.imap_folder = '"[Gmail]/Sent Mail"'
            v = imap_node.get('trash')
            if v is not None:
                self.imap_trash = str(v)
            else:
                self.imap_trash = '"[Gmail]/Trash"'
            self.imap_use_ssl = imap_node.get('ssl') == 'True' or imap_node.get('ssl') == 'true'
        else:
            raise IOError('No imap element specified in the XML configuration, refer to the autoreplier.xsd')
        account_id: str = imap_node.get('account-id')
        account = accounts[account_id]
        if account:
            self.imap_user = account[0]
            self.imap_password = account[1]
        self.path = os.path.dirname(path)


def create_rotating_log(path: str, level: str) -> logging.Logger:
    """
    Create the logger with file rotation.
    :param path: the path of the main log file
    :param level: the log level as defined in logging module
    :return: the logger
    """
    result: logging.Logger = logging.getLogger("imap_deletion")
    path_obj: pathlib.Path = pathlib.Path(path)
    if not os.path.exists(path_obj.parent.absolute()):
        os.makedirs(path_obj.parent.absolute())
    if os.path.exists(path):
        open(path, 'w').close()
    else:
        path_obj.touch()
    # noinspection Spellchecker
    formatter: logging.Formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler: logging.Handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    result.addHandler(console_handler)
    file_handler: logging.Handler = RotatingFileHandler(path, maxBytes=1024 * 1024 * 5, backupCount=5)
    # noinspection PyUnresolvedReferences
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    result.addHandler(file_handler)
    # noinspection PyUnresolvedReferences
    result.setLevel(level)
    return result


def cleanup() -> None:
    global logger
    logger.log(logging.INFO, "Cleaning...")
    if 'mailbox' in globals():
        global mailbox
        if 'logger' in globals():
            logger.log(logging.INFO, 'IMAP session state: %s' % mailbox.state)
        if 'SELECTED' == mailbox.state:
            mailbox.expunge()
            mailbox.close()
            mailbox.logout()


def signal_handler(sig=None, frame=None) -> None:
    cleanup()


parser = argparse.ArgumentParser(prog='imap_deletion.py', description='Delete sent messages from IMAP server')
parser.add_argument('-f', required=True, help='Configuration file')
parser.add_argument('-l', help='Log level', default='INFO')
parser.add_argument('-v', default=False, action='store_true', help='Verbose')
args = parser.parse_args()
LOG_LEVEL: str = args.l
if LOG_LEVEL.startswith('"') and LOG_LEVEL.endswith('"'):
    LOG_LEVEL = LOG_LEVEL[1:-1]
if LOG_LEVEL.startswith("'") and LOG_LEVEL.endswith("'"):
    LOG_LEVEL = LOG_LEVEL[1:-1]
CONFIG_PATH: str = args.f
if CONFIG_PATH.startswith('"') and CONFIG_PATH.endswith('"'):
    CONFIG_PATH = CONFIG_PATH[1:-1]
if CONFIG_PATH.startswith("'") and CONFIG_PATH.endswith("'"):
    CONFIG_PATH = CONFIG_PATH[1:-1]
if not os.path.exists(CONFIG_PATH):
    CONFIG_PATH = str(pathlib.Path(__file__).parent) + os.sep + CONFIG_PATH
LOG_PATH: str = os.path.splitext(CONFIG_PATH)[0] + '.log'
logger = create_rotating_log(LOG_PATH, LOG_LEVEL)
logger.log(logging.INFO, 'Using arguments: %s' % repr(args))

if not args.f or not os.path.isfile(args.f):
    print('Input file is required and must be valid.')
    exit(1)

LOCK_PATH: str = os.path.abspath(os.path.dirname(CONFIG_PATH)) + os.sep + '.imap_deletion.lck'
settings: Settings = Settings()
settings.log_path = LOG_PATH
settings.log_level = LOG_LEVEL
settings.parse(os.path.abspath(CONFIG_PATH))
logger.setLevel(settings.log_level)
logger.log(logging.INFO, 'Log levels et to: %s' % logging.getLevelName(logger.level))
atexit.register(signal_handler)
signal.signal(signal.SIGINT, signal_handler)
logger.log(logging.INFO, 'Connecting to server: %s:%s with user: %s' % (settings.imap_server, str(settings.imap_port), settings.imap_user))

if settings.imap_use_ssl:
    mailbox = imaplib.IMAP4_SSL(host=settings.imap_server, port=settings.imap_port)
else:
    mailbox = imaplib.IMAP4(host=settings.imap_server, port=settings.imap_port)

mailbox.login(settings.imap_user, settings.imap_password)
if logger.isEnabledFor(logging.DEBUG):
    buffer : str = 'Available folders:\n'
    for i in mailbox.list()[1]:
        p = i.decode().split(' "/" ')
        buffer += (p[0] + " = " + p[1]) + '\n'
    logger.log(logging.DEBUG, buffer)
logger.log(logging.INFO, 'Selecting folder: %s' % settings.imap_folder)
mailbox.select(settings.imap_folder)
typ, data = mailbox.search(None, 'ALL')

for num in data[0].split():
    mailbox.store(num, '+FLAGS', '\\Deleted')

mailbox.select(settings.imap_trash)  # select all trash
mailbox.store("1:*", '+FLAGS', '\\Deleted')  #Flag all Trash as Deleted
exit(0)

__version__ = '1.1.1'
__author__ = 'Marshall L Smith Jr <marshallsmithjr@gmail.com>'
__license__ = 'GPLv3'


#
# Global state indicators
#
from queue import Queue

SSH: str = "/usr/bin/ssh"
VERBOSE = False
KEEP_SOURCE = False
DRY_RUN = False
SHOW_INFO = False

console = None

status_queue = Queue()

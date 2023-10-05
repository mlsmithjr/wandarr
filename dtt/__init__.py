__version__ = '1.0.0'
__author__ = 'Marshall L Smith Jr <marshallsmithjr@gmail.com>'
__license__ = 'GPLv3'


#
# Global state indicators
#
from queue import Queue

verbose = False
keep_source = False
dry_run = False
show_info = False

console = None

status_queue = Queue()

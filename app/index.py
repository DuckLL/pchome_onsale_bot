from utils import *

monitor_db.create_index(['user', 'pid'])
prod_db.create_index(['pid'])

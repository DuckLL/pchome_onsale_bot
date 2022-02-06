#!/bin/sh

cd /app
cp ./crontab /etc/crontab
pip install -r requirements.txt
tmux new-session -d 'python3 /app/bot.py'
/sbin/my_init
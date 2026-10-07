import json, requests
import dataset
from time import sleep

db = dataset.connect('sqlite:///bot.db')
monitor_db = db['monitor']
prod_db = db['prod']


def log2file(msg):
    with open("log.txt", "a") as f:
        f.write(msg)
    return


def get_prod_info(pid):
    url = f"https://ecapi.pchome.com.tw/ecshop/prodapi/v2/prod/{pid}&fields=Name,Price&_callback=."
    headers = {
              'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; rv:91.0) Gecko/20100101 Firefox/91.0'
              }
    for i in range(5):
        sleep(1)
        res = requests.get(url,headers=headers)
        if res.status_code == 200:
            break
    if res.status_code != 200:
        log2file(res.text)
        return None
    resj = json.loads(res.text)
    if f"{pid}-000" not in resj:
        log2file(res.text)
        return None
    return resj[f"{pid}-000"]


def add_monitor(user, pid):
    prod_info = get_prod_info(pid)
    monitor_db.insert(dict(user=user, pid=pid, name=prod_info["Name"]))
    if prod_db.find_one(pid=pid) == None:
        prod_db.insert(
            dict(pid=pid,
                 last_price=prod_info["Price"]["P"],
                 name=prod_info["Name"],
                 error=0))
    return


def delete_monitor(user, pid):
    monitor_db.delete(user=user, pid=pid)
    return

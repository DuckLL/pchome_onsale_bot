import json, requests
import dataset

db = dataset.connect('sqlite:///bot.db')
monitor_db = db['monitor']
prod_db = db['prod']

def get_prod_info(pid):
    url = f"https://ecapi.pchome.com.tw/ecshop/prodapi/v2/prod/{pid}&fields=Name,Price&_callback=."
    res = requests.get(url)
    resj = json.loads(res.text)
    if f"{pid}-000" in resj:
        return resj[f"{pid}-000"]
    else:
        return None

def add_monitor(user,pid):
    prod_info = get_prod_info(pid)
    monitor_db.insert({"user":user,"pid":pid,"name":prod_info["Name"]})
    if prod_db.find_one(pid=pid) == None:
        prod_db.insert({"pid":pid,"last_price":prod_info["Price"]["P"],"name":prod_info["Name"]})
    return

def delete_monitor(user,pid):
    monitor_db.delete(user=user,pid=pid)
    return

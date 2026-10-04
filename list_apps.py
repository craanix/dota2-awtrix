import requests

apps = requests.get("http://192.168.31.41/api/v1/apps", timeout=5).json()


def key(a):
    s = a.get("slot")
    return (1, 99) if s is None else (0, s)


for a in sorted(apps, key=key):
    print(
        f"slot={str(a.get('slot')):>4} inLoop={str(a.get('inLoop')):>5} "
        f"enabled={str(a.get('enabled')):>5} present={str(a.get('present')):>5} "
        f"{str(a.get('origin')):>7} {a['name']}"
    )
"""Accounts of the local server, kept in server/data/accounts.json (passwords as salted PBKDF2).

Nicknames are unique without regard to case. Every account gets the user id of the captured account for now:
the templates carry that id in object ids and data (server-notes/registration-to-tutorial.md).
"""
import hashlib, json, os, secrets, time

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'accounts.json')
TEMPLATE_USER_ID = 3074457415747269434   # 0x2aaaaabafeae733a, the captured account


def _digest(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), 100000).hex()


class Accounts:
    def __init__(self, path=PATH):
        self.path = path
        self.users = json.load(open(path, encoding='utf-8')) if os.path.isfile(path) else {}

    def get(self, uid):
        return next((u for name, u in self.users.items() if name.lower() == uid.lower()), None)

    def create(self, uid, password):
        salt = secrets.token_hex(16)
        user = {'uid': uid, 'userId': TEMPLATE_USER_ID, 'salt': salt, 'password': _digest(password, salt),
                'hash': secrets.token_urlsafe(48), 'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'tank': None}
        self.users[uid] = user
        self.save()
        return user

    def check(self, uid, password):
        user = self.get(uid)
        return user if user and _digest(password, user['salt']) == user['password'] else None

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.users, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

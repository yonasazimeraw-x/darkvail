#!/usr/bin/env python3
# ============================================================
#  Sliced-Baton Scraper & Auto Adder (with confirmation gate)
#  With Android/Termux Specific Device-Lock License System
# ============================================================
import sys
import os
import json
import time
import uuid
import hashlib
import platform
import urllib.request
import urllib.parse
import urllib.error

from telethon.sync import TelegramClient
from telethon.tl.functions.channels import JoinChannelRequest, InviteToChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.errors.rpcerrorlist import (
    PeerFloodError, UserPrivacyRestrictedError,
    UserAlreadyParticipantError, FloodWaitError, ChatAdminRequiredError,
    InviteHashExpiredError, InviteRequestSentError,
    ChannelPrivateError, UserDeactivatedBanError, UserRestrictedError
)
from colorama import init, Fore

init()

# ============= COLORS =============
_r = Fore.RED
_lg = Fore.LIGHTGREEN_EX
_n = Fore.RESET
_w = Fore.WHITE
_cy = Fore.CYAN
_ye = Fore.YELLOW
_grey = '\033[97m'

_i = f'{_lg}[{_w}i{_lg}]{_n}'
_e = f'{_lg}[{_r}!{_lg}]{_n}'
_s = f'{_w}[{_lg}*{_w}]{_n}'
_in = f'{_lg}[{_cy}~{_lg}]{_n}'
_p = f'{_w}[{_lg}+{_w}]{_n}'
_m = f'{_w}[{_lg}-{_w}]{_n}'

# ============= CONFIG =============
AI_API_ID = int(os.environ.get('TG_API_ID', '3910389'))
AI_API_HASH = os.environ.get('TG_API_HASH', '86f861352f0ab76a251866059a6adbd6')
DATABASE = 'accounts.json'
SESSION_FILE = 'add_session.json'
SESSIONS_DIR = 'sessions'

# ====== SUPABASE CONFIG ======
SUPABASE_URL = 'https://famjzltzlkrwmrabucqn.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZhbWp6bHR6bGtyd21yYWJ1Y3FuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTEyMTcwOTYsImV4cCI6MjEwNjc5MzA5Nn0.k2RwT48cg3fIVml9PF9mymLgxIqYtbCUhwf6UxHNEAM'
CUSTOMER_NAME = 'Default User' 
ALLOW_OFFLINE_MODE = True 
LOCAL_CACHE_FILE = '.lic_cache'

# ====== BEHAVIOR CONFIG ======
FLOODWAIT_THRESHOLD = 30       # FloodWait longer than this -> switch account
PER_ACCOUNT_LIMIT = 50         # adds per account per run
INTER_ACCOUNT_DELAY = 60       # cool-down between accounts
ADD_BUFFER = 15                # scrape extra users to absorb failures
PEERFLOOD_TOLERANCE = 8        # stop account after this many PeerFlood errors
MAX_GENERIC_FAILURES = 3       # retries before a user is marked failed
MIN_API_MEMBERS = 20           # if API shows fewer, list is hidden -> also scan history


# ============= SUPABASE DEVICE LOCK SYSTEM =============
class SecurityLock:
    @staticmethod
    def get_hwid():
        """
        Generates a highly unique ID specifically for Android/Termux.
        Uses multiple methods (Termux API, getprop) to prevent mixing devices.
        """
        android_id = ""
        
        # Method 1: Try Termux API (requires termux-api package installed on device)
        try:
            # Reads the device IMEI/Phone info
            android_id = os.popen('termux-telephony-device 2>/dev/null | grep -i "id" | head -n 1').read().strip()
        except Exception:
            pass

        # Method 2: Try Android Secure Settings (android_id)
        if not android_id:
            try:
                android_id = os.popen('settings get secure android_id 2>/dev/null').read().strip()
            except Exception:
                pass

        # Method 3: Try getprop for serial number
        if not android_id or len(android_id) < 5:
            try:
                android_id = os.popen('getprop ro.serialno 2>/dev/null').read().strip()
            except Exception:
                pass

        # Method 4: Fallback to Network MAC if everything else fails (extremely rare in Termux)
        if not android_id or len(android_id) < 5:
            android_id = str(uuid.getnode())

        # Mix with hostname (device name) to guarantee uniqueness even on identical phone models
        hostname = platform.node()
        raw_id = f"{android_id}-{hostname}"
        
        # Hash it to make it clean and uniform
        return hashlib.sha256(raw_id.encode()).hexdigest()

    @staticmethod
    def save_local_cache(hwid):
        try:
            salted = f"yonisalt_{hwid}_secure"
            token = hashlib.sha256(salted.encode()).hexdigest()
            with open(LOCAL_CACHE_FILE, 'w') as f:
                f.write(token)
        except Exception:
            pass

    @staticmethod
    def verify_local_cache(hwid):
        if not os.path.exists(LOCAL_CACHE_FILE):
            return False
        try:
            with open(LOCAL_CACHE_FILE, 'r') as f:
                token = f.read().strip()
            salted = f"yonisalt_{hwid}_secure"
            expected_token = hashlib.sha256(salted.encode()).hexdigest()
            return token == expected_token
        except Exception:
            return False

    @staticmethod
    def check_license():
        hwid = SecurityLock.get_hwid()
        headers = {
            'apikey': SUPABASE_KEY,
            'Authorization': f'Bearer {SUPABASE_KEY}',
            'Content-Type': 'application/json'
        }

        conflict_retries = 0  # Prevent infinite loop on 409 conflict
        while True:
            try:
                check_url = f"{SUPABASE_URL}/rest/v1/licenses?select=status,name&hwid=eq.{hwid}"
                req = urllib.request.Request(check_url, headers=headers)
                response = urllib.request.urlopen(req, timeout=10)
                data = json.loads(response.read().decode())
                
                if data:
                    status = data[0].get('status', 'invalid')
                    db_name = data[0].get('name', 'Unknown')
                    if status == 'valid':
                        ok(f'License Valid for: {_w}{db_name}')
                        SecurityLock.save_local_cache(hwid)
                        return True
                    else:
                        fail(f'License Revoked for {db_name}! Contact admin.')
                        return False
                else:
                    info('First run detected. Registering device...')
                    post_data = json.dumps({"hwid": hwid, "status": "valid", "name": CUSTOMER_NAME}).encode()
                    post_req = urllib.request.Request(
                        f"{SUPABASE_URL}/rest/v1/licenses",
                        data=post_data, headers=headers, method='POST'
                    )
                    urllib.request.urlopen(post_req, timeout=10)
                    ok(f'Device Successfully Registered to {CUSTOMER_NAME}!')
                    SecurityLock.save_local_cache(hwid)
                    time.sleep(1)
                    return True
                    
            except urllib.error.HTTPError as e:
                if e.code == 409:
                    conflict_retries += 1
                    if conflict_retries >= 3:
                        fail("Failed to register device after 3 conflicts. Possible DB issue.")
                        return False
                    info('Device already registered. Verifying...')
                    continue 
                else:
                    fail(f'License Server Error: {e.code}')
                    return False
                    
            except Exception:
                if ALLOW_OFFLINE_MODE and SecurityLock.verify_local_cache(hwid):
                    warn('License server unreachable. Using offline verified mode.')
                    return True
                elif ALLOW_OFFLINE_MODE:
                    fail('Network Error: Cannot reach license server.')
                    info('This is your first run. You must connect to the internet at least once to verify.')
                    info('Retrying in 10 seconds... (Press Ctrl+C to quit)')
                    time.sleep(10)
                else:
                    fail('Network Error: Could not verify license.')
                    return False


# ============= BANNER =============

def print_banner():
    print(f'{_cy}')
    print('╔════════════════════════════════════════════════╗')
    print('║           TELEGRAM AUTO ADDER PRO              ║')
    print('╚════════════════════════════════════════════════╝')
    print(f'{_n}')


# ============= PERSISTENCE =============

def load_accounts():
    if os.path.exists(DATABASE):
        try:
            with open(DATABASE, 'r') as f:
                return json.load(f)
        except Exception:
            return []
    return []


def load_session():
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return None
    return None


# ============= FRIENDLY UI HELPERS =============

def line():
    print(f'{_grey}' + '─' * 50 + f'{_n}')


def section(title):
    print(f'\n{_cy}── {title} ' + '─' * max(0, 44 - len(title)) + f'{_n}')


def ok(msg):   print(f'{_p}{_lg} ✓ {msg}{_n}')
def info(msg): print(f'{_i}{_cy} {msg}{_n}')
def fail(msg): print(f'{_e}{_r} ✗ {msg}{_n}')
def warn(msg): print(f'{_i}{_ye} ⚠ {msg}{_n}')


def ask_link(prompt_text):
    """Lenient link input. Cleans quotes/slashes. Re-asks if empty or has spaces."""
    while True:
        raw = input(f'{_in}{_cy} {prompt_text}{_n}\n{_cy}> {_n}').strip()
        if not raw:
            fail('Please paste or type the link (or press Ctrl+C to quit).')
            continue
        link = raw.strip('\'" ').rstrip('/')
        if ' ' in link:
            fail('The link should be one piece with no spaces. Try pasting it again.')
            continue
        if len(link) < 3:
            fail('That looks too short to be a group link. Try again.')
            continue
        ok(f'Using: {link}')
        return link


def ask_number(prompt_text, default, minimum=0, maximum=None):
    """Press Enter = recommended default. Re-asks politely on bad input."""
    while True:
        raw = input(f'{_in}{_cy} {prompt_text} {_grey}(press Enter = {default}){_n}\n{_cy}> {_n}').strip()
        if not raw:
            ok(f'Using {default}')
            return default
        try:
            val = int(raw.replace(',', ''))
        except ValueError:
            fail(f'"{raw}" is not a number. Type a number like {default}, or just press Enter.')
            continue
        if val < minimum:
            fail(f'Number must be {minimum} or more.')
            continue
        if maximum and val > maximum:
            fail(f'Number must be {maximum} or less.')
            continue
        return val


def ask_yesno(prompt_text, default_yes=True):
    """Enter = default. Accepts y/yes/n/no in any case."""
    while True:
        hint = 'Enter = yes' if default_yes else 'Enter = no'
        raw = input(f'{_in}{_cy} {prompt_text} {_grey}({hint}){_n}\n{_cy}> {_n}').strip().lower()
        if not raw:
            return default_yes
        if raw in ('y', 'yes'):
            return True
        if raw in ('n', 'no'):
            return False
        fail('Please type yes or no (or press Enter).')


def confirm_start(cfg):
    """The confirmation gate — shows everything, requires typed YES."""
    line()
    section('PLEASE CHECK EVERYTHING IS CORRECT')
    sleep_note = '  (safe)' if cfg['sleep'] >= 30 else '  (⚠ fast — ban risk!)'
    rows = [
        ('COPY members FROM',  cfg['source']),
        ('ADD members TO',     cfg['target']),
        ('Accounts to use',    str(len(cfg['accounts']))),
        ('Wait between adds',  f"{cfg['sleep']} seconds{sleep_note}"),
        ('Messages to scan',   str(cfg['limit']) if cfg['limit'] else 'ALL'),
    ]
    for label, val in rows:
        print(f'  {_w}{label:<22}{_n}: {_lg}{val}{_n}')
    line()

    while True:
        ans = input(f'{_ye}  Start now? Type {_w}YES{_ye} or {_w}NO{_n}: ').strip().lower()
        if ans in ('yes', 'y'):
            return True
        if ans in ('no', 'n'):
            return False
        fail('Please type YES or NO.')


# ============= ACCOUNT SELECTION =============

def select_accounts(accounts):
    """Shows the account list, asks for a range. Re-asks on bad input."""
    while True:
        info(f'Total {_w}{len(accounts)}{_lg} account(s) available:')
        line()
        for idx, acct in enumerate(accounts, start=1):
            name = acct.get('name') or acct.get('first_name') or 'Account'
            print(f'  {_w}{idx:>3}{_n}. {_lg}{name}{_n} {_grey}({acct.get("phone", "?")}){_n}')
        line()
        raw = input(f'{_in}{_cy} Which accounts? Type a range like {_w}1-10{_cy}, '
                    f'a number like {_w}3{_cy}, or {_w}all{_n}\n{_cy}> {_n}').strip().lower()

        if raw in ('', 'all', 'a'):
            ok(f'Using all {len(accounts)} account(s).')
            return accounts[:]

        try:
            if '-' in raw:
                parts = raw.split('-')
                start, end = int(parts[0].strip()), int(parts[1].strip())
                if not (1 <= start <= len(accounts)) or not (1 <= end <= len(accounts)):
                    fail(f'Range must be between 1 and {len(accounts)}. Try again.')
                    continue
                picked = accounts[end - 1:start][::-1] if start > end else accounts[start - 1:end]
            else:
                num = int(raw)
                if not (1 <= num <= len(accounts)):
                    fail(f'Number must be between 1 and {len(accounts)}. Try again.')
                    continue
                picked = [accounts[num - 1]]

            ok(f'Selected {len(picked)} account(s).')
            return picked
        except (ValueError, IndexError):
            fail(f'Did not understand "{raw}". Example: 1-10  or  3  or  all')


# ============= SETTINGS FLOW (with confirmation gate) =============

def collect_settings(accounts):
    """Guided setup. Re-runs from the top if the user rejects the summary."""
    while True:
        section('STEP 1/4 · SOURCE GROUP')
        info('This is the group we COPY members FROM.')
        source = ask_link('Paste the source group link or @username')

        section('STEP 2/4 · TARGET GROUP')
        info('This is YOUR group where members will be ADDED.')
        target = ask_link('Paste the target group link or @username')

        if source == target:
            warn('Source and target are the same group — this is usually a mistake.')
            if not ask_yesno('Continue anyway?', default_yes=False):
                continue

        section('STEP 3/4 · SPEED & SIZE')
        info('Waiting 30 seconds between adds keeps accounts safe.')
        sleep_t = ask_number('Seconds to wait between each add', default=30, minimum=0, maximum=3600)
        msg_limit = ask_number('How many messages to scan for members (0 = all)',
                               default=5000, minimum=0, maximum=2_000_000)

        section('STEP 4/4 · ACCOUNTS')
        to_use = select_accounts(accounts)

        cfg = {'source': source, 'target': target, 'sleep': sleep_t,
               'limit': msg_limit, 'accounts': to_use}

        if confirm_start(cfg):
            return source, target, sleep_t, msg_limit, to_use

        while True:
            ans = input(f'{_ye}  Type {_w}r{_ye} to re-enter settings, or {_w}q{_ye} to quit: {_n}').strip().lower()
            if ans in ('r', ''):
                break
            if ans in ('q', 'quit', 'exit'):
                fail('Cancelled by user.')
                sys.exit(0)


# ============= USER VALIDATION =============

def valid_user(uo):
    if not uo or not hasattr(uo, 'id') or uo.id is None:
        return False
    if getattr(uo, 'deleted', False):
        return False
    if getattr(uo, 'is_bot', False):
        return False
    if getattr(uo, 'is_self', False):
        return False
    return True


# ============= LINK HELPERS =============

def is_invite_link(link):
    return '/joinchat/' in link or 't.me/+' in link


def invite_hash(link):
    tail = link.rstrip('/').split('/')[-1]
    if tail.startswith('+'):
        tail = tail[1:]
    return tail if tail else None


# ============= SCRAPE =============

def print_progress_bar(current, total, ids):
    if total <= 0:
        total = current
    percent = min(100, int((current / total) * 100))
    filled = percent // 10
    bar = '█' * filled + '░' * (10 - filled)
    print(f'{_i}{_lg} [{bar}] {percent}% | {current}/{total} msgs | IDs:{ids} ')


def unified_scrape(client, source_entity, msg_limit, target=0, offset_id=0, exclude=None):
    """
    Sliced-baton scraper.
    Returns (ordered_user_list, last_msg_id, api_mode)
    """
    members = {}
    hidden_ids = set()
    msg_count = 0
    last_id = offset_id or 0
    ex = exclude if exclude is not None else set()

    def new_count():
        return sum(1 for uid in members if uid not in ex)

    print(f'{_i}{_lg} Checking if the member list is visible...')
    api_mode = False
    try:
        for u in client.get_participants(source_entity):
            if valid_user(u):
                members[u.id] = u
        if len(members) >= MIN_API_MEMBERS:
            ok(f'Found {len(members)} members directly!')
            return list(members.values()), last_id, True
        if members:
            info(f'Member list looks hidden (only {len(members)} visible). '
                 f'Scanning message history too...')
        else:
            info('Member list is hidden. Reading message history instead...')
    except ChatAdminRequiredError:
        info('Member list is hidden. Reading message history instead...')
    except Exception:
        info('Direct list unavailable. Reading message history instead...')

    print(f'{_i}{_lg} Scanning history (Limit: {_w}{msg_limit or "all"}{_lg} | '
          f'From offset: {_w}{offset_id or "newest"}{_lg})...')

    iter_limit = msg_limit if (msg_limit and msg_limit > 0) else None

    for msg in client.iter_messages(source_entity, limit=iter_limit, offset_id=(offset_id or 0)):
        if msg is None:
            continue
        msg_count += 1
        last_id = msg.id
        if msg_count % 500 == 0:
            print_progress_bar(msg_count, iter_limit or msg_count, len(members))

        if msg.sender and valid_user(msg.sender) and msg.sender.id not in members:
            members[msg.sender.id] = msg.sender

        # Reactions -> hidden reactor IDs
        if getattr(msg, 'reactions', None):
            try:
                for react in msg.reactions.results:
                    reactors = getattr(react, 'recent_reactors', None)
                    if reactors:
                        for reactor in reactors:
                            rid = getattr(reactor, 'user_id', None)
                            if rid and rid not in members:
                                hidden_ids.add(rid)
            except Exception:
                pass

        # Service actions (joins/invites) -> user IDs
        action = getattr(msg, 'action', None)
        if action is not None:
            try:
                users = getattr(action, 'users', None)
                if users:
                    if isinstance(users, (list, tuple)):
                        for u in users:
                            uid = u if isinstance(u, int) else getattr(u, 'id', None)
                            if uid and uid not in members:
                                hidden_ids.add(uid)
                    else:
                        uid = getattr(users, 'id', None)
                        if uid and uid not in members:
                            hidden_ids.add(uid)
                uid = getattr(action, 'user_id', None)
                if uid and uid not in members:
                    hidden_ids.add(uid)
            except Exception:
                pass

        if target and new_count() >= target:
            print(f'\n{_s}{_lg} Found enough users after {_w}{msg_count}{_lg} messages.')
            break

    print(f'\n{_i}{_lg} Scan done: {_w}{len(members)}{_lg} known users '
          f'& {_w}{len(hidden_ids)}{_lg} hidden IDs.')

    # Only pay for the expensive hidden-ID fetch if we're still short of target
    if hidden_ids and (not target or new_count() < target):
        info(f'Fetching {len(hidden_ids)} hidden user objects...')
        hidden_list = list(hidden_ids)
        try:
            fetched = client.get_entities(hidden_list)
            for u in fetched:
                if valid_user(u):
                    members[u.id] = u
        except Exception:
            for uid in hidden_list:
                if uid not in members:
                    try:
                        u = client.get_entity(uid)
                        if valid_user(u):
                            members[u.id] = u
                    except Exception:
                        pass

    return list(members.values()), last_id, api_mode


# ============= JOIN HELPER =============

def join_group(client, link, label, account_phone, account_name):
    """Returns: 'ok', 'skip_account', or 'fatal'."""
    try:
        if is_invite_link(link):
            h = invite_hash(link)
            if not h:
                fail(f'Invalid invite link: {link}')
                return 'skip_account'
            try:
                client(ImportChatInviteRequest(h))
                ok(f'{account_name} joined the {label} group')
            except UserAlreadyParticipantError:
                pass
            except InviteRequestSentError:
                fail(f'{account_name} join request is pending admin approval. '
                     f'Skipping this account until it is approved.')
                return 'skip_account'
            except (InviteHashExpiredError, ChannelPrivateError):
                fail(f'Account {account_phone} cannot join the {label} group. Skipping account...')
                return 'skip_account'
        else:
            try:
                client(JoinChannelRequest(link))
                ok(f'{account_name} joined the {label} group')
            except UserAlreadyParticipantError:
                pass
            except ChannelPrivateError:
                fail(f'Account {account_phone} cannot join private {label} channel. Skipping account...')
                return 'skip_account'
        return 'ok'
    except Exception:
        fail(f'Account {account_phone} failed to join {label}. Skipping account...')
        return 'skip_account'


# ============= MAIN =============

def main():
    print_banner()
    line()
    
    # --- License Check ---
    info('Checking License...')
    if not SecurityLock.check_license():
        fail("Access Denied. This script has not been authorized for this device.")
        sys.exit(1)
    line()

    accounts = load_accounts()
    if not accounts:
        fail(f'No profiles found in {DATABASE}!')
        sys.exit(1)

    os.makedirs(SESSIONS_DIR, exist_ok=True)

    # ---- State ----
    state = {
        'source_link': '', 'target_link': '', 'sleep_time': 30,
        'message_limit': 5000, 'account_index': 0, 'member_index': 0,
        'offset_current': 0, 'offset_next': 0,
        'failed_users': [], 'used_users': [], 'generic_fail_users': {},
    }

    failed_users = set()
    used_users = set()
    generic_fails = {}
    member_index_local = 0
    start_k = 0
    off_next = 0
    off_current = 0
    history_done = False

    # ---- Resume or fresh setup ----
    saved = load_session()
    if saved:
        if ask_yesno('A previous session was found. Continue it?', default_yes=True):
            saved_clean = {k: saved[k] for k in state if k in saved}
            state.update(saved_clean)
            source = state['source_link']
            target = state['target_link']
            sleep_t = state['sleep_time']
            msg_limit = state['message_limit']
            member_index_local = state.get('member_index', 0)
            start_k = state.get('account_index', 0)
            off_next = state.get('offset_next', 0)
            off_current = state.get('offset_current', 0)
            failed_users = set(state.get('failed_users', []))
            used_users = set(state.get('used_users', []))
            generic_fails = dict(state.get('generic_fail_users', {}))
            to_use = accounts[:]
        else:
            if os.path.exists(SESSION_FILE):
                os.remove(SESSION_FILE)
            source, target, sleep_t, msg_limit, to_use = collect_settings(accounts)
    else:
        source, target, sleep_t, msg_limit, to_use = collect_settings(accounts)

    # Guard: a saved index beyond the account list is meaningless — start fresh
    if start_k >= len(to_use):
        info('Saved session is already complete. Starting fresh settings.')
        start_k = 0
        member_index_local = 0
        off_next = 0
        off_current = 0
        source, target, sleep_t, msg_limit, to_use = collect_settings(accounts)

    state['source_link'] = source
    state['target_link'] = target
    state['sleep_time'] = sleep_t
    state['message_limit'] = msg_limit

    # ---- Budget split across accounts ----
    if msg_limit and msg_limit > 0:
        share = max(400, msg_limit // max(1, len(to_use)))
    else:
        share = 0

    print()
    info('Mode: SLICED-BATON SCRAPE (each account scans a different part, no repeats)')
    info(f'Source: {source}  |  Target: {target}')
    info(f'Accounts: {len(to_use)} | Sleep: {sleep_t}s | Adds per account: {PER_ACCOUNT_LIMIT}')
    info(f'Message budget: {msg_limit} -> per account: {share or "unlimited"}')
    line()

    def save_state():
        """Single save point — always saves every field, atomically."""
        state['account_index'] = current_k
        state['member_index'] = member_index_local
        state['offset_next'] = off_next
        state['offset_current'] = off_current
        state['failed_users'] = list(failed_users)
        state['used_users'] = list(used_users)
        state['generic_fail_users'] = generic_fails
        tmp = SESSION_FILE + '.tmp'
        try:
            with open(tmp, 'w') as f:
                json.dump(state, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, SESSION_FILE)
        except Exception as e:
            fail(f"CRITICAL: Could not save session state! Error: {e}")

    added_total = 0
    skipped_total = 0
    invalid_total = 0
    save_interval = 10
    save_counter = 0

    # ===== OUTER LOOP: PER ACCOUNT =====
    current_k = start_k
    while current_k < len(to_use):
        acct = to_use[current_k]
        phone = acct.get('phone', 'Unknown')

        client = TelegramClient(
            os.path.join(SESSIONS_DIR, phone),
            AI_API_ID,
            AI_API_HASH,
            device_model=acct.get('device_model', 'Samsung Galaxy A10'),
            system_version=acct.get('system_version', 'Android 9.0.0'),
            app_version=acct.get('app_version', '8.0.0')
        )

        try:
            client.start(phone=phone)
        except Exception:
            fail(f'Could not start session for {phone}. Skipping account.')
            current_k += 1
            continue

        acct_name = client.get_me().first_name or "User"
        print(f'\n{_p}{_grey} ===== Account {current_k + 1}/{len(to_use)}: '
              f'{_cy}{acct_name}{_lg} ({phone}) ====={_n}')

        # ---- Join source ----
        if join_group(client, source, 'source', phone, acct_name) != 'ok':
            client.disconnect()
            current_k += 1
            continue

        # ---- Join target ----
        status = join_group(client, target, 'target', phone, acct_name)
        if status == 'fatal':
            save_state()
            client.disconnect()
            sys.exit(1)
        if status != 'ok':
            client.disconnect()
            current_k += 1
            continue

        # ---- Resolve entities ----
        try:
            target_entity = client.get_entity(target)
            target_peer = client.get_input_entity(target)
        except Exception:
            fail(f'Could not resolve target for {phone}. Skipping account.')
            client.disconnect()
            current_k += 1
            continue

        # ---- Warm-up ----
        try:
            client.get_dialogs(limit=50)
        except Exception:
            pass

        # ---- Baton: assign slice (history mode) ----
        resumed_slice = (current_k == start_k and member_index_local > 0)
        off_for_me = off_current if resumed_slice else off_next
        if not resumed_slice:
            off_current = off_next

        try:
            source_entity = client.get_entity(source)
        except Exception:
            fail(f'{phone} could not open the source group. Skipping account.')
            client.disconnect()
            current_k += 1
            continue

        info(f'{acct_name} is scanning its own slice of the group...')
        try:
            user_list, last_id, api_mode = unified_scrape(
                client, source_entity, share,
                target=(PER_ACCOUNT_LIMIT + ADD_BUFFER),
                offset_id=off_for_me,
                exclude=(failed_users | used_users)
            )
        except FloodWaitError as e:
            warn(f'Telegram asked {acct_name} to wait {e.seconds}s. '
                 f'Stopped. Run again later to continue.')
            save_state()
            client.disconnect()
            current_k = len(to_use) + 1   # exit loop WITHOUT overwriting the save
            continue

        # Baton advance: next account continues AFTER this slice (history mode)
        off_next = last_id
        save_state()

        # ---- Build the work list ----
        if api_mode:
            base = current_k * PER_ACCOUNT_LIMIT
            window = user_list[base:base + PER_ACCOUNT_LIMIT]
            work = [u for u in window
                    if u.id not in failed_users and u.id not in used_users]
            print(f'{_s}{_lg} {acct_name} -- Member list visible: '
                  f'window [{base} -> {base + PER_ACCOUNT_LIMIT}] '
                  f'({len(work)} new users){_n}')
        else:
            work = [u for u in user_list
                    if u.id not in failed_users and u.id not in used_users]
            print(f'{_s}{_lg} {acct_name} -- Slice scanned: {_w}{len(user_list)}{_lg} users '
                  f'(baton at msg {_w}{last_id}){_n}')

        if not work:
            if api_mode:
                warn('This window had no new users. Next account takes the next window...')
                client.disconnect()
                current_k += 1
                continue
            if last_id == off_for_me:
                warn('Reached the end of the group history. Run complete.')
                history_done = True
                client.disconnect()
                break
            warn('This slice had no new users. Next account continues deeper...')
            client.disconnect()
            current_k += 1
            continue

        info(f'New users for this account: {len(work)}')

        print(f'{_p}{_grey} {acct_name} -- Starting to add users...{_n}')
        peerflood_count = 0
        success = 0
        stop_reason = None

        win_start = member_index_local if (api_mode and resumed_slice) else 0
        member_index_local = win_start

        # ===== INNER LOOP: PER USER (manual index so FloodWait retries same user) =====
        j = win_start
        end = len(work)

        while j < end:
            uo = work[j]
            member_index_local = j + 1

            if not api_mode and success >= PER_ACCOUNT_LIMIT:
                stop_reason = 'limit'
                break

            if not valid_user(uo):
                failed_users.add(uo.id)
                invalid_total += 1
                j += 1
                continue

            if uo.id in failed_users or uo.id in used_users:
                invalid_total += 1
                j += 1
                continue

            if generic_fails.get(uo.id, 0) >= MAX_GENERIC_FAILURES:
                failed_users.add(uo.id)
                skipped_total += 1
                j += 1
                continue

            if peerflood_count >= PEERFLOOD_TOLERANCE:
                save_state()
                stop_reason = 'peerflood'
                time.sleep(20)
                break

            try:
                client(InviteToChannelRequest(target_peer, [uo]))
                print(f'{_p}{_grey} {_cy}{acct_name}{_lg} -- '
                      f'{_cy}{uo.first_name or "Unknown"}{_lg} --> '
                      f'{_cy}{target_entity.title}{_n}')
                added_total += 1
                success += 1
                used_users.add(uo.id)
                generic_fails.pop(uo.id, None)
                j += 1

                save_counter += 1
                if save_counter >= save_interval:
                    save_state()
                    save_counter = 0

                if sleep_t > 0:
                    time.sleep(sleep_t)

            except PeerFloodError:
                peerflood_count += 1
                failed_users.add(uo.id)
                save_state()
                time.sleep(15)
                if peerflood_count >= PEERFLOOD_TOLERANCE:
                    stop_reason = 'peerflood'
                    break

            except (UserPrivacyRestrictedError, UserDeactivatedBanError, UserRestrictedError):
                failed_users.add(uo.id)
                skipped_total += 1
                j += 1

            except UserAlreadyParticipantError:
                used_users.add(uo.id)
                skipped_total += 1
                j += 1

            except FloodWaitError as e:
                if e.seconds > FLOODWAIT_THRESHOLD:
                    save_state()
                    stop_reason = 'floodwait'
                    break
                time.sleep(e.seconds + 1)

            except Exception:
                generic_fails[uo.id] = generic_fails.get(uo.id, 0) + 1
                skipped_total += 1
                save_counter += 1
                if save_counter >= save_interval:
                    save_state()
                    save_counter = 0
                j += 1

        # ---- Slice finished -> save + next account ----
        save_state()
        client.disconnect()

        if stop_reason == 'peerflood':
            warn(f'{acct_name} stopped after adding {success} users. '
                 f'Account needs rest — moving to the next one.')
        elif stop_reason == 'floodwait':
            warn(f'{acct_name} stopped after adding {success} users. '
                 f'Telegram says slow down — moving to the next one.')
        else:
            print(f'{_i}{_lg} {acct_name} -- Done. Added {_w}{success}{_lg} users.')

        if history_done:
            break

        if current_k < len(to_use) - 1:
            warn(f'Resting {INTER_ACCOUNT_DELAY}s before the next account...')
            time.sleep(INTER_ACCOUNT_DELAY)

        current_k += 1

    # ===== SUMMARY =====
    print(f'\n{_grey}-' * 50)
    print(f'{_s}{_lg} COMPLETE!{_n}')
    print(f'{_i}{_lg} Successfully added: {_w}{added_total}')
    print(f'{_i}{_lg} Skipped: {_w}{skipped_total}')
    print(f'{_i}{_lg} Invalid: {_w}{invalid_total}')
    print(f'{_i}{_lg} Total unique users handled: {_w}{len(used_users | failed_users)}')
    print(f'{_i}{_lg} Final baton (last msg scanned): {_w}{off_next}')

    if history_done and os.path.exists(SESSION_FILE):
        os.remove(SESSION_FILE)

    print(f'\n{_s}{_lg} All sessions closed.{_n}')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(f'\n{_e}{_r} Stopped by user.')
        print(f'{_i}{_lg} Session saved — you can continue next time!{_n}')
        sys.exit(0)
    except SystemExit:
        raise

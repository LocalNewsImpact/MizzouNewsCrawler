"""
JA3 search script for running inside extraction pod
- Tries targeted removals of suspect TLS extensions (65037 ECH, 17513, 65281)
- Falls back to single/pair/triple/quads removals from full extension list, capped by attempt limit
- On match, writes /tmp/ja3_match.json and prints details
"""
import itertools
import json
import sys
import time
from tls_client import Session

TARGET = "1a35fa7b8bc1f11a7ed5e4f1cda22c86"
CLIENTS = ["chrome_116", "chrome_120", "chrome_110", "chrome_107", "chrome_104", "chrome_101"]
SUSPECTS = ['65037', '17513', '65281']
MAX_ATTEMPTS = 2000
MAX_REMOVE = 4
PROGRESS_EVERY = 50

attempts = 0
found = None

print(f"Starting JA3 search (max attempts={MAX_ATTEMPTS})")
start_time = time.time()
for client in CLIENTS:
    print(f"\n== client: {client} ==")
    session_base = Session(client_identifier=client, random_tls_extension_order=False)
    try:
        r = session_base.get('https://tools.scrapfly.io/api/fp/ja3')
        base = r.json()
    except Exception as e:
        print("base fetch error:", e)
        continue
    base_digest = base.get('ja3_digest')
    base_ja3 = base.get('ja3')
    print('base_digest:', base_digest)
    print('base_ja3:', base_ja3)
    if base_digest == TARGET:
        print('Base matches target for client', client)
        found = (client, base_ja3, base)
        break

    parts = base_ja3.split(',')
    if len(parts) != 5:
        print('unexpected ja3 format, skipping')
        continue
    ver, ciphers, exts, curves, points = parts
    ext_list = exts.split('-') if exts else []

    # 1) targeted suspects combinations
    present_suspects = [s for s in SUSPECTS if s in ext_list]
    print('suspects present:', present_suspects)

    # try all combinations of present suspects first (small)
    for rcount in range(1, len(present_suspects) + 1):
        for rem_set in itertools.combinations(present_suspects, rcount):
            attempts += 1
            cand_exts = [e for e in ext_list if e not in rem_set]
            cand_str = '-'.join(cand_exts) if cand_exts else ''
            cand = ','.join([ver, ciphers, cand_str, curves, points])
            try:
                s = Session(client_identifier=client, ja3_string=cand, random_tls_extension_order=False)
                jr = s.get('https://tools.scrapfly.io/api/fp/ja3').json()
            except Exception as e:
                jr = {'error': str(e)}
            digest = jr.get('ja3_digest')
            if attempts % PROGRESS_EVERY == 0:
                print('attempts', attempts, 'last_digest', digest)
            if digest == TARGET:
                found = (client, cand, jr)
                break
            if attempts >= MAX_ATTEMPTS:
                break
        if found or attempts >= MAX_ATTEMPTS:
            break
    if found or attempts >= MAX_ATTEMPTS:
        break

    # 2) broad search by removing up to MAX_REMOVE extensions (combinatorial, capped)
    if not found and len(ext_list) > 0:
        print(f'Starting broader removals up to {MAX_REMOVE} (capped attempts total={MAX_ATTEMPTS})')
        for rcount in range(1, min(MAX_REMOVE, len(ext_list)) + 1):
            for rem in itertools.combinations(range(len(ext_list)), rcount):
                attempts += 1
                cand_exts = [e for i, e in enumerate(ext_list) if i not in rem]
                cand_str = '-'.join(cand_exts) if cand_exts else ''
                cand = ','.join([ver, ciphers, cand_str, curves, points])
                try:
                    s = Session(client_identifier=client, ja3_string=cand, random_tls_extension_order=False)
                    jr = s.get('https://tools.scrapfly.io/api/fp/ja3').json()
                except Exception as e:
                    jr = {'error': str(e)}
                digest = jr.get('ja3_digest')
                if attempts % PROGRESS_EVERY == 0:
                    print('attempts', attempts, 'last_digest', digest)
                if digest == TARGET:
                    found = (client, cand, jr)
                    break
                if attempts >= MAX_ATTEMPTS:
                    break
            if found or attempts >= MAX_ATTEMPTS:
                break
    if found or attempts >= MAX_ATTEMPTS:
        break

print('\n--- finished search ---')
print('total attempts:', attempts)
if found:
    client, cand_ja3, jr = found
    print('FOUND MATCH! client:', client)
    print('ja3:', cand_ja3)
    print('server response:', json.dumps(jr, indent=2)[:2000])
    # test HTTP/2 with target settings
    s_test = Session(client_identifier=client, ja3_string=cand_ja3, h2_settings={"1":65536, "2":0, "4":6291456, "6":262144}, h2_settings_order=["1","2","4","6"], random_tls_extension_order=False)
    ak = s_test.get('https://tools.scrapfly.io/api/fp/akamai').json()
    print('\nakamai:', json.dumps(ak, indent=2))
    out = {'client': client, 'ja3': cand_ja3, 'ja3_server': jr, 'akamai': ak}
    with open('/tmp/ja3_match.json', 'w') as fh:
        fh.write(json.dumps(out, indent=2))
    print('\nSaved match to /tmp/ja3_match.json')
    sys.exit(0)
else:
    print('No match found within attempt limit')
    sys.exit(2)

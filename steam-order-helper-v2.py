import csv
import logging
import logging.config
import math

import requests
import time

from bs4 import BeautifulSoup
from datetime import datetime
from decouple import Config, RepositoryEnv
from enum import Enum
from howlongtobeatpy import HowLongToBeat
from steam_web_api import Steam

class GameSelection(Enum):
    ALL = 1
    STEAM_ONLY = 2
    OTHERS_ONLY = 3

class ProtonCompatibilityMode(Enum):
    NONE = 1
    SOFT = 2
    HARD = 3

GAME_SELECTION = GameSelection.ALL
FORCE_DATA_UPDATE = False
LIMIT = 550
PROTON_COMPATIBILITY = ProtonCompatibilityMode.HARD
UNIQUE_LOGS = False

# Setup logger (global)
logging.config.dictConfig({'version': 1, 'disable_existing_loggers': True})
logger = logging.getLogger(__name__)

# Snipped from 'ProtonDB-to-Steam-Library' GitHub
class ProtonDBError(Exception):
    pass

# Source GPT-5 mini
def fetch_metacritic_scores(metacritic_id_or_qid: str):
    """
    Inputs:
      - metacritic_id_or_qid: either a Metacritic slug/ID (e.g. 'uplink') or a Wikidata QID.
        If a QID is provided, the function expects the Metacritic ID to be the Wikidata
        'Metacritic ID' value (property P1258) already extracted by the caller; if you only
        have a QID, resolve P1258 first (Wikidata SPARQL) and pass the resulting slug here.
    Returns:
      {"metascore": int|None, "userscore": float|None, "url": str|None}
    """
    # If input looks like a Wikidata QID, caller should resolve P1258 first.
    slug = metacritic_id_or_qid.strip()
    # Common Metacritic URL patterns: /game/<platform>/<slug> or /game/<slug>
    # Best-effort: try likely platforms list if slug alone doesn't work.
    platforms_to_try = ["pc", "mac", "ios", "switch", "ps4", "ps5", "xbox-one", "xbox-series-x"]
    tried_urls = []

    def parse_page(text, url):
        soup = BeautifulSoup(text, "html.parser")
        # Try JSON-LD first
        ld = soup.find("script", type="application/ld+json")
        if ld:
            try:
                import json
                obj = json.loads(ld.string)
                # object may be dict or list; look for aggregateRating
                if isinstance(obj, list):
                    for o in obj:
                        if o.get("@type") == "VideoGame" or o.get("aggregateRating"):
                            obj = o
                            break
                ar = obj.get("aggregateRating") or {}
                metascore = ar.get("ratingValue")
                userscore = ar.get("reviewCount")  # not always userscore; ignore if wrong
                # Metacritic JSON-LD often misses userscore; still try HTML fallback
                ms = int(metascore) if metascore is not None else None
                us = float(userscore) if userscore is not None else None
                return {"metascore": ms, "userscore": us, "url": url}
            except Exception:
                pass
        # HTML fallback: look for metascore and userscore nodes
        # Metascore: <div class="metascore_w xlarge game positive">75</div>
        meta_node = soup.select_one(".metascore_w.xlarge") or soup.select_one(".metascore_w")
        user_node = soup.select_one(".userscore_wrap .metascore_w") or soup.select_one(".userscore")
        metascore = None
        userscore = None
        if meta_node and meta_node.text.strip().isdigit():
            metascore = int(meta_node.text.strip())
        # userscore can be like "8.3" or "tbd"
        if user_node:
            us_text = user_node.text.strip()
            try:
                userscore = float(us_text)
            except Exception:
                userscore = None
        return {"metascore": metascore, "userscore": userscore, "url": url}

    # Try direct slug as-if it's already the full path (e.g., 'uplink')
    # Try common patterns
    for p in [""] + platforms_to_try:
        if p:
            url = f"https://www.metacritic.com/game/{p}/{slug}"
        else:
            # try generic /game/<slug>
            url = f"https://www.metacritic.com/game/{slug}"
        tried_urls.append(url)
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                return parse_page(r.text, url)
            # Metacritic blocks some requests with 403; skip to next
        except requests.RequestException:
            continue

    # If not found by slug, try search page (site search) using Metacritic search endpoint
    search_url = f"https://www.metacritic.com/search/game/{slug}/results"
    tried_urls.append(search_url)
    try:
        r = requests.get(search_url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            first_link = soup.select_one(".result_title a")
            if first_link and first_link.get("href"):
                url = "https://www.metacritic.com" + first_link["href"]
                r2 = requests.get(url, headers=HEADERS, timeout=10)
                if r2.status_code == 200:
                    return parse_page(r2.text, url)
    except requests.RequestException:
        pass

    return {"metascore": None, "userscore": None, "url": None}

# Source: GPT-5 mini
def get_app_reviews(appid):
    url = f"https://store.steampowered.com/appreviews/{appid}?json=1&language=all&review_type=all&purchase_type=all"
    r = requests.get(url, timeout=10).json()
    qs = r.get("query_summary", {})
    pos = qs.get("total_positive", 0)
    n = qs.get("total_reviews", 0)
    return pos, n

def get_hltb_stats(hltb_id):
    return HowLongToBeat().search_from_id(int(hltb_id))

# Snipped from 'ProtonDB-to-Steam-Library' GitHub
def get_protondb_rating(app_id):
    protondb_api_result = requests.get("https://www.protondb.com/api/v1/reports/summaries/{}.json".format(app_id))
    if protondb_api_result.status_code != 200:
        raise ProtonDBError()
    protondb_api_json = protondb_api_result.json()
    # use trendingTier as this reflects a more up-to-date rating rather than an all-time rating
    return protondb_api_json["trendingTier"]

# Source: GPT-5 mini, modified
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "steam-order-helper-v2/1.0 (example@example.com)"}
def get_wikidata_properties_from_qids(qids):
    labels = {}
    hltb_ids = {}
    metacritic_ids = {}
    qids_formatted = f"{' '.join(['wd:' + str(q) for q in qids])}"
    sparql = f"""
        SELECT ?item ?itemLabel ?hltb ?metacritic WHERE {{
          VALUES ?item {{ {qids_formatted} }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
          OPTIONAL {{ ?item rdfs:label ?itemLabel FILTER(LANG(?itemLabel) = "en"). }}
          OPTIONAL {{ ?item wdt:P2816 ?hltb. }}
          OPTIONAL {{ ?item wdt:P12054 ?metacritic. }}
        }}
        ORDER BY xsd:integer(?qid)
        """
    resp = requests.get(WIKIDATA_SPARQL_URL, params={"format": "json", "query": sparql}, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    bindings = data.get("results", {}).get("bindings", [])
    if not bindings:
        return None
    for b in bindings:
        item_url = b.get("item", {}).get("value")
        qid = item_url.rsplit("/", 1)[-1] if item_url else None
        labels[qid] = b.get("itemLabel", {}).get("value")
        hltb_ids[qid] = b.get("hltb", {}).get("value")
        metacritic_ids[qid] = b.get("metacritic", {}).get("value")
    return labels, hltb_ids, metacritic_ids

# Source: GPT-5 mini, modified
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "steam-order-helper-v2/1.0 (example@example.com)"}
def get_wikidata_properties_from_steam_appids(appids):
    qids = {}
    hltb_ids = {}
    metacritic_ids = {}
    appids_formatted = f"{' '.join(['"' + str(a) + '"' for a in appids])}"
    sparql = f"""
    SELECT ?item ?appid ?hltb ?metacritic WHERE {{
      VALUES ?appid {{ {appids_formatted} }}
      ?item wdt:P1733 ?appid .
      OPTIONAL {{ ?item wdt:P2816 ?hltb. }}
      OPTIONAL {{ ?item wdt:P12054 ?metacritic. }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    ORDER BY xsd:integer(?appid)
    """
    resp = requests.get(WIKIDATA_SPARQL_URL, params={"format": "json", "query": sparql}, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    bindings = data.get("results", {}).get("bindings", [])
    if not bindings:
        return None
    #logger.debug('Steam AppID, QID, HLTB ID, Metacritic ID')
    for b in bindings:
        appid = b.get("appid", {}).get("value")
        item_url = b.get("item", {}).get("value")
        qids[appid] = item_url.rsplit("/", 1)[-1] if item_url else None
        hltb_ids[qids[appid]] = b.get("hltb", {}).get("value")
        metacritic_ids[qids[appid]] = b.get("metacritic", {}).get("value")
        #logger.debug(f'{appid}, {qids[appid]}, {hltb_ids[qids[appid]]}, {metacritic_ids[qids[appid]]}')
    return qids, hltb_ids, metacritic_ids

def isfloat(s):
    try:
        float(s)
        return True
    except ValueError:
        return False

# Source: GPT-5 mini
def wilson_lower(pos, n, z=1.96):
    if n == 0: return 0
    p = pos / n
    z2 = z*z
    denom = 1 + z2/n
    num = p + z2/(2*n) - z * math.sqrt((p*(1-p) + z2/(4*n)) / n)
    return num / denom

# Main Script
# TODO Fix bindings in wikidata to fix multiple entries
# TODO Add logs and output directory check & creation
if __name__=="__main__":

    games = []

    # Begin timer for overall runtime tracker and open log
    scriptStartTime = time.time()
    log_filename_postfix = f'_{datetime.now().strftime('%Y%m%d-%H%M%S')}' if UNIQUE_LOGS else ''
    logging.basicConfig(filename=f'logs/steam-order-helper-v2{log_filename_postfix}.log', filemode='w', format='%(asctime)s %(levelname)-8s %(message)s', level=logging.DEBUG, datefmt='%Y-%m-%d %H:%M:%S')
    logger.info(f'Script started')
    logger.info(f'\tGame Selection: {GAME_SELECTION.name}')
    logger.info(f'\tForce Data Update: {FORCE_DATA_UPDATE}')
    logger.info(f'\tProton Compatibility: {PROTON_COMPATIBILITY.name}')

    # Setup configuration file
    DOTENV_FILE = '.env'
    env_config = Config(RepositoryEnv(DOTENV_FILE))

    # Open up list.csv to use as a data cache
    cache = {}
    with open('output/list.csv', 'r', newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if row['qid'] not in cache.keys():
                cache[row['qid']] = row

    # Open up manual_fields.csv
    manual_fields = {}
    with open('input/manual_fields.csv', 'r', newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if row['qid'] not in manual_fields.keys():
                manual_fields[row['qid']] = row

    # Initialize some shared dictionaries
    game_list = []
    qids = {}
    hltb_ids = {}
    metacritic_ids = {}

    if GAME_SELECTION == GameSelection.ALL or GAME_SELECTION == GameSelection.STEAM_ONLY:
        # Setup Steam connection
        steam_api_key = env_config.get('STEAM_API_KEY')
        steam = Steam(steam_api_key)
        logger.info('Steam API connection initialized')

        # Retrieve user's steamid
        steamid = steam.users.search_user('gschive')['player']['steamid']
        logger.info(f'SteamID: {steamid}')

        # Retrieve user's owned games
        game_list = steam.users.get_owned_games(steamid)['games']
        logger.info(f'Steam Owned Games Count: {len(game_list)}')

        # Retrieve the Wikidata properties in a single query
        qids, hltb_ids, metacritic_ids = get_wikidata_properties_from_steam_appids([game['appid'] for game in game_list])

        # Retrieve the overrides
        qid_overrides_by_appid = {}
        qid_overrides_by_qid = {}
        hltb_overrides_by_appid = {}
        hltb_overrides_by_qid = {}
        metacritic_overrides_by_appid = {}
        metacritic_overrides_by_qid = {}
        with open('input/overrides.csv', 'r', newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if row['appid'] != '':
                    qid_overrides_by_appid[row['appid']] = row['qid_override']
                    hltb_overrides_by_appid[row['appid']] = row['hltb_override']
                    metacritic_overrides_by_appid[row['appid']] = row['metacritic_override']
                if row['qid'] != '':
                    qid_overrides_by_qid[row['qid']] = row['qid_override']
                    hltb_overrides_by_qid[row['qid']] = row['hltb_override']
                    metacritic_overrides_by_qid[row['qid']] = row['metacritic_override']

    if GAME_SELECTION == GameSelection.ALL or GAME_SELECTION == GameSelection.OTHERS_ONLY:
        # Retrieve the list of other games (non-Steam, emulated, etc.)
        other_games = []
        with open('input/other_games.csv', 'r', newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                other_games.append({'qid': row['qid'], 'name': None, 'playtime': int(row['playtime_minutes'])})

        # Retrieve the properties for the other games from Wikidata
        labels, other_hltb_ids, other_metacritic_ids = get_wikidata_properties_from_qids([o['qid'] for o in other_games])
        for o in other_games:
            o['name'] = labels[o['qid']]
            hltb_ids[o['qid']] = other_hltb_ids[o['qid']]
            metacritic_ids[o['qid']] = other_metacritic_ids[o['qid']]

        # Add other games to master game list
        for o in other_games:
            game_list.append(o)

    count = 0
    for game in game_list:
        # Debug break for faster testing
        if count >= LIMIT:
            break

        games.append({})

        # Add basic info from Steam to master list
        if 'appid' in game.keys():
            games[-1]['qid'] = qids[str(game['appid'])] if str(game['appid']) in qids.keys() else None
            games[-1]['name'] = game['name']
            appid = game['appid']
            playtime = game['playtime_forever']
        # Add basic info from other games to master list
        else:
            games[-1]['qid'] = game['qid']
            games[-1]['name'] = game['name']
            appid = None
            playtime = game['playtime']

        if 'appid' in game.keys():
            # Apply QID overrides
            old_qid = games[-1]['qid']
            games[-1]['qid'] = qid_overrides_by_qid[str(games[-1]['qid'])] if str(games[-1]['qid']) in qid_overrides_by_qid.keys() else qid_overrides_by_appid[str(appid)] if str(appid) in qid_overrides_by_appid.keys() else games[-1]['qid']
            if old_qid != games[-1]['qid']:
                logger.debug(f'Updating QID for {games[-1]['name']} from {old_qid} to {games[-1]['qid']}')

            # Update HLTB and Metacritic IDs after QID overrides
            if str(appid) in qid_overrides_by_appid.keys() or old_qid in qid_overrides_by_qid.keys():
                logger.debug(f'Updating HLTB and Metacritic IDs for QID {games[-1]['qid']}')
                labels, hltb_ids_updates, metacritic_ids_updates = get_wikidata_properties_from_qids([games[-1]['qid']])
                hltb_ids[games[-1]['qid']] = hltb_ids_updates[games[-1]['qid']]
                metacritic_ids[games[-1]['qid']] = metacritic_ids_updates[games[-1]['qid']]

            # Apply HLTB overrides
            if str(appid) in hltb_overrides_by_appid.keys() and hltb_overrides_by_appid[str(appid)] != '':
                logger.debug(f'Applying HLTB override for QID {games[-1]['qid']}')
                hltb_ids[games[-1]['qid']] = hltb_overrides_by_appid[str(appid)]
            elif old_qid in hltb_overrides_by_qid.keys() and hltb_overrides_by_qid[old_qid] != '':
                logger.debug(f'Applying HLTB override for QID {games[-1]['qid']}')
                hltb_ids[games[-1]['qid']] = hltb_overrides_by_qid[old_qid]

            # Apply Metacritic overrides
            if str(appid) in metacritic_overrides_by_appid.keys() and metacritic_overrides_by_appid[str(appid)] != '':
                logger.debug(f'Applying Metacritic override for QID {games[-1]['qid']}')
                metacritic_ids[games[-1]['qid']] = metacritic_overrides_by_appid[str(appid)]
            elif old_qid in metacritic_overrides_by_qid.keys() and metacritic_overrides_by_qid[old_qid] != '':
                logger.debug(f'Applying Metacritic override for QID {games[-1]['qid']}')
                metacritic_ids[games[-1]['qid']] = metacritic_overrides_by_qid[old_qid]

        # Log the various identifiers
        logger.debug(f'{appid}, {games[-1]['name']}, {games[-1]['qid']}, '
                     f'{hltb_ids[games[-1]['qid']] if games[-1]['qid'] is not None and games[-1]['qid'] in hltb_ids.keys() else None}, '
                     f'{metacritic_ids[games[-1]['qid']] if games[-1]['qid'] is not None and games[-1]['qid'] in metacritic_ids.keys() else None}')

        if 'appid' in game.keys():
            # Retrieve favorability (already normalized) and apply Wilson score interval
            if games[-1]['qid'] in cache.keys() and not FORCE_DATA_UPDATE:
                games[-1]['favorability'] = float(cache[games[-1]['qid']]['favorability']) if isfloat(cache[games[-1]['qid']]['favorability']) else cache[games[-1]['qid']]['favorability']
            else:
                pos, n = get_app_reviews(appid)
                games[-1]['favorability'] = wilson_lower(pos, n)
        else:
            # For non-Steam games, substitute the userscore from Metacritic for favorability, if available, if the scraper works
            games[-1]['favorability'] = 'n/a'

        # Retrieve critic scores and normalize
        if games[-1]['qid'] in cache.keys() and not FORCE_DATA_UPDATE:
            games[-1]['critic_score'] = float(cache[games[-1]['qid']]['critic_score'])
        else:
            if metacritic_ids[games[-1]['qid']] is not None:
                metacritic_data = fetch_metacritic_scores(metacritic_ids[games[-1]['qid']])
                games[-1]['critic_score'] = metacritic_data['metascore'] / 100 if metacritic_data['metascore'] is not None else 0
            else:
                games[-1]['critic_score'] = 0

        if 'appid' in game.keys():
            # Retrieve ProtonDB ratings and normalize
            if games[-1]['qid'] in cache.keys() and not FORCE_DATA_UPDATE:
                games[-1]['protonDB_rating'] = float(cache[games[-1]['qid']]['protonDB_rating']) if isfloat(cache[games[-1]['qid']]['protonDB_rating']) else cache[games[-1]['qid']]['protonDB_rating']
            else:
                try:
                    rating = get_protondb_rating(appid)
                    games[-1]['protonDB_rating'] = 1.0 if rating == 'platinum' else 0.9 if rating == 'gold' else 0.75 if rating == 'silver' else 0.5 if rating == 'bronze' else 0.0
                except ProtonDBError:
                    logger.warning(f'{games[-1]['name']} not found in ProtonDB')
                    games[-1]['protonDB_rating'] = 0.0
        else:
            games[-1]['protonDB_rating'] = 'n/a'

        # Retrieve "Personal Interest"
        if games[-1]['qid'] in manual_fields.keys():
            games[-1]['personal_interest'] = int(manual_fields[games[-1]['qid']]['personal_interest'])
        else:
            logger.warning(f'QID {games[-1]['qid']} not found in manual_fields.csv')
            games[-1]['personal_interest'] = 0

        # Retrieve HLTB "Main + Extras", calculate completion percentage
        if games[-1]['qid'] in cache.keys() and not FORCE_DATA_UPDATE:
            games[-1]['completion'] = float(cache[games[-1]['qid']]['completion']) if isfloat(cache[games[-1]['qid']]['completion']) else cache[games[-1]['qid']]['completion']
        else:
            if games[-1]['qid'] in hltb_ids.keys() and hltb_ids[games[-1]['qid']] is not None:
                hltb_stats = get_hltb_stats(hltb_ids[games[-1]['qid']])
                if hltb_stats is not None:
                    games[-1]['completion'] = min(1, ((playtime / 60) / hltb_stats.main_extra) if hltb_stats.main_extra != 0 and hltb_stats.main_extra is not None else 0)
                else:
                    logger.warning(f'QID {games[-1]['qid']} has a HLTB result of None')
                    games[-1]['completion'] = 0
            elif games[-1]['qid'] in hltb_ids.keys():
                logger.warning(f'QID {games[-1]['qid']} has a HLTB ID of None')
                games[-1]['completion'] = 0
            else:
                logger.warning(f'QID {games[-1]['qid']} has no HLTB ID')
                games[-1]['completion'] = 0

        # Combine weightings with previous data into weighted values
        if 'appid' in game.keys():
            if PROTON_COMPATIBILITY == ProtonCompatibilityMode.NONE or PROTON_COMPATIBILITY == ProtonCompatibilityMode.HARD:
                games[-1]['favorability_weighted'] = games[-1]['favorability'] * 0.40           # Favorability
                games[-1]['critic_score_weighted'] = games[-1]['critic_score'] * 0.27           # Critic Scores
                games[-1]['protonDB_rating_weighted'] = 'n/a'                                   # ProtonDB Rating (weighted value not used)
                games[-1]['personal_interest_weighted'] = games[-1]['personal_interest'] * 0.20 # Personal Interest
                games[-1]['completion_weighted'] = games[-1]['completion'] * 0.13               # Completion
            else:
                games[-1]['favorability_weighted'] = games[-1]['favorability'] * 0.30           # Favorability
                games[-1]['critic_score_weighted'] = games[-1]['critic_score'] * 0.20           # Critic Scores
                games[-1]['protonDB_rating_weighted'] = games[-1]['protonDB_rating'] * 0.25     # ProtonDB Rating
                games[-1]['personal_interest_weighted'] = games[-1]['personal_interest'] * 0.15 # Personal Interest
                games[-1]['completion_weighted'] = games[-1]['completion'] * 0.10               # Completion
        else:
            games[-1]['favorability_weighted'] = 'n/a'                                      # Favorability
            games[-1]['critic_score_weighted'] = games[-1]['critic_score'] * 0.57           # Critic Scores
            games[-1]['protonDB_rating_weighted'] = 'n/a'                                   # ProtonDB Rating (weighted value not used)
            games[-1]['personal_interest_weighted'] = games[-1]['personal_interest'] * 0.43 # Personal Interest
            games[-1]['completion_weighted'] = 'n/a'                                        # Completion

        # Combine weighted values into final score

        # Filter out Completed and Ignore games (Pass #2 with overridden QIDs)
        if games[-1]['qid'] in manual_fields.keys() and (int(manual_fields[games[-1]['qid']]['completed']) == 1 or int(manual_fields[games[-1]['qid']]['ignore']) == 1):
            logger.debug(f'Zeroing \'final_score\' for QID {games[-1]['qid']}, Reason: Marked as Completed or Ignore')
            games[-1]['final_score'] = 0
        else:
            if 'appid' in game.keys():
                if PROTON_COMPATIBILITY == ProtonCompatibilityMode.HARD:
                    games[-1]['final_score'] = games[-1]['protonDB_rating'] * (games[-1]['favorability_weighted'] + games[-1]['critic_score_weighted'] + games[-1]['personal_interest_weighted'] + games[-1]['completion_weighted'])
                elif PROTON_COMPATIBILITY == ProtonCompatibilityMode.SOFT:
                    games[-1]['final_score'] = games[-1]['favorability_weighted'] + games[-1]['critic_score_weighted'] + games[-1]['protonDB_rating_weighted'] + games[-1]['personal_interest_weighted'] + games[-1]['completion_weighted']
                else:
                    games[-1]['final_score'] = games[-1]['favorability_weighted'] + games[-1]['critic_score_weighted'] + games[-1]['personal_interest_weighted'] + games[-1]['completion_weighted']
            else:
                games[-1]['final_score'] = games[-1]['critic_score_weighted'] + games[-1]['personal_interest_weighted']

        # Sleep 1s to prevent rate-limiting
        if games[-1]['qid'] not in cache.keys() or FORCE_DATA_UPDATE:
            time.sleep(1)

        # Debug print to see master games list
        print(f'{len(games)} / {min(LIMIT, len(game_list))}: {games[-1]}')

        # Debug counter for faster testing
        count += 1

    logger.info(f'Total Game Count: {len(games)}')

    # Write results to CSV file
    with open('output/list.csv', 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        # Save headers
        writer.writerow(games[0].keys())
        # Save data
        for g in games:
            writer.writerow(g.values())
        logger.info(f'Data exported to "{csvfile.name}"')

    # Print/log out script execution time
    scriptFinishTime = time.time()
    print(f'\nScript Execution Time: {(scriptFinishTime - scriptStartTime):.2f} seconds')
    logger.info(f'Script Execution Time: {(scriptFinishTime - scriptStartTime):.2f} seconds')

    # Write final log entry
    logger.info(f'Script finished')

    exit()
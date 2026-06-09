import csv
import logging
import math
import requests
import time

from bs4 import BeautifulSoup
from datetime import datetime
from decouple import Config, RepositoryEnv
from howlongtobeatpy import HowLongToBeat
from steam_web_api import Steam

FORCE_DATA_UPDATE = False
LIMIT = 5
PROTON_HARD_COMPATIBILITY = True

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
    result = HowLongToBeat().search_from_id(int(hltb_id))
    if result == None:
        print(f'HLTB ID {hltb_id} result is NoneType')
        return 999999
    else:
        return result.main_extra

# Source: GPT-5 mini, modified
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "steam-order-helper-v2/1.0 (example@example.com)"}
def get_wikidata_properties_from_steam_appids(appids):
    qids = {}
    hltb_ids = {}
    appids_formatted = f"{' '.join(['"' + str(a) + '"' for a in appids])}"
    #print(appids_formatted)
    sparql = f"""
    SELECT ?item ?qid ?appid ?hltb ?metacritic_id WHERE {{
      VALUES ?appid {{ {appids_formatted} }}
      ?item wdt:P1733 ?appid .
      OPTIONAL {{ ?item wdt:P1733 ?appid. }}
      OPTIONAL {{ ?item wdt:P2816 ?hltb. }}
      OPTIONAL {{ ?item wdt:P12054 ?metacritic_id. }}
    }}
    ORDER BY xsd:integer(?appid)
    """
    #print(sparql)
    resp = requests.get(WIKIDATA_SPARQL_URL, params={"format": "json", "query": sparql}, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    #print(data)
    bindings = data.get("results", {}).get("bindings", [])
    if not bindings:
        return None
    for b in bindings:
        appid = b.get("appid", {}).get("value")
        item_url = b.get("item", {}).get("value")
        qids[appid] = item_url.rsplit("/", 1)[-1] if item_url else None
        hltb_ids[appid] = b.get("hltb", {}).get("value")
        print(appid, b.get("metacritic_id", {}).get("value"))
    return qids, hltb_ids

# Snipped from 'ProtonDB-to-Steam-Library' GitHub
def get_protondb_rating(app_id):
    protondb_api_result = requests.get("https://www.protondb.com/api/v1/reports/summaries/{}.json".format(app_id))
    if protondb_api_result.status_code != 200:
        raise ProtonDBError()
    protondb_api_json = protondb_api_result.json()
    # use trendingTier as this reflects a more up-to-date rating rather than an all-time rating
    return protondb_api_json["trendingTier"]

# Source: GPT-5 mini
def wilson_lower(pos, n, z=1.96):
    if n == 0: return 0
    p = pos / n
    z2 = z*z
    denom = 1 + z2/n
    num = p + z2/(2*n) - z * math.sqrt((p*(1-p) + z2/(4*n)) / n)
    return num / denom

# Main Script
# TODO Overhaul and consistent handling of non-existant entries and multiple entries
# TODO Add Wikidata QID indexing and overrides
# TODO Add in emulator games capability
if __name__=="__main__":

    games = []

    # Setup logger
    logger = logging.getLogger(__name__)
    logging.basicConfig(filename='steam-order-helper-v2.log', level=logging.INFO, filemode='w')

    # Begin timer for overall runtime tracker
    scriptStartTime = time.time()
    logger.info(f'Started at {datetime.fromtimestamp(scriptStartTime)}')

    # Setup configuration file
    DOTENV_FILE = '.env'
    env_config = Config(RepositoryEnv(DOTENV_FILE))

    # Setup Steam connection
    steam_api_key = env_config.get('STEAM_API_KEY')
    steam = Steam(steam_api_key)
    logger.info('Steam API connection initialized.')

    # Retrieve user's steamid
    steamid = steam.users.search_user('gschive')['player']['steamid']
    logger.info(f'SteamID: {steamid}')

    # Open up list.csv to use as a data cache
    cache = {}
    with open('list.csv', 'r', newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            cache[row['appid']] = row

    # Retrieve user's owned games
    owned_games = steam.users.get_owned_games(steamid)['games']

    # Retrieve the Wikidata properties in a reduced set of queries
    qids, hltb_ids = get_wikidata_properties_from_steam_appids([game['appid'] for game in owned_games])

    count = 0
    for game in owned_games:
        # Debug break for faster testing
        if count >= LIMIT:
            break

        games.append({})

        # Add basic info from Steam to master list
        games[-1]['qid'] = qids[str(game['appid'])] if str(game['appid']) in qids.keys() else None
        games[-1]['appid'] = game['appid']
        games[-1]['name'] = game['name']
        playtime = game['playtime_forever']

        # Retrieve favorability (already normalized) and apply Wilson score interval
        if str(games[-1]['appid']) in cache.keys() and not FORCE_DATA_UPDATE:
            games[-1]['favorability'] = float(cache[str(games[-1]['appid'])]['favorability'])
        else:
            pos, n = get_app_reviews(games[-1]['appid'])
            games[-1]['favorability'] = wilson_lower(pos, n)

        # Retrieve critic scores and normalize
        games[-1]['critic_score'] = 1
        # TODO Add  Metacritic scraper

        # Retrieve ProtonDB ratings and normalize
        if str(games[-1]['appid']) in cache.keys() and not FORCE_DATA_UPDATE:
            games[-1]['protonDB_rating'] = float(cache[str(games[-1]['appid'])]['protonDB_rating'])
        else:
            try:
                rating = get_protondb_rating(games[-1]['appid'])
                games[-1]['protonDB_rating'] = 1 if rating == 'platinum' else 0.9 if rating == 'gold' else 0.75 if rating == 'silver' else 0.5 if rating == 'bronze' else 0
            except ProtonDBError:
                print(games[-1]['name'], 'not found in ProtonDB')
                games[-1]['protonDB_rating'] = 0

        # Retrieve "Personal Interest", filter out Completed, Not Interested, and Ignore
        # TODO
        games[-1]['personal_interest'] = 1

        # Retrieve HLTB "Main + Extras", calculate completion percentage
        # TODO Solve missing and NoneType HLTB IDs, and NoneType results
        if str(games[-1]['appid']) in cache.keys() and not FORCE_DATA_UPDATE:
            games[-1]['completion'] = float(cache[str(games[-1]['appid'])]['completion'])
        else:
            if str(games[-1]['appid']) in hltb_ids.keys() and hltb_ids[str(games[-1]['appid'])] is not None:
                hltb_main_extra = get_hltb_stats(hltb_ids[str(games[-1]['appid'])])
                games[-1]['completion'] = min(1, ((playtime / 60) / hltb_main_extra) if hltb_main_extra != 0 else 0)
            elif str(games[-1]['appid']) in hltb_ids.keys():
                print('NoneType HLTB ID')
                games[-1]['completion'] = 0
            else:
                print('Missing HLTB ID')
                games[-1]['completion'] = 0

        # Combine weightings with previous data into weighted values
        if PROTON_HARD_COMPATIBILITY:
            games[-1]['favorability_weighted'] = games[-1]['favorability'] * 0.425          # Favorability
            games[-1]['critic_score_weighted'] = games[-1]['critic_score'] * 0.325          # Critic Scores
            games[-1]['protonDB_rating_weighted'] = -1                                      # ProtonDB Rating = -1 (weighted value not used)
            games[-1]['personal_interest_weighted'] = games[-1]['personal_interest'] * 0.15 # Personal Interest
            games[-1]['completion_weighted'] = games[-1]['completion'] * 0.10               # Completion
        else:
            games[-1]['favorability_weighted'] = games[-1]['favorability'] * 0.30           # Favorability
            games[-1]['critic_score_weighted'] = games[-1]['critic_score'] * 0.20           # Critic Scores
            games[-1]['protonDB_rating_weighted'] = games[-1]['protonDB_rating'] * 0.25     # ProtonDB Rating
            games[-1]['personal_interest_weighted'] = games[-1]['personal_interest'] * 0.15 # Personal Interest
            games[-1]['completion_weighted'] = games[-1]['completion'] * 0.10               # Completion

        # Combine weighted values into final score
        if PROTON_HARD_COMPATIBILITY:
            games[-1]['final_score'] = games[-1]['protonDB_rating'] * (games[-1]['favorability_weighted'] + games[-1]['critic_score_weighted'] + games[-1]['personal_interest_weighted'] + games[-1]['completion_weighted'])
        else:
            games[-1]['final_score'] = games[-1]['favorability_weighted'] + games[-1]['critic_score_weighted'] + games[-1]['protonDB_rating_weighted'] + games[-1]['personal_interest_weighted'] + games[-1]['completion_weighted']

        # Sleep 1s to prevent rate-limiting
        if str(games[-1]['appid']) not in cache.keys() or FORCE_DATA_UPDATE:
            time.sleep(1)

        # Debug print to see master games list
        print(len(games), games[-1])

        # Debug counter for faster testing
        count += 1

    logger.info(f'Steam Game Count: {len(games)}')

    # Write results to CSV file
    with open('list.csv', 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        # Save headers
        writer.writerow(games[0].keys())
        # Save data
        for g in games:
            writer.writerow(g.values())

    # Print out script execution time
    scriptFinishTime = time.time()
    print(f'\nScript Execution Time: {(scriptFinishTime - scriptStartTime):.2f} seconds')

    # Write final log entry
    logger.info(f'Finished at {datetime.fromtimestamp(scriptFinishTime)} ({(scriptFinishTime - scriptStartTime):.2f} seconds)')

    exit()
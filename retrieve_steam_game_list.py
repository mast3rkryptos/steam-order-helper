from steam_web_api import Steam
from decouple import Config, RepositoryEnv
from datetime import datetime

import csv
import logging
import math
import requests
import time

def favorability(appid):
    url = f"https://store.steampowered.com/appreviews/{appid}?json=1&language=all&review_type=all&purchase_type=all"
    r = requests.get(url, timeout=10).json()
    qs = r.get("query_summary", {})
    pos = qs.get("total_positive", 0)
    neg = qs.get("total_negative", 0)
    total = pos + neg
    return pos/total if total>0 else None

def get_app_reviews(appid):
    url = f"https://store.steampowered.com/appreviews/{appid}?json=1&language=all&review_type=all&purchase_type=all"
    r = requests.get(url, timeout=10).json()
    qs = r.get("query_summary", {})
    pos = qs.get("total_positive", 0)
    n = qs.get("total_reviews", 0)
    return pos, n

def wilson_lower(pos, n, z=1.96):
    if n == 0: return 0
    p = pos / n
    z2 = z*z
    denom = 1 + z2/n
    num = p + z2/(2*n) - z * math.sqrt((p*(1-p) + z2/(4*n)) / n)
    return num / denom

# Main Script
if __name__=="__main__":

    games = []

    # Setup logger
    logger = logging.getLogger(__name__)
    logging.basicConfig(filename='retrieve.log', level=logging.INFO, filemode='w')

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

    # Retrieve user's owned games, and trim results
    for game in steam.users.get_owned_games(steamid)['games']:
        games.append([game['appid'], game['name'], game['playtime_forever']])
        try:
            achievements = steam.apps.get_user_achievements(steamid, games[-1][0])['playerstats']['achievements']
            games[-1].append(len([x for x in achievements if x['achieved'] == 1]) / len(achievements))
        except Exception as e:
            print('An exception occurred: ', e)
            games[-1].append(-1)
        # app_details = steam.apps.get_app_details(game['appid'], filters='metacritic')
        # if app_details is not None and ('data' in app_details[str(game['appid'])] and len(app_details[str(game['appid'])]['data']) > 0):
        #     games[-1].append(app_details[str(game['appid'])]['data']['metacritic']['score'])
        # elif app_details is not None:
        #     games[-1].append(-1)
        # else:
        #     games[-1].append(-2)
        pos, n = get_app_reviews(game['appid'])
        games[-1].append(wilson_lower(pos, n))
        print(games[-1])
    logger.info(f'Steam Game Count: {len(games)}')

    # Write results to CSV file
    with open('out.csv', 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['appid', 'name', 'playtime_forever', 'achievement'])
        writer.writerows(games)

    # Print out script execution time
    scriptFinishTime = time.time()
    print(f'\nScript Execution Time: {(scriptFinishTime - scriptStartTime):.2f} seconds')

    # Write final log entry
    logger.info(f'Finished at {datetime.fromtimestamp(scriptFinishTime)} ({(scriptFinishTime - scriptStartTime):.2f} seconds)')

    exit()

    # Begin timer for overall runtime tracker
    scriptStartTime = time.time()

    # Retrieve Steam game ID list
    DOTENV_FILE = 'C:\\personal_files\\SteamOrderHelperEnv\\.env'
    env_config = Config(RepositoryEnv(DOTENV_FILE))
    KEY = env_config.get("STEAM_API_KEY")
    steam = Steam(KEY)
    steamIdList = []
    for game in steam.users.get_owned_games("76561197990222251")["games"]:
        print(game)

    # Print out script execution time
    print(f"\nScript Execution Time: {(time.time() - scriptStartTime):.2f} seconds")
    exit()
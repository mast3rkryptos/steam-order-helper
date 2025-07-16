import json
import logging
import requests
import time

from datetime import datetime
from decouple import Config, RepositoryEnv
from igdb.wrapper import IGDBWrapper
from pprint import pprint
from steam_web_api import Steam
from time import sleep
from tqdm import tqdm

def initializeWrapper(client_id, client_secret):
    r = requests.post(f"https://id.twitch.tv/oauth2/token?client_id={client_id}&client_secret={client_secret}&grant_type=client_credentials")
    access_token = json.loads(r._content)['access_token']
    return IGDBWrapper(client_id, access_token)

def executeIgdbQuery(endpoint, query):
    igdbResults = igdb_wrapper.api_request(endpoint, bytes(query, "utf-8").decode("latin-1", "ignore"))
    igdbResultsJson = igdbResults.decode('utf8')
    igdbResultsData = json.loads(igdbResultsJson)
    return igdbResultsData

def get_game_details(app_id):
    url = f"https://store.steampowered.com/api/appdetails?appids={app_id}"
    response = requests.get(url)

    # There is a limit of 200 successful requests per 5 minutes (old rate limit?)
    while response.status_code != 200:
        if response.status_code == 429:
            print('Received "429:Too Many Requests" status code, retrying every 10 seconds')
            logger.info('Received "Too Many Requests" status code, retrying every 10 seconds')
            sleep(10)
        elif response.status_code == 403:
            print('Received "403:Forbidden" status code, waiting 5 minutes')
            logger.info('Received "403:Forbidden" status code, waiting 5 minutes')
            sleep(5 * 60)
        else:
            break
        response = requests.get(url)

    data = response.json()

    if data[str(app_id)]['success']:
        game_data = data[str(app_id)]['data']
        name = game_data['name']
        description = game_data['short_description']
        if 'price_overview' in game_data:
            price = game_data['price_overview']['final_formatted']
        else:
            price = 'Free' if game_data['is_free'] else 'price not available'
        return {
            'name': name,
            'description': description,
            'price': price
        }
    else:
        return 'details not found'

# Main Script
if __name__ == '__main__':

    # ID (Steam) : (Name (Steam), Metacritic (Steam), ID (IGDB), Parent ID (IGDB), Parent Name (IGDB))
    games = {}

    # Setup logger
    logger = logging.getLogger(__name__)
    logging.basicConfig(filename='alt.log', level=logging.INFO, filemode='w')

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
        games[game['appid']] = (game['name'], -1, -1, -1, None)
    logger.info(f'Steam Game Count: {len(games)}')

    # Initialize the IGDB connection
    igdb_client_id = env_config.get('IGDB_Client_ID')
    igdb_client_secret = env_config.get('IGDB_Client_Secret')
    igdb_wrapper = initializeWrapper(igdb_client_id, igdb_client_secret)
    logger.info('IGDB API connection initialized.')

    # Retrieve IGDB IDs (from Steam IDs)
    results = executeIgdbQuery('external_games', f'fields game, name, uid; limit 500; where uid=({",".join([str(x) for x in games])}) & category=1;')
    logger.info(f'IGDB Game Count: {len(results)}')

    # Insert data from IGDB results into master games list
    for k in games.keys():
        found = False
        for g in results:
            if str(k) == g['uid']:
                games[k] = (games[k][0], -1, g['game'], -1, None)
                found = True
                continue
        if not found:
            logger.warning(f'Missing IGDB game: {games[k][0]}')

    # Retrieve IGDB game info
    igdb_ids = [str(games[k][2]) for k in games.keys()]
    results = executeIgdbQuery('games',
                               f'fields name,parent_game.name,category; limit 500; where id = ({",".join(igdb_ids)}); sort name asc;')
    for k in games.keys():
        found = False
        for g in results:
            if games[k][2] == g['id'] and 'parent_game' in g.keys():
                games[k] = (games[k][0], -1, games[k][2], g['parent_game']['id'], g['parent_game']['name'])
                found = True
                continue
    logger.info(f'IGDB Result Count: {len(results)}')

    # Retrieve Metacritic scores from the Steam API
    with tqdm(total=len(games)) as pbar:
        pbar.set_description('Steam Metacritic Score Retrieval')
        for k in games.keys():
            #print(k, games[k])
            # Steam rate limits to 100,000 requests per day
            details = steam.apps.get_app_details(k, filters='metacritic')
            if details is not None and details[f'{k}']['success'] == True and len(details[f'{k}']['data']) != 0:
                games[k] = (games[k][0], details[f'{k}']['data']['metacritic']['score'], games[k][2], games[k][3], games[k][4])
            else:
                logger.warning(f'Missing Steam Metacritic Score: {games[k][0]} (Parent={games[k][4]})')
            pbar.update(1)
    #pprint(sorted(list(steam_metacritic.values())))


    # results = executeIgdbQuery('games', f'fields name, category; limit 500; where id=({",".join([str(igdb_id) for igdb_id in igdb_ids])}); sort category asc;')
    # logger.info(f'IGDB Result Count: {len(results)}')
    #
    # # Find missing games in IGDB results
    # for i in igdb_ids:
    #     found = False
    #     for g in results:
    #         if i == g['id']:
    #             found = True
    #             continue
    #     if not found:
    #         logger.warning(f'Missing IGDB game: {i}')
    #
    # # Retrieve IGDB game info
    # results = executeIgdbQuery('games',
    #                            f'fields name,rating,rating_count,aggregated_rating,aggregated_rating_count,parent_game.name,category; limit 500; where id = ({",".join([str(igdb_id) for igdb_id in igdb_ids])}); sort rating asc;')
    # pprint(results)
    # logger.info(f'IGDB Result Count: {len(results)}')

    # Print out script execution time
    scriptFinishTime = time.time()
    print(f'\nScript Execution Time: {(scriptFinishTime - scriptStartTime):.2f} seconds')

    # Write final log entry
    logger.info(f'Finished at {datetime.fromtimestamp(scriptFinishTime)} ({(scriptFinishTime - scriptStartTime):.2f} seconds)')

    exit()
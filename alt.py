import json
import logging
import requests
import time

from datetime import datetime
from decouple import Config, RepositoryEnv
from igdb.wrapper import IGDBWrapper
from pprint import pprint
from steam_web_api import Steam

def initializeWrapper(client_id, client_secret):
    r = requests.post(f"https://id.twitch.tv/oauth2/token?client_id={client_id}&client_secret={client_secret}&grant_type=client_credentials")
    access_token = json.loads(r._content)['access_token']
    return IGDBWrapper(client_id, access_token)

def executeIgdbQuery(endpoint, query):
    igdbResults = igdb_wrapper.api_request(endpoint, bytes(query, "utf-8").decode("latin-1", "ignore"))
    igdbResultsJson = igdbResults.decode('utf8')
    igdbResultsData = json.loads(igdbResultsJson)
    return igdbResultsData

# Main Script
if __name__ == '__main__':

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
    steam_games = {}
    for game in steam.users.get_owned_games(steamid)['games']:
        steam_games[game['appid']] = game['name']
    logger.info(f'Steam Game Count: {len(steam_games)}')

    # Initialize the IGDB connection
    igdb_client_id = env_config.get('IGDB_Client_ID')
    igdb_client_secret = env_config.get('IGDB_Client_Secret')
    igdb_wrapper = initializeWrapper(igdb_client_id, igdb_client_secret)
    logger.info('IGDB API connection initialized.')

    # Retrieve IGDB IDs (from Steam IDs)
    results = executeIgdbQuery('external_games', f'fields game, name, uid; limit 500; where uid=({",".join([str(x) for x in steam_games.keys()])}) & category=1;')
    igdb_ids = [x['game'] for x in results]
    logger.info(f'IGDB Game Count: {len(igdb_ids)}')

    # Find missing games in IGDB results
    for k in steam_games.keys():
        found = False
        for g in results:
            if str(k) == g['uid']:
                found = True
                continue
        if not found:
            logger.warning(f'Missing IGDB game: {steam_games[k]}')

    # Retrieve IGDB game info
    results = executeIgdbQuery('games',
                               f'fields name,parent_game.name,category; limit 500; where id = ({",".join([str(igdb_id) for igdb_id in igdb_ids])}); sort name asc;')
    pprint(results)
    logger.info(f'IGDB Result Count: {len(results)}')

    # Use IGDB to normalize game list, specifically retrieving parent games and Steam IDs for bundles, etc.

    # # Retrieve Metacritic scores from the Steam API
    # steam_metacritic = {}
    # for id in steam_games.keys():
    #     details = steam.apps.get_app_details(id, filters='metacritic')
    #     if details is not None and details[f'{id}']['success'] == True and len(details[f'{id}']['data']) != 0:
    #         steam_metacritic[id] = (details[f'{id}']['data']['metacritic']['score'], steam_games[id])
    #     else:
    #         steam_metacritic[id] = (-1, steam_games[id])
    # pprint(sorted(list(steam_metacritic.values())))
    #
    #
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
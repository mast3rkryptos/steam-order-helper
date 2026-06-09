import csv
import logging
import re
import steamspypi
import time

from datetime import datetime
from decouple import Config, RepositoryEnv
from Game import Game
from howlongtobeatpy import HowLongToBeat
from pprint import pprint
from steam_web_api import Steam
from tqdm import tqdm

def lookupHltb(input):
    best_element = None
    if input.isdigit():
        best_element = HowLongToBeat().search_from_id(int(input))
    else:
        results = HowLongToBeat().search(re.sub(r'[^ -~]', "", input.strip()), similarity_case_sensitive=False)
        if results is not None and len(results) > 0:
            best_element = max(results, key=lambda element: element.similarity)
    return best_element

# Main Script
if __name__ == '__main__':

    games = []

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
        games.append(Game(game['appid'], game['name']))
    logger.info(f'Steam Game Count: {len(games)}')

    # Retrieve user ratings from SteamSpy
    temp_count = 0
    with tqdm(total=len(games)) as pbar:
        pbar.set_description('SteamSpy Score Retrieval')
        for i in range(len(games)):
            # if temp_count >= 10:
            #     break
            # else:
            #     temp_count += 1
            data_request = dict()
            data_request['request'] = 'appdetails'
            data_request['appid'] = str(games[i].steam_id)

            data = steamspypi.download(data_request)
            #print(i, games[i].steam_name, data['positive'], data['negative'], (data['positive'] + data['negative']) > 0, ((data['positive'] + data['negative']) > 0))
            games[i].steam_reviews = round((data['positive'] / (data['positive'] + data['negative'])) * 100, 2) if ((data['positive'] + data['negative']) > 0) else -1
            pbar.update(1)
    #pprint([g.to_dict() for g in sorted(games, key=lambda x: x.steam_reviews)], width=1000)

    # Retrieve HLTB stats
    with tqdm(total=len(games)) as pbar:
        pbar.set_description('HLTB Stats Retrieval')
        for g in games:
            best_element = lookupHltb(g.steam_name)
            if best_element is not None:
                g.hltb = best_element.completionist
            else:
                g.hltb = "n/f"
            pbar.update(1)

    # Write results to CSV file
    with open('out.csv', 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Name', 'Score', 'HLTB'])
        writer.writerows([[g.steam_name, g.steam_reviews, g.hltb] for g in sorted(games, key=lambda x: x.steam_reviews)])

    # Print out script execution time
    scriptFinishTime = time.time()
    print(f'\nScript Execution Time: {(scriptFinishTime - scriptStartTime):.2f} seconds')

    # Write final log entry
    logger.info(f'Finished at {datetime.fromtimestamp(scriptFinishTime)} ({(scriptFinishTime - scriptStartTime):.2f} seconds)')

    exit()
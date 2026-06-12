import csv
import time

from decouple import Config, RepositoryEnv
from steam_web_api import Steam

# Setup configuration file
DOTENV_FILE = '.env'
env_config = Config(RepositoryEnv(DOTENV_FILE))

# Initialize some shared dictionaries
game_list = []

# Setup Steam connection
steam_api_key = env_config.get('STEAM_API_KEY')
steam = Steam(steam_api_key)

# Retrieve user's steamid
steamid = steam.users.search_user('gschive')['player']['steamid']

# Retrieve user's owned games
game_list = steam.users.get_owned_games(steamid)['games']

with open('output/test.csv', 'w', newline='', encoding='utf-8') as csvfile:
    writer = csv.writer(csvfile)
    # Save headers
    writer.writerow(['appid', 'description'])
    # Save data
    for game in game_list:
        details = steam.apps.get_app_details(game['appid'])
        if details is not None and details[str(game['appid'])]['success'] == True:
            name = details[str(game['appid'])]['data']['name']
            description = details[str(game['appid'])]['data']['short_description']
            print(f'{game['appid']}, {name}, {description}')
            writer.writerow([game['appid'], name, description])
        else:
            print(f'{game['appid']} failed')
            writer.writerow([game['appid'], 'failed', 'failed'])
        time.sleep(5)
from howlongtobeatpy import HowLongToBeat
from igdb.wrapper import IGDBWrapper
from steam import Steam
from decouple import Config, RepositoryEnv

import csv
import json
import re
import requests
import time

_IGDBCategories = {0: "main_game",
                   1: "dlc_addon",
                   2: "expansion",
                   3: "bundle",
                   4: "standalone_expansion",
                   5: "mod",
                   6: "episode",
                   7: "season",
                   8: "remake",
                   9: "remaster",
                   10: "expanded_game",
                   11: "port",
                   12: "fork",
                   13: "pack",
                   14: "update"}

class GameEntity:
    def __init__(self, name, steamId):
        self.name = name
        self.steamId = steamId
        self.igdbId = -1
        self.igdbParentGame = -1
        self.igdbRating = -1
        self.igdbWeightedRating = -1
        self.hltb = -1

    def getCsvList(self):
        return [self.name, self.igdbId, self.igdbParentGame, self.igdbRating, self.igdbWeightedRating, self.hltb]

    def __str__(self):
        return f'{self.name}(steam{self.steamId}/igdb{self.igdbId}) :: {self.igdbParentGame} :: {self.igdbRating} :: {self.igdbWeightedRating} :: {self.hltb}'


def initializeWrapper(client_id, client_secret):
    r = requests.post(f"https://id.twitch.tv/oauth2/token?client_id={client_id}&client_secret={client_secret}&grant_type=client_credentials")
    access_token = json.loads(r._content)['access_token']
    return IGDBWrapper(client_id, access_token)

def lookupHltb(name):
    best_element = None
    results = HowLongToBeat().search(re.sub(r'[^ -~]', "", name.strip()))
    if results is not None and len(results) > 0:
        best_element = max(results, key=lambda element: element.similarity)
    return best_element

def executeIgdbQuery(endpoint, query):
    igdbResults = wrapper.api_request(endpoint, bytes(query, "utf-8").decode("latin-1", "ignore"))
    igdbResultsJson = igdbResults.decode('utf8')
    igdbExtGamesResultsData = json.loads(igdbResultsJson)
    return igdbExtGamesResultsData

def getIgdbGameIds(gameEntities):
    limit = 500
    return executeIgdbQuery('external_games', f'fields game,uid; limit {limit}; where uid = ({",".join([x.steamId for x in gameEntities])}) & category = 1; sort uid asc;')

def getIgdbGameInfo(gameEntities):
    limit = 500
    return executeIgdbQuery('games', f'fields name,rating,rating_count,aggregated_rating,aggregated_rating_count,parent_game,category; limit {limit}; where id = ({",".join([str(x.igdbId) for x in gameEntities])}); sort id asc;')


# Main Script

# Begin timer for overall runtime tracker
scriptStartTime = time.time()

wrapper = initializeWrapper("wnc0qtcgt76myt2u0619qi9stmhv2u", "ej7q5zbheyyv9yth1pzrw53aywcyo2")

gameEntities = []

# Retrieve Steam game ID list
DOTENV_FILE = 'C:\\personal_files\\SteamOrderHelperEnv\\.env'
env_config = Config(RepositoryEnv(DOTENV_FILE))
KEY = env_config.get("STEAM_API_KEY")
steam = Steam(KEY)
#print(steam.users.get_owned_games("76561197990222251"))
steamIdList = []
for game in steam.users.get_owned_games("76561197990222251")["games"]:
    gameEntities.append(GameEntity(game['name'], game['appid']))
    steamIdList.append(f'\"{game["appid"]}\"')

# Match Steam IDs to IGDB IDs
overrideList = {}
with open("override.csv", "r", encoding='utf-8') as f:
    for line in f:
        splitline = line.split(",")
        overrideList[splitline[0]] = splitline[1].rstrip()
results = executeIgdbQuery('external_games', f'fields game, uid; limit 500; where uid=({",".join(steamIdList)}) & category=1;')
for ge in gameEntities:
    foundIt = False
    for result in results:
        if not foundIt and result["uid"] == str(ge.steamId):
            ge.igdbId = result["game"]
            foundIt = True
            break
    if not foundIt:
        nameResult = executeIgdbQuery('games', f'fields id, name; limit 500; where name=\"{ge.name if ge.name not in overrideList.keys() else overrideList[ge.name]}\";')
        if len(nameResult) > 0:
            ge.igdbId = nameResult[0]["id"]
        else:
            print(f"ERROR: Could not cross-reference Steam ID or name for: {ge.name}")

# Add supplemental GameEntities (from other game services/platforms mostly); format of each entry is:
# [Name],[IGDB ID]
with open("supplemental.csv", "r") as f:
    supplementalGames = []
    for line in f:
        splitline = line.split(",")
        supplementalGames.append(splitline[1])
    queryableSGString = ",".join([sg for sg in supplementalGames])
    results = executeIgdbQuery('games', f'fields id, name; limit 500; where id=({",".join([sg for sg in supplementalGames])}); sort name asc;')
    for game in results:
        gameEntities.append(GameEntity(game["name"], 0))
        gameEntities[-1].igdbId = game["id"]

# Now that we have a good list of IGDB IDs, divide based on category
igdbIds = [ge.igdbId for ge in gameEntities if ge.igdbId != -1]
results = executeIgdbQuery('games', f'fields name, category; limit 500; where id=({",".join([f"{igdbId}" for igdbId in igdbIds])}); sort category asc;')
#print("\n".join([f"{_IGDBCategories[int(result['category'])]} {result['name']}" for result in results]))

# Get IGDB Info
igdbGameInfo = getIgdbGameInfo(gameEntities)
#print("\nIGDB Game Info:\n ", "\n  ".join([str(igi) for igi in igdbGameInfo]))
#igdbGameInfo = [x for x in igdbGameInfo if "parent_game" not in x.keys()]

# Retrieve rating information (calculating weighted rating as well)
for gameEntity in gameEntities:
    for igi in igdbGameInfo:
        if gameEntity.igdbId == igi["id"]:
            if "parent_game" in igi.keys():
                gameEntity.igdbParentGame = igi["parent_game"]
            if "rating" in igi.keys():
                gameEntity.igdbRating = float("{rating:.2f}".format(rating=igi["rating"]))
                gameEntity.igdbWeightedRating = float("{rating:.2f}".format(rating=igi["rating"] * igi["rating_count"]))
            elif "aggregated_rating" in igi.keys():
                gameEntity.igdbRating = float("{rating:.2f}".format(rating=igi["aggregated_rating"]))
                gameEntity.igdbWeightedRating = float("{rating:.2f}".format(rating=igi["aggregated_rating"] * igi["aggregated_rating_count"]))

# TODO Print to log; add category to query and GemeEntity
# Lookup HLTB statistics
statusIndicatorWrap = 100
count = 0
for ge in gameEntities:
    best_element = lookupHltb(ge.name)
    if best_element is not None:
        ge.hltb = best_element.completionist
    elif ge.igdbParentGame != -1:
        # Attempt to retry using parent_game
        print(f"Retrying {ge.name} with parent game ID {ge.igdbParentGame}")
        results = executeIgdbQuery('games', f'fields name; limit 500; where id={ge.igdbParentGame};')
        print(f"Matched {ge.name} to parent game {results[0]['name']}")
        best_element = lookupHltb(results[0]["name"])
        ge.hltb = best_element.completionist if best_element is not None else "n/f"
    else:
        ge.hltb = "n/f"
    #print(ge)
    #print("\n." if count % statusIndicatorWrap == 0 else ".", end="")
    #count += 1

# TODO Weighted rating causes remakes, remasters, bundles, mods, etc. to be much lower on the list
gameEntities.sort(key=lambda x: x.igdbWeightedRating)
with open("output.csv", "w", newline='', encoding='utf-8') as csvfile:
    csvwriter = csv.writer(csvfile)
    csvwriter.writerow(["Name", "IGDB ID", "Parent Game", "Rating", "Weighted Rating", "HLTB"])
    for ge in gameEntities:
        csvwriter.writerow(ge.getCsvList())
print("\n".join([f"{ge}" for ge in gameEntities]))
# Print out script execution time
print(f"\nScript Execution Time: {(time.time() - scriptStartTime):.2f} seconds")
exit()

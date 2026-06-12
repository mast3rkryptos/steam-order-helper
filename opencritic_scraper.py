import requests
import urllib.parse

games = ['onion asault','Untitled Goose Game','COD']

#need these headers else they know you are scraping and tell you to go get an api key lol
headers = {
        'accept':'application/json, text/plain, */*',
        'origin':'https://opencritic.com',
        'referer':'https://opencritic.com/',
        'user-agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36'
        }

for game in games:

        safe_game_name = urllib.parse.quote_plus(game) #url encoding
        search_url = f'https://api.opencritic.com/api/meta/search?criteria={safe_game_name}'

        results = requests.get(search_url,headers=headers)
        results_json = results.json()

        if game.lower() == results_json[0]['name'].lower():
                print(f'{results_json[0]["name"]} found!')
                found_id = results_json[0]['id']
        else:
                print(f'{game} not found exactly, getting review for closest result: {results_json[0]["name"]}')
                found_id = results_json[0]["id"]

        info_url = f'https://api.opencritic.com/api/game/{found_id}'

        info = requests.get(info_url,headers=headers)
        info_json = info.json()
        # print(info_json) #all the data in this json
        # do whatever you want with the data here, edit code to store in csv or something I don't know

        print(info_json['name'],
        info_json['medianScore'],
        info_json['numReviews'],
        info_json['tier'],
        info_json['topCriticScore'])
class Game:
    def __init__(self, steam_id, steam_name):
        self.steam_id = steam_id
        self.steam_name = steam_name
        self.steam_metacritic = -1
        self.steam_reviews = -1
        self.hltb = -1

    def to_dict(self):
        return {'steam_id':self.steam_id,
                'steam_name':self.steam_name,
                'steam_metacritic':self.steam_metacritic,
                'steam_reviews':self.steam_reviews,
                'hltb':self.hltb}
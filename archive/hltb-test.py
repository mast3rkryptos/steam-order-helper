from howlongtobeatpy import HowLongToBeat, HowLongToBeatEntry

results = HowLongToBeat().search("Portal 2")
for result in results:
    print(result.game_id, result.game_name, result.game_type, result.review_score, result.main_extra, result.completionist, result.all_styles)

result = HowLongToBeat().search_from_id(7231)
print(result.game_id, result.game_name, result.game_type, result.review_score, result.main_extra, result.completionist, result.all_styles, result.json_content)

import time

from httplib2 import socks, ProxyInfo, Http
import numpy as np
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import pandas as pd
import json
import pycountry
from scraper import base_path
from scraper import get_nameMap
from sql_dao.sql_utils import insert_comment, detect_duplicated_comment
from scraper.my_translater import youdao_translate
from scraper.my_utils import parse_date_format, identify_lang_to_country, text_clean, \
    analyze_polarity, fan_to_jian, identify_lang


# 调用Youtube API的 channels.list 方法获取频道所属的国家
def list_channel_country(youtube, channel_id, comment):
    results = youtube.channels().list(
        part='snippet',
        id=channel_id
    ).execute()

    if 'country' in results['items'][0]['snippet']:
        country = results['items'][0]['snippet']['country']
        return get_nameMap()[pycountry.countries.get(alpha_2=country).name]
    else:
        return identify_lang_to_country(comment)


def scrap_reviews(keyword, workId):
    return get_comments(keyword, 7, 2, 40, workId)


def get_comments(keyword, max_videos, max_pages, max_comment_cnt, workId):
    scopes = ["https://www.googleapis.com/auth/youtube.force-ssl"]
    platform = "Youtube"

    DEVELOPER_KEY = 'AIzaSyAp0oxZY8Sa6avNrEAmU3JZCKwW1_-okik'
    YOUTUBE_API_SERVICE_NAME = 'youtube'
    YOUTUBE_API_VERSION = 'v3'

    # 设置http代理，
    proxy_info = ProxyInfo(socks.PROXY_TYPE_SOCKS5, "127.0.0.1", 10808)
    http = Http(timeout=30, proxy_info=proxy_info)
    # Disable OAuthlib's HTTPS verification when running locally.
    # *DO NOT* leave this option enabled in production.
    youtube = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION,
                    developerKey=DEVELOPER_KEY, http=http)

    search_response = youtube.search().list(  # 根据搜索关键词查询匹配的视频id
        q=keyword,
        part='id,snippet',
        maxResults=max_videos
    ).execute()
    videos = []
    for search_result in search_response.get('items', []):
        if search_result['id']['kind'] == 'youtube#video':
            temp = {}
            temp["title"] = search_result['snippet']['title']
            temp["video_id"] = search_result['id']['videoId']
            videos.append(temp)
    videos_json = json.dumps(videos, indent=4, ensure_ascii=False)
    with open(base_path + '/out/{}视频id_{}.json'.format(keyword, platform), 'w', encoding='utf-8') as f:
        f.write(videos_json)
    comments = []
    count = 0
    video_cnt = 0
    try:
        for video in videos:
            video_cnt += 1
            videoId = video["video_id"]
            try:
                request = youtube.commentThreads().list(
                    part="snippet,replies",
                    videoId=videoId,
                    maxResults=max_comment_cnt
                )
                # print(comments)
                print("爬取第{}个视频的评论".format(video_cnt))
                response = request.execute()

                totalResults = int(response['pageInfo']['totalResults'])
                nextPageToken = ''

                first = True
                further = True
                cnt = 0
                while further:
                    cnt += 1
                    if cnt > max_pages:
                        break
                    halt = False
                    if not first:
                        print('..')
                        try:
                            response = youtube.commentThreads().list(
                                part="snippet,replies",
                                videoId=videoId,
                                maxResults=max_comment_cnt,
                                textFormat='plainText',
                                pageToken=nextPageToken
                            ).execute()
                            totalResults = int(response['pageInfo']['totalResults'])
                        except HttpError as e:
                            print("An HTTP error %d occurred:\n%s" % (e.resp.status, e.content))
                            halt = True

                    if halt == False:
                        count += totalResults
                        for item in response["items"]:
                            # This is only a part of the data.
                            # You can choose what you need. You can print the data information you can get and crawl it as needed.
                            comment = item["snippet"]["topLevelComment"]
                            # author = comment["snippet"]["authorDisplayName"]
                            text = text_clean(comment["snippet"]["textDisplay"])
                            # print(text)
                            if len(text.strip()) == 0:
                                continue
                            likeCount = comment["snippet"]['likeCount']
                            publishtime = parse_date_format(comment['snippet']['publishedAt'])
                            # channelId = comment['snippet']['authorChannelId']["value"]
                            country = identify_lang_to_country(text)
                            language = identify_lang(text)
                            if country != "中国":
                                translated = youdao_translate(text)
                                time.sleep(1)
                                if len(translated.strip()) == 0:
                                    continue
                                # translated = text
                            else:
                                translated = text
                            translated = fan_to_jian(translated)
                            dup = detect_duplicated_comment(workId, country, platform, publishtime, text)
                            if dup:
                                continue
                            success = insert_comment(text, translated, language, likeCount, workId,
                                           analyze_polarity(translated), country, platform, publishtime)
                            if not success:
                                continue
                            comments.append([text, translated, likeCount, workId,
                                             analyze_polarity(translated), country, platform, publishtime])
                        if totalResults < max_comment_cnt:  # 获取的最大评论数
                            further = False
                        else:
                            further = True
                            first = False
                            try:
                                nextPageToken = response["nextPageToken"]
                            except KeyError as e:
                                print("An KeyError error occurred: %s" % e)
                                further = False
            except HttpError as e:
                print("An HttpError error occurred: %s" % e)
                continue
    except ConnectionResetError as e:
        print("远程主机强迫关闭了一个现有的连接：%s" % e)
    print('get data count: ', str(count))
    if not comments:
        return
    ### write to csv file
    # data = np.array(comments)
    # df = pd.DataFrame(data, columns=['content', 'translated', 'likes', 'workId',
    #                                  'sentiment', 'country', 'platform', 'postTime'])
    # df.to_csv(base_path + '/out/{}_{}.csv'.format(keyword, platform), index=False, sep="|", encoding='utf-8')
    return True

    ### write to json file
    # result = []
    # for time, vote, country, comment in comments:
    #     temp = {}
    #     temp['publishtime'] = time
    #     temp['likeCount'] = vote
    #     temp['country'] = country
    #     temp['comment'] = comment
    #     result.append(temp)
    # print('result: ', len(result))
    #
    # json_str = json.dumps(result, indent=4, ensure_ascii=False)
    # with open('./data/{}评论.json'.format(keyword), 'w', encoding='utf-8') as f:
    #     f.write(json_str)


if __name__ == "__main__":
    scrap_reviews("流浪地球1", 2)

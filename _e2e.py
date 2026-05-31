import sys; sys.path.insert(0, '.')
from common.article_envelope import build_article_envelope
from common.topic_splitter import detect_multi_topic, split_article_into_topics
from common.normalizer import normalize_topic

blocks = [
    {'type': 'article_text', 'text': '一、积分五倍赠', 'is_heading_like': True},
    {'type': 'article_text', 'text': '活动时间：6月1日-30日'},
    {'type': 'article_text', 'text': '活动内容：消费享5倍积分'},
    {'type': 'article_text', 'text': '二、新客返现100', 'is_heading_like': True},
    {'type': 'article_text', 'text': '活动对象：新客户'},
    {'type': 'article_text', 'text': '活动内容：消费3笔返100元'},
]
envelope = build_article_envelope(url='https://mp.weixin.qq.com/s/test', publisher_name='农行信用卡', raw_title='618合集', content_blocks=blocks)
detection = detect_multi_topic(envelope)
print(f'Multi-topic: {detection["is_multi_topic_candidate"]}', flush=True)
print(f'Signals: {detection["signals"]}', flush=True)

if detection['is_multi_topic_candidate']:
    topics = split_article_into_topics(envelope)
    print(f'Topics: {len(topics)}', flush=True)
    for t in topics:
        item = normalize_topic(t)
        print(f'  [{t["topic_id"]}] {t["headline"]} -> {item.category} | multi={item.is_multi_topic_split}', flush=True)

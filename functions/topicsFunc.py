from flask_security import current_user

from classes.shared import db
from classes.shared import cache

from classes import topics, Channel, RecordedVideo

from functions import cachedDbCalls, system

from globals import globalvars


def deleteTopic(topicID: int, toTopicID: int) -> bool:

    topicID = int(topicID)
    toTopicID = int(toTopicID)

    topicQuery = topics.topics.query.filter_by(
        id=topicID
    ).with_entities(
        topics.topics.id,
        topics.topics.name
    ).first()

    newTopic = topics.topics.query.filter_by(id=toTopicID).first()

    Channel.Channel.query.filter_by(topic=topicQuery.id).update(dict(topic=newTopic.id))
    RecordedVideo.RecordedVideo.query.filter_by(topic=topicQuery.id).update(dict(topic=newTopic.id))

    topics.topics.query.filter_by(id=topicQuery.id).delete()

    system.newLog(
        1, f"User {current_user.username} deleted Topic {str(topicQuery.name)}"
    )

    db.session.commit()
    cache.delete_memoized(cachedDbCalls.getAllTopics)

    # Initialize the Topic Cache
    topicQuery = cachedDbCalls.getAllTopics()
    for topic in topicQuery:
        globalvars.topicCache[topic.id] = topic.name

    return True

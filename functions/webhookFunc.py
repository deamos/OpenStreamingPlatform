import json
import requests
import logging

from typing import Union

from classes.shared import db
from classes import webhook

from functions import system

log = logging.getLogger("app.functions.database")


@system.asynch
def runWebhook(channelID: Union[str, int], triggerType: str, **kwargs: dict) -> bool:
    webhookQueue = []
    if channelID != "ZZZ":

        webhookQuery = webhook.webhook.query.filter_by(
            channelID=channelID, requestTrigger=triggerType
        ).all()
        webhookQueue.append(webhookQuery)

    globalWebhookQuery = webhook.globalWebhook.query.filter_by(
        requestTrigger=triggerType
    ).all()
    webhookQueue.append(globalWebhookQuery)

    for queue in webhookQueue:
        if queue:
            for hook in queue:
                url = hook.endpointURL
                payload = processWebhookVariables(hook.requestPayload, **kwargs)
                header = json.loads(hook.requestHeader)
                requestType = hook.requestType
                try:
                    if requestType == 0:
                        requests.post(url, headers=header, data=payload, timeout=10)
                    elif requestType == 1:
                        requests.get(url, headers=header, data=payload, timeout=10)
                    elif requestType == 2:
                        requests.put(url, headers=header, data=payload, timeout=10)
                    elif requestType == 3:
                        requests.delete(url, headers=header, data=payload, timeout=10)
                except Exception:
                    pass
                system.newLog(8, f"Processing Webhook for ID #{str(hook.id)} - Destination: {str(url)}",)
    db.session.commit()
    db.session.close()
    return True


@system.asynch
def testWebhook(webhookType: str, webhookID: int, **kwargs: dict) -> None:
    system.newLog(8, f"Testing Webhook for ID #{str(webhookID)} Type: {webhookType}")
    webhookQuery = None
    if webhookType == "channel":
        webhookQuery = webhook.webhook.query.filter_by(id=webhookID).first()
    elif webhookType == "global":
        webhookQuery = webhook.globalWebhook.query.filter_by(id=webhookID).first()
    if webhookQuery is not None:
        url = webhookQuery.endpointURL
        payload = processWebhookVariables(webhookQuery.requestPayload, **kwargs)
        header = json.loads(webhookQuery.requestHeader)
        requestType = webhookQuery.requestType
        try:
            if requestType == 0:
                requests.post(url, headers=header, data=payload, timeout=10)
            elif requestType == 1:
                requests.get(url, headers=header, data=payload, timeout=10)
            elif requestType == 2:
                requests.put(url, headers=header, data=payload, timeout=10)
            elif requestType == 3:
                requests.delete(url, headers=header, data=payload, timeout=10)
        except Exception as e:
            print(f"Webhook Error-{str(e)}")
        system.newLog(8, f"Completed Webhook Test for ID #{str(webhookQuery.id)} - Destination: {str(url)}",)


def processWebhookVariables(payload: dict, **kwargs: dict) -> dict:
    for key, value in kwargs.items():
        replacementValue = "%" + key + "%"
        if value is None or value == "":
            value = "NA"
        payload = payload.replace(replacementValue, str(value))

    return payload
